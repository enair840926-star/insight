# -*- coding: utf-8 -*-
"""손절선을 걸었으면 어땠을지 재는 도구 — 개인 거래규칙을 표본으로 고치기 위해

    python tools/score_stops.py            # 전체
    python tools/score_stops.py kr us      # 자산군 지정
    python tools/score_stops.py --stops 2,3,4     # 고정 %로 잴 값
    python tools/score_stops.py --mults 1,1.5,2   # 하루 변동폭 배수로 잴 값

`score_picks.py`가 "그 픽이 맞았는가"를 잰다면 이건 **"거기에 손절선을
걸었으면 손에 쥐는 것이 달라졌는가"**를 잰다. 규칙을 고르는 일과 그 위에서
거래하는 일은 다른 문제라 따로 잰다.

## 왜 고정 %를 그대로 믿으면 안 되는가

-2%는 자산군마다 완전히 다른 사건이다. 실측(2026-08-14, 상승픽 32건):

    자산군   하루 변동폭 중간   -2%는 그 몇 배인가
    미장          4.58%            0.44배
    국장          3.39%            0.59배
    매크로        2.62%            0.76배

미장 픽에 -2%를 걸면 평소 하루 움직임의 **절반도 안 되는 폭**에 손절이
걸린다. 근거가 깨져서가 아니라 그냥 그날 흔들려서 잘린다. 같은 -2%가
매크로에서는 하루치에 가까워 뜻이 전혀 다르다. 그래서 이 도구는 고정 %와
**하루 변동폭 배수**를 나란히 찍는다.

## 이 도구가 못 재는 것

**장중 저가가 기록에 없다.** `history/`에는 다음 세션의 종가만 남는다
(`core/history.py`의 `record_out`). 그래서 여기서 "손절에 걸렸다"는
**종가가 그 아래로 마감했다**는 뜻이지 장중에 찍었다는 뜻이 아니다.

실제 손절은 장중 저가에 걸리므로 **여기 나오는 손절 건수는 실제보다 적고,
손절을 건 성적은 실제보다 좋게 나온다.** 이 값을 그대로 "손절이 이득이었다"로
읽으면 안 된다. 없는 것과 못 받은 것을 구분하라는 규칙이 여기에도 걸린다.

갭하락도 못 본다. 국장·미장 픽은 밤을 넘겨 재므로 -3% 손절을 걸어도 시가가
-8%에 열리면 그 자리에 체결된다. 그런 경우 손절은 손실을 못 막는다.

## 한 건이 전부를 끌고 가는지 반드시 보라

표본이 작을 때 손절의 이득은 대개 **가장 크게 틀린 한 건**에서 나온다.
실측에서 미장 FLR -8.33% 하나를 빼자 -2% 손절의 이득이 +0.27%p에서
+0.08%p로 줄었다 — 남은 것은 잡음이다. 그래서 `--drop-worst`로 최악 한 건을
빼고 다시 찍어 준다. 두 값이 크게 다르면 그 결론은 아직 한 건짜리다.
"""
import argparse
import os
import statistics as st
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import history

# 판정 기준은 core/history.py 가 갖는다. 사본을 두면 도구끼리 다른 숫자를 말한다.
MARKETS = history.MARKETS
_pairs = history.pairs
_verdict = history.verdict
_WANT = history._WANT

# 손절을 읽을 만해지는 표본. `ENOUGH["calib"]`(100)와 같은 자리에 둔다 —
# "그 선이 실제로 얼마나 깨지나"와 같은 질문이기 때문이다.
ENOUGH_STOP = 100

DEFAULT_STOPS = (2.0, 2.5, 3.0, 4.0)
DEFAULT_MULTS = (0.8, 1.0, 1.5, 2.0)


def _held(pick, out):
    """그 픽을 방향대로 들었을 때의 손익 %. 방향이 없으면 None.

    하락·피할 것은 부호를 뒤집는다. `daily_sums`와 같은 처리다 — 그래야
    상승 픽과 같은 잣대가 된다.
    """
    want = _WANT.get(pick.get("kind"))
    ret = out.get("ret_pct")
    if want is None or ret is None:
        return None
    return ret * want


def _apply(rows, stop_pct=None, mult=None):
    """손절선을 걸었을 때의 손익 목록. stop_pct 는 고정 %, mult 는 변동폭 배수.

    둘 다 None 이면 손절 없이 그대로 든 값이다. 반환: [(손익, 걸렸나)].

    **종가 기준이다.** 장중 저가가 없어 "그 아래로 마감했으면 그 값에
    잘렸다"로 근사한다. 실제보다 덜 걸리고 더 좋게 나온다.
    """
    out = []
    for p, o in rows:
        r = _held(p, o)
        if r is None:
            continue
        line = stop_pct
        if mult is not None:
            vol = p.get("vol_20d")
            if not vol:
                # 변동성이 없으면 이 픽에는 배수 손절을 걸 수가 없다.
                # 손절 없이 센 값을 넣으면 '안 걸렸다'로 세어져 비율이
                # 낮게 나오므로 아예 뺀다 — 코인에 이 값이 없다.
                continue
            line = mult * vol
        if line is not None and r <= -line:
            out.append((-line, True))
        else:
            out.append((r, False))
    return out


def _row(label, rows, stop_pct=None, mult=None):
    xs = _apply(rows, stop_pct, mult)
    if not xs:
        return None
    vals = [v for v, _ in xs]
    hit = sum(1 for _, h in xs if h)
    return label, len(xs), st.mean(vals), hit


