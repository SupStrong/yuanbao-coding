# -*- coding: utf-8 -*-
"""一键跑完整验真管线：

    模型回答 (answers/*.json)
        -> 题干定目标车次
        -> official 取 VR 卡权威逐站时刻（缓存优先，带 fetched_at 与 TTL）
        -> verify 逐站四态判定
        -> results.json + 验真报告.html

用法：
    python run_verify.py                     # 跑 answers/ 下全部模型
    python run_verify.py answers/doubao.json # 只跑一个
    python run_verify.py --refresh           # 忽略缓存，重新抓权威数据

没有 .env 密钥时自动进入离线模式（用仓库内 official_trains.json），
判定会标 stale=True，结论照样可复现——clone 下来就能跑。
"""
import glob
import json
import os
import sys

from make_report import render
from verify import summarize, verify_answer
from wsa_client import WsaClient

BASE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(BASE, "results.json")
REPORT = os.path.join(BASE, "验真报告.html")


def make_client():
    try:
        return WsaClient()
    except ValueError:
        print("! 未检测到 TENCENTCLOUD_SECRET_ID / SECRET_KEY，进入离线缓存模式")
        print("  （cp .env.example .env 并填入密钥即可联网刷新）\n")
        return None


def main():
    args = sys.argv[1:]
    refresh = "--refresh" in args
    files = [a for a in args if not a.startswith("--")]
    if not files:
        files = sorted(glob.glob(os.path.join(BASE, "answers", "*.json")))
    if not files:
        print("answers/ 下没有模型回答文件")
        return

    client = make_client()
    results, by_model = [], {}

    for f in files:
        data = json.load(open(f, encoding="utf-8"))
        model = data.get("model", os.path.basename(f))
        print(f"===== 模型：{model}（{len(data['answers'])} 题）=====")
        per = []
        for a in data["answers"]:
            r = verify_answer(client, model, a["qid"], a["question"], a["answer"], refresh=refresh)
            per.append(r)
            results.append(r)
            if r["verdict"] == "unknown":
                tag = "存疑（权威库未收录）"
            elif r["verdict"] == "no_target":
                tag = "跳过（题干无单一车次）"
            elif r["verdict"] == "api_error":
                tag = "接口异常"
            else:
                tag = f"可比对 {r['total']} 站：正确 {r['correct']}，不符 {r['mismatch']}"
            print(f"  [{r['qid']}] {r.get('train', '') or '-':<7} {tag}")
        s = summarize(per)
        by_model[model] = s
        acc = "—" if s["accuracy"] is None else f"{s['accuracy'] * 100:.0f}%"
        print(f"  → 小计：{s['correct']}/{s['decidable_stations']} 站正确（{acc}）\n")

    with open(OUT, "w", encoding="utf-8") as fp:
        json.dump({"models": by_model, "questions": results}, fp, ensure_ascii=False, indent=1)

    print("===== 汇总 =====")
    for m, s in by_model.items():
        acc = "—" if s["accuracy"] is None else f"{s['accuracy'] * 100:.1f}%"
        print(f"  {m}: 正确 {s['correct']} / 可判定 {s['decidable_stations']} 站"
              f"（准确率 {acc}），存疑 {s['unknown_questions']} 题，截断跳过 {s['skipped_stations']} 站")
    stale = sum(1 for r in results if r.get("stale"))
    if stale:
        print(f"  ! 其中 {stale} 题使用过期缓存（stale=True），报告中已标注")

    render(results, by_model, REPORT)
    print(f"明细：{OUT}（{len(results)} 题）")


if __name__ == "__main__":
    main()
