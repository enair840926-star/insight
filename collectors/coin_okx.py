# -*- coding: utf-8 -*-
"""OKX 파생 지표 — 바이낸스가 막힌 환경(미국 IP)에서의 대체 소스

바이낸스는 미국 IP에 451을 준다. 약관상 지역 제한이므로 우회하지 않고
같은 지표를 공개 API로 주는 다른 거래소를 쓴다.

출력 형태를 바이낸스 경로와 똑같이 맞춘다. 그래야 collect_coin.py와
프롬프트 생성 코드가 어느 쪽에서 온 데이터인지 몰라도 된다.

지표 대응:
    바이낸스                          OKX
    ticker/24hr                    → /market/tickers?instType=SWAP
    premiumIndex                   → /public/funding-rate (심볼별)
    openInterest                   → /public/open-interest?instType=SWAP (일괄)
    openInterestHist               → /rubik/stat/contracts/open-interest-volume
    globalLongShortAccountRatio    → /rubik/.../long-short-account-ratio-contract
    topLongShortPositionRatio      → /rubik/.../long-short-position-ratio-contract-top-trader
    takerlongshortRatio            → /rubik/stat/taker-volume

바이낸스보다 나은 점이 하나 있다. 바이낸스는 상위트레이더를 포지션
기준으로만 주는데 OKX는 계좌 기준과 포지션 기준을 둘 다 준다.
"""
from concurrent.futures import ThreadPoolExecutor

from core.http import fetch_json

BASE = "https://www.okx.com/api/v5"

TICKERS = f"{BASE}/market/tickers?instType=SWAP"
OI_ALL = f"{BASE}/public/open-interest?instType=SWAP"
FUNDING = f"{BASE}/public/funding-rate?instId={{inst}}"
OI_HIST = (f"{BASE}/rubik/stat/contracts/open-interest-volume"
           "?ccy={ccy}&period=1D")
LS_ACCOUNT = (f"{BASE}/rubik/stat/contracts/long-short-account-ratio-contract"
              "?instId={inst}&period=1H")
# 상위트레이더는 '계좌 기준'을 쓴다. 전체계좌 롱숏비와 같은 축이라야
# 둘을 비교할 수 있기 때문이다. 포지션 기준은 롱·숏이 계약 단위로
# 짝을 이루는 성질 때문에 값이 1 근처로 눌려 변별력이 떨어진다
# (실측: BTC 0.98 / ETH 0.92 / SOL 0.87 — 계좌 기준은 1.05 / 1.39 / 1.33).
LS_TOP = (f"{BASE}/rubik/stat/contracts/"
          "long-short-account-ratio-contract-top-trader"
          "?instId={inst}&period=1H")
# 선물 기준으로 받는다. 바이낸스 takerlongshortRatio도 선물 지표이고,
# 실측 커버리지도 CONTRACTS가 SPOT보다 넓다(15/18 vs 14/18).
TAKER = f"{BASE}/rubik/stat/taker-volume?ccy={{ccy}}&instType=CONTRACTS&period=1H"

# OKX rubik 통계는 IP당 초당 요청 수가 빡빡하다. 8스레드로 때리면 429가
# 섞여 지표가 군데군데 빈다(실측 테이커 8/18). 동시성을 낮추면 채워진다.
RUBIK_WORKERS = 3


def _f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _data(url, timeout=25):
    """OKX는 {"code":"0","msg":"","data":[...]} 형태로 감싸서 준다."""
    j = fetch_json(url, timeout=timeout)
    if not isinstance(j, dict) or str(j.get("code")) != "0":
        return []
    return j.get("data") or []


def _inst(sym):
    return f"{sym}-USDT-SWAP"


