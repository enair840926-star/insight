# -*- coding: utf-8 -*-
"""픽의 결과를 남긴다 — 되짚을 수 있어야 나아진다

`core/pick.py`가 매일 3종을 고르지만 지금까지는 그것이 맞았는지 아무도
재지 않았다. 재는 기록이 없으면 규칙을 고칠 근거도 없고, 고쳐도 나아졌는지
알 수 없다. 여기서 픽과 그 결과를 한 줄씩 남긴다.

**형식은 JSONL이고 덧붙이기만 한다.** 클라우드가 하루에 여러 번 커밋하고
PC도 따로 커밋하므로, 줄 단위로 쌓여야 병합에서 잃는 것이 없다
(`.gitattributes`의 `merge=union`). 한 파일에 픽과 결과를 함께 두되
`t` 필드로 가른다 — 두 파일로 나누면 병합이 두 배로 어긋난다.

## 언제 기록하지 않는가

**장중 스냅샷은 남기지 않는다.** 그때의 가격은 이미 결과가 절반 섞인
값이라, 그것을 기준으로 다음 세션 수익률을 재면 앞뒤가 겹친다. 개장 전
스냅샷의 종가끼리 비교해야 정확히 한 세션이 된다.

하루에 여러 번 수집되면 같은 자산군의 픽이 여러 줄 쌓인다. 지우지 않고
그대로 두되 **집계에서 자산군·날짜별로 마지막 것만 쓴다** — 어느 것이
실제로 글에 나갔는지는 그때 가서 판단하는 편이 안전하다.

## 무엇을 '맞았다'로 볼 것인가

**벤치마크 대비 초과수익.** 시장이 다 오르는 날 픽이 오른 것은 정보가
아니다. `pick.py`의 상대강도가 같은 논리를 쓰고 있어 일관된다.

    상승 픽 · 팽팽 아닌 것   초과수익 > 0 이면 맞음
    하락 픽 · 피할 것        초과수익 < 0 이면 맞음
    팽팽                     채점하지 않는다 (따로 센다)

매크로에는 벤치마크가 없다. 금과 원유를 함께 재는 지수가 없으므로
절대 등락으로 남기고, 집계에서 그 사실을 밝힌다.
"""
import datetime as dt
import json
import statistics as stat
from pathlib import Path

from core import pick, regime, session, store

# 규칙을 바꾸면 올린다. 이 값이 다르면 기록끼리 직접 비교하면 안 된다.
# 신호 목록도 함께 남기므로 사후에 어떤 규칙이었는지 역추적할 수 있다.
RULES_VERSION = "2026-08-09"

# 결과로 인정할 최소 간격. 예약이 겹쳐 같은 날 여러 번 수집되면 1분 간격
# 스냅샷끼리 결과를 채우게 되는데, 그건 등락 0%를 '틀림'으로 채점하는
# 짓이다(실측: 그 때문에 국장 62건 중 맞음이 2건으로 나왔다). 세션 하나가
# 지나야 결과다 — 국장·미장은 개장 전끼리 약 24시간, 주말이 끼면 더 길다.
MIN_HOURS = 12

DIR = store.ROOT / "history"

# 자산군별 벤치마크. 시장이 다 오른 날의 상승은 정보가 아니다.
BENCH = {
    "us": "S&P500",
    "kr": "코스피",
    "coin": "코인 총시총",
    "macro": None,      # 금과 원유를 함께 재는 지수가 없다
}


def _path(when):
    return DIR / f"picks-{when:%Y-%m}.jsonl"


def _append(rows):
    if not rows:
        return 0
    DIR.mkdir(exist_ok=True)
    f = _path(dt.datetime.now())
    with f.open("a", encoding="utf-8") as fp:
        for r in rows:
            fp.write(json.dumps(r, ensure_ascii=False) + "\n")
    return len(rows)


def load(months=6):
    """최근 N개월치를 읽는다. 반환: (픽 dict, 결과 dict) — 둘 다 id 기준.

    같은 id가 여러 줄이면 뒤엣것이 이긴다. union 병합이 중복을 만들 수
    있는데, 픽 내용은 같으므로 덮어써도 잃는 것이 없다.
    """
    picks, outs = {}, {}
    if not DIR.is_dir():
        return picks, outs
    for f in sorted(DIR.glob("picks-*.jsonl"))[-months:]:
        for line in f.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except ValueError:
                continue      # 병합이 줄을 반토막 냈을 수 있다. 버린다.
            t = r.get("t")
            if t == "regime":
                continue      # 시장 판정은 load_regimes()가 따로 읽는다
            (outs if t == "out" else picks)[r.get("id")] = r
    return picks, outs


