# -*- coding: utf-8 -*-
"""验真核心：把模型回答拆成「车站 + 时刻」原子断言，与元宝搜索 VR 卡逐站比对。

为什么按站点而不是按车次判定：
    一条回答里会混进终到时刻、换乘时刻、其他车次的时刻。按车次聚合时刻集合，
    只要有一个数对上就算"正确"，太松；全都不对上就算"错误"，又把格式噪声算成人错。
    拆到「这一站这个时刻」粒度，才是可以逐条复核的最小单元。

判定口径（四态）：
    correct    站点存在，且断言时刻等于官方「到站」或「发车」任一字段
    mismatch   站点存在，官方时刻完整，但断言时刻两个都不等
    unknown    权威库未收录该车次 → 判「存疑」，绝不判「编造」
    skip       官方该站时刻被截断（如 "09:..."），无法比对 → 跳过，不计入分母

分母口径：准确率 = correct / (correct + mismatch)。unknown 与 skip 一律不计入。
"""
import json
import re
from pathlib import Path

from official import fetch_official

TIME_RE = re.compile(r"(?<!\d)([01]?\d|2[0-3]):([0-5]\d)(?!\d)")
FULL_TIME = re.compile(r"^\d{2}:\d{2}$")
TRAIN_NO = re.compile(r"\b([GDKCTZS]\d{1,5})\b", re.IGNORECASE)
# 文本里形如"北京西站"的站点引用（用于识别"提到了不属于本车次的车站"）
STATION_REF = re.compile(r"([\u4e00-\u9fa5]{2,6})站")
# 这些"XX站"不是站名，是描述性词语，必须排除
NOT_A_STATION = {
    "到达", "出发", "发车", "经停", "停靠", "中转", "换乘", "终点", "始发",
    "沿途", "每个", "各个", "所在", "城市", "火车", "汽车", "地铁", "沿线",
    "下一", "上一", "部分", "中间", "沿途",
}


def collect_stations(cache: dict) -> set:
    """所有已缓存车次的站名集合，用于判断一行文本在说哪一站"""
    out = set()
    for v in cache.values():
        if isinstance(v, dict) and not v.get("_empty"):
            for s in v.get("stops", []):
                if s.get("station"):
                    out.add(s["station"])
    return out


def parse_station_claims(text: str, stations: set) -> tuple[list[dict], list[dict]]:
    """从回答里抽 (车站, [时刻...]) 断言，返回 (已知站断言, 非本车次站断言)。

    只保留同时含"站名"和"时刻"的行——宁可漏掉一条模糊断言，
    也不把一句闲聊当成车次事实。

    未知站名也要收：如果模型说"G677 从北京西站 08:00 发车"，
    而 G677 实际是上海虹桥→汉口，"北京西站"就不是本车次车站，
    这是站名层面的错误，必须判错——只按时刻判会把它漏掉。
    """
    rows, unknown = [], []
    ordered = sorted((s for s in stations if s), key=len, reverse=True)
    for line in text.split("\n"):
        line = line.strip()
        if not line:
            continue
        times = [f"{int(h):02d}:{m}" for h, m in TIME_RE.findall(line)]
        if not times:
            continue
        rest, hit = line, []
        # 最长站名优先匹配，匹配后挖空，避免"南京"抢占"南京南"
        for st in ordered:
            if st in rest:
                hit.append(st)
                rest = rest.replace(st, "\u3000")
        for st in hit:
            rows.append({"station": st, "times": times, "line": line[:120]})
        # 挖空后仍以"站"结尾的，视为提到了本车次以外的车站
        for name in STATION_REF.findall(rest):
            # "当日到站""终到站""次日到站"这类是描述词，不是站名
            if name in NOT_A_STATION or name.endswith("到") or name.endswith("日"):
                continue
            unknown.append({"station": name, "times": times, "line": line[:120]})
    return rows, unknown


