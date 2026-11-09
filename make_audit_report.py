# -*- coding: utf-8 -*-
"""把网络信息审计结果渲染成 HTML 报告"""
import collections
import json
import os

BASE = os.path.dirname(os.path.abspath(__file__))
d = json.load(open(os.path.join(BASE, "web_audit_results.json"), encoding="utf-8"))
rows, official = d["web_rows"], d["official"]

cnt = collections.Counter(r["verdict"] for r in rows)
total = len(rows)
judged = cnt["match"] + cnt["mismatch"]
bad = cnt["mismatch"]
irr = cnt["irrelevant"]
und = cnt["undetermined"]

site = collections.defaultdict(lambda: [0, 0])
for r in rows:
    if r["verdict"] in ("match", "mismatch"):
        site[r["site"]][1] += 1
        if r["verdict"] == "mismatch":
            site[r["site"]][0] += 1
site_rows = [(s, b, t) for s, (b, t) in site.items() if t >= 4]
site_rows.sort(key=lambda x: -(x[1] / x[2]))

per_train = collections.defaultdict(lambda: collections.Counter())
for r in rows:
    per_train[r["train"]][r["verdict"]] += 1


def pct(a, b):
    return f"{a / b * 100:.1f}%" if b else "—"


site_html = ""
for s, b, t in site_rows:
    w = b / t * 100
    color = "#e5484d" if w >= 30 else ("#f5a524" if w > 0 else "#30a46c")
    site_html += f"""
    <div class="bar-row">
      <span class="bar-label">{s}</span>
      <span class="bar-track"><span class="bar-fill" style="width:{max(w,1.5):.1f}%;background:{color}"></span></span>
      <span class="bar-val">{b}/{t}</span>
    </div>"""

train_html = ""
for t in sorted(per_train):
    o = official.get(t) or {}
    c = per_train[t]
    j = c["match"] + c["mismatch"]
    cls = "bad" if c["mismatch"] else ("ok" if j else "none")
    train_html += f"""<tr>
      <td><b>{t}</b></td>
      <td>{o.get('始发站','—')} <span class="mono">{o.get('出发时间','—')}</span></td>
      <td>{o.get('终点站','—')} <span class="mono">{o.get('到达时间','—')}</span></td>
      <td class="c">{c['match']}</td>
      <td class="c {cls}">{c['mismatch'] or '—'}</td>
      <td class="c muted">{c['undetermined']}</td>
      <td class="c muted">{c['irrelevant']}</td>
    </tr>"""

bad_rows = [r for r in rows if r["verdict"] == "mismatch"]
bad_html = ""
for r in bad_rows:
    bad_html += f"""<tr>
      <td><b>{r['train']}</b></td>
      <td>{r['site']}</td>
      <td class="mono bad">{r['claim_time'] or r['claim_route']}</td>
      <td class="muted">{r['basis'].split('（')[0]}</td>
      <td class="muted small">{r['title'][:34]}</td>
    </tr>"""