def load_regimes(months=6):
    """시장 판정 기록. 반환: id -> 레코드.

    픽과 같은 파일에 두되 `t`로 가른다. 두 파일로 나누면 union 병합이
    두 배로 어긋난다.
    """
    out = {}
    if not DIR.is_dir():
        return out
    for f in sorted(DIR.glob("picks-*.jsonl"))[-months:]:
        for line in f.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except ValueError:
                continue
            if r.get("t") == "regime":
                out[r.get("id")] = r
    return out


# ---------------------------------------------------------------- 기록
def _bench_value(market, bundle):
    """벤치마크의 현재 수준. 없으면 None."""
    if market == "us":
        return ((bundle.get("indices") or {}).get("S&P500") or {}).get("price")
    if market == "kr":
        for ix in bundle.get("indices") or []:
            if ix.get("name") == "코스피":
                return ix.get("close")
        return None
    if market == "coin":
        return (bundle.get("global") or {}).get("total_market_cap_usd")
    return None


def record(market, picks, bundle, partial=False):
    """이번 픽을 남긴다. 반환: 남긴 줄 수.

    장중 스냅샷은 남기지 않는다 — 위 설명 참조.
    """
    if partial or not picks:
        return 0
    at = bundle.get("collected_at") or ""
    stamp = at.replace("-", "").replace("T", "_").replace(":", "")[:13]
    bench = _bench_value(market, bundle)
    by_key = {c.get("key"): c for c in pick.BY_MARKET[market](bundle)}

    rows = []
    for i, p in enumerate(picks, 1):
        c = by_key.get(p["key"]) or {}
        rows.append({
            "t": "pick",
            "id": f"{market}|{stamp}|{p['key']}",
            "market": market, "at": at, "key": p["key"], "label": p["label"],
            "rank": i, "kind": p["kind"], "score": p["score"],
            "signals": p["why"],
            "price": c.get("price"),
            "vol_20d": c.get("volatility_20d"),
            "bench": bench, "bench_name": BENCH.get(market),
            "rules": RULES_VERSION,
        })
    return _append(rows)


# ---------------------------------------------------------------- 결과
# 픽의 방향과 초과수익의 부호가 맞아야 '맞음'이다. 팽팽은 채점하지 않는다.
_WANT = {"상승": 1, "하락": -1, "피할 것": -1}


# 스냅샷에서 종목 배열을 꺼내는 법과, 그 장이 아직 안 열렸다고 볼 시각(KST).
# 국장 09:00, 미장 22:30(서머타임 23:30) 개장이다. 그 전에 낸 픽은 **같은
# 날짜의 장**을 겨냥한 것이므로 그날 봉과 비교하면 된다.
#
# 코인·매크로는 없다. 24시간 거래라 '그날 장'이 없거나 일별 OHLC를 안 받는다.
_SESSION_SRC = {
    "kr": ("stocks", "code", 9),
    "us": ("selected", "symbol", 22),
}


def _excursion(market, bundle, pick):
    """픽이 겨냥한 장이 어디까지 갔나. 반환: (갭%, 최고%, 최저%) 또는 None.

    **`cloud/` 에서 나중에 읽으면 안 되기 때문에 여기서 남긴다.**
    `core/store.py`의 `publish(keep=2)`가 자산군당 스냅샷을 2세대만 남기고
    지운다. 표본 100건이 쌓일 때쯤이면 그 픽이 겨냥했던 장의 시가·고가·저가는
    작업 트리에서 이미 사라져 있다. `history/*.jsonl` 은 덧붙이기만 하는
    영구 기록이라(`.gitattributes`의 merge=union) 여기 넣어야 남는다.

    이 셋이 있어야 답할 수 있는 것:
      갭   — 손절 주문이 그 값에 체결됐을까, 아니면 시가에 밀렸을까
      최저 — 손절선이 장중에 걸렸을까 (종가만으로는 덜 걸린 것으로 나온다)
      최고 — **익절선을 어디에 두면 얼마를 쥐었을까**

    최고가 없으면 익절 수치는 영영 못 찾는다. 종가만 보면 "얼마까지 갔다가
    돌아왔는지"가 안 보이기 때문이다.
    """
    src = _SESSION_SRC.get(market)
    at, base = pick.get("at") or "", pick.get("price")
    if not src or not base or len(at) < 13:
        return None
    arr_key, code_key, open_h = src
    if int(at[11:13]) >= open_h:
        return None            # 장이 열린 뒤 낸 픽 — 그 장은 이미 지났다
    want_date = at[:10].replace("-", "")
    for s in bundle.get(arr_key) or []:
        if s.get(code_key) != pick.get("key"):
            continue
        for r in s.get("ohlcv_tail") or []:
            if str(r.get("date")) != want_date:
                continue
            o, h, l = r.get("open"), r.get("high"), r.get("low")
            if not (o and h and l):
                return None
            return (round((o / base - 1) * 100, 3),
                    round((h / base - 1) * 100, 3),
                    round((l / base - 1) * 100, 3))
    return None


