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
from pathlib import Path

from core import pick, session, store

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
            (outs if r.get("t") == "out" else picks)[r.get("id")] = r
    return picks, outs


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


def track(market, bundle):
    """수집기가 부르는 입구. 결과를 먼저 채우고 이번 픽을 남긴다.

    장중 판단을 수집기 넷이 각자 하면 하나가 틀려도 모른다. 여기서 한 번만
    한다 — `pick.block`이 같은 자리에서 같은 방식으로 판단한다.

    반환: (채운 결과 수, 남긴 픽 수)
    """
    partial = "장중" in (session.describe(market).get("state") or "")
    n_out = settle(market, bundle, partial)
    picks, _ = pick.compute(pick.BY_MARKET[market](bundle),
                            market=market, partial=partial)
    return n_out, record(market, picks, bundle, partial)


def _hours(a, b):
    try:
        return (dt.datetime.fromisoformat(b)
                - dt.datetime.fromisoformat(a)).total_seconds() / 3600
    except (TypeError, ValueError):
        return 0.0


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
