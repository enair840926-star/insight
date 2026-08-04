# -*- coding: utf-8 -*-
"""코인 시세·파생 지표

수집 순서:
  1. 코인게코 100개  → 시총·ATH대비·7일변동 (유니버스 기준)
  2. 바이낸스 선물 전체 → 거래대금·펀딩비 (각각 1회 호출로 728/855개)
  3. 동적 선별 18개
  4. 선별된 것만 → 미결제약정·롱숏비율·상위계좌·테이커비율
  5. 업비트 → 김치프리미엄

3번까지가 4회 호출이다. 국장(종목당 3회)과 대조적이다.
"""
from concurrent.futures import ThreadPoolExecutor

from core.http import fetch_json


def _f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------- 일괄 수집
def coingecko_universe(url, exclude=(), limit=100):
    rows = fetch_json(url, timeout=40)
    if not isinstance(rows, list):
        return []
    out = []
    for r in rows[:limit]:
        sym = (r.get("symbol") or "").upper()
        if sym in exclude:
            continue
        out.append({
            "symbol": sym,
            "name": r.get("name"),
            "rank": r.get("market_cap_rank"),
            "price": r.get("current_price"),
            "market_cap": r.get("market_cap"),
            "volume_24h": r.get("total_volume"),
            "change_1h": r.get("price_change_percentage_1h_in_currency"),
            "change_pct": r.get("price_change_percentage_24h_in_currency"),
            "change_7d": r.get("price_change_percentage_7d_in_currency"),
            "ath_change_pct": r.get("ath_change_percentage"),
            "reasons": [],
        })
    return out


def binance_futures(url_24h, url_funding):
    """728개 24h + 855개 펀딩비. 각 1회 호출."""
    fut = fetch_json(url_24h, timeout=40) or []
    fnd = fetch_json(url_funding, timeout=40) or []

    perp = {}
    for r in fut:
        s = r.get("symbol", "")
        if not s.endswith("USDT"):
            continue
        perp[s[:-4]] = {
            "fut_symbol": s,
            "fut_change_pct": _f(r.get("priceChangePercent")),
            "turnover": _f(r.get("quoteVolume")),
            "trades": r.get("count"),
        }
    for r in fnd:
        s = r.get("symbol", "")
        if not s.endswith("USDT"):
            continue
        base = s[:-4]
        if base in perp:
            perp[base]["funding_rate"] = _f(r.get("lastFundingRate"))
            perp[base]["mark_price"] = _f(r.get("markPrice"))
            perp[base]["next_funding"] = r.get("nextFundingTime")
    return perp


def merge(universe, perp):
    """코인게코(현물 시총) + 바이낸스(선물 수급)를 심볼로 결합"""
    for c in universe:
        d = perp.get(c["symbol"])
        if d:
            c.update(d)
            c["has_perp"] = True
        else:
            c["has_perp"] = False
    return universe


# ---------------------------------------------------------------- 선별
def select(coins, *, watchlist=(), movers_n=8, turnover_n=8, funding_n=6,
           min_market_cap=3e8, max_total=18, funding_extreme=0.0004):
    """국장·미장과 같은 3티어 구조에 코인 고유 축(펀딩비)을 더한다."""
    wl = {s.upper() for s in watchlist}
    live = [c for c in coins
            if (c.get("market_cap") or 0) >= min_market_cap]
    by_sym = {c["symbol"]: c for c in live}
    picked = {}

    def add(c, why):
        cur = picked.setdefault(c["symbol"], c)
        if why not in cur["reasons"]:
            cur["reasons"].append(why)

    for s in wl:
        if s in by_sym:
            add(by_sym[s], "관심코인")

    moved = [c for c in live if c.get("change_pct") is not None]
    for c in sorted(moved, key=lambda x: -x["change_pct"])[:movers_n]:
        add(c, "급등")
    for c in sorted(moved, key=lambda x: x["change_pct"])[:movers_n]:
        add(c, "급락")

    traded = [c for c in live if c.get("turnover")]
    for c in sorted(traded, key=lambda x: -x["turnover"])[:turnover_n]:
        add(c, "거래대금상위")

    # 코인 고유 — 펀딩비 극단은 포지션 쏠림이고 청산 연쇄의 씨앗이다
    funded = [c for c in live if c.get("funding_rate") is not None]
    for c in sorted(funded, key=lambda x: -x["funding_rate"])[:funding_n]:
        if c["funding_rate"] >= funding_extreme:
            add(c, "펀딩비높음(롱과열)")
    for c in sorted(funded, key=lambda x: x["funding_rate"])[:funding_n]:
        if c["funding_rate"] <= -funding_extreme:
            add(c, "펀딩비낮음(숏과열)")

    sel = list(picked.values())
    sel.sort(key=lambda c: (
        100 if "관심코인" in c["reasons"] else 0,
        len(c["reasons"]),
        (c.get("turnover") or 0) / 1e9 + abs(c.get("change_pct") or 0),
    ), reverse=True)
    return sel[:max_total]


