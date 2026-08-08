# -*- coding: utf-8 -*-
"""미장 시세 — 스크리너 스냅샷 + 선별 종목 상세

수집 전략이 국장과 반대다.
  국장: 종목 리스트를 먼저 정하고 → 종목마다 API 호출
  미장: 전종목 스냅샷을 먼저 받고 → 거기서 골라 → 고른 것만 상세

미장 쪽이 낫다. 오늘 움직인 종목을 놓칠 수가 없기 때문이다.
"""
import datetime as dt
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import quote

from core.http import fetch_json
from core.screen import to_num

YAHOO_CHART = ("https://query1.finance.yahoo.com/v8/finance/chart/{s}"
               "?range={r}&interval=1d")


# ---------------------------------------------------------------- 스냅샷
def screener_snapshot(url):
    """7,113개 전종목. 단일 호출."""
    j = fetch_json(url, timeout=60)
    try:
        return j["data"]["rows"]
    except (TypeError, KeyError):
        return []


# ---------------------------------------------------------------- 상세
def _detail(args):
    symbol, rng = args
    j = fetch_json(YAHOO_CHART.format(s=quote(symbol), r=rng))
    try:
        res = j["chart"]["result"][0]
        meta = res["meta"]
        quotes = res["indicators"]["quote"][0]
    except (TypeError, KeyError, IndexError):
        return symbol, None

    closes = [c for c in (quotes.get("close") or []) if c is not None]
    volumes = [v for v in (quotes.get("volume") or []) if v is not None]
    price = meta.get("regularMarketPrice")

    out = {}
    if price and len(closes) >= 2:
        # meta.chartPreviousClose는 range에 따라 값이 달라진다(매크로에서 확인).
        # 전일 종가는 closes[-2]로 잡는다.
        out["change_pct_yahoo"] = round((price / closes[-2] - 1) * 100, 2)

    def ma(n):
        return sum(closes[-n:]) / n if len(closes) >= n else None

    for n in (20, 60):
        m = ma(n)
        if m and price:
            out[f"vs_ma{n}_pct"] = round((price / m - 1) * 100, 2)

    if len(closes) >= 6 and closes[-6]:
        out["change_5d_pct"] = round((price / closes[-6] - 1) * 100, 2)
    if len(closes) >= 21 and closes[-21]:
        out["change_20d_pct"] = round((price / closes[-21] - 1) * 100, 2)

    rets = [(closes[i] / closes[i - 1] - 1) * 100
            for i in range(1, len(closes)) if closes[i - 1]]
    if len(rets) >= 20:
        r20 = rets[-20:]
        mean = sum(r20) / len(r20)
        out["volatility_20d"] = round(
            (sum((x - mean) ** 2 for x in r20) / len(r20)) ** 0.5, 2)

    if volumes and len(volumes) >= 20:
        avg = sum(volumes[-20:]) / 20
        if avg:
            out["volume_ratio"] = round(volumes[-1] / avg, 2)

    hi, lo = meta.get("fiftyTwoWeekHigh"), meta.get("fiftyTwoWeekLow")
    if price and hi and lo and hi != lo:
        out["pos_52w"] = round((price - lo) / (hi - lo) * 100, 1)
        out["from_52w_high_pct"] = round((price / hi - 1) * 100, 1)

    return symbol, out


def enrich_details(selected, rng="3mo", max_workers=8):
    """선별된 종목만 야후로 히스토리 보강. 30개면 3초쯤."""
    tasks = [(r["symbol"], rng) for r in selected]
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        details = dict(ex.map(_detail, tasks))
    for r in selected:
        d = details.get(r["symbol"])
        if d:
            r.update(d)
    return selected


# ---------------------------------------------------------------- 실적 서프라이즈
NASDAQ_SURPRISE = "https://api.nasdaq.com/api/company/{s}/earnings-surprise"


