# -*- coding: utf-8 -*-
"""
多垂类断言核验：同一套三态框架，跑在金价 / 股价上。

与 verify.py（火车）共用的东西：
- 权威值来自元宝搜索 VR 卡（Mode=1），含当日最高/最低与快照时间
- 被验对象来自检索结果（Mode=0），即"联网模型真正读到的原料"
- 判定仍是三态：correct / mismatch / uncertain

不同的东西（对应文章 11.2 / 11.3）：
- 断言形态：火车是 (车次, 站, 到/发, 时刻)；价格是 (品种, 口径, 数值, 时点)
- 比对器：时刻是等值 + ±1 分钟；价格是相对区间 ±0.5%
- 额外约束：价格必须带时点。时点对不上官方快照，只能判"不可判"，不能判"不符"

用法:
    python multi_vertical.py            # 结果写入 multi_vertical_result.json
"""
import json
import re
import time
from pathlib import Path

from wsa_client import WsaClient

TOL = 0.005          # 价格容差 ±0.5%
ALIGN_MIN = 60       # 时点与官方快照的允许偏差（分钟）

CONFIGS = [
    {
        "key": "gold",
        "name": "金价",
        "query": "今日黄金价格多少钱一克",
        "unit": "元/克",
        "official_re": r"价格值类型：国内价格\(元/克\)(?s:.*?)价格：([\d.]+)",
        "range_re": [r"价格值类型：最高\s*\n?\s*价格值：([\d.]+)", r"价格值类型：最低\s*\n?\s*价格值：([\d.]+)"],
        "claim_re": [r"黄金大盘价格\s*([\d.]+)", r"国内金价\s*([\d.]+)"],
        "time_re": r"(\d{2}:\d{2}:\d{2})",
        "date_re": r"(\d{4})年(\d{1,2})月(\d{1,2})日",
        "semantics": "intraday",      # 盘中连续变量：必须时点对齐才可判
    },
    {
        "key": "stock",
        "name": "股价",
        "query": "贵州茅台股价",
        "unit": "元/股",
        "official_re": r"实时股价：([\d.]+)",
        "range_re": [r"今日最高价：([\d.]+)", r"今日最低价：([\d.]+)"],
        # 每个信源的摘要格式不同，抽取必须按站点适配（这本身就是迁移成本）
        "claim_re": [
            r"贵州茅台\s+([\d,]+\.\d{2})",
            r"[现現]价[（(]人民币[)）]\s*[▼▲]?\s*([\d,]+\.\d{1,3})",
            r"貴州茅台\s*([\d,]+\.\d{3})",
            r"\(600519\.SS\)\s*([\d,]+\.\d{2})",
            r"600519\.SH\)\s*[-\d.%\s]*?([\d,]{4,7}\.\d{2})",
            r"最新[:：]\s*([\d,]+\.\d{2})",
        ],
        "time_re": r"(\d{4}[-/]\d{1,2}[-/]\d{1,2}[ T]\d{2}:\d{2}(?::\d{2})?)",
        "date_re": None,
        "semantics": "daily_close",   # 已收盘：日终快照，同日的数值可直接比
    },
]


def _num(s):
    return float(s.replace(",", ""))


def get_official(client, cfg):
    pages = client.pages(cfg["query"], mode=1)
    for p in pages:
        if p.get("vr_category") != cfg["key"]:
            continue
        passage = p.get("passage") or ""
        m = re.search(cfg["official_re"], passage)
        if not m:
            continue
        rng = []
        for pat in cfg["range_re"]:
            mr = re.search(pat, passage)
            rng.append(_num(mr.group(1)) if mr else None)
        stamp = ""
        mt = re.search(r"更新时间：(\d{10})", passage)
        if mt:
            stamp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(int(mt.group(1))))
        else:
            mt = re.search(r"更新时间：(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})", passage)
            if mt:
                stamp = mt.group(1)
        status = ""
        ms = re.search(r"交易状态：(on|off|已收盘|休市)", passage)
        if ms:
            status = ms.group(1)
        return {"vrid": p.get("vrid"), "value": _num(m.group(1)), "unit": cfg["unit"],
                "site": p.get("site"), "stamp": stamp, "status": status,
                "high": rng[0] if rng else None, "low": rng[1] if len(rng) > 1 else None}
    return None


