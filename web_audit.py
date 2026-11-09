# -*- coding: utf-8 -*-
"""网络信息可信度审计：
同一个车次，网页（Mode=0 自然结果）怎么说 vs 官方 VR 卡（Mode=1）怎么说。
全部依赖元宝搜索自身的两种模式对比，不依赖任何外部模型。"""
import json
import os
import re
import time

from wsa_client import WsaClient

BASE = os.path.dirname(os.path.abspath(__file__))

TRAINS = ["G677", "G1", "G3", "G27", "K79", "Z386",
          "G1847", "G1684", "K2084", "C260", "G2556", "G676",
          "G7", "G11", "G31", "G55", "K117", "Z21",
          "T110", "D2281", "G7008", "K511"]

TIME_RE = re.compile(r"(?:始发时间|发车时间|出发时间|开车时间|开点)[：:\s]*([0-2]?\d[:：][0-5]\d)")
ROUTE_RE = re.compile(r"(?:从|由)\s*([\u4e00-\u9fa5]{2,8}站?)\s*(?:开往|开向|发往|到)\s*([\u4e00-\u9fa5]{2,8}站?)")


def norm(t: str) -> str:
    t = t.replace("：", ":").strip()
    if ":" in t:
        h, m = t.split(":")[:2]
        return f"{int(h):02d}:{int(m):02d}"
    return t


def mentions_train(train: str, title: str) -> bool:
    """标题里必须精确出现该车次号（排除 G2701 / K7901 / G17 这类近似号）"""
    return re.search(r"(?<![A-Za-z0-9])" + re.escape(train) + r"(?![0-9])", title) is not None


def get_official(c: WsaClient, train: str) -> dict | None:
    ps = c.pages(train, mode=1, cnt=10)
    vrs = [p for p in ps if p.get("vr")]
    if not vrs:
        return None
    v = vrs[0]
    pas = v.get("passage", "")
    info = {"vrid": v.get("vrid", ""), "url": v.get("url", "")}
    for k in ["始发站", "终点站", "出发时间", "到达时间", "全程时间", "火车类型"]:
        m = re.search(rf"#\s*{k}[：:]\s*(\S+)", pas)
        if m:
            info[k] = m.group(1)
    stops = re.findall(r"经停站名称：(\S+)\n到站时间：(\S+)\n发车时间：(\S+)", pas)
    info["stops"] = [{"station": a, "arrive": b, "depart": d} for a, b, d in stops]
    return info


def audit_web(c: WsaClient, train: str, official: dict) -> list[dict]:
    pages = c.pages(f"{train} 次列车 时刻表 发车时间", mode=0, cnt=10)
    off_time = norm(official.get("出发时间", ""))
    off_from = (official.get("始发站") or "").replace("站", "")
    off_to = (official.get("终点站") or "").replace("站", "")
    rows = []
    for p in pages:
        text = (p.get("content") or "")[:1200]
        title = p.get("title", "")
        site = p.get("site", "")
        tm = TIME_RE.search(text)
        rt = ROUTE_RE.search(text)
        claim_time = norm(tm.group(1)) if tm else ""
        claim_from = rt.group(1).replace("站", "") if rt else ""
        claim_to = rt.group(2).replace("站", "") if rt else ""

        if not mentions_train(train, title):
            verdict = "irrelevant"
            basis = "标题未出现该车次号（相似车次噪声）"
        elif claim_time and off_time:
            verdict = "match" if claim_time == off_time else "mismatch"
            basis = f"发车时间 {claim_time}（官方 {off_time}）"
        elif claim_from and claim_to and off_from:
            ok_from = claim_from in off_from or off_from in claim_from
            ok_to = claim_to in off_to or off_to in claim_to
            verdict = "match" if (ok_from and ok_to) else "mismatch"
            basis = f"线路 {claim_from}→{claim_to}（官方 {off_from}→{off_to}）"
        else:
            verdict = "undetermined"
            basis = "摘要中无明确时间/线路声明"

        rows.append({
            "train": train, "site": site, "title": title[:60],
            "url": p.get("url", ""), "verdict": verdict, "basis": basis,
            "claim_time": claim_time, "claim_route": f"{claim_from}→{claim_to}" if claim_from else "",
        })
    return rows


def main():
    c = WsaClient()
    all_rows, official_map = [], {}
    for t in TRAINS:
        try:
            off = get_official(c, t)
        except RuntimeError as e:
            print(f"[{t}] 权威值获取失败: {str(e)[:70]}", flush=True)
            off = None
        if not off:
            print(f"[{t}] VR 无召回，跳过", flush=True)
            official_map[t] = None
            continue
        official_map[t] = off
        print(f"[{t}] 官方: {off.get('始发站')} {off.get('出发时间')} -> {off.get('终点站')} {off.get('到达时间')} | 经停 {len(off.get('stops', []))} 站", flush=True)
        time.sleep(0.8)
        rows = audit_web(c, t, off)
        all_rows.extend(rows)
        cnt = {}
        for r in rows:
            cnt[r["verdict"]] = cnt.get(r["verdict"], 0) + 1
        print(f"      网页判定: {cnt}", flush=True)
        time.sleep(0.8)

    outs = {"official": official_map, "web_rows": all_rows}
    with open(os.path.join(BASE, "web_audit_results.json"), "w", encoding="utf-8") as f:
        json.dump(outs, f, ensure_ascii=False, indent=1)

    judged = [r for r in all_rows if r["verdict"] in ("match", "mismatch")]
    bad = [r for r in judged if r["verdict"] == "mismatch"]
    irr = [r for r in all_rows if r["verdict"] == "irrelevant"]
    print("\n================ 汇总 ================")
    print(f"覆盖车次: {sum(1 for v in official_map.values() if v)}/{len(TRAINS)}")
    print(f"网页条目总数: {len(all_rows)}")
    print(f"车内噪声剔除（标题非该车次）: {len(irr)}")
    print(f"可判定（有明确时间/线路声明）: {len(judged)}")
    print(f"与官方不符: {len(bad)}")
    if judged:
        print(f"网络信息失效率: {len(bad)/len(judged)*100:.1f}%")
    print(f"明细 -> web_audit_results.json")


if __name__ == "__main__":
    main()