def settle(market, bundle, partial=False):
    """아직 결과가 없는 픽에 이번 스냅샷의 가격을 채운다. 반환: 채운 수."""
    if partial:
        return 0
    picks, outs = load()
    open_ = [p for p in picks.values()
             if p.get("market") == market and p["id"] not in outs
             and p.get("price")]
    if not open_:
        return 0

    now_at = bundle.get("collected_at") or ""
    price_of = {c.get("key"): c.get("price")
                for c in pick.BY_MARKET[market](bundle)}
    bench_now = _bench_value(market, bundle)

    rows = []
    for p in open_:
        now = price_of.get(p["key"])
        if not now or p["at"] >= now_at:
            continue          # 같은 스냅샷이거나 종목이 빠졌다
        hours = _hours(p["at"], now_at)
        if hours < MIN_HOURS:
            continue          # 아직 한 세션이 안 지났다. 다음 수집을 기다린다.
        ret = (now / p["price"] - 1) * 100
        b_ret = None
        if p.get("bench") and bench_now:
            b_ret = (bench_now / p["bench"] - 1) * 100
        excess = round(ret - b_ret, 3) if b_ret is not None else round(ret, 3)

        want = _WANT.get(p.get("kind"))
        exc = _excursion(market, bundle, p)
        rows.append({
            "t": "out",
            "id": p["id"], "market": market, "at": now_at,
            "hours": round(hours, 1),
            "price": now, "ret_pct": round(ret, 3),
            # 그 장이 어디까지 갔나 — 손절·익절 수치를 나중에 찾기 위한 값.
            # 못 받으면 키를 아예 안 넣는다. 0으로 채우면 '안 움직였다'로
            # 읽혀서, 없는 것과 못 받은 것이 구별되지 않는다.
            **(dict(zip(("gap_pct", "mfe_pct", "mae_pct"), exc)) if exc else {}),
            "bench_ret_pct": round(b_ret, 3) if b_ret is not None else None,
            "excess_pct": excess,
            # 벤치마크가 없는 매크로는 절대 등락으로 잰다는 사실을 남긴다.
            "vs_bench": b_ret is not None,
            # 초과수익이 정확히 0이면 맞다고도 틀렸다고도 할 수 없다.
            "correct": (None if want is None or excess == 0
                        else (excess * want > 0)),
            # '오늘 볼 선'이 실제로 깨졌는지. 표본이 적어도 답이 나오는
            # 질문이라 1단계의 첫 목표다.
            "broke_1sigma": (bool(p.get("vol_20d")) and ret <= -p["vol_20d"]),
        })
    return _append(rows)


# 판정을 채점할 잣대.
#
# **판정이 맞았다 = 판정한 방향대로 그 시장이 다음 세션에 움직였다.**
# '중립'은 방향을 주장하지 않았으므로 채점하지 않는다 — 픽의 '팽팽'과 같다.
#
# 매크로만 픽과 다른 것을 쓴다. 픽의 `BENCH["macro"]`가 None인 이유는 금과
# 원유를 함께 재는 지수가 없어서인데, **판정이 재는 것은 금·원유 자체가
# 아니라 그 배경인 위험 선호다**(`core/regime.py`의 `_macro`). 그래서
# S&P500을 대리로 쓴다. 미장 판정과 같은 잣대가 되지만, 두 판정이 갈리는
# 것 자체가 정보다 — 신호 구성이 다르기 때문이다.
REGIME_BENCH = {
    "kr": "코스피", "us": "S&P500", "coin": "코인 총시총",
    "macro": "S&P500 (위험 선호 대리)",
}

_REGIME_WANT = {"우호": 1, "비우호": -1}     # 중립은 없다 = 채점 안 함


def _regime_bench(market, bundle):
    """판정 채점용 벤치마크 수준. 없으면 None."""
    if market == "macro":
        for r in bundle.get("records") or []:
            if isinstance(r, dict) and r.get("name") == "S&P500":
                return r.get("price")
        return None
    return _bench_value(market, bundle)


