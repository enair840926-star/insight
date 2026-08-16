# -*- coding: utf-8 -*-
"""픽 신호가 실제로 걸리는지 센다 — 픽이 아니라 **후보 전체**에서

    python tools/signal_probe.py            # 전체
    python tools/signal_probe.py kr us      # 자산군 지정
    python tools/signal_probe.py --live     # 기록 대신 지금 스냅샷에서 계산
    python tools/signal_probe.py --all      # 같은 날 기록도 전부 (기본은 날짜별 마지막)

`regime_probe.py`가 장 판정 신호에 하는 일을 픽 신호에 한다. 그쪽에 있고
이쪽에 없어서 픽 신호는 몇 번 걸리는지 아무도 안 세고 있었다.

## 왜 픽에서 세면 안 되나

**픽은 점수가 높아서 뽑힌 것이다.** 거기서 신호를 세면 한쪽으로 보이는
것이 당연하다 — 선택 편향이다. 실측(2026-08-16):

    픽 85건에서      뉴스 호재 69회 / 악재  0회
    후보 109개에서   뉴스 호재 74회 / 악재  3회

방향은 같지만 **픽에서 잰 숫자는 애초에 그 질문에 답할 수 없다.**
그래서 `core/history.record_signals`가 수집 때마다 후보 전체를 세어 남기고,
이 도구는 그 기록을 읽는다.

## 무엇을 찾나

    1. 한 번도 안 걸리는 신호   죽은 조건이다. 임계값이 실제 범위 밖이거나
                              필드 이름이 안 맞는다. 실제로 코인 임계값을
                              read.py에서 그대로 가져왔다가 OKX 스케일에서
                              한 번도 안 걸린 적이 있다.
    2. 모두에게 걸리는 신호     신호가 아니라 상수다. 코인 펀딩비 임계를
                              75%로 뒀더니 17개 중 16개에서 켜졌다.
    3. 한 부호만 나오는 신호    판정이 아니라 라벨이 된다.
    4. 방향이 굳은 자산군      국장이 66개 중 59개 '상승'으로 굳은 적이 있다.

## 읽을 때 조심할 것

**날이 적으면 굳은 것과 그 며칠이 실제로 한 방향이었던 것을 구별할 수
없다.** 강세장 사흘이면 '추세 상승'이 100%로 나오는 것이 정상이다. 반대로
뉴스 판정처럼 **시장 방향과 무관해야 하는 신호가 한쪽으로 굳으면** 그건
며칠로도 의심할 만하다 — 무엇이 그 신호를 만드는지 함께 봐야 한다.
"""
import argparse
import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import history, pick, store

MARKETS = history.MARKETS

# 이 비율을 넘게 걸리면 상수로 의심한다. 코인 펀딩비가 17개 중 16개(94%)에서
# 켜졌던 것이 실측 사례다.
CONST_RATE = 0.9

# 날이 이만큼은 있어야 '굳었다'고 말한다. 그 아래면 강세장 며칠과 구별이
# 안 된다. `regime_probe.py`와 같은 값이다.
ENOUGH_DAYS = 10


def _live(markets):
    """기록이 없을 때 지금 스냅샷에서 바로 계산한다. 반환: [레코드]."""
    out = []
    for m in markets:
        j = store.bundle(m)
        if not j:
            continue
        t = pick.tally(m, j)
        if not t.get("cands"):
            continue
        out.append({"market": m, "at": j.get("collected_at") or "",
                    "cands": t["cands"], "n": t["n"], "gated": t["gated"],
                    "gate_why": t["gate_why"], "dirs": t["dirs"],
                    "sig": t["sig"]})
    return out


def _merge(rows):
    """자산군별로 합친다. 반환: {market: {n, days, dirs, sig, gate_why}}."""
    agg = {}
    for r in rows:
        m = r.get("market")
        a = agg.setdefault(m, {"n": 0, "cands": 0, "gated": 0, "days": 0,
                               "dirs": defaultdict(int),
                               "sig": defaultdict(lambda: [0, 0]),
                               "gate_why": defaultdict(int)})
        a["days"] += 1
        a["n"] += r.get("n") or 0
        a["cands"] += r.get("cands") or 0
        a["gated"] += r.get("gated") or 0
        for k, v in (r.get("dirs") or {}).items():
            a["dirs"][k] += v
        for k, v in (r.get("gate_why") or {}).items():
            a["gate_why"][k] += v
        for k, v in (r.get("sig") or {}).items():
            a["sig"][k][0] += v[0]
            a["sig"][k][1] += v[1]
    return agg


