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
        rows.append({
            "t": "out",
            "id": p["id"], "market": market, "at": now_at,
            "hours": round(hours, 1),
            "price": now, "ret_pct": round(ret, 3),
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


def record_regime(market, bundle, partial=False):
    """시장 판정을 남긴다. 반환: 남긴 줄 수.

    **판정을 안 남기면 픽 때와 같은 자리로 돌아간다** — 매일 '우호'라고
    써 놓고 그것이 맞았는지 아무도 못 재는 상태다. 임계값이 지금은 실측이
    아니라 추정이라 더욱 남겨야 한다. 표본이 차면 이 기록으로 고친다.
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
        "rules": regime.VERSION,
    }])


def track(market, bundle):
    """수집기가 부르는 입구. 결과를 먼저 채우고 이번 픽과 판정을 남긴다.

    장중 판단을 수집기 넷이 각자 하면 하나가 틀려도 모른다. 여기서 한 번만
    한다 — `pick.block`이 같은 자리에서 같은 방식으로 판단한다.

    반환: (채운 결과 수, 남긴 픽 수)
    """
    partial = "장중" in (session.describe(market).get("state") or "")
    n_out = settle(market, bundle, partial)
    picks, _ = pick.compute(pick.BY_MARKET[market](bundle),
                            market=market, partial=partial)
    record_regime(market, bundle, partial)
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


def daily_sums(rows, market):
    """날짜별 픽 등락 합계와 누적. 반환: [(날짜, 종목수, 합계, 누적)].

    그날 픽을 같은 무게로 하나씩 들었다고 보고 등락을 더한다 — 3종이
    합쳐 3% 오르면 그날은 +3이다. 적중률은 '몇 번 맞았나'만 답하고
    폭을 안 보는데, 아홉 번 +0.1%로 맞고 한 번 -5%로 틀리면 적중률은
    90%지만 누적은 마이너스다. 그 차이를 여기서 본다.

    **하락 픽은 부호를 뒤집는다.** '하락'·'피할 것'이 실제로 내렸으면
    맞은 것이므로 플러스로 센다. 그래야 상승 픽과 같은 잣대가 된다.
    팽팽은 방향이 없어 뺀다.

    합계는 자산군 안에서만 이어 볼 수 있다. 자산군마다 픽 수가 다르고
    (주식 3종·선물 2종) 변동성도 달라, 섞으면 큰 쪽이 전부를 가린다.
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
        d = by_day.setdefault(day, [0, 0.0])
        d[0] += 1
        d[1] += ret * want
    out, run = [], 0.0
    for day in sorted(by_day):
        n, s = by_day[day]
        run += s
        out.append((day, n, round(s, 2), round(run, 2)))
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
        d = {"calib": None, "hit": None}

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
        if d["calib"] or d["hit"]:
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