HTML = f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<title>车次信息可信度审计报告</title>
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:-apple-system,BlinkMacSystemFont,"PingFang SC","Microsoft YaHei",sans-serif;
background:#f5f7fa;color:#1f2430;line-height:1.65;padding:32px 20px}}
.wrap{{max-width:920px;margin:0 auto}}
.hero{{background:linear-gradient(135deg,#1d3fbf,#2b5ce6);color:#fff;border-radius:16px;padding:32px 34px;margin-bottom:22px}}
.hero h1{{font-size:26px;font-weight:700;letter-spacing:.3px;margin-bottom:8px}}
.hero p{{opacity:.9;font-size:14px}}
.hero .tag{{display:inline-block;background:rgba(255,255,255,.18);border-radius:20px;padding:3px 12px;font-size:12px;margin-top:14px;margin-right:6px}}
.card{{background:#fff;border-radius:14px;padding:24px 26px;margin-bottom:18px;box-shadow:0 1px 3px rgba(16,24,40,.06)}}
h2{{font-size:17px;margin-bottom:14px;padding-left:10px;border-left:4px solid #2b5ce6}}
.kpis{{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-bottom:18px}}
.kpi{{background:#fff;border-radius:12px;padding:18px 16px;text-align:center;box-shadow:0 1px 3px rgba(16,24,40,.06)}}
.kpi .n{{font-size:28px;font-weight:700;color:#2b5ce6;line-height:1.2}}
.kpi .n.red{{color:#e5484d}}
.kpi .l{{font-size:12px;color:#6b7280;margin-top:4px}}
.kpi .s{{font-size:11px;color:#9aa3b2;margin-top:2px}}
table{{width:100%;border-collapse:collapse;font-size:13px}}
th{{text-align:left;color:#6b7280;font-weight:500;font-size:12px;padding:8px 10px;border-bottom:1px solid #e8ebf0;background:#fafbfc}}
td{{padding:9px 10px;border-bottom:1px solid #f0f2f5}}
.c{{text-align:center}} .bad{{color:#e5484d;font-weight:600}} .ok{{color:#30a46c;font-weight:600}}
.muted{{color:#8b95a5}} .small{{font-size:12px}}
.mono{{font-family:ui-monospace,Menlo,Consolas,monospace;background:#f2f4f7;padding:1px 6px;border-radius:4px;font-size:12px}}
.bar-row{{display:flex;align-items:center;gap:10px;margin-bottom:9px;font-size:13px}}
.bar-label{{width:150px;flex:0 0 150px;color:#374151}}
.bar-track{{flex:1;height:9px;background:#eef1f5;border-radius:5px;overflow:hidden}}
.bar-fill{{display:block;height:100%;border-radius:5px}}
.bar-val{{width:56px;text-align:right;color:#6b7280;font-size:12px}}
.case{{display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin-top:6px}}
.case div{{border-radius:10px;padding:16px;font-size:13px}}
.case .t{{font-size:11px;letter-spacing:.5px;margin-bottom:8px;font-weight:600}}
.case .v{{font-size:19px;font-weight:700;font-family:ui-monospace,Menlo,monospace}}
.case .d{{font-size:11px;margin-top:6px;opacity:.8}}
.good{{background:#eafaf1;color:#186b45}}
.badc{{background:#fdecec;color:#a3171b}}
.warn{{background:#fff8e8;color:#8a5a00}}
.note{{background:#f0f4ff;border-radius:10px;padding:14px 16px;font-size:13px;color:#33406b;margin-top:12px}}
ul{{margin-left:18px;font-size:13.5px}} li{{margin-bottom:7px}}
.foot{{text-align:center;color:#9aa3b2;font-size:12px;padding:8px 0 20px}}
</style></head><body><div class="wrap">

<div class="hero">
  <h1>车次信息可信度审计报告</h1>
  <p>用元宝搜索 VR 卡作为真值源，核验网络公开信息与 AI 回答中的车次时刻声明</p>
  <span class="tag">Mode=1 权威车次卡</span><span class="tag">Mode=0 自然结果</span>
  <span class="tag">22 个车次</span><span class="tag">220 条网页信息</span>
</div>

<div class="kpis">
  <div class="kpi"><div class="n">{total}</div><div class="l">抓取网页信息</div><div class="s">22 车次 × 10 条</div></div>
  <div class="kpi"><div class="n">{irr}</div><div class="l">答非所问</div><div class="s">{pct(irr,total)} 标题是别的车次</div></div>
  <div class="kpi"><div class="n">{judged}</div><div class="l">可判定的明确声明</div><div class="s">含时间或线路</div></div>
  <div class="kpi"><div class="n red">{pct(bad,judged)}</div><div class="l">与官方不一致</div><div class="s">{bad} / {judged} 条</div></div>
</div>

<div class="card">
  <h2>一个具体案例：G677 次</h2>
  <p style="font-size:13.5px;color:#4b5563;margin-bottom:12px">
    同一个车次，三个来源给出三个答案。注意第二、三个答案都不是“明显的胡说”，
    而是看起来完全合理的时刻表 —— 这正是这类错误最难被发现的原因。</p>
  <div class="case">
    <div class="good"><div class="t">元宝搜索 VR 卡（权威）</div>
      <div class="v">10:25</div><div class="d">上海虹桥 → 汉口 14:44<br>全程 4 小时 19 分</div></div>
    <div class="badc"><div class="t">train.hao86.com</div>
      <div class="v">08:38</div><div class="d">同为“上海虹桥→汉口”<br>却把时刻表整体错位</div></div>
    <div class="badc"><div class="t">大模型回答</div>
      <div class="v">07:00</div><div class="d">答“广州南 → 深圳北”<br>车次、线路、时刻全错</div></div>
  </div>
</div>

<div class="card">
  <h2>错误集中在哪：按站点统计</h2>
  <p style="font-size:12.5px;color:#8b95a5;margin-bottom:14px">仅统计可判定的条目（≥4 条样本），条越长表示该站点信息与官方越不一致。</p>
  {site_html}
  <div class="note">一个站点贡献了一半的错误，而另外几个站点零错误 —— 说明这不是随机噪声，而是<strong>站点级的数据维护问题</strong>。这类差异只有做全量核验才看得出来。</div>
</div>

<div class="card">
  <h2>不一致条目明细（{bad} 条）</h2>
  <table>
    <thead><tr><th>车次</th><th>来源站点</th><th>网页声明</th><th>差异类型</th><th>页面标题</th></tr></thead>
    <tbody>{bad_html}</tbody>
  </table>
</div>

<div class="card">
  <h2>逐车次审计明细</h2>
  <table>
    <thead><tr><th>车次</th><th>官方始发</th><th>官方终到</th><th class="c">一致</th><th class="c">不一致</th><th class="c">无声明</th><th class="c">非该车次</th></tr></thead>
    <tbody>{train_html}</tbody>
  </table>
</div>

<div class="card">
  <h2>方法与判定口径</h2>
  <ul>
    <li><strong>真值源</strong>：元宝搜索 SearchPro 的 <span class="mono">Mode=1</span> 垂直权威信源卡，返回车站、发车时刻、经停站与全程耗时，数据来自携程车次库。</li>
    <li><strong>待验对象</strong>：<span class="mono">Mode=0</span> 自然搜索结果的前 10 条网页摘要。</li>
    <li><strong>四态判定</strong>：一致 / 不一致 / 无明确声明（不判对错）/ 非该车次（噪声剔除）。<strong>“无法判定”单独成态而不是硬判对错</strong>，是这套审计能站得住的前提。</li>
    <li><strong>噪声过滤</strong>：搜索 “G27 次列车” 会返回 G17、G2701、K7901 等相似车次页面，若不按车次号精确匹配剔除，会把别人的时刻表算成错误（初版误报率因此高达 17.3%，收紧后降至 12.4%）。</li>
  </ul>
  <div class="note">这套流程可以原样迁移到任何“有权威结构化真值”的领域：金价、油价、汇率、天气、股价、手机参数。车次只是第一个验证对象。</div>
</div>

<div class="card">
  <h2>数据可复现说明</h2>
  <ul>
    <li>调用方式：腾讯云 SearchPro，零依赖手写 TC3-HMAC-SHA256 签名（未安装任何 SDK）。</li>
    <li>调用量：22 车次 × 2 次（权威卡 + 自然结果）= 44 次，成本约 ¥0.9。</li>
    <li>原始数据：<span class="mono">web_audit_results.json</span>，含每条网页的 URL、判定依据与官方值。</li>
  </ul>
</div>

<div class="foot">数据采集于 2026-11-09 · 全部条目可通过原始 JSON 逐条复核</div>
</div></body></html>"""

dst = os.path.join(BASE, "车次信息审计报告.html")
with open(dst, "w", encoding="utf-8") as f:
    f.write(HTML)
print("生成:", dst)