def _diagnose(fired, n, pos, neg, days):
    """이 신호를 어떻게 읽어야 하나. 반환: 짧은 진단 또는 ''."""
    if not n:
        return ""
    rate = fired / n
    if days < ENOUGH_DAYS:
        # 날이 적으면 단정하지 않는다. 다만 부호가 한쪽뿐인 것은 표본과
        # 무관하게 구조일 수 있으므로 눈에 띄게만 해 둔다.
        if fired >= 15 and (pos == 0 or neg == 0):
            return "한 부호만 (날이 적어 단정은 못 함)"
        return ""
    if rate >= CONST_RATE:
        return f"← 상수 의심 ({rate*100:.0f}%가 켜짐)"
    if pos == 0 or neg == 0:
        return "← 한 부호만"
    return ""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("markets", nargs="*", default=None)
    ap.add_argument("--live", action="store_true",
                    help="기록 대신 지금 스냅샷에서 계산")
    ap.add_argument("--all", action="store_true",
                    help="같은 날 기록도 전부 (기본은 날짜별 마지막)")
    a = ap.parse_args()
    markets = a.markets or MARKETS

    rows = ([] if a.live
            else history.load_signals(markets=markets, per_day=not a.all))
    live = a.live or not rows
    if live:
        rows = _live(markets)
        if not rows:
            print("스냅샷도 기록도 없습니다.")
            return 1
        print("※ 기록이 없어 **지금 스냅샷 하나**로 계산했습니다. 하루치라")
        print("  '늘 켜진다/한 번도 안 걸린다'를 판단할 수 없습니다.")
        print("  수집이 돌기 시작하면 기록에서 날짜별로 세어 줍니다.\n")

    agg = _merge(rows)
    seen_any = defaultdict(int)          # 신호 -> 걸린 자산군 수
    for m, aggm in agg.items():
        for k, (p, n_) in aggm["sig"].items():
            if p or n_:
                seen_any[k] += 1

    for m in markets:
        d = agg.get(m)
        if not d:
            print(f"\n### {m}: 기록 없음")
            continue
        n, days = d["n"], d["days"]
        print(f"\n### {m} — 날짜 {days}개 · 점수 매긴 후보 {n}개"
              f" (수집된 후보 {d['cands']}개)")
        if d["gated"]:
            why = " · ".join(f"{k} {v}" for k, v in
                             sorted(d["gate_why"].items(), key=lambda kv: -kv[1]))
            print(f"  게이트 탈락 {d['gated']}개 — {why}")

        print(f"  {'켜짐률':>6s} {'+':>5s} {'-':>5s}  신호")
        for k, (p, ng) in sorted(d["sig"].items(),
                                 key=lambda kv: -(kv[1][0] + kv[1][1])):
            fired = p + ng
            note = _diagnose(fired, n, p, ng, days)
            print(f"  {fired*100/n:5.0f}% {p:5d} {ng:5d}  {k[:40]:42s}{note}")

        # 방향이 한쪽으로 굳었는지. 픽이 뽑히기 전, 후보 단계의 분포다.
        dirs = d["dirs"]
        tot = sum(dirs.values())
        if tot:
            top = max(dirs.values())
            warn = ""
            if days < ENOUGH_DAYS:
                warn = f"  (날이 {days}일뿐이라 굳었는지 판단 못 함)"
            elif top >= tot * 0.8:
                warn = "  ← 한쪽으로 굳었다"
            print(f"  후보 방향 분포: " +
                  " · ".join(f"{k} {v}" for k, v in dirs.items()) + warn)

    # 자산군을 가로질러 본다. 한 곳에서는 걸리는데 다른 곳에서 0이면
    # 그 자산군에 그 축이 없는 것인지 임계값이 안 맞는 것인지 갈린다.
    print(f"\n{'='*70}\n자산군을 가로질러 — 여기선 걸리는데 저기선 안 걸리는 신호")
    shown = 0
    for k, cnt in sorted(seen_any.items(), key=lambda kv: -kv[1]):
        miss = [m for m in markets
                if agg.get(m) and not any(agg[m]["sig"].get(k, [0, 0]))]
        if miss and cnt >= 1:
            print(f"  {k[:44]:46s} 없음: {'·'.join(miss)}")
            shown += 1
        if shown >= 12:
            break
    if not shown:
        print("  없음 — 모든 신호가 모든 자산군에서 한 번은 걸렸습니다.")
    print("  그 자산군에 **그 축이 아예 없는 것**(미장엔 수급이 없다)과")
    print("  **임계값이 안 맞는 것**은 다르다. 어댑터(`core/pick.py`의")
    print("  `from_*`)에 그 필드가 실리는지부터 보라.")

    print(f"\n{'='*70}")
    total_days = max((d["days"] for d in agg.values()), default=0)
    if total_days < ENOUGH_DAYS:
        print(f"날짜가 {total_days}일뿐이다 — 굳은 것과 그 며칠이 한 방향이었던")
        print("것을 구별할 수 없다. 강세장 사흘이면 '추세 상승'이 100%로 나오는")
        print("것이 정상이다.")
    print("**시장 방향과 무관해야 하는 신호가 한쪽으로 굳으면** 날이 적어도")
    print("의심할 만하다 — 뉴스 판정이 그렇다. 무엇이 그 값을 만드는지 보라.")
    print("신호를 고치는 것은 그다음이고, 표본 1000건까지는 기여도를 못 읽는다.")
    return 0


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    sys.exit(main())