# ---------------------------------------------------------------- 일괄 수집
def futures(tickers_url=TICKERS, oi_url=OI_ALL):
    """무기한선물 24시간 + 미결제약정. 2회 호출.

    반환 형태는 coin_market.binance_futures()와 동일하다.
    다만 펀딩비는 OKX가 일괄 조회를 안 주므로 여기서 채우지 않는다 —
    선별된 코인에 대해서만 enrich에서 가져온다. 그래서 펀딩비 극단으로
    코인을 뽑는 선별 기준은 이 경로에서 약해진다(아래 주석 참고).
    """
    rows = _data(tickers_url, timeout=40)
    perp = {}
    for r in rows:
        inst = r.get("instId") or ""
        if not inst.endswith("-USDT-SWAP"):
            continue
        base = inst.split("-", 1)[0]
        last, open24 = _f(r.get("last")), _f(r.get("open24h"))
        # OKX는 달러 거래대금을 직접 주지 않는다. volCcy24h가 코인 수량이므로
        # 가격을 곱해야 바이낸스 quoteVolume과 같은 축이 된다.
        vol_ccy = _f(r.get("volCcy24h"))
        perp[base] = {
            "fut_symbol": inst,
            "fut_change_pct": (round((last / open24 - 1) * 100, 2)
                               if last and open24 else None),
            "turnover": (vol_ccy * last) if (vol_ccy and last) else None,
            "mark_price": last,
        }

    for r in _data(oi_url, timeout=40):
        inst = r.get("instId") or ""
        if not inst.endswith("-USDT-SWAP"):
            continue
        base = inst.split("-", 1)[0]
        if base in perp:
            # oiCcy = 코인 단위 미결제약정. 바이낸스 openInterest와 같은 축.
            perp[base]["open_interest"] = _f(r.get("oiCcy"))
    return perp


def fill_funding(perp, symbols, max_workers=8):
    """펀딩비는 심볼별 호출이라 필요한 것만 채운다.

    바이낸스 경로는 855개를 1회로 받아 전 코인의 펀딩비를 알지만
    OKX는 그게 안 된다. 선별 전에 상위 코인 펀딩비를 미리 받아 두면
    '펀딩비 극단' 선별 기준을 어느 정도 살릴 수 있다.
    """
    targets = [s for s in symbols if s in perp]

    def one(sym):
        d = _data(FUNDING.format(inst=_inst(sym)))
        if not d:
            return sym, None
        return sym, {"funding_rate": _f(d[0].get("fundingRate")),
                     "next_funding": d[0].get("nextFundingTime")}

    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        for sym, got in ex.map(one, targets):
            if got:
                perp[sym].update(got)
    return perp


# ---------------------------------------------------------------- 포지셔닝
def _series_last(rows, idx=1):
    """rubik 응답은 [[ts, 값], ...] 배열이고 최신이 앞에 온다."""
    if not rows or not isinstance(rows[0], list) or len(rows[0]) <= idx:
        return None
    return _f(rows[0][idx])


def _positioning(sym):
    out = {}
    inst = _inst(sym)

    acct = _data(LS_ACCOUNT.format(inst=inst))
    ratio = _series_last(acct)
    if ratio:
        out["long_short_account"] = round(ratio, 4)
        # 롱숏비 r → 롱 비율 = r/(1+r). 바이낸스는 longAccount를 직접 준다.
        out["long_account_pct"] = round(ratio / (1 + ratio) * 100, 2)

    top = _data(LS_TOP.format(inst=inst))
    tratio = _series_last(top)
    if tratio:
        out["long_short_top"] = round(tratio, 4)
        out["long_top_pct"] = round(tratio / (1 + tratio) * 100, 2)

    tk = _data(TAKER.format(ccy=sym))
    # [ts, 매도량, 매수량] 순서다. 바이낸스 buySellRatio와 맞추려면 매수/매도.
    if tk and isinstance(tk[0], list) and len(tk[0]) >= 3:
        sell, buy = _f(tk[0][1]), _f(tk[0][2])
        if sell:
            out["taker_buy_sell"] = round(buy / sell, 4)

    hist = _data(OI_HIST.format(ccy=sym))
    # [ts, 미결제약정USD, 거래량USD], 최신이 앞. 7일 전과 비교한다.
    vals = [_f(h[1]) for h in hist[:8]
            if isinstance(h, list) and len(h) >= 2 and _f(h[1])]
    if len(vals) >= 2 and vals[-1]:
        out["oi_change_7d_pct"] = round((vals[0] / vals[-1] - 1) * 100, 2)

    return sym, out


def enrich_positioning(selected, max_workers=RUBIK_WORKERS):
    """선별된 코인만 포지셔닝 조회. coin_market.enrich_positioning과 대응."""
    targets = [c for c in selected if c.get("has_perp")]
    with ThreadPoolExecutor(max_workers=min(max_workers, RUBIK_WORKERS)) as ex:
        res = dict(ex.map(_positioning, [c["symbol"] for c in targets]))
    for c in selected:
        d = res.get(c["symbol"])
        if d:
            c.update(d)
    return selected


def reachable():
    """OKX가 이 IP에서 열리는지. 1회 호출로 확인한다."""
    return bool(_data(FUNDING.format(inst="BTC-USDT-SWAP"), timeout=15))