def record_regime(market, bundle, partial=False):
    """시장 판정을 남긴다. 반환: 남긴 줄 수.

    **판정을 안 남기면 픽 때와 같은 자리로 돌아간다** — 매일 '우호'라고
    써 놓고 그것이 맞았는지 아무도 못 재는 상태다. 임계값이 지금은 실측이
    아니라 추정이라 더욱 남겨야 한다. 표본이 차면 이 기록으로 고친다.

    **벤치마크 수준을 함께 남긴다.** 판정만 남기면 '무엇과 비교해 맞았나'를
    나중에 정할 수가 없다 — 그때의 지수 값이 있어야 다음 세션 등락을 낸다.
    """
    if partial:
        return 0
    r = regime.judge(market, bundle)
    if r["state"] == "알 수 없음":
        return 0                      # 잴 재료가 없던 것까지 남기지는 않는다
    at = bundle.get("collected_at") or ""
    stamp = at.replace("-", "").replace("T", "_").replace(":", "")[:13]
    return _append([{
        "t": "regime",
        "id": f"regime|{market}|{stamp}",
        "market": market, "at": at,
        "state": r["state"], "score": r["score"], "n": r["n"],
        "signals": r["why"],
        "bench": _regime_bench(market, bundle),
        "bench_name": REGIME_BENCH.get(market),
        "rules": regime.VERSION,
    }])


def record_signals(market, bundle, partial=False):
    """후보 전체에서 신호가 몇 번 켜졌는지 남긴다. 반환: 남긴 줄 수.

    **스냅샷에서 나중에 다시 세면 되지 않느냐** — 안 된다. `core/store.py`의
    `publish(keep=2)`가 자산군당 스냅샷을 2세대만 남기고 지운다. 며칠만
    지나도 그때 후보가 몇 개였고 어느 신호가 걸렸는지 알 방법이 없다.
    `mfe_pct`를 기록에 넣은 것과 같은 이유다.

    **픽 기록으로는 대신할 수 없다.** 픽은 점수가 높아서 뽑힌 셋뿐이라
    거기서 신호를 세면 선택 편향이 걸린다(`pick.tally`의 설명 참조).
    죽은 신호도 상수 신호도 후보 전체를 봐야 보인다.

    장중 스냅샷은 남기지 않는다 — 거래량 게이트가 그때만 걸려서 탈락
    분포가 달라진다. 섞으면 둘 다 못 읽는다.
    """
    if partial:
        return 0
    try:
        t = pick.tally(market, bundle, partial)
    except Exception:
        return 0                      # 집계 때문에 수집이 죽으면 안 된다
    if not t.get("cands"):
        return 0
    at = bundle.get("collected_at") or ""
    stamp = at.replace("-", "").replace("T", "_").replace(":", "")[:13]
    return _append([{
        "t": "signals",
        "id": f"signals|{market}|{stamp}",
        "market": market, "at": at,
        "cands": t["cands"], "n": t["n"], "gated": t["gated"],
        "gate_why": t["gate_why"], "dirs": t["dirs"], "sig": t["sig"],
        "rules": RULES_VERSION,
    }])


def load_signals(months=6, markets=None, per_day=True):
    """신호 집계 기록. 반환: [레코드].

    기본은 **자산군·날짜별 마지막 하나**다. 하루에 여러 번 수집되므로
    전부 세면 그날이 여러 번 반영돼 분포가 부푼다 — `pairs()`·
    `regime_probe.snapshots()`와 같은 처리다.
    """
    rows = []
    if not DIR.is_dir():
        return rows
    for f in sorted(DIR.glob("picks-*.jsonl"))[-months:]:
        for line in f.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except ValueError:
                continue
            if r.get("t") != "signals":
                continue
            if markets and r.get("market") not in markets:
                continue
            rows.append(r)
    if per_day:
        best = {}
        for r in rows:
            k = (r.get("market"), (r.get("at") or "")[:10])
            if k not in best or (r.get("at") or "") > best[k].get("at", ""):
                best[k] = r
        rows = list(best.values())
    return sorted(rows, key=lambda r: (r.get("market", ""), r.get("at", "")))


