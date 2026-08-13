# -*- coding: utf-8 -*-
"""매크로 시세 수집 및 파생 지표 계산

국장 수집기와 다른 점:
  - 종목이 40개뿐이라 선별하지 않고 전량 수집·전량 전달
  - 수급/펀더멘털/공시가 없다. 대신 **자산군 간 관계**가 핵심 신호다
  - 개별 등락보다 괴리(divergence)와 금리 커브가 정보량이 크다
"""
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import quote

from core.http import fetch_json

YAHOO = ("https://query1.finance.yahoo.com/v8/finance/chart/{s}"
         "?range={r}&interval=1d")


# ---------------------------------------------------------------- 수집
def _fetch_one(args):
    group, name, symbol, unit, rng = args
    j = fetch_json(YAHOO.format(s=quote(symbol), r=rng))
    try:
        res = j["chart"]["result"][0]
        meta = res["meta"]
        quotes = res["indicators"]["quote"][0]
    except (TypeError, KeyError, IndexError):
        return {"group": group, "name": name, "symbol": symbol,
                "error": "조회 실패"}

    closes = [c for c in (quotes.get("close") or []) if c is not None]
    volumes = [v for v in (quotes.get("volume") or []) if v is not None]

    price = meta.get("regularMarketPrice")

    # 전일 종가는 closes[-2]로 잡는다.
    # meta.chartPreviousClose는 '차트 시작점 직전의 종가'라서 range에 따라
    # 값이 달라진다 (range=5d면 84.46, range=3mo면 106.42 — 같은 종목인데).
    # 그걸 전일 종가로 쓰면 등락률이 통째로 조회 기간 수익률이 된다.
    # meta.previousClose는 이 엔드포인트에서 제공되지 않는다(None).
    prev = closes[-2] if len(closes) >= 2 else meta.get("chartPreviousClose")

    rec = {
        "group": group,
        "name": name,
        "symbol": symbol,
        "unit": unit,
        "price": price,
        "prev_close": prev,
        "currency": meta.get("currency"),
        "history_days": len(closes),
    }
    # 선물이면 어느 계약인지 밝힌다. 여기 40종의 절반 이상이 선물인데
    # 이름만 '금'·'WTI원유'면 현물로 읽히고, 롤오버로 근월물이 바뀌어도
    # 모른 채 어제와 오늘을 비교하게 된다.
    if meta.get("instrumentType") == "FUTURE":
        rec["contract"] = meta.get("shortName") or meta.get("longName")
    if price and prev:
        rec["change_pct"] = round((price / prev - 1) * 100, 2)

    rec.update(_derive(price, closes, volumes))

    # 52주 고저는 meta가 직접 준다 — 조회 기간과 무관하게 정확하다
    hi52, lo52 = meta.get("fiftyTwoWeekHigh"), meta.get("fiftyTwoWeekLow")
    if price and hi52 and lo52 and hi52 != lo52:
        rec["high_52w"] = hi52
        rec["low_52w"] = lo52
        rec["pos_52w"] = round((price - lo52) / (hi52 - lo52) * 100, 1)
        rec["from_52w_high_pct"] = round((price / hi52 - 1) * 100, 1)
    return rec


def _derive(price, closes, volumes):
    """이동평균·변동성·52주 위치·추세. 개별 지표는 그 자체로는 약하지만
    40개를 나란히 놓으면 '무엇이 정상 범위를 벗어났나'가 보인다."""
    out = {}
    if not closes or price is None:
        return out

    def ma(n):
        return sum(closes[-n:]) / n if len(closes) >= n else None

    for n in (5, 20, 60):
        m = ma(n)
        if m:
            out[f"ma{n}"] = round(m, 4)
            out[f"vs_ma{n}_pct"] = round((price / m - 1) * 100, 2)

    if len(closes) >= 2:
        hi, lo = max(closes), min(closes)
        if hi != lo:
            # 조회 기간(3개월) 내 위치. 52주 위치는 meta에서 따로 받는다.
            out["pos_3mo"] = round((price - lo) / (hi - lo) * 100, 1)

    # 일간 등락률의 표준편차 = 변동성
    rets = [(closes[i] / closes[i - 1] - 1) * 100
            for i in range(1, len(closes)) if closes[i - 1]]
    if len(rets) >= 20:
        recent = rets[-20:]
        mean = sum(recent) / len(recent)
        out["volatility_20d"] = round(
            (sum((x - mean) ** 2 for x in recent) / len(recent)) ** 0.5, 2)
        # 누적 수익률
        if len(closes) >= 21 and closes[-21]:
            out["change_20d_pct"] = round((price / closes[-21] - 1) * 100, 2)
        if len(closes) >= 6 and closes[-6]:
            out["change_5d_pct"] = round((price / closes[-6] - 1) * 100, 2)

    if volumes and len(volumes) >= 20:
        avg = sum(volumes[-20:]) / 20
        if avg:
            out["volume_ratio"] = round(volumes[-1] / avg, 2)

    return out


