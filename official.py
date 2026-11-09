# -*- coding: utf-8 -*-
"""从元宝搜索 VR 卡抽取官方车次时刻（逐站到发时刻），带日期戳缓存。

缓存设计要点（对应文章 6.4 节）：
1. 每条缓存都写入 fetched_at（UTC ISO8601），没有时间戳的缓存视为不可信；
2. 超过 TTL（默认 7 天）视为过期——铁路调图后同一趟车的时刻会变；
3. 过期不等于报错：有 client 就重新抓，没有 client 就降级用旧数据并标 _stale=True，
   让报告显式显示"这条判定基于过期数据"，而不是悄悄当成权威。
"""
import calendar
import json
import re
import time
from pathlib import Path

CACHE = Path(__file__).parent / "official_trains.json"
FETCH_TTL = 7 * 24 * 3600  # 7 天


# ---------- 时间戳工具 ----------
def now_iso() -> str:
    """当前 UTC 时间，形如 2026-11-09T02:40:00Z"""
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _age_seconds(iso: str) -> float:
    """该时间戳距今的秒数；解析失败返回极大值（视为过期）"""
    try:
        return time.time() - calendar.timegm(time.strptime(iso, "%Y-%m-%dT%H:%M:%SZ"))
    except (ValueError, TypeError):
        return float("inf")


def is_fresh(entry, ttl: int = FETCH_TTL) -> bool:
    """缓存条目是否仍在有效期内。没有 fetched_at 一律判过期。"""
    if not isinstance(entry, dict):
        return False
    ts = entry.get("fetched_at")
    if not ts:
        return False
    return _age_seconds(ts) < ttl


# ---------- VR 卡解析 ----------
def _parse_passage(passage: str) -> dict:
    """解析 VR 卡 passage，得到车次基本信息 + 逐站到发时刻"""
    d = {"stops": []}
    kv = {
        "始发站": "from_station", "终点站": "to_station", "火车类型": "train_type",
        "车次": "train_no", "出发时间": "dep_time", "到达时间": "arr_time", "全程时间": "duration",
    }
    for line in passage.splitlines():
        line = line.strip()
        if not line.startswith("#"):
            continue
        body = line.lstrip("# ").strip()
        for cn, en in kv.items():
            if body.startswith(cn + "："):
                d[en] = body.split("：", 1)[1].strip()

    # 逐站：经停站名称 / 到站时间 / 发车时间 / 停留时长
    blocks = re.split(r"经停站名称：", passage)[1:]
    for b in blocks:
        name = b.split("\n", 1)[0].strip()
        arr = re.search(r"到站时间：([^\n]*)", b)
        dep = re.search(r"发车时间：([^\n]*)", b)
        stay = re.search(r"停留时长：([^\n]*)", b)
        clean = lambda m: (m.group(1).strip() if m else "").replace("----", "").strip()
        d["stops"].append({
            "station": name,
            "arr": clean(arr),
            "dep": clean(dep),
            "stay": clean(stay),
        })
    return d


# ---------- 读写缓存 ----------
def load_cache() -> dict:
    return json.loads(CACHE.read_text(encoding="utf-8")) if CACHE.exists() else {}


def save_cache(cache: dict) -> None:
    CACHE.write_text(json.dumps(cache, ensure_ascii=False, indent=1), encoding="utf-8")


def fetch_official(client, train_no: str, refresh: bool = False, ttl: int = FETCH_TTL) -> dict | None:
    """取单个车次的官方数据。

    - 缓存 fresh 且非 refresh：直接返回
    - 缓存 stale 且 client 为 None：返回旧数据并标 _stale=True（降级，不静默当权威）
    - 缓存缺失/stale 且有 client：重新抓取并写入 fetched_at
    - 接口无 VR 卡召回：写入 _empty 记录（同样带 fetched_at，避免每次都重试）
    """
    cache = load_cache()
    entry = cache.get(train_no)

    if not refresh and is_fresh(entry, ttl):
        return None if entry.get("_empty") else entry

    if client is None:
        # 离线模式：只能退回旧数据，并明确标记过期
        if isinstance(entry, dict) and not entry.get("_empty"):
            stale = dict(entry)
            stale["_stale"] = True
            return stale
        return None

    pages = client.pages(f"{train_no} 次列车 时刻表", mode=1, cnt=10)
    vrs = [p for p in pages if p.get("vr")]
    if not vrs:
        cache[train_no] = {"_empty": True, "fetched_at": now_iso()}
    else:
        info = _parse_passage(vrs[0].get("passage", ""))
        info["_source_url"] = vrs[0].get("url", "")
        info["_vrid"] = vrs[0].get("vrid", "")
        info["fetched_at"] = now_iso()
        info["_stale"] = False
        cache[train_no] = info
    save_cache(cache)
    entry = cache[train_no]
    return None if entry.get("_empty") else entry


def all_official(client, trains: list[str], refresh: bool = False) -> dict:
    return {t: fetch_official(client, t, refresh) for t in trains}


if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(Path(__file__).parent))

    trains = ["G677", "K79", "G2556", "C260", "D8494", "G1847"]

    # 离线模式：不构造 client，直接用仓库内缓存
    data = all_official(None, trains)
    for t, v in data.items():
        if not v:
            print(f"{t:<8} 无权威数据（VR 卡未收录或缓存缺失）")
            continue
        flag = " [缓存已过期]" if v.get("_stale") else ""
        print(f"{t:<8} {v.get('from_station')}→{v.get('to_station')}  "
              f"{v.get('dep_time')}—{v.get('arr_time')}  经停{len(v['stops'])}站"
              f"  fetched_at={v.get('fetched_at')}{flag}")
        for s in v["stops"][:3]:
            print(f"    {s['station']:<8} 到{s['arr'] or '--':<6} 发{s['dep'] or '--':<6} 停{s['stay']}")
