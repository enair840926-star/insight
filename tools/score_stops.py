# -*- coding: utf-8 -*-
"""손절선을 걸었으면 어땠을지 재는 도구 — 개인 거래규칙을 표본으로 고치기 위해

    python tools/score_stops.py            # 전체
    python tools/score_stops.py kr us      # 자산군 지정
    python tools/score_stops.py --stops 2,3,4     # 고정 %로 잴 값
    python tools/score_stops.py --mults 1,1.5,2   # 하루 변동폭 배수로 잴 값

`score_picks.py`가 "그 픽이 맞았는가"를 잰다면 이건 **"거기에 손절선을
걸었으면 손에 쥐는 것이 달라졌는가"**를 잰다. 규칙을 고르는 일과 그 위에서
거래하는 일은 다른 문제라 따로 잰다.

개인 규칙은 `notes/trading-rules.md` 에 있다. 이 도구는 그 규칙을 표본이
쌓인 뒤 다시 재기 위한 것이다 — 두 곳의 숫자가 어긋나면 안 되므로 문서에
적은 표는 전부 여기서 나온다.

## 왜 고정 %를 그대로 믿으면 안 되는가

-2%는 종목마다 완전히 다른 사건이다. 실측(2026-08-14, 국장·미장 21건):

    자산군   하루 변동폭 중간   -2%는 그 몇 배   -3%는
    미장          4.58%            0.44배        0.66배
    국장          3.39%            0.59배        0.88배

미장 픽에 -2%를 걸면 평소 하루 움직임의 **절반도 안 되는 폭**에 손절이
걸린다. 근거가 깨져서가 아니라 그냥 그날 흔들려서 잘린다. 국장 픽은
변동폭이 2.4%부터 11.2%까지 갈려(대형주와 급등 중소형주가 섞여 나온다)
손절값 하나로는 못 덮는다. 그래서 이 도구는 고정 %와 **하루 변동폭 배수**를
나란히 찍고, 변동폭이 큰 픽을 빼면 달라지는지도 함께 본다([5]).

## 국장은 장중 저가로 직접 잰다 — 미장은 아직 못 잰다

`history/`에는 다음 스냅샷의 가격만 남아(`record_out`) 손절이 장중에
걸렸는지를 못 잰다. 그래서 [2]·[3]은 **종가 기준 근사**이고 손절이 실제보다
덜 걸린 것으로 나온다.

**다만 국장은 잴 수 있다.** `cloud/kr_*.json` 의 종목마다 `ohlcv_tail`
(일별 OHLC 5일치)이 들어 있어서 픽 다음 장의 시가·저가를 그대로 쓸 수
있다. [1b]가 그것이다.

이걸 붙이고 나서 **모형 추정이 크게 빗나간 것을 알았다** — -3%가 걸릴 확률을
48%로 추정했는데 실측은 27%였고, "변동성이 크면 반드시 스친다"고 본 종목
(변동폭 10.06%)이 장중에 진입가 아래로 한 번도 안 내려가고 +8.36%로
끝났다. 그 추정으로 만들었던 '변동폭 상한' 규칙을 그래서 뺐다.

**미장은 2026-08-14 수집부터 쌓인다.** 야후 차트 응답에 시가·고가·저가가
다 들어 있는데 `collectors/us_market.py`의 `_detail`이 종가와 거래량만 쓰고
버리고 있었다. 같은 이름·같은 모양으로 남기게 고쳤으므로 그 뒤 픽부터는
국장과 똑같이 [1b]에서 잰다. **그전 픽은 영영 못 잰다** — 표본이 쌓이길
기다린다고 생기는 값이 아니라 그때 안 남겨서 없는 것이다.

정작 표본에서 가장 큰 손실(FLR -8.33%)이 미장이라, **손절이 그 꼬리를
막았을지는 미장 표본이 쌓일 때까지 답이 없다.**

갭하락은 국장에서 [1b]가 함께 센다. 시가가 손절선 아래로 열리면 손절은
그 자리에 체결되므로 손실을 못 막는다.

## 한 건이 전부를 끌고 가는지 반드시 보라

표본이 작을 때 손절의 이득은 대개 **가장 크게 틀린 한 건**에서 나온다.
실측(국장·미장)에서 미장 FLR -8.33% 하나를 빼자 -2% 손절의 이득이
+0.38%p에서 +0.09%p로 줄었다 — 남은 것은 잡음이다. 그래서 `--drop-worst`로
최악 한 건을 빼고 다시 찍어 준다. 두 값이 크게 다르면 그 결론은 아직
한 건짜리다.
"""
import argparse
import glob
import json
import math
import os
import statistics as st
import sys
from collections import defaultdict

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

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


