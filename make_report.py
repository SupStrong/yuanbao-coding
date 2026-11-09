# -*- coding: utf-8 -*-
"""把 results.json 渲染成 HTML 验真报告：KPI + 逐题卡片 + 逐站断言表"""
import json
import os

BASE = os.path.dirname(os.path.abspath(__file__))

V = {
    "correct": ("#eaf3de", "#3b6d11", "属实"),
    "mismatch": ("#fcebeb", "#a32d2d", "不符"),
    "unknown": ("#f1efe8", "#5f5e5a", "存疑"),
    "no_target": ("#f1efe8", "#5f5e5a", "跳过"),
    "api_error": ("#fbeaf0", "#993556", "接口异常"),
}


def _esc(s) -> str:
    return (str(s) if s is not None else "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _question_card(r: dict) -> str:
    _, fg, label = V.get(r["verdict"], ("#f1efe8", "#444", r["verdict"]))
    head = (f'<div class="qhead"><span class="badge" style="background:{fg}">{label}</span>'
            f'<b>{_esc(r.get("train") or "—")}</b>'
            f'<span class="muted">{_esc(r["qid"])} · {_esc(r["question"])[:40]}</span></div>')

    if r["verdict"] in ("unknown", "no_target", "api_error"):
        return (f'<div class="card" style="border-left:4px solid {fg}">{head}'
                f'<div class="note-in">{_esc(r.get("detail", ""))}</div></div>')

    body = ""
    if r.get("rows"):
        trs = []
        for row in r["rows"]:
            _, rfg, rlabel = V[row["verdict"]]
            claim = "、".join(row["claim"][:4]) or "—"
            trs.append(f'<tr><td><b>{_esc(row["station"])}</b></td>'
                       f'<td>{_esc(claim)}</td>'
                       f'<td>{_esc(row["official_arr"]) or "—"}</td>'
                       f'<td>{_esc(row["official_dep"]) or "—"}</td>'
                       f'<td style="color:{rfg};font-weight:600">{rlabel}</td></tr>')
        body = ('<table><thead><tr><th>车站</th><th>模型断言</th><th>官方到站</th>'
                '<th>官方发车</th><th>判定</th></tr></thead><tbody>'
                + "".join(trs) + "</tbody></table>")

    foot = []
    if r.get("skipped"):
        foot.append(f'{r["skipped"]} 站因官方时刻截断而跳过（不计入分母）')
    if r.get("stale"):
        foot.append("本条基于过期缓存（stale），仅供参考")
    src = f'<a href="{_esc(r["source_url"])}" target="_blank">权威源</a>' if r.get("source_url") else ""
    foot_html = f'<div class="foot">{"；".join(foot)}{("　" + src) if src else ""}</div>' if (foot or src) else ""
    return f'<div class="card" style="border-left:4px solid {fg}">{head}{body}{foot_html}</div>'


def render(results: list[dict], by_model: dict, out_path: str) -> None:
    total_correct = sum(s["correct"] for s in by_model.values())
    total_decidable = sum(s["decidable_stations"] for s in by_model.values())

    kpis = "".join(
        f'<div><b>{s["correct"]}/{s["decidable_stations"]}</b>{_esc(m)}</div>'
        for m, s in by_model.items()
    )
    kpis += f'<div><b>{total_correct}/{total_decidable}</b>合计可判定</div>'

    blocks = []
    for m in by_model:
        qs = sorted([r for r in results if r.get("model") == m], key=lambda x: x["qid"])
        checked = [q for q in qs if q["verdict"] == "checked"]
        blocks.append(
            f'<h2>{_esc(m)}</h2>'
            f'<div class="sub">{len(qs)} 题，其中 {len(checked)} 题可逐站核验</div>'
            + "".join(_question_card(q) for q in qs)
        )

    html = f'''<!DOCTYPE html><html lang="zh-CN"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>AI 车次断言验真报告</title><style>
*{{box-sizing:border-box}}
body{{font-family:"Microsoft YaHei","PingFang SC",sans-serif;max-width:900px;margin:0 auto;
padding:32px 20px 60px;background:#fafbfc;color:#1f2328;line-height:1.65}}
h1{{font-size:26px;margin:0 0 6px;border-bottom:3px solid #e34040;padding-bottom:12px}}
h2{{font-size:18px;margin:34px 0 4px;padding-left:9px;border-left:4px solid #e34040}}
.sub{{color:#6a737d;font-size:13px;margin-bottom:10px}}
.note{{background:#fff8e6;border-left:4px solid #d97706;padding:10px 14px;font-size:13px;margin:16px 0}}
.kpi{{display:flex;gap:12px;flex-wrap:wrap;margin:18px 0}}
.kpi div{{flex:1;min-width:130px;background:#fff;border:1px solid #e1e4e8;border-radius:8px;
padding:12px;text-align:center;font-size:13px;color:#57606a}}
.kpi b{{display:block;font-size:21px;color:#e34040;margin-bottom:2px}}
.card{{background:#fff;border:1px solid #e1e4e8;border-radius:8px;padding:13px 16px;margin:10px 0;font-size:14px}}
.qhead{{display:flex;align-items:center;gap:8px;flex-wrap:wrap}}
.badge{{color:#fff;font-size:12px;border-radius:10px;padding:2px 10px}}
.muted{{color:#6a737d;font-size:12px}}
table{{width:100%;border-collapse:collapse;margin-top:9px;font-size:13px}}
th,td{{text-align:left;padding:5px 8px;border-bottom:1px solid #eef0f2}}
th{{background:#f6f8fa;color:#57606a;font-weight:600}}
.foot{{margin-top:7px;color:#8b949e;font-size:12px}}
.note-in{{color:#57606a;font-size:13px;margin-top:4px}}
a{{color:#185fa5}}
</style></head><body>
<h1>AI 车次断言验真报告</h1>
<div class="note">验真数据源：腾讯云元宝搜索 SearchPro · VR 权威信源卡（火车时刻，Mode=1）。
判定粒度是「车站 + 时刻」，不是整段回答。准确率只按可判定站点计算，权威库未收录一律记为「存疑」而不是「编造」。</div>
<div class="kpi">{kpis}</div>
{"".join(blocks)}
</body></html>'''
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)
    print("报告已生成:", out_path)


if __name__ == "__main__":
    data = json.load(open(os.path.join(BASE, "results.json"), encoding="utf-8"))
    render(data["questions"], data["models"], os.path.join(BASE, "验真报告.html"))