def settle_regime(market, bundle, partial=False):
    """결과가 없는 판정에 이번 스냅샷의 벤치마크를 채운다. 반환: 채운 수.

    `settle()`이 픽에 하는 일을 판정에 한다. 같은 이유로 `MIN_HOURS`를
    지킨다 — 예약이 겹쳐 1분 뒤에 또 수집되면 등락 0%를 결과로 쓰게 된다.

    **'맞았다/틀렸다'를 여기서 정하지 않는다.** 등락만 남기고 판정은
    `regime_verdict()`가 한다. 횡보로 볼 폭을 지금은 모르기 때문이다 —
    상수를 박아 두면 나중에 분포를 보고도 못 고친다.
    """
    if partial:
        return 0
    regs, outs = load_regimes(), load_regime_outs()
    now_at = bundle.get("collected_at") or ""
    now_bench = _regime_bench(market, bundle)
    if not now_bench:
        return 0

    rows = []
    for r in regs.values():
        if r.get("market") != market or r["id"] in outs or not r.get("bench"):
            continue
        if r.get("state") not in _REGIME_WANT:
            continue                  # 중립은 방향 주장이 없어 채점 대상이 아니다
        if not r.get("at") or r["at"] >= now_at:
            continue
        hours = _hours(r["at"], now_at)
        if hours < MIN_HOURS:
            continue
        rows.append({
            "t": "regime_out",
            "id": r["id"], "market": market, "at": now_at,
            "hours": round(hours, 1),
            "bench": now_bench,
            "bench_ret_pct": round((now_bench / r["bench"] - 1) * 100, 3),
        })
    return _append(rows)


def load_regime_outs(months=6):
    """판정 결과. 반환: id -> 레코드."""
    out = {}
    if not DIR.is_dir():
        return out
    for f in sorted(DIR.glob("picks-*.jsonl"))[-months:]:
        for line in f.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except ValueError:
                continue
            if r.get("t") == "regime_out":
                out[r.get("id")] = r
    return out


def regime_pairs(markets=None):
    """(판정, 결과) 쌍. 자산군·날짜별 마지막 판정만 쓴다.

    하루에 여러 번 수집되므로 전부 세면 그날이 여러 번 반영돼 표본이
    부푼다 — `pairs()`와 같은 이유다.
    """
    markets = markets or MARKETS
    regs, outs = load_regimes(), load_regime_outs()
    best = {}
    for r in regs.values():
        if r.get("market") not in markets:
            continue
        k = (r["market"], (r.get("at") or "")[:10])
        if k not in best or r["at"] > best[k]["at"]:
            best[k] = r
    return [(r, outs[r["id"]]) for r in best.values() if r["id"] in outs]


def regime_flat_band(rows, market, k=None):
    """횡보로 볼 폭. **상수를 안 쓴다** — 그 시장 벤치마크가 실제로 얼마나
    움직였는지에서 낸다.

    코스피의 0.3%와 코인 총시총의 0.3%는 다른 사건이다. 그렇다고 지금
    자산군별 상수를 박으면 분포를 모르는 채로 정하는 것이라, 기록에서
    중간 절대 등락을 구해 그 `k`배를 쓴다.

    표본이 모자라면 0을 돌려준다 — 가르지 않는다는 뜻이다. 없는 기준으로
    '횡보'를 만들면 적중률이 그 임의값에 끌려간다.
    """
    xs = [abs(o["bench_ret_pct"]) for r, o in rows
          if r.get("market") == market and o.get("bench_ret_pct") is not None]
    if len(xs) < REGIME_BAND_MIN:
        return 0.0
    return (FLAT_K if k is None else k) * stat.median(xs)


def regime_verdict(reg, out, band=0.0):
    """판정이 맞았나. 반환: '맞음' · '틀림' · '횡보' · None(중립·자료없음)."""
    want = _REGIME_WANT.get(reg.get("state"))
    ret = out.get("bench_ret_pct")
    if want is None or ret is None:
        return None
    if band and abs(ret) < band:
        return "횡보"
    return "맞음" if ret * want > 0 else "틀림"


# 횡보 폭을 낼 수 있는 최소 표본. 이보다 적으면 가르지 않는다.
REGIME_BAND_MIN = 10

# 판정을 읽을 만해지는 표본. 픽의 캘리브레이션과 같은 자리에 둔다.
ENOUGH_REGIME = 100


def track(market, bundle):
    """수집기가 부르는 입구. 결과를 먼저 채우고 이번 픽과 판정을 남긴다.

    장중 판단을 수집기 넷이 각자 하면 하나가 틀려도 모른다. 여기서 한 번만
    한다 — `pick.block`이 같은 자리에서 같은 방식으로 판단한다.

    반환: (채운 결과 수, 남긴 픽 수)
    """
    partial = "장중" in (session.describe(market).get("state") or "")
    n_out = settle(market, bundle, partial)
    # 판정 결과를 픽 결과와 같은 자리에서 채운다. 따로 부르게 두면
    # 한쪽만 불리는 날이 생기고, 그러면 기록이 어긋난 채로 쌓인다.
    settle_regime(market, bundle, partial)
    picks, _ = pick.compute(pick.BY_MARKET[market](bundle),
                            market=market, partial=partial)
    record_regime(market, bundle, partial)
    # 후보 전체의 신호 분포. 픽 셋만으로는 죽은 신호도 상수 신호도 못 본다.
    record_signals(market, bundle, partial)
    return n_out, record(market, picks, bundle, partial)


