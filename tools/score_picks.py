# -*- coding: utf-8 -*-
"""픽이 맞았는지 재는 도구 — 표본이 모자라면 모자라다고 말한다

    python tools/score_picks.py           # 전체
    python tools/score_picks.py kr us     # 자산군 지정
    python tools/score_picks.py --signals # 신호별 기여도까지

이 저장소의 다른 도구와 같은 이유로 있다. `probe.py`가 "이 IP에서 어디까지
닿는가"를 재듯, 이건 "그 픽이 맞았는가"를 잰다. 추측하지 말고 측정한다.

**적중률 하나를 놓고 규칙을 고치면 안 된다.** 동전을 45번 던져 21번
앞면이 나온 것과 규칙이 나쁜 것은 이 표본으로 구별되지 않는다. 그래서
모든 숫자에 "이만큼이면 판단할 수 있는가"를 함께 찍는다.

## 답이 나오는 순서

    1. 캘리브레이션   '오늘 볼 선'이 실제로 얼마나 깨지나   표본 100이면 대략
    2. 점수-결과      점수 높은 픽이 실제로 나은가          표본 200~
    3. 신호별 기여도  어느 근거가 값을 하나                 표본 1000~ (6개월+)

위를 건너뛰고 3번부터 보면 노이즈에 규칙을 맞추게 된다.
"""
import argparse
import os
import re
import statistics as st
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import history

# 집계·판정 기준은 core/history.py 가 갖는다. 대시보드도 같은 함수를 쓰므로
# 여기 사본을 두면 화면과 도구가 다른 숫자를 말하게 된다.
MARKETS = history.MARKETS
ENOUGH = history.ENOUGH
_pairs = history.pairs
_verdict = history.verdict
_wilson_gap = history.coin_flip_gap


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("markets", nargs="*", default=None)
    ap.add_argument("--signals", action="store_true", help="신호별 기여도까지")
    a = ap.parse_args()
    markets = a.markets or MARKETS

    rows = _pairs(markets)
    if not rows:
        print("기록이 없습니다. 수집이 몇 번 돌아야 결과가 쌓입니다.")
        return 0

    vers = {p.get("rules") for p, _ in rows}
    print(f"픽 {len(rows)}건 (결과가 채워진 것만) · 규칙 버전 {', '.join(sorted(vers))}")
    if len(vers) > 1:
        print("  ※ 규칙 버전이 섞여 있습니다. 버전이 다른 기록은 직접 비교하면 안 됩니다.")

    # ---------------------------------------------------------- 1. 캘리브레이션
    print("\n[1] 캘리브레이션 — '오늘 볼 선'이 얼마나 깨지나")
    print("    하루 변동폭 1배 아래로 빠지는 일이 실제로 얼마나 잦은가.")
    print("    정규분포라면 15.9%다. 크게 높으면 그 선은 '드문 일'이 아니고,")
    print("    크게 낮으면 변동성이 지금 국면을 과대평가하고 있다는 뜻이다.")
    for m in markets:
        # 변동성을 못 받은 픽은 분모에서 뺀다. 넣으면 '안 깨졌다'로 세어져
        # 비율이 실제보다 낮게 나온다 — 코인에는 이 값이 아예 없다.
        xs = [o for p, o in rows if p["market"] == m and p.get("vol_20d")]
        n = len(xs)
        if not n:
            print(f"  {m:6s} 변동성 기록이 없어 잴 수 없다")
            continue
        broke = sum(1 for o in xs if o.get("broke_1sigma"))
        print(f"  {m:6s} {broke*100/n:5.1f}% ({broke}/{n})   "
              + _verdict(n, ENOUGH["calib"], "읽을 만하다"))

    # ---------------------------------------------------------- 2. 적중률
    print("\n[2] 적중률 — 벤치마크 대비 초과수익의 부호가 맞았나")
    for m in markets:
        xs = [(p, o) for p, o in rows
              if p["market"] == m and o.get("correct") is not None]
        n = len(xs)
        if not n:
            continue
        hits = sum(1 for _, o in xs if o["correct"])
        ex = [o["excess_pct"] for _, o in xs]
        note = "" if any(o.get("vs_bench") for _, o in xs) else " (벤치마크 없음 — 절대 등락)"
        print(f"  {m:6s} {hits*100/n:5.1f}% ({hits}/{n})  "
              f"평균 초과 {st.mean(ex):+6.2f}%{note}")
        print(f"         {_wilson_gap(hits, n)}")

    # ---------------------------------------------------------- 3. 점수-결과
    print("\n[3] 점수와 결과 — 점수가 높으면 실제로 나은가")
    buckets = defaultdict(list)
    for p, o in rows:
        if o.get("correct") is None:
            continue
        s = abs(p["score"])
        buckets["3~4점" if s <= 4 else "5~6점" if s <= 6 else "7점 이상"].append(
            o["excess_pct"] * (1 if p["kind"] in ("상승",) else -1))
    for label in ("3~4점", "5~6점", "7점 이상"):
        xs = buckets.get(label) or []
        if not xs:
            continue
        print(f"  {label:8s} n={len(xs):3d}  평균 초과 {st.mean(xs):+6.2f}%  "
              f"중간 {st.median(xs):+6.2f}%")
    total = sum(len(v) for v in buckets.values())
    print(f"  → {_verdict(total, ENOUGH['score'], '점수가 값을 하는지 읽을 만하다')}")

    # ---------------------------------------------------------- 4. 신호별
    if a.signals:
        print("\n[4] 신호별 기여도")
        sig = defaultdict(list)
        for p, o in rows:
            if o.get("correct") is None:
                continue
            d = o["excess_pct"] * (1 if p["kind"] in ("상승",) else -1)
            for s in p.get("signals") or []:
                sig[re.sub(r"^\([+-]\d+\)\s*", "", re.sub(r"[-+]?\d[\d,]*\.?\d*",
                                                          "N", s))].append(d)
        base = st.mean([o["excess_pct"] for _, o in rows
                        if o.get("correct") is not None]) if rows else 0
        for name, xs in sorted(sig.items(), key=lambda kv: -st.mean(kv[1])):
            if len(xs) < 5:
                continue
            print(f"  {st.mean(xs):+6.2f}%  n={len(xs):3d}  {name[:52]}")
        print(f"  (전체 평균 {base:+.2f}%)")
        print(f"  → {_verdict(total, ENOUGH['signal'], '신호를 손댈 만하다')}")

    print("\n적중률 하나로 규칙을 고치지 마라. 위 '판단할 수 있는가'를 먼저 보라.")
    return 0


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    sys.exit(main())