def collect(universe_fn, rng="3mo", max_workers=8):
    tasks = [(g, n, s, u, rng) for g, n, s, u in universe_fn()]
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        return list(ex.map(_fetch_one, tasks))


# ---------------------------------------------------------------- 금리 커브
def yield_curve(records, pairs):
    """장단기 스프레드. 개별 금리보다 정보량이 많다 —
    2년물이 내리는데 30년물이 오르면 '인하 기대 + 인플레 우려'다."""
    by_symbol = {r["symbol"]: r for r in records if not r.get("error")}
    out = []
    for label, long_sym, short_sym, note in pairs:
        lo, sh = by_symbol.get(long_sym), by_symbol.get(short_sym)
        if not lo or not sh or lo.get("price") is None or sh.get("price") is None:
            continue
        spread = lo["price"] - sh["price"]
        rec = {
            "label": label,
            "spread_bp": round(spread * 100, 1),   # %p -> bp
            "long": {"name": lo["name"], "value": lo["price"],
                     "change_pct": lo.get("change_pct")},
            "short": {"name": sh["name"], "value": sh["price"],
                      "change_pct": sh.get("change_pct")},
            "inverted": spread < 0,
            "note": note,
        }
        # 커브 방향: 장기가 더 오르면 스티프닝, 단기가 더 오르면 플래트닝
        lc, sc = lo.get("change_pct"), sh.get("change_pct")
        if lc is not None and sc is not None:
            diff = lc - sc
            if abs(diff) >= 0.5:
                rec["shape_move"] = "스티프닝" if diff > 0 else "플래트닝"
                rec["shape_gap"] = round(diff, 2)
        out.append(rec)
    return out


# ---------------------------------------------------------------- 괴리 탐지
_GROUP_PROXY = {
    "원자재": ["구리", "WTI원유", "금"],
    "글로벌경기": ["구리", "S&P500"],
    "코스피 외국인": [],   # 국장 수집기에서만 판단 가능
}


def _resolve(records_by_name, key):
    """관계식의 한쪽이 개별 심볼이 아니라 묶음일 수 있다."""
    if key in records_by_name:
        r = records_by_name[key]
        return r.get("change_pct")
    proxies = _GROUP_PROXY.get(key) or []
    vals = [records_by_name[p].get("change_pct") for p in proxies
            if p in records_by_name
            and records_by_name[p].get("change_pct") is not None]
    return round(sum(vals) / len(vals), 2) if vals else None


def divergences(records, relations, threshold=0.3):
    """'정상적으로는 반대로 움직이는데 오늘은 같이 움직였다'를 찾는다.

    이게 매크로 인사이트의 핵심이다. 개별 자산의 등락률은 뉴스에도 나오지만,
    관계가 깨진 순간은 아무도 짚어주지 않는다.
    """
    by_name = {r["name"]: r for r in records if not r.get("error")}
    out = []
    for a_key, b_key, expected, note in relations:
        a = _resolve(by_name, a_key)
        b = _resolve(by_name, b_key)
        if a is None or b is None:
            continue
        # 둘 다 유의미하게 움직였을 때만 판단한다
        if abs(a) < threshold or abs(b) < threshold:
            continue
        same_dir = (a > 0) == (b > 0)
        broken = same_dir if expected == "역" else (not same_dir)
        out.append({
            "pair": f"{a_key} vs {b_key}",
            "a": {"name": a_key, "change_pct": a},
            "b": {"name": b_key, "change_pct": b},
            "expected": expected,
            "broken": broken,
            "note": note,
        })
    return out


# ---------------------------------------------------------------- 이상치
def outliers(records, top=8):
    """오늘 정상 범위를 벗어난 것들. 매크로는 종목이 적어서 전량을
    프롬프트에 넣지만, '무엇을 먼저 보라'는 순서는 알려줘야 한다."""
    live = [r for r in records if not r.get("error")]

    def rank(key, label, reverse=True, absolute=False, min_abs=None):
        vals = [(abs(r[key]) if absolute else r[key], r) for r in live
                if r.get(key) is not None]
        if min_abs is not None:
            vals = [(v, r) for v, r in vals if abs(v) >= min_abs]
        vals.sort(key=lambda x: x[0], reverse=reverse)
        return [{"label": label, "name": r["name"], "group": r["group"],
                 "value": r[key], "metric": key} for _, r in vals[:top]]

    return {
        "biggest_moves": rank("change_pct", "당일 등락", absolute=True, min_abs=1.0),
        "trend_20d": rank("change_20d_pct", "20일 추세", absolute=True, min_abs=5.0),
        "stretched": rank("vs_ma20_pct", "20일선 이격", absolute=True, min_abs=5.0),
        "high_vol": rank("volatility_20d", "변동성"),
    }