def _hours(a, b):
    try:
        return (dt.datetime.fromisoformat(b)
                - dt.datetime.fromisoformat(a)).total_seconds() / 3600
    except (TypeError, ValueError):
        return 0.0


# ---------------------------------------------------------------- 집계
# 표본이 이보다 적으면 숫자를 내되 판단하지 말라고 함께 적는다.
# 답이 나오는 순서가 다르다 — 캘리브레이션이 먼저 답하고 신호별이 제일 늦다.
ENOUGH = {"calib": 100, "score": 200, "signal": 1000}

MARKETS = ["kr", "us", "coin", "macro"]


def pairs(markets=None):
    """(픽, 결과) 쌍. 자산군·날짜별로 마지막 픽만 쓴다.

    예약이 겹쳐 하루에 여러 번 수집되면 같은 자산군의 픽이 여러 줄 쌓인다.
    전부 세면 그날 하루가 여러 번 반영돼 표본이 부풀고, 같은 종목이
    중복돼 특정 날에 결과가 쏠린다.
    """
    markets = markets or MARKETS
    picks, outs = load()
    best = {}
    for p in picks.values():
        if p.get("market") not in markets:
            continue
        day = (p.get("at") or "")[:10]
        k = (p["market"], day, p.get("key"))
        if k not in best or p["at"] > best[k]["at"]:
            best[k] = p
    return [(p, outs[p["id"]]) for p in best.values() if p["id"] in outs]


# 절대 등락으로 셀 때 '횡보'로 볼 폭. 그 종목의 평소 하루 변동폭(20일
# 변동성)에 곱한다. 고정 퍼센트로 두면 안 된다 — 비트코인의 0.5%와
# 삼성전자의 0.5%는 다른 사건이라, 고정값이면 변동성 큰 종목만 계속
# 맞거나 계속 틀린 것으로 잡힌다.
#
# 0.5배인 이유: 이보다 작은 움직임은 방향이라기보다 그날의 잡음이다.
# +0.01%를 '맞음'으로 세면 적중률이 부풀고, 그 숫자로는 규칙이 나아졌는지
# 알 수 없다.
FLAT_K = 0.5


def abs_verdict(pick, out, k=FLAT_K):
    """절대 등락 기준 판정. 반환: '맞음' · '틀림' · '횡보' · None.

    `correct` 는 벤치마크 대비 초과수익으로 잰다 — 시장이 다 오르는 날의
    상승은 정보가 아니기 때문이다. 그건 **규칙이 값을 하는가**에 답한다.

    이쪽은 벤치마크를 빼지 않는다. 코스피 방향은 이 시스템의 예측 대상이
    아니라서, 지수를 함께 공매도하는 게 아니라면 초과수익은 거래로 옮길
    수가 없다. 실제로 손에 쥐는 것은 절대 등락이고, 이건 **근거대로
    움직였는가**에 답한다. 어느 쪽도 틀리지 않아 둘 다 남긴다.
    """
    want = _WANT.get(pick.get("kind"))
    if want is None:                      # 팽팽은 방향이 없다
        return None
    ret = out.get("ret_pct")
    if ret is None:
        return None
    vol = pick.get("vol_20d")
    band = k * vol if vol else 0.0        # 변동성이 없으면 횡보를 안 가른다
    if abs(ret) < band:
        return "횡보"
    return "맞음" if ret * want > 0 else "틀림"


# 누적 등락을 낼 자산군. 선물(코인·매크로)은 뺀다.
#
# 대상이 고정이기 때문이다. 주식은 국장 266개·미장 30개 후보에서 3종을
# 고르므로 '이걸 골랐다'가 곧 규칙의 성적이지만, 선물은 BTC·ETH / 금·WTI가
# 매일 그대로 올라온다. 그걸 같은 무게로 들었다고 치면 나오는 값은 규칙의
# 성적이 아니라 그 넷의 시장 수익률이다.
#
# 실측 2026-08-13: macro 4일 8건이 **전부 '상승'** 이라 누적 +4.89%가
# 금과 WTI원유를 4일 들고 있던 것과 완전히 같은 값이었다. 규칙을 통째로
# 바꿔도 이 숫자는 안 움직인다 — 잴 수 있는 것이 없다는 뜻이다.
#
# 선물에서도 방향은 여전히 센다([2]·[2b]). 고정 대상이 어느 쪽으로 갈지가
# 애초에 그쪽에 바라는 전부다.
CUM_MARKETS = ["kr", "us"]

