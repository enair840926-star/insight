# -*- coding: utf-8 -*-
"""국장 시세·수급·펀더멘털·공시 수집 (네이버 금융)

한 종목당 3회 호출:
  integration  -> 펀더멘털(PER/PBR/EPS/추정PER/배당) + 수급 추이 + 시세 요약
  siseJson     -> 일별 OHLCV + 외국인소진율
  disclosure   -> 공시
"""
import datetime as dt
from concurrent.futures import ThreadPoolExecutor

from core.http import fetch, fetch_json
from core.parse import (to_int, to_float, korean_amount, clean_text,
                        parse_sise_json)

BASE = "https://m.stock.naver.com/api"


# ---------------------------------------------------------------- 지수
def get_index(code="KOSPI"):
    j = fetch_json(f"{BASE}/index/{code}/basic")
    if not j:
        return None
    return {
        "code": code,
        "name": j.get("stockName"),
        "close": to_float(j.get("closePrice")),
        "change": to_float(j.get("compareToPreviousClosePrice")),
        "change_pct": to_float(j.get("fluctuationsRatio")),
        "market_status": j.get("marketStatus"),
        "traded_at": j.get("localTradedAt"),
    }


# ---------------------------------------------------------------- 종목
_FUND_KEYS = {
    "per": "per", "pbr": "pbr", "eps": "eps", "bps": "bps",
    "cnsPer": "est_per", "cnsEps": "est_eps",
    "dividendYieldRatio": "dividend_yield", "dividend": "dividend",
    "highPriceOf52Weeks": "high_52w", "lowPriceOf52Weeks": "low_52w",
    "foreignRate": "foreign_ratio", "openPrice": "open",
    "highPrice": "high", "lowPrice": "low",
    "lastClosePrice": "prev_close",
    "accumulatedTradingVolume": "volume",
}


def get_stock_core(code, name, trend_days=10):
    """integration 1회로 펀더멘털 + 수급 + 시세를 모두 얻는다."""
    j = fetch_json(f"{BASE}/stock/{code}/integration")
    if not j:
        return None

    out = {"code": code, "name": j.get("stockName") or name,
           # 업종코드. kr_screen.industry_map으로 이름을 붙인다.
           "industry_code": j.get("industryCode")}

    # 펀더멘털 / 시세 요약
    fund = {}
    for info in (j.get("totalInfos") or []):
        k = _FUND_KEYS.get(info.get("code"))
        if not k:
            continue
        fund[k] = to_float(info.get("value"))
        if info.get("valueDesc"):
            fund[k + "_asof"] = info["valueDesc"]
    for info in (j.get("totalInfos") or []):
        if info.get("code") == "marketValue":
            fund["market_cap"] = korean_amount(info.get("value"))
        elif info.get("code") == "accumulatedTradingValue":
            fund["trading_value"] = korean_amount(info.get("value"))
    out["fundamentals"] = fund

    # 수급 (외국인/기관/개인 순매수)
    trend = []
    for t in (j.get("dealTrendInfos") or [])[:trend_days]:
        trend.append({
            "date": t.get("bizdate"),
            "close": to_int(t.get("closePrice")),
            "change": to_int(t.get("compareToPreviousClosePrice")),
            "volume": to_int(t.get("accumulatedTradingVolume")),
            "foreign_net": to_int(t.get("foreignerPureBuyQuant")),
            "organ_net": to_int(t.get("organPureBuyQuant")),
            "individual_net": to_int(t.get("individualPureBuyQuant")),
            "foreign_hold_ratio": to_float(t.get("foreignerHoldRatio")),
        })
    out["trend"] = trend
    return out


def get_ohlcv(code, days=60):
    end = dt.date.today()
    start = end - dt.timedelta(days=int(days * 1.6) + 10)   # 휴장일 보정
    url = (f"https://api.finance.naver.com/siseJson.naver?symbol={code}"
           f"&requestType=1&startTime={start:%Y%m%d}&endTime={end:%Y%m%d}"
           f"&timeframe=day")
    raw = fetch(url)
    return parse_sise_json(raw)[-days:]


# KOSCOM이 자동 생성하는 공시. 매일 쏟아지는데 정보가치가 없어서
# 실적공시·주요경영사항 같은 진짜 공시를 밀어낸다.
_DISCLOSURE_NOISE = (
    "가격제한폭 확대요건",
    "투자주의",
    "투자경고",
    "시장경보",
    "단기과열",
)


