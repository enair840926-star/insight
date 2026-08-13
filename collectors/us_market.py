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

# 프리마켓은 일봉으로 못 본다. `includePrePost=true`를 붙여도 일봉 meta에는
# preMarketPrice가 아예 없고(실측: 5종목 전부 없음, 대신 hasPrePostMarketData만
# True), v7/quote는 막혀 있다. 분봉을 따로 받아야 한다.
YAHOO_INTRADAY = ("https://query1.finance.yahoo.com/v8/finance/chart/{s}"
                  "?range=1d&interval=5m&includePrePost=true")


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


def _premarket(symbol):
    """프리마켓 등락률과 체결된 봉 수. 개장 전 수집일 때만 값이 있다.

    미장 수집은 개장 1시간 전(21:30 KST)에 도는데, 그때 프리마켓은 이미
    4시간 반이 지나 있다. 그 구간을 통째로 못 보고 전일 종가만 들고 개장 전
    글을 쓰고 있었다.

    **기준은 `regularMarketPrice`(직전 정규장 종가)다.** `previousClose`는
    그보다 하루 더 전이라(실측: NVDA가 224.09 vs 217.5) 그걸로 재면 프리마켓
    등락에 하루치 등락이 섞인다 — 처음 재봤을 때 ±10%가 나온 것이 그 때문이다.
    제대로 재면 -1.75%~+2.88%, 중간값 +0.27%다.

    **거래량은 안 온다.** 프리마켓 5분봉의 volume이 None이 아니라 전부 0이다
    (NVDA 55개 봉 전부). 그래서 얇은 호가에 한 번 튄 값인지 실제 수급인지
    구분할 방법이 없고, 대신 **체결된 봉 수**를 함께 낸다 — 같은 4시간 반인데
    55봉인 종목이 있고 20봉인 종목이 있다.
    """
    j = fetch_json(YAHOO_INTRADAY.format(s=quote(symbol)))
    try:
        res = j["chart"]["result"][0]
        meta, ts = res["meta"], res.get("timestamp") or []
        closes = res["indicators"]["quote"][0].get("close") or []
        pre = meta["tradingPeriods"]["pre"][0][0]
    except (TypeError, KeyError, IndexError):
        return symbol, None

    base = meta.get("regularMarketPrice")
    last, bars = None, 0
    for i, t in enumerate(ts):
        if pre["start"] <= t < pre["end"]:
            bars += 1
            c = closes[i] if i < len(closes) else None
            if c is not None:
                last = c
    if last is None or not base:
        return symbol, None
    return symbol, {"pre_change_pct": round((last / base - 1) * 100, 2),
                    "pre_bars": bars}


def enrich_premarket(selected, max_workers=8):
    """선별 종목에 프리마켓 등락률을 붙인다. 30개에 2.0초.

    점수(`core/pick.py`)에는 넣지 않는다. 거래량이 없어 신뢰도를 잴 수 없는
    값이라, 점수에 섞으면 나중에 픽이 틀렸을 때 어느 근거가 틀렸는지 되짚을
    수가 없다 — 목표주가·투자등급을 점수에서 뺀 것과 같은 이유다.
    개장 시가가 어디서 시작하는지 알려주는 '사실'이므로 프롬프트에는 낸다.
    """
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        got = dict(ex.map(_premarket, [r["symbol"] for r in selected]))
    n = 0
    for r in selected:
        d = got.get(r["symbol"])
        if d:
            r.update(d)
            n += 1
    return n


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
    """선별 종목의 실적 서프라이즈. 30개면 6초쯤.

    **여기서 PER도 함께 낸다.** 야후 quoteSummary가 401이라 미장만
    밸류에이션이 비어 있었는데, 위에서 받은 분기 EPS 네 개를 합치면
    후행 12개월 이익이고 주가로 나누면 PER이다 — 새 소스가 필요 없다.
    실측에서 선별 30개 중 28개에 붙었고 숫자도 맞다(GOOGL 17.8배,
    NVDA 39.5배, PLTR 175.5배).

    적자면 PER을 내지 않는다. 음수 PER은 '싸다'로 읽히기 쉬워 위험하다.
    """
    syms = [r["symbol"] for r in selected]
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        got = dict(ex.map(_surprise, syms))
    for r in selected:
        s = got.get(r["symbol"])
        if not s:
            continue
        r["surprise"] = s
        eps = [q["eps"] for q in s["quarters"] if q.get("eps") is not None]
        if len(eps) < 4:
            continue
        ttm = sum(eps)
        r["ttm_eps"] = round(ttm, 3)
        price = to_num(r.get("price"))
        if price and ttm > 0:
            r["per"] = round(price / ttm, 1)
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
