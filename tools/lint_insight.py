# -*- coding: utf-8 -*-
"""인사이트 글 검사 — 전문용어가 남았는지

    python tools/lint_insight.py            # 전체 검사
    python tools/lint_insight.py macro       # 하나만
    python tools/lint_insight.py --fix       # 기계적으로 바꿀 수 있는 것만 치환

프롬프트에도 스킬에도 용어 규칙을 적어 뒀는데 계속 되돌아온다.
수만 자짜리 글을 쓰다 보면 규칙 하나가 묻힌다. 바라는 대신 재서
막는다 — 커밋 전에 이걸 돌리고 걸리면 고친다.

제목(##·###)에 들어간 것은 더 나쁘다. 목록만 훑는 사람이 제일 먼저
보는 자리이므로 따로 표시한다.
"""
import argparse
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import store

INSIGHTS = store.ROOT / "insights"
MARKETS = ["kr", "us", "macro", "coin"]

# 기계적으로 바꿔도 뜻이 안 상하는 것만 넣는다. 문맥을 봐야 하는 것은
# --fix 대상에서 빼고 사람이 고치게 남긴다.
SAFE = {
    "플래트닝": "장단기 금리차 축소",
    "스티프닝": "장단기 금리차 확대",
}

# 문맥에 따라 표현이 달라져 자동 치환이 위험한 것들
MANUAL = {
    "백워데이션": "지금 물건이 나중보다 비쌈 (공급 빠듯)",
    "콘탱고": "나중이 더 비쌈 (공급 여유)",
    "타이트": "부족 / 빠듯",
    "스티프": "장단기 금리차가 넓음",
    "롱숏비": "롱이 숏의 N배",
}

ALL = {**SAFE, **MANUAL}
_PAT = re.compile("|".join(sorted(map(re.escape, ALL), key=len, reverse=True)))

# 같은 줄에서 바로 풀어 쓰면 통과시킨다. '롱숏비 5.15(롱 83.7%)'는
# 용어를 몰라도 읽히므로 고칠 이유가 없다. 지적할 것은 설명 없이
# 던져 놓은 경우다 — 그건 독자가 뜻을 떠올려야 한다.
_EXPLAINED = {
    # 숫자와 함께 풀어 쓴 경우, 또는 지표 이름 자체를 가리키는 경우.
    # "롱숏비의 절대 수준은 같은 거래소 안에서만 비교하라" 같은 문장은
    # 용어를 설명하는 자리라 바꿀 것이 없다.
    "롱숏비": re.compile(r"롱\s*\d|\d\s*배|롱\s*\d+(\.\d+)?%"
                       r"|롱숏비(는|의|·|,|\))|기준|절대 수준"),
}


def scan(text):
    """반환: [(줄번호, 용어, 제목여부, 줄내용), ...]"""
    hits = []
    for i, line in enumerate(text.splitlines(), 1):
        in_head = line.lstrip().startswith("#")
        for m in _PAT.finditer(line):
            word = m.group()
            ok = _EXPLAINED.get(word)
            if ok and ok.search(line):
                continue
            hits.append((i, word, in_head, line.strip()))
    return hits


def fix(text):
    """자동 치환이 안전한 것만 바꾼다. 반환: (새 글, 바꾼 횟수)"""
    n = 0
    for bad, good in SAFE.items():
        c = text.count(bad)
        if c:
            text = text.replace(bad, good)
            n += c
    return text, n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("markets", nargs="*", default=None)
    ap.add_argument("--fix", action="store_true",
                    help="자동 치환이 안전한 용어만 바꾼다")
    a = ap.parse_args()

    targets = a.markets or MARKETS
    total, headline = 0, 0

    for m in targets:
        f = INSIGHTS / f"insight_{m}.md"
        if not f.exists():
            continue
        text = f.read_text(encoding="utf-8")

        if a.fix:
            text, n = fix(text)
            if n:
                f.write_text(text, encoding="utf-8")
                print(f"[{m}] 자동 치환 {n}건")

        hits = scan(text)
        if not hits:
            continue
        print(f"\n[{m}] {len(hits)}건")
        for ln, word, in_head, line in hits:
            mark = "제목! " if in_head else "      "
            total += 1
            headline += in_head
            print(f"  {mark}{ln:>4}줄  '{word}' → {ALL[word]}")
            print(f"            {line[:76]}")

    if not total:
        print("전문용어 없음")
        return 0

    print(f"\n총 {total}건" + (f" (그중 제목 {headline}건)" if headline else ""))
    print("폰에서 훑는 글이다. 용어를 떠올려야 읽히는 문장은 실패한 문장이다.")
    return 1


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    sys.exit(main())
