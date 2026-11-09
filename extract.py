# -*- coding: utf-8 -*-
"""从 AI 回答中抽取数字断言：车次 + 时刻对"""
import re

TRAIN_NO = re.compile(r'\b([GDKCTZS]\d{1,5})\b', re.IGNORECASE)
TIME = re.compile(r'([01]?\d|2[0-3])[时:：点]\s*([0-5]\d)?[分]?')
# 形如 "G677 07:15 出发" / "G677次，07:15从北京西出发" 的车次+时刻邻接对
PAIR_WIN = 60  # 车次与时刻允许的最大字符距离

def extract_train_assertions(text: str) -> list[dict]:
    """返回 [{train_no, times:[...], snippet}]，times 为车次邻域内的时刻列表"""
    out = []
    for m in TRAIN_NO.finditer(text):
        no = m.group(1).upper()
        lo, hi = max(0, m.start() - PAIR_WIN), min(len(text), m.end() + PAIR_WIN)
        window = text[lo:hi]
        times = [f"{t[0]}:{t[1] or '00'}" for t in TIME.findall(window)]
        if times:
            out.append({
                "train_no": no,
                "times": times[:6],
                "snippet": window.replace("\n", " ").strip()[:80],
            })
    return out

def extract_train_nos(text: str) -> list[str]:
    """仅抽取全部车次号（去重保序）"""
    seen, out = set(), []
    for m in TRAIN_NO.finditer(text):
        no = m.group(1).upper()
        if no not in seen:
            seen.add(no)
            out.append(no)
    return out

if __name__ == "__main__":
    demo = "推荐乘坐 G1 次 07:00 从北京南出发，或 G27 次 10:15 出发，另外 K79 次 14:30 也可以。"
    for a in extract_train_assertions(demo):
        print(a)