def get_claims(client, cfg):
    pages = client.pages(cfg["query"], mode=0, cnt=10)
    out = []
    for p in pages:
        passage = p.get("passage") or ""
        title = p.get("title") or ""
        hit = None
        for pat in cfg["claim_re"]:
            hit = re.search(pat, title) or re.search(pat, passage)
            if hit:
                break
        if not hit:
            out.append({"site": p.get("site"), "title": title[:42], "price": None,
                        "stamp": "", "ctx": passage[:60].replace("\n", " ")})
            continue
        mt = re.search(cfg["time_re"], passage) or re.search(cfg["time_re"], title)
        stamp = mt.group(1).replace("/", "-") if mt else ""
        if not stamp and cfg.get("date_re"):
            md = re.search(cfg["date_re"], passage)
            if md:
                stamp = f"{md.group(1)}-{int(md.group(2)):02d}-{int(md.group(3)):02d}"
        page_date = (p.get("date") or "").replace("/", "-")[:10]
        # 有效日期：显式时间戳 > "收市:11月6日" 这类声明 > 页面 date
        eff = stamp[:10] if len(stamp) >= 10 else ""
        if not eff:
            mc = re.search(r"收[市盤][:：]\s*(\d{1,2})月(\d{1,2})日", passage)
            if mc:
                eff = f"{(page_date or '2026')[:4]}-{int(mc.group(1)):02d}-{int(mc.group(2)):02d}"
        if not eff:
            eff = page_date
        out.append({"site": p.get("site"), "title": title[:42], "price": _num(hit.group(1)),
                    "stamp": stamp, "page_date": page_date, "eff_date": eff,
                    "ctx": passage[max(0, hit.start() - 20):hit.end() + 16].replace("\n", " ")})
    return out


def _minutes(a, b):
    """两个 'YYYY-MM-DD HH:MM:SS' 的分钟差；任一方不完整则返回 None"""
    if len(a) < 19 or len(b) < 19:
        return None
    ta = time.mktime(time.strptime(a[:19], "%Y-%m-%d %H:%M:%S"))
    tb = time.mktime(time.strptime(b[:19], "%Y-%m-%d %H:%M:%S"))
    return abs(ta - tb) / 60


def judge(claims, official, semantics):
    val, hi, lo = official["value"], official["high"], official["low"]
    tol_lo, tol_hi = val * (1 - TOL), val * (1 + TOL)
    off_date = (official["stamp"] or "")[:10]
    closed = "收盘" in (official.get("status") or "") or "休市" in (official.get("status") or "")
    for c in claims:
        if c["price"] is None:
            c["verdict"], c["why"] = "unknown", "摘要里没有该口径的价格字段"
            continue
        diff = (c["price"] - val) / val * 100
        c["diff_pct"] = round(diff, 2)
        stamp = c["stamp"]
        if len(stamp) == 8:                       # 只有时分秒 → 用页面日期补全
            stamp = f"{c['page_date']} {stamp}"
        c["stamp_full"] = stamp
        same_day = bool(c["eff_date"]) and c["eff_date"] == off_date
        in_range = (lo is None or c["price"] >= lo) and (hi is None or c["price"] <= hi)
        gap = _minutes(stamp, official["stamp"] or "")

        if semantics == "daily_close":
            if same_day:
                ok = tol_lo <= c["price"] <= tol_hi
                c["verdict"] = "correct" if ok else "mismatch"
                c["why"] = "已收盘，同日快照可直接比" + ("" if ok else "，差值超出 ±0.5%")
            else:
                c["verdict"] = "uncertain"
                c["why"] = "时点不在同一交易日，无法确认是否为当日收盘价"
        else:                                      # intraday：连续变量，必须时点对齐
            if same_day and gap is not None and gap <= ALIGN_MIN:
                ok = tol_lo <= c["price"] <= tol_hi
                c["verdict"] = "correct" if ok else "mismatch"
                c["why"] = f"与官方快照相距 {gap:.0f} 分钟" + ("" if ok else "，差值超出 ±0.5%")
            elif not in_range:
                c["verdict"] = "uncertain"
                c["why"] = "落在当日区间外，但时点不可确认（可能是旧数据）"
            else:
                c["verdict"] = "uncertain"
                c["why"] = "盘中连续变量，时点差 " + (f"{gap:.0f} 分钟" if gap is not None else "未知") + "，数值不可比"
    return claims


def main():
    client = WsaClient()
    result = {"generated_at": time.strftime("%Y-%m-%d %H:%M:%S"), "tol": TOL, "verticals": []}
    for cfg in CONFIGS:
        official = get_official(client, cfg)
        if not official:
            print(f"[跳过] {cfg['name']}：VR 卡未召回或不含权威值")
            continue
        claims = judge(get_claims(client, cfg), official, cfg["semantics"])
        n = {k: sum(1 for c in claims if c["verdict"] == k) for k in ("correct", "mismatch", "uncertain", "unknown")}
        result["verticals"].append({"key": cfg["key"], "name": cfg["name"], "query": cfg["query"],
                                    "official": official, "claims": claims, "summary": n})
        print(f"\n===== {cfg['name']}：官方 {official['value']} {official['unit']} "
              f"（{official['site']}，快照 {official['stamp']}，当日区间 "
              f"{official['low']}–{official['high']}）=====")
        for c in claims:
            d = f"{c['diff_pct']:+6.2f}%" if "diff_pct" in c else "     —"
            print(f"  [{c['verdict']:9s}] {str(c['site'])[:13]:13s} {str(c['price'] or '—'):>9s} {d} "
                  f"{c['stamp'][:19]:19s} {c['why']}")
        print(f"  → 正确 {n['correct']}｜不符 {n['mismatch']}｜不可判 {n['uncertain']}｜无数值 {n['unknown']}")

    out = Path(__file__).parent / "multi_vertical_result.json"
    out.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n结果已写入 {out.name}")


if __name__ == "__main__":
    main()