def get_disclosures(code, limit=5):
    # 노이즈를 걸러낼 걸 감안해 넉넉히 받는다
    j = fetch_json(f"{BASE}/stock/{code}/disclosure?pageSize={limit * 5}&page=1")
    if not isinstance(j, list):
        return []
    out, seen = [], set()
    for d in j:
        title = clean_text(d.get("title"))
        if not title or any(n in title for n in _DISCLOSURE_NOISE):
            continue
        # 같은 날 같은 제목이 여러 건 올라온다 (정정공시 등)
        sig = (title, (d.get("datetime") or "")[:10])
        if sig in seen:
            continue
        seen.add(sig)
        out.append({
            "title": title,
            "datetime": d.get("datetime"),
            "author": d.get("author"),
        })
        if len(out) >= limit:
            break
    return out


# ---------------------------------------------------------------- 파생 지표
def derive_signals(stock, ohlcv):
    """수집한 원자료에서 판단 재료를 계산한다.

    LLM에 '외국인 -389만주'만 주면 그게 큰지 작은지 모른다.
    평균 대비 배수로 줘야 판단이 나온다.
    """
    sig = {}
    trend = stock.get("trend") or []

    if trend:
        # 연속 순매수/순매도 일수
        def streak(key):
            if not trend or trend[0].get(key) is None:
                return 0
            sign = 1 if trend[0][key] > 0 else -1
            n = 0
            for t in trend:
                v = t.get(key)
                if v is None or (1 if v > 0 else -1) != sign:
                    break
                n += 1
            return n * sign

        sig["foreign_streak"] = streak("foreign_net")
        sig["organ_streak"] = streak("organ_net")

        # 최근 5일 누적 순매수
        sig["foreign_net_5d"] = sum(
            t["foreign_net"] for t in trend[:5] if t.get("foreign_net") is not None)
        sig["organ_net_5d"] = sum(
            t["organ_net"] for t in trend[:5] if t.get("organ_net") is not None)

        # 외국인 지분율 변화
        ratios = [t["foreign_hold_ratio"] for t in trend
                  if t.get("foreign_hold_ratio") is not None]
        if len(ratios) >= 2:
            sig["foreign_ratio_delta"] = round(ratios[0] - ratios[-1], 3)

    if ohlcv and len(ohlcv) >= 20:
        closes = [r["close"] for r in ohlcv if r.get("close")]
        vols = [r["volume"] for r in ohlcv if r.get("volume")]
        if len(closes) >= 20:
            sig["ma20"] = round(sum(closes[-20:]) / 20, 1)
            sig["vs_ma20_pct"] = round(
                (closes[-1] / sig["ma20"] - 1) * 100, 2)
        if len(closes) >= 60:
            sig["ma60"] = round(sum(closes[-60:]) / 60, 1)
        if len(vols) >= 20:
            avg20 = sum(vols[-20:]) / 20
            if avg20:
                sig["volume_ratio"] = round(vols[-1] / avg20, 2)
        # 최근 변동성 (일간 등락률 표준편차)
        rets = [(closes[i] / closes[i - 1] - 1) * 100
                for i in range(1, len(closes)) if closes[i - 1]]
        if len(rets) >= 20:
            recent = rets[-20:]
            mean = sum(recent) / len(recent)
            var = sum((x - mean) ** 2 for x in recent) / len(recent)
            sig["volatility_20d"] = round(var ** 0.5, 2)

    fund = stock.get("fundamentals") or {}
    if fund.get("high_52w") and fund.get("prev_close"):
        sig["from_52w_high_pct"] = round(
            (fund["prev_close"] / fund["high_52w"] - 1) * 100, 1)
    # 실적 개선 기대 = 현재 PER 대비 추정 PER 하락폭
    if fund.get("per") and fund.get("est_per"):
        sig["per_gap_pct"] = round((fund["est_per"] / fund["per"] - 1) * 100, 1)

    return sig


# ---------------------------------------------------------------- 일괄 수집
def collect_stock(args):
    code, name, cfg = args
    core = get_stock_core(code, name, cfg["trend_days"])
    if not core:
        return {"code": code, "name": name, "error": "integration 조회 실패"}
    ohlcv = get_ohlcv(code, cfg["ohlcv_days"])
    core["ohlcv_tail"] = ohlcv[-5:]
    core["disclosures"] = get_disclosures(code, cfg["disclosure_limit"])
    core["signals"] = derive_signals(core, ohlcv)
    return core


def collect_all(watchlist, cfg, max_workers=6):
    tasks = [(c, n, cfg) for c, n in watchlist]
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        return list(ex.map(collect_stock, tasks))