def _phi(z):
    return 0.5 * (1 + math.erf(z / math.sqrt(2)))


def _touch(x, vol):
    """하루 안에 -x%를 찍을 확률 추정. **실측이 아니라 모형값이다.**

    장중 저가가 기록에 없어 실측으로는 못 잰다. 무추세 임의보행에서
    장중 최저가가 -x% 아래로 내려갈 확률은 종가가 -x% 아래로 마감할
    확률의 약 2배다(반사원리). 그 근사를 쓴다.

    실제 장중 움직임은 이보다 덜 흔들릴 수 있어 손절이 덜 걸릴 수 있다.
    방향은 믿을 만하고 정확한 값은 아니다.
    """
    return min(1.0, 2 * _phi(-x / vol))


def _ev_with_touch(rows, x):
    """장중 스침까지 넣은 기대 손익. 반환: (기대값, 잘리는 비율, 건수).

    종가가 이미 -x% 아래면 확실히 잘린 것으로 본다. 종가는 버텼어도
    장중에 스쳤을 수 있으므로, 그 조건부 확률만큼 -x% 로 바꾼다.
    P(스침 & 종가 생존) / P(종가 생존) = Φ(-x/σ) / (1 - Φ(-x/σ)).

    **손절 없이 든 값과 비교할 때만 뜻이 있다.** 절대 수준은 모형에 기댄다.
    """
    vals, cut = [], []
    for p, o in rows:
        r = _held(p, o)
        vol = p.get("vol_20d")
        if r is None or not vol:
            continue
        if r <= -x:
            vals.append(-x)
            cut.append(1.0)
        else:
            z = _phi(-x / vol)
            q = z / (1 - z) if z < 1 else 1.0
            vals.append(q * (-x) + (1 - q) * r)
            cut.append(q)
    if not vals:
        return None
    return st.mean(vals), st.mean(cut), len(vals)


# 스냅샷에서 일별 OHLC를 꺼내는 법. (파일 패턴, 종목 배열 키, 종목 코드 키,
# '개장 전'으로 볼 시각 상한)
#
# 마지막 값은 **수집 시각(KST) 기준으로 그 장이 아직 안 열렸다고 볼 시각**이다.
# 국장은 09:00 개장이라 9, 미장은 22:30 개장(서머타임 때 23:30)이라 22를 쓴다.
# 그 시각 전에 낸 픽은 **같은 날짜의 장**을 겨냥한 것이므로, 그날 봉의
# 시가·저가와 픽 가격을 비교하면 된다.
#
# 코인·매크로는 없다. 대상이 고정된 선물이라 손절 규칙을 안 걸고
# (`notes/trading-rules.md`), 스냅샷에 일별 OHLC도 없다.
_INTRADAY_SRC = {
    "kr": ("kr_*.json", "stocks", "code", 9),
    "us": ("us_*.json", "selected", "symbol", 22),
}