def judge_train(train_no: str, text: str, info: dict | None) -> dict:
    """对一道题（一个目标车次）做逐站核验"""
    base = {"train": train_no}
    if not info:
        return {**base, "verdict": "unknown", "detail": "权威车次库未收录该车次",
                "correct": 0, "mismatch": 0, "total": 0, "skipped": 0, "rows": []}

    # 口径只核验「经停站」：VR 卡的 stops 是逐站到发时刻，
    # 而 passage 顶部的出发/到达时间是全程首末时刻，混进来会让分母口径不纯。
    # 因此起终点不补进 stops，遇到相关断言单独计数、不计入分母。
    stops = {s["station"]: s for s in info.get("stops", []) if s.get("station")}
    terminals = {x for x in (info.get("from_station"), info.get("to_station")) if x}
    claims, unknown = parse_station_claims(text, set(stops))
    seen, rows, skipped = set(), [], 0
    for c in claims:
        st = c["station"]
        if st in seen:          # 同一站重复提及只判一次
            continue
        seen.add(st)
        s = stops.get(st)
        if not s:
            continue
        arr, dep = (s.get("arr") or "").strip(), (s.get("dep") or "").strip()
        if not (FULL_TIME.match(arr) or FULL_TIME.match(dep)):
            skipped += 1        # 官方数据被截断，不能拿来判人错
            continue
        hit_arr = bool(FULL_TIME.match(arr)) and arr in c["times"]
        hit_dep = bool(FULL_TIME.match(dep)) and dep in c["times"]
        rows.append({
            "station": st,
            "verdict": "correct" if (hit_arr or hit_dep) else "mismatch",
            "claim": c["times"],
            "official_arr": arr, "official_dep": dep,
            "granularity": "arr" if hit_arr else ("dep" if hit_dep else ""),
        })

    # 站名错：模型提到了带时刻的车站，但该站根本不在本车次经停表里
    terminals_skipped = 0
    for u in unknown:
        if u["station"] in terminals:
            terminals_skipped += 1   # 起终点不在逐站表内，跳过而不是判错
            continue
        key = u["station"] + "*"
        if key in seen:
            continue
        seen.add(key)
        rows.append({
            "station": f"{u['station']}站（非本车次车站）",
            "verdict": "mismatch",
            "claim": u["times"],
            "official_arr": "", "official_dep": "",
            "granularity": "",
        })

    ok = sum(1 for r in rows if r["verdict"] == "correct")
    bad = sum(1 for r in rows if r["verdict"] == "mismatch")
    return {
        **base, "verdict": "checked" if rows else "unknown",
        "correct": ok, "mismatch": bad, "total": len(rows), "skipped": skipped,
        "terminals_skipped": terminals_skipped,
        "rows": rows,
        "fetched_at": info.get("fetched_at", ""),
        "stale": bool(info.get("_stale")),
        "source_url": info.get("_source_url", "") or info.get("_source_url", ""),
    }


def verify_answer(client, model: str, qid: str, question: str, answer: str, refresh: bool = False) -> dict:
    """一道题：从题干定目标车次 → 取权威数据 → 逐站核验"""
    nos = [m.upper() for m in TRAIN_NO.findall(question)]
    if not nos:
        return {"qid": qid, "model": model, "question": question, "train": "",
                "verdict": "no_target", "detail": "题干未指定单一车次（多车次/开放题，不做逐站核验）",
                "correct": 0, "mismatch": 0, "total": 0, "skipped": 0, "rows": []}
    train_no = nos[0]
    try:
        info = fetch_official(client, train_no, refresh=refresh)
    except Exception as e:
        return {"qid": qid, "model": model, "question": question, "train": train_no,
                "verdict": "api_error", "detail": str(e)[:160],
                "correct": 0, "mismatch": 0, "total": 0, "skipped": 0, "rows": []}

    r = judge_train(train_no, answer, info)
    r.update({"qid": qid, "model": model, "question": question,
              "answer_len": len(answer), "head": answer.replace("\n", " ")[:110]})
    return r


def summarize(per_question: list[dict]) -> dict:
    """汇总：只有 checked 的题贡献分母"""
    ok = sum(q.get("correct", 0) for q in per_question)
    bad = sum(q.get("mismatch", 0) for q in per_question)
    denom = ok + bad
    return {
        "questions": len(per_question),
        "correct": ok,
        "mismatch": bad,
        "decidable_stations": denom,
        "accuracy": round(ok / denom, 4) if denom else None,
        "unknown_questions": sum(1 for q in per_question if q.get("verdict") == "unknown"),
        "skipped_stations": sum(q.get("skipped", 0) for q in per_question),
    }


if __name__ == "__main__":
    import sys

    try:
        from wsa_client import WsaClient
        c = WsaClient()
    except ValueError:
        c = None
        print("! 未检测到密钥，走离线缓存")

    demo = sys.argv[1] if len(sys.argv) > 1 else "G677：上海虹桥 10:25 发车，汉口 14:44 到达"
    print(json.dumps(verify_answer(c, "demo", "demo", "G677 次高铁的时刻？", demo),
                     ensure_ascii=False, indent=1))