# ---------------------------------------------------------------- 선별 후 상세
def _positioning(args):
    sym, cfg = args
    fut = f"{sym}USDT"
    out = {}

    oi = fetch_json(cfg["oi"].format(sym=fut))
    if isinstance(oi, dict) and oi.get("openInterest"):
        out["open_interest"] = _f(oi["openInterest"])

    hist = fetch_json(cfg["oi_hist"].format(sym=fut))
    if isinstance(hist, list) and len(hist) >= 2:
        vals = [_f(h.get("sumOpenInterest")) for h in hist]
        vals = [v for v in vals if v]
        if len(vals) >= 2 and vals[0]:
            out["oi_change_7d_pct"] = round((vals[-1] / vals[0] - 1) * 100, 2)

    acct = fetch_json(cfg["ls_account"].format(sym=fut))
    if isinstance(acct, list) and acct:
        out["long_short_account"] = _f(acct[-1].get("longShortRatio"))
        out["long_account_pct"] = round((_f(acct[-1].get("longAccount")) or 0) * 100, 2)

    top = fetch_json(cfg["ls_top"].format(sym=fut))
    if isinstance(top, list) and top:
        out["long_short_top"] = _f(top[-1].get("longShortRatio"))
        out["long_top_pct"] = round((_f(top[-1].get("longAccount")) or 0) * 100, 2)

    taker = fetch_json(cfg["taker"].format(sym=fut))
    if isinstance(taker, list) and taker:
        out["taker_buy_sell"] = _f(taker[-1].get("buySellRatio"))

    return sym, out


def enrich_positioning(selected, cfg, max_workers=8):
    """선별된 코인만 포지셔닝 조회. 18개면 5초쯤."""
    targets = [c for c in selected if c.get("has_perp")]
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        res = dict(ex.map(_positioning, [(c["symbol"], cfg) for c in targets]))
    for c in selected:
        d = res.get(c["symbol"])
        if d:
            c.update(d)
    return selected


# ---------------------------------------------------------------- 김치프리미엄
def kimchi_premium(selected, upbit_url, usdkrw_url, markets_url):
    """업비트 원화가 vs 바이낸스 달러가 × 환율.

    국내 수급 온도계다. 플러스면 국내가 비싸게 사는 중(과열),
    마이너스면 국내가 싸게 파는 중(이탈).

    주의: 업비트 ticker는 요청한 마켓 중 하나라도 존재하지 않으면
    400으로 전체를 거부한다. 상장 목록을 먼저 받아 교집합만 요청해야 한다.
    """
    fx = fetch_json(usdkrw_url)
    rate = None
    try:
        rate = fx["chart"]["result"][0]["meta"]["regularMarketPrice"]
    except (TypeError, KeyError, IndexError):
        pass
    if not rate:
        return None, {}

    listed = fetch_json(markets_url) or []
    krw_syms = {m["market"].split("-", 1)[1] for m in listed
                if isinstance(m, dict) and str(m.get("market", "")).startswith("KRW-")}
    syms = [c["symbol"] for c in selected if c["symbol"] in krw_syms]
    if not syms:
        return rate, {}

    markets = ",".join(f"KRW-{s}" for s in syms)
    rows = fetch_json(upbit_url.format(markets=markets)) or []
    if not isinstance(rows, list):
        rows = []

    out = {}
    for r in rows:
        sym = (r.get("market") or "").replace("KRW-", "")
        krw = r.get("trade_price")
        coin = next((c for c in selected if c["symbol"] == sym), None)
        if not coin or not krw:
            continue
        usd = coin.get("mark_price") or coin.get("price")
        if not usd:
            continue
        implied = usd * rate
        out[sym] = {
            "upbit_krw": krw,
            "global_krw": round(implied),
            "premium_pct": round((krw / implied - 1) * 100, 2),
            "upbit_change_pct": round((r.get("signed_change_rate") or 0) * 100, 2),
            "upbit_turnover_krw": r.get("acc_trade_price_24h"),
            "high_52w": r.get("highest_52_week_price"),
            "low_52w": r.get("lowest_52_week_price"),
        }
    for c in selected:
        k = out.get(c["symbol"])
        if k:
            c["kimchi"] = k
    return rate, out


# ---------------------------------------------------------------- 시장 전체
def global_stats(url):
    j = fetch_json(url)
    d = (j or {}).get("data") or {}
    mc = (d.get("total_market_cap") or {}).get("usd")
    vol = (d.get("total_volume") or {}).get("usd")
    dom = d.get("market_cap_percentage") or {}
    return {
        "total_market_cap_usd": mc,
        "total_volume_usd": vol,
        "market_cap_change_24h_pct": d.get("market_cap_change_percentage_24h_usd"),
        "btc_dominance": round(dom.get("btc", 0), 2) if dom else None,
        "eth_dominance": round(dom.get("eth", 0), 2) if dom else None,
        "active_coins": d.get("active_cryptocurrencies"),
    }


def fear_greed(url):
    j = fetch_json(url)
    data = (j or {}).get("data") or []
    if not data:
        return None
    cur = data[0]
    out = {"value": int(cur["value"]), "rating": cur["value_classification"]}
    if len(data) >= 2:
        out["prev"] = int(data[1]["value"])
    if len(data) >= 8:
        out["week_ago"] = int(data[7]["value"])
    return out


# ---------------------------------------------------------------- 시장 집계
def aggregate(coins, selected_syms):
    live = [c for c in coins if c.get("change_pct") is not None]
    if not live:
        return {}
    up = sum(1 for c in live if c["change_pct"] > 0)
    fundings = [c["funding_rate"] for c in coins
                if c.get("funding_rate") is not None]
    return {
        "counted": len(live),
        "up": up,
        "down": len(live) - up,
        "up_ratio": round(up / len(live) * 100, 1),
        "median_change_pct": round(
            sorted(c["change_pct"] for c in live)[len(live) // 2], 2),
        "avg_funding_bp": round(sum(fundings) / len(fundings) * 10000, 3)
        if fundings else None,
        "positive_funding_ratio": round(
            sum(1 for f in fundings if f > 0) / len(fundings) * 100, 1)
        if fundings else None,
        "not_selected": len(live) - len(selected_syms),
    }
