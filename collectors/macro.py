# -*- coding: utf-8 -*-
"""매크로 환경 + 센티먼트 지표

국장 판단에는 원달러·미10년물·VIX·나스닥선물이 개별 종목 뉴스보다
설명력이 클 때가 많다. 특히 외국인 수급은 환율과 강하게 붙는다.
"""
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import quote

from core.http import fetch_json

YAHOO = ("https://query1.finance.yahoo.com/v8/finance/chart/{s}"
         "?range=5d&interval=1d")


def _quote(item):
    name, symbol = item
    j = fetch_json(YAHOO.format(s=quote(symbol)))
    try:
        meta = j["chart"]["result"][0]["meta"]
    except (TypeError, KeyError, IndexError):
        return name, None
    price = meta.get("regularMarketPrice")
    prev = meta.get("chartPreviousClose") or meta.get("previousClose")
    rec = {"symbol": symbol, "price": price, "prev_close": prev,
           "currency": meta.get("currency")}
    # 선물이면 어느 계약인지 밝힌다. 이름만 '금'이면 현물로 읽히고, 롤오버로
    # 근월물이 바뀌어도 모른 채 어제와 오늘을 비교하게 된다 — 코인 파생을
    # 거래소별로 구분해 두는 것과 같은 이유다.
    if meta.get("instrumentType") == "FUTURE":
        rec["contract"] = meta.get("shortName") or meta.get("longName")
    if price and prev:
        rec["change_pct"] = round((price / prev - 1) * 100, 2)
    return name, rec


def get_macro(symbols, max_workers=6):
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        return {n: r for n, r in ex.map(_quote, symbols.items()) if r}


def get_sentiment():
    out = {}

    cnn = fetch_json("https://production.dataviz.cnn.io/index/fearandgreed/graphdata")
    if cnn and "fear_and_greed" in cnn:
        fg = cnn["fear_and_greed"]
        out["us_fear_greed"] = {
            "score": round(fg.get("score", 0), 1),
            "rating": fg.get("rating"),
            "prev_close": round(fg.get("previous_close", 0), 1),
            "week_ago": round(fg.get("previous_1_week", 0), 1),
        }

    coin = fetch_json("https://api.alternative.me/fng/?limit=2")
    if coin and coin.get("data"):
        d = coin["data"][0]
        out["crypto_fear_greed"] = {
            "score": int(d["value"]),
            "rating": d["value_classification"],
        }

    return out