def _surprise(symbol):
    """최근 4분기 실제 EPS 대 발표 전 컨센서스.

    야후 quoteSummary가 401이라 미장에는 펀더멘털이 없다. 이건 그 자리를
    메우는 **사실**이다 — 애널리스트 목표주가처럼 남의 판정이 아니라
    실제로 발표된 숫자와 발표 전 예상의 대조라 사후 검증이 된 값이다.
    """
    j = fetch_json(NASDAQ_SURPRISE.format(s=quote(symbol)))
    rows = (((j or {}).get("data") or {})
            .get("earningsSurpriseTable") or {}).get("rows") or []
    out = []
    for r in rows[:4]:
        pct = to_num(r.get("percentageSurprise"))
        if pct is None:
            continue
        out.append({"quarter": r.get("fiscalQtrEnd"),
                    "reported": r.get("dateReported"),
                    "eps": to_num(r.get("eps")),
                    "consensus": to_num(r.get("consensusForecast")),
                    "surprise_pct": pct})
    if not out:
        return symbol, None
    return symbol, {
        "quarters": out,
        "latest_pct": out[0]["surprise_pct"],
        # 4분기를 다 채운 종목만 '연속'을 따진다. 신규 상장은 이력이
        # 짧아 2분기 전승을 4분기 전승과 같이 세면 안 된다.
        "beats": sum(1 for q in out if q["surprise_pct"] > 0),
        "count": len(out),
    }


def enrich_surprise(selected, max_workers=8):
    """선별 종목의 실적 서프라이즈. 30개면 6초쯤."""
    syms = [r["symbol"] for r in selected]
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        got = dict(ex.map(_surprise, syms))
    for r in selected:
        s = got.get(r["symbol"])
        if s:
            r["surprise"] = s
    return selected


# ---------------------------------------------------------------- 지수
def get_indices(indices, max_workers=6):
    def one(kv):
        name, sym = kv
        j = fetch_json(YAHOO_CHART.format(s=quote(sym), r="3mo"))
        try:
            res = j["chart"]["result"][0]
            meta = res["meta"]
            closes = [c for c in res["indicators"]["quote"][0]["close"]
                      if c is not None]
        except (TypeError, KeyError, IndexError):
            return name, None
        price = meta.get("regularMarketPrice")
        rec = {"symbol": sym, "price": price}
        if price and len(closes) >= 2:
            rec["change_pct"] = round((price / closes[-2] - 1) * 100, 2)
        if price and len(closes) >= 21 and closes[-21]:
            rec["change_20d_pct"] = round((price / closes[-21] - 1) * 100, 2)
        hi, lo = meta.get("fiftyTwoWeekHigh"), meta.get("fiftyTwoWeekLow")
        if price and hi and lo and hi != lo:
            rec["pos_52w"] = round((price - lo) / (hi - lo) * 100, 1)
        return name, rec

    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        return {n: r for n, r in ex.map(one, indices.items()) if r}


# ---------------------------------------------------------------- 캘린더
_NASDAQ_H = {"Referer": "https://www.nasdaq.com/"}


def earnings_calendar(url_tpl, days=2, symbols=None, limit=25):
    """오늘·내일 실적 발표. symbols가 주어지면 그 종목 것만 남긴다."""
    want = {s.upper() for s in (symbols or [])}
    out = []
    for i in range(days):
        d = (dt.date.today() + dt.timedelta(days=i)).isoformat()
        j = fetch_json(url_tpl.format(date=d), headers=_NASDAQ_H)
        rows = ((j or {}).get("data") or {}).get("rows") or []
        for r in rows:
            sym = (r.get("symbol") or "").upper()
            rec = {
                "date": d,
                "symbol": sym,
                "name": r.get("name"),
                "time": (r.get("time") or "").replace("time-", ""),
                "eps_forecast": r.get("epsForecast"),
                "market_cap": to_num(r.get("marketCap")),
                "watched": sym in want,
            }
            out.append(rec)
    # 관심종목 우선, 그다음 시총순
    out.sort(key=lambda x: (not x["watched"], -(x["market_cap"] or 0)))
    return out[:limit]


def econ_calendar(url_tpl, days=2, limit=20):
    out = []
    for i in range(days):
        d = (dt.date.today() + dt.timedelta(days=i)).isoformat()
        j = fetch_json(url_tpl.format(date=d), headers=_NASDAQ_H)
        rows = ((j or {}).get("data") or {}).get("rows") or []
        for r in rows:
            out.append({
                "date": d,
                "time": r.get("gmt"),
                "country": r.get("country"),
                "event": r.get("eventName"),
                "actual": r.get("actual"),
                "consensus": r.get("consensus"),
                "previous": r.get("previous"),
            })
    # 미국 지표를 앞으로
    out.sort(key=lambda x: (x["country"] != "United States",))
    return out[:limit]