def _table(title, rows, markets, kind, values):
    """자산군 × 손절선 표 하나. kind 는 'pct' 또는 'mult'."""
    print(f"\n{title}")
    head = f"  {'손절선':>10s} {'전체':>16s}"
    for m in markets:
        head += f" {m:>13s}"
    print(head)

    specs = [("없음", None, None)]
    for v in values:
        if kind == "pct":
            specs.append((f"-{v:g}%", v, None))
        else:
            specs.append((f"변동폭 {v:g}배", None, v))

    for label, pct, mult in specs:
        line = f"  {label:>10s}"
        r = _row(label, rows, pct, mult)
        line += (f" {r[2]:+7.2f}% {r[3]:2d}/{r[1]:<3d}" if r else f" {'—':>16s}")
        for m in markets:
            sub = [(p, o) for p, o in rows if p["market"] == m]
            r = _row(label, sub, pct, mult)
            line += (f" {r[2]:+7.2f}% {r[3]:2d}/{r[1]:<2d}" if r
                     else f" {'—':>13s}")
        print(line)
    print("     (평균 손익 · 걸린건수/센건수)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("markets", nargs="*", default=None)
    ap.add_argument("--stops", default=None, metavar="2,3,4",
                    help="고정 %로 잴 손절선 (쉼표)")
    ap.add_argument("--mults", default=None, metavar="1,1.5,2",
                    help="하루 변동폭 배수로 잴 손절선 (쉼표)")
    ap.add_argument("--drop-worst", type=int, default=1, metavar="N",
                    help="최악 N건을 뺀 값도 함께 찍는다 (기본 1, 0이면 안 찍음)")
    a = ap.parse_args()

    markets = a.markets or MARKETS
    stops = ([float(x) for x in a.stops.split(",")] if a.stops
             else list(DEFAULT_STOPS))
    mults = ([float(x) for x in a.mults.split(",")] if a.mults
             else list(DEFAULT_MULTS))

    rows = [(p, o) for p, o in _pairs(markets) if _held(p, o) is not None]
    if not rows:
        print("기록이 없습니다. 수집이 몇 번 돌아야 결과가 쌓입니다.")
        return 0

    vers = {p.get("rules") for p, _ in rows}
    print(f"방향이 있는 픽 {len(rows)}건 (결과가 채워진 것만) · "
          f"규칙 버전 {', '.join(sorted(vers))}")
    if len(vers) > 1:
        print("  ※ 규칙 버전이 섞여 있습니다. 직접 비교하면 안 됩니다.")
    print("\n※ 장중 저가가 기록에 없어 **종가 기준**으로 근사한 값이다.")
    print("  실제 손절은 장중에 걸리므로 걸린 건수는 이보다 많고,")
    print("  손절을 건 성적은 이보다 나쁘다. 갭하락도 못 본다.")

    # ------------------------------------------------- 1. -2%가 뭔 뜻인가
    print("\n[1] 고정 %는 자산군마다 다른 사건이다")
    print("    같은 -2%가 어디서는 하루치고 어디서는 반나절치다.")
    print(f"  {'자산군':6s} {'건수':>4s} {'하루 변동폭 중간':>16s}  " +
          "  ".join(f"-{s:g}%는" for s in stops))
    for m in markets:
        v = [p["vol_20d"] for p, _ in rows
             if p["market"] == m and p.get("vol_20d")]
        if not v:
            print(f"  {m:6s} {'':4s} 변동성 기록이 없어 잴 수 없다")
            continue
        md = st.median(v)
        cols = "  ".join(f"{s/md:5.2f}배" for s in stops)
        print(f"  {m:6s} {len(v):4d} {md:15.2f}%  {cols}")
    print("    0.5배 근처면 근거가 깨져서가 아니라 그날 흔들려서 잘린다.")

    # ------------------------------------------------------- 2·3. 두 방식
    _table("[2] 고정 % 손절 — 자산군에 상관없이 같은 숫자를 쓸 때",
           rows, markets, "pct", stops)
    _table("[3] 하루 변동폭 배수 손절 — 그 종목의 평소 움직임으로 재서 걸 때",
           rows, markets, "mult", mults)
    print("     변동성이 없는 픽은 분모에서 뺀다 (코인에 이 값이 없다).")

    # -------------------------------------------- 4. 한 건이 끌고 가는가
    if a.drop_worst:
        worst = sorted(rows, key=lambda x: _held(*x))[:a.drop_worst]
        kept = [r for r in rows if r not in worst]
        print(f"\n[4] 최악 {a.drop_worst}건을 빼면 — 결론이 한 건짜리인지 본다")
        for p, o in worst:
            print(f"    뺀 것: {p['market']} {p['key']} {_held(p, o):+.2f}% "
                  f"({p['at'][:10]}, 하루 변동폭 "
                  f"{p.get('vol_20d') or '?'}%)")
        if kept:
            base = st.mean([_held(*r) for r in kept])
            print(f"  {'손절선':>10s} {'평균':>9s}  {'손절 없음 대비':>12s}")
            print(f"  {'없음':>10s} {base:+8.2f}%")
            for s in stops:
                r = _row("", kept, s, None)
                if r:
                    print(f"  {f'-{s:g}%':>10s} {r[2]:+8.2f}% "
                          f"{r[2]-base:+13.2f}%p")
            print("    이 차이가 [2]의 차이보다 훨씬 작으면, 손절이 좋아 보였던")
            print("    이유는 규칙이 아니라 그 한 건이다.")

    print(f"\n→ {_verdict(len(rows), ENOUGH_STOP, '손절선을 손댈 만하다')}")
    print("손절선은 규칙이 고른 픽이 아니라 **내가 어떻게 드느냐**의 문제다.")
    print("표본이 찰 때까지는 큰 손실을 막는 쪽으로만 쓰고, 이 표로")
    print("최적값을 찾으려 하지 마라 — 지금 표본에서는 잡음에 맞추게 된다.")
    return 0


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    sys.exit(main())