# 누적을 읽을 만해지는 날 수. 건수가 아니라 **날 수**로 센다 — 누적은
# 하루가 한 점이라 픽 60건이 20일치면 점이 20개뿐이다.
CUM_DAYS = 60


def daily_sums(rows, market):
    """날짜별 픽 평균 등락과 그 누적. 반환: [(날짜, 종목수, 평균, 누적)].

    그날 픽 3종에 돈을 똑같이 나눠 넣었다고 보고 등락을 **평균**낸다.
    적중률은 '몇 번 맞았나'만 답하고 폭을 안 보는데, 아홉 번 +0.1%로 맞고
    한 번 -5%로 틀리면 적중률은 90%지만 누적은 마이너스다. 그 차이를
    여기서 본다.

    **합이 아니라 평균이다.** 합은 3종을 각각 한 몫씩 들었다는 뜻이라
    3배로 굴린 값이 되어 손에 쥐는 것과 다르다. 게다가 날마다 픽 수가
    같지 않다 — 실측 2026-08-13 국장은 3종·3종·2종·1종이었고, 그대로
    더하면 종목이 많은 날이 그 이유만으로 크게 잡혀 날끼리 비교가 안 된다.
    평균이면 '그날 픽을 들었으면 얼마'가 되어 날짜가 같은 잣대로 이어진다.

    **벤치마크를 빼지 않는다.** 지수와 무관한 절대 손익이다 — 코스피가
    오르든 내리든 계좌에 찍히는 것은 이 값이다.

    **하락 픽은 부호를 뒤집는다.** '하락'·'피할 것'이 실제로 내렸으면
    맞은 것이므로 플러스로 센다. 그래야 상승 픽과 같은 잣대가 된다.
    팽팽은 방향이 없어 뺀다.

    자산군 안에서만 이어 볼 수 있다. 변동성이 달라 섞으면 큰 쪽이 전부를
    가린다. 부르는 쪽은 `CUM_MARKETS` 만 넘긴다 — 선물은 대상이 고정이라
    누적이 규칙이 아니라 시장을 재게 된다.
    """
    by_day = {}
    for p, o in rows:
        if p.get("market") != market:
            continue
        want = _WANT.get(p.get("kind"))
        ret = o.get("ret_pct")
        if want is None or ret is None:
            continue
        day = (p.get("at") or "")[:10]
        by_day.setdefault(day, []).append(ret * want)
    out, run = [], 0.0
    for day in sorted(by_day):
        xs = by_day[day]
        avg = stat.mean(xs)
        run += avg
        out.append((day, len(xs), round(avg, 2), round(run, 2)))
    return out


def verdict(n, need, claim):
    if n >= need:
        return claim
    return f"표본 {n}건 — {need}건은 모여야 판단할 수 있다. 아직 읽지 마라."


def coin_flip_gap(hits, n):
    """정말 동전 던지기와 다른가. 반환: 설명 문자열.

    p=0.5의 표준오차는 0.5/sqrt(n)이다. 2배를 못 넘으면 우연과 구별되지
    않는다 — 그 상태에서 규칙을 고치면 노이즈를 쫓는 것이다.
    """
    if not n:
        return ""
    p = hits / n
    se = 0.5 / (n ** 0.5)
    if abs(p - 0.5) > 2 * se:
        return f"동전 던지기와 다르다 (오차 범위 ±{2*se*100:.0f}%p)"
    return f"우연과 구별 안 됨 (오차 범위 ±{2*se*100:.0f}%p)"