def _intraday(markets=None):
    """픽별 (갭%, 장중최저%)를 실측한다. 반환: [(pick, out, 갭, 최저)].

    스냅샷의 종목마다 `ohlcv_tail`(일별 OHLC 5일치)이 들어 있어서, 픽을 낸
    뒤 열린 장의 시가·저가를 그대로 쓸 수 있다. `history/`에는 다음 스냅샷의
    가격만 남아(`core/history.py`의 record_out) 이걸로만 잴 수 있다.

    **개장 전에 낸 픽만 센다.** 장이 열린 뒤 낸 픽에 그날 장을 결과로 붙이면
    이미 지나간 장을 결과로 쓰는 것이 된다. 그 픽이 겨냥한 것은 다음 장이다.

    **`history.pairs()` 를 그대로 못 쓴다.** 그쪽은 날짜·종목별로 **마지막**
    픽만 남기는데, 국장은 저녁에도 수집되므로 그 마지막이 저녁 픽이다.
    저녁 픽은 다음 장을 겨냥한 것이라 개장 전 필터에서 통째로 빠지고,
    정작 그날 장을 겨냥했던 아침 픽까지 같이 사라진다(실측: 11건이 9건으로).
    그래서 여기서는 **개장 전 픽 안에서** 날짜·종목별 마지막을 고른다.

    이 함수가 있는 이유: 손절이 걸리는 비율을 모형으로 추정했다가 크게
    빗나갔다. 실측 −3% 27% vs 추정 48%. 잴 수 있으면 재야 한다.

    **미장은 2026-08-14부터 쌓인다.** 그전 스냅샷에는 `ohlcv_tail`이 없어
    빈 값으로 나온다 — 없는 것과 못 받은 것을 구분해야 하므로 0으로 세지
    않고 아예 빼고, 부르는 쪽이 자산군별 건수를 함께 찍는다.
    """
    markets = [m for m in (markets or MARKETS) if m in _INTRADAY_SRC]
    tail = defaultdict(dict)
    for m in markets:
        pattern, arr_key, code_key, _ = _INTRADAY_SRC[m]
        for path in glob.glob(os.path.join(_ROOT, "cloud", pattern)):
            try:
                with open(path, encoding="utf-8") as fp:
                    snap = json.load(fp)
            except (OSError, ValueError):
                continue
            for s in snap.get(arr_key) or []:
                for r in s.get("ohlcv_tail") or []:
                    tail[(m, s.get(code_key))][str(r.get("date"))] = r

    picks, outs = history.load()
    best = {}
    for p in picks.values():
        at = p.get("at") or ""
        m = p.get("market")
        if m not in markets or not p.get("price") or len(at) < 13:
            continue
        if int(at[11:13]) >= _INTRADAY_SRC[m][3]:
            continue                      # 개장 후 픽 — 그 장은 이미 지났다
        if _held(p, outs.get(p["id"]) or {}) is None:
            continue                      # 결과가 아직 없거나 방향이 없다
        k = (m, at[:10], p.get("key"))
        if k not in best or p["at"] > best[k]["at"]:
            best[k] = p

    out = []
    for p in sorted(best.values(), key=lambda x: x["at"]):
        r = tail.get((p["market"], p.get("key")), {}).get(
            p["at"][:10].replace("-", ""))
        if not r or not r.get("open") or not r.get("low"):
            continue
        base = p["price"]
        out.append((p, outs[p["id"]], (r["open"] / base - 1) * 100,
                    (r["low"] / base - 1) * 100))
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

    print("\n    손절이 걸릴 확률 (픽별 변동폭에서 추정 — 실측 아님):")
    for m in markets:
        v = [p["vol_20d"] for p, _ in rows
             if p["market"] == m and p.get("vol_20d")]
        if not v:
            continue
        cols = "  ".join(f"-{s:g}% {st.mean([_touch(s, x) for x in v])*100:3.0f}%"
                         for s in stops)
        print(f"      {m:6s} {cols}")
    print("    실제로 그 아래로 **마감한** 건수는 아래 [2]에 있다. 둘이 크게")
    print("    벌어지면, 걸리는 대부분이 스쳤다 돌아온 자리라는 뜻이다.")

    # ------------------------------------- 1b. 장중 저가로 직접 (국장만)
    intra = _intraday(markets)
    if intra:
        by_m = defaultdict(int)
        for p, _, _, _ in intra:
            by_m[p["market"]] += 1
        got = " · ".join(f"{m} {by_m[m]}건" for m in markets if by_m.get(m))
        missing = [m for m in markets if m in _INTRADAY_SRC and not by_m.get(m)]
        print(f"\n[1b] 장중 저가로 직접 잰 것 — 개장 전 픽 {len(intra)}건 ({got})")
        print("     추정이 아니다. 스냅샷의 ohlcv_tail 을 그대로 쓴다.")
        if missing:
            print(f"     ※ {'·'.join(missing)}는 아직 0건이다 — 없는 게 아니라")
            print("       ohlcv_tail 이 쌓이기 전 스냅샷이라 못 받은 것이다.")
        print(f"  {'손절선':>8s} {'실제로 닿음':>12s} {'추정이었다면':>13s} "
              f"{'갭으로 통과':>11s}")
        for s in stops:
            n = sum(1 for _, _, _, low in intra if low <= -s)
            gaps = sum(1 for _, _, g, _ in intra if g <= -s)
            vs = [p["vol_20d"] for p, _, _, _ in intra if p.get("vol_20d")]
            est = (f"{st.mean([_touch(s, v) for v in vs])*100:11.0f}%"
                   if vs else f"{'—':>12s}")
            print(f"  {f'-{s:g}%':>8s} {n:6d}/{len(intra):<3d} "
                  f"({n*100/len(intra):3.0f}%) {est} {gaps:9d}건")
        print("     추정이 실측보다 크게 높으면 모형이 과하게 흔든 것이다.")

        print("\n     실제 체결로 실현한 손익 (갭이면 시가에 체결):")
        base = st.mean([_held(p, o) for p, o, _, _ in intra])
        print(f"       {'손절 없음':>10s} {base:+8.2f}%")
        for s in stops:
            vals = []
            for p, o, gap, low in intra:
                vals.append((gap if gap <= -s else -s) if low <= -s
                            else _held(p, o))
            cut = sum(1 for _, _, _, low in intra if low <= -s)
            print(f"       {f'-{s:g}%':>10s} {st.mean(vals):+8.2f}%  "
                  f"{cut}건 잘림")
        print("     손절 없음보다 낮아도 놀랄 것 없다 — 손절의 값은 평균이")
        print("     아니라 꼬리에서 나오는데, 표본에 꼬리가 없으면 비용만 남는다.")

    # ------------------------------------------------------- 2·3. 두 방식
    _table("[2] 고정 % 손절 — 자산군에 상관없이 같은 숫자를 쓸 때",
           rows, markets, "pct", stops)
    _table("[3] 하루 변동폭 배수 손절 — 그 종목의 평소 움직임으로 재서 걸 때",
           rows, markets, "mult", mults)
    print("     변동성이 없는 픽은 분모에서 뺀다 (코인에 이 값이 없다).")

    # ------------------------------------------------ 4. 장중 스침까지
    print("\n[4] 장중에 스쳐서 잘리는 것까지 넣으면")
    print("    종가는 실측이지만 장중 저가는 기록에 없다. 하루 변동폭에서")
    print("    추정한 값이다 — 정확한 값이 아니라 방향을 보는 것이다.")
    # 변동성이 없으면 스침을 추정할 방법이 없다 — 코인이 그렇다.
    with_vol = [(p, o) for p, o in rows if p.get("vol_20d")]
    if not with_vol:
        print("    변동성 기록이 있는 픽이 없어 잴 수 없다.")
    else:
        print(f"  {'손절선':>8s} {'기대 손익':>10s} {'잘리는 비율':>11s}   "
              f"(자산군별 기대 손익)")
        base = st.mean([_held(p, o) for p, o in with_vol])
        print(f"  {'없음':>8s} {base:+9.2f}% {'—':>11s}")
        for s in stops:
            r = _ev_with_touch(rows, s)
            if not r:
                continue
            line = f"  {f'-{s:g}%':>8s} {r[0]:+9.2f}% {r[1]*100:10.0f}%   "
            for m in markets:
                sub = [(p, o) for p, o in rows if p["market"] == m]
                rm = _ev_with_touch(sub, s)
                if rm:
                    line += f" {m} {rm[0]:+.2f}%"
            print(line)
        print("    손절 없이 든 값보다 낮으면 잡음에 잘리고 있다는 뜻인데,")
        print("    **이 추정은 실제보다 과하게 잘린다.** [1b]와 비교해서 읽어라.")

        # ---------------------------- 5. 변동폭이 큰 픽을 빼면 달라지나
        print("\n[5] 변동폭이 큰 픽을 아예 안 들면")
        print("    한때 이 표를 근거로 '변동폭 3% 넘는 픽은 안 든다'를 규칙에")
        print("    넣었다가 뺐다. 여기 쓰인 스침이 추정이라 그렇다 — [1b]에서")
        print("    실측하니 변동폭 10%인 종목이 장중에 진입가 아래로 한 번도")
        print("    안 내려가고 +8.36%로 끝났다. 실측이 있으면 그쪽을 믿어라.")
        for s in stops:
            print(f"  [-{s:g}% 손절]  " + "  ".join(
                f"{'상한없음' if c is None else f'변동폭 {c:g}%'}:" +
                (lambda r: f"{r[0]:+.2f}%({r[2]}건,{r[1]*100:.0f}%컷)"
                 if r else "—")(_ev_with_touch(
                     [(p, o) for p, o in rows
                      if c is None or (p.get("vol_20d") or 99) <= c], s))
                for c in (None, 5.0, 4.0, 3.0)))
        print("    '건수'가 확 줄면 그만큼 드는 날이 줄어든다는 뜻이다.")

    # -------------------------------------------- 6. 한 건이 끌고 가는가
    if a.drop_worst:
        worst = sorted(rows, key=lambda x: _held(*x))[:a.drop_worst]
        kept = [r for r in rows if r not in worst]
        print(f"\n[6] 최악 {a.drop_worst}건을 빼면 — 결론이 한 건짜리인지 본다")
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