def summary(markets=None):
    """픽 성적 집계. `tools/score_picks.py`와 대시보드가 함께 쓴다.

    집계를 여기 두는 이유는 사본을 만들지 않기 위해서다. 화면에 찍는 숫자와
    도구가 찍는 숫자가 다르면 어느 쪽을 믿어야 할지 알 수 없고, 한쪽만
    고쳐진 채로 오래 간다.

    **표본 충분 여부를 값마다 함께 낸다.** 적중률만 떼어 크게 보이면 우연을
    실력으로 읽는다 — 동전을 45번 던져 21번 앞면이 나온 것과 규칙이 나쁜
    것은 이 표본으로 구별되지 않는다.
    """
    markets = markets or MARKETS
    rows = pairs(markets)
    out = {"n": len(rows), "need": dict(ENOUGH), "markets": {},
           "versions": sorted({p.get("rules") for p, _ in rows if p.get("rules")}),
           "buckets": [], "bucket_total": 0}
    out["mixed_rules"] = len(out["versions"]) > 1
    if not rows:
        return out

    for m in markets:
        d = {"calib": None, "hit": None, "abs": None, "cum": None}

        # 변동성을 못 받은 픽은 분모에서 뺀다. 넣으면 '안 깨졌다'로 세어져
        # 비율이 실제보다 낮게 나온다 — 코인에는 이 값이 아예 없다.
        xs = [o for p, o in rows if p["market"] == m and p.get("vol_20d")]
        if xs:
            broke = sum(1 for o in xs if o.get("broke_1sigma"))
            d["calib"] = {"n": len(xs), "broke": broke,
                          "pct": round(broke * 100 / len(xs), 1),
                          "enough": len(xs) >= ENOUGH["calib"]}

        ys = [(p, o) for p, o in rows
              if p["market"] == m and o.get("correct") is not None]
        if ys:
            hits = sum(1 for _, o in ys if o["correct"])
            ex = [o["excess_pct"] for _, o in ys]
            d["hit"] = {"n": len(ys), "hits": hits,
                        "pct": round(hits * 100 / len(ys), 1),
                        "excess": round(stat.mean(ex), 2),
                        "vs_bench": any(o.get("vs_bench") for _, o in ys),
                        "gap": coin_flip_gap(hits, len(ys)),
                        "enough": len(ys) >= ENOUGH["score"]}
        # 절대 등락 — 지수와 무관하게 근거대로 움직였나. 화면에 크게 내는
        # 것은 이쪽이다. 초과수익은 지수를 함께 공매도해야 손에 쥐는 값이라
        # 계좌에 찍히는 숫자가 아니다.
        zs = [(p, o, v) for p, o in rows if p["market"] == m
              for v in [abs_verdict(p, o)] if v]
        if zs:
            hit = sum(1 for _, _, v in zs if v == "맞음")
            miss = sum(1 for _, _, v in zs if v == "틀림")
            flat = sum(1 for _, _, v in zs if v == "횡보")
            dd = hit + miss          # 횡보는 분모에서 뺀다
            d["abs"] = {
                "n": len(zs), "hits": hit, "miss": miss, "flat": flat,
                "denom": dd,
                "pct": round(hit * 100 / dd, 1) if dd else None,
                "mean": round(stat.mean([o["ret_pct"] for _, o, _ in zs]), 2),
                "gap": coin_flip_gap(hit, dd) if dd else "",
                "enough": dd >= ENOUGH["score"],
            }

        # 누적 손익 — 주식만. 선물은 대상이 고정이라 시장을 재게 된다.
        if m in CUM_MARKETS:
            days = daily_sums(rows, m)
            if days:
                d["cum"] = {
                    "days": days,
                    "total": days[-1][3],
                    "wins": sum(1 for _, _, a, _ in days if a > 0),
                    "n_days": len(days),
                    "best": max(days, key=lambda x: x[2]),
                    "worst": min(days, key=lambda x: x[2]),
                    "enough": len(days) >= CUM_DAYS,
                }

        if d["calib"] or d["hit"] or d.get("abs"):
            out["markets"][m] = d

    buckets = {}
    for p, o in rows:
        if o.get("correct") is None:
            continue
        s = abs(p["score"])
        label = "3~4점" if s <= 4 else "5~6점" if s <= 6 else "7점 이상"
        # 하락·피할 것은 부호를 뒤집어야 '판정이 맞은 정도'가 된다.
        buckets.setdefault(label, []).append(
            o["excess_pct"] * (1 if p["kind"] in ("상승",) else -1))
    for label in ("3~4점", "5~6점", "7점 이상"):
        xs = buckets.get(label) or []
        if xs:
            out["buckets"].append({"label": label, "n": len(xs),
                                   "mean": round(stat.mean(xs), 2),
                                   "median": round(stat.median(xs), 2)})
    out["bucket_total"] = sum(len(v) for v in buckets.values())
    out["bucket_enough"] = out["bucket_total"] >= ENOUGH["score"]
    return out


def open_keys(market, limit=6):
    """결과를 아직 못 채운 픽의 종목. 다음 수집의 워치리스트에 넣는다.

    미장 스크리너는 급등·급락으로 뽑아 어제 픽이 오늘 목록에서 사라진다
    (실측: 최근 세 쌍이 1/3, 1/3, 0/3). 워치리스트는 조용해도 항상
    포함되므로 그 자리에 넣으면 결과를 놓치지 않는다.
    """
    picks, outs = load(months=2)
    keys = [p["key"] for p in sorted(picks.values(), key=lambda x: x["at"],
                                     reverse=True)
            if p.get("market") == market and p["id"] not in outs]
    seen, out = set(), []
    for k in keys:
        if k not in seen:
            seen.add(k)
            out.append(k)
        if len(out) >= limit:
            break
    return out
