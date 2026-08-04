# -*- coding: utf-8 -*-
"""원자재 고유 신호 — COT 포지셔닝 / 선물 커브 / ETF 거래량

다른 자산군에는 가격 외의 축이 있는데 원자재만 없었다.
  국장 → 외국인·기관 수급, 내부자 거래
  코인 → 펀딩비, 미결제약정, 롱숏비율
  원자재 → **COT 포지셔닝과 선물 커브**

COT(Commitment of Traders)는 CFTC가 매주 발표하는 실제 포지션 보고다.
코인의 롱숏비율과 성격이 같지만 이쪽이 훨씬 신뢰도가 높다 — 추정이 아니라
법적 보고 의무에 따른 실제 수치이기 때문이다.

  투기(noncommercial) = 헤지펀드·CTA. 방향성 베팅. 극단이면 반전 위험.
  상업(commercial)    = 생산자·정유사·가공업체. 실물 헤지. 통상 투기의 반대편.
"""
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import quote

from core.http import fetch_json

COT_BASE = "https://publicreporting.cftc.gov/resource/6dca-aqww.json"
YAHOO = "https://query1.finance.yahoo.com/v8/finance/chart/{s}?range={r}&interval=1d"


def _i(v):
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------- COT
def latest_report_date():
    j = fetch_json(f"{COT_BASE}?$select=report_date_as_yyyy_mm_dd"
                   f"&$order=report_date_as_yyyy_mm_dd%20DESC&$limit=1")
    if not j:
        return None
    return j[0]["report_date_as_yyyy_mm_dd"][:10]


def _cot_one(args):
    """계약명을 하드코딩하지 않고 패턴으로 찾은 뒤 미결제약정이 가장 큰 것을
    고른다. CFTC가 계약명을 바꿔도 알아서 따라간다 (실측: 'CRUDE OIL'은
    3개가 매칭되는데 그중 진짜는 OI 78만인 'CRUDE OIL, LIGHT SWEET-WTI')."""
    label, pattern = args
    url = (f"{COT_BASE}?$where=contract_market_name%20like%20"
           f"'%25{quote(pattern)}%25'"
           f"&$order=report_date_as_yyyy_mm_dd%20DESC,open_interest_all%20DESC"
           f"&$limit=40")
    rows = fetch_json(url, timeout=30)
    if not isinstance(rows, list) or not rows:
        return label, None

    newest = rows[0]["report_date_as_yyyy_mm_dd"][:10]
    same_day = [r for r in rows if r["report_date_as_yyyy_mm_dd"][:10] == newest]
    cur = max(same_day, key=lambda r: _i(r.get("open_interest_all")) or 0)
    name = cur["contract_market_name"]

    # 같은 계약의 직전 주 — 포지션 변화를 봐야 의미가 있다
    prev = next((r for r in rows
                 if r["contract_market_name"] == name
                 and r["report_date_as_yyyy_mm_dd"][:10] != newest), None)

    def pack(r):
        nl, ns = _i(r.get("noncomm_positions_long_all")), _i(r.get("noncomm_positions_short_all"))
        cl, cs = _i(r.get("comm_positions_long_all")), _i(r.get("comm_positions_short_all"))
        oi = _i(r.get("open_interest_all"))
        d = {"spec_long": nl, "spec_short": ns, "comm_long": cl, "comm_short": cs,
             "open_interest": oi}
        if nl is not None and ns is not None:
            d["spec_net"] = nl - ns
            d["spec_ratio"] = round(nl / ns, 2) if ns else None
            if oi:
                d["spec_net_pct_oi"] = round((nl - ns) / oi * 100, 1)
        if cl is not None and cs is not None:
            d["comm_net"] = cl - cs
        return d

    out = {"contract": name, "report_date": newest}
    out.update(pack(cur))
    if prev:
        p = pack(prev)
        out["prev_date"] = prev["report_date_as_yyyy_mm_dd"][:10]
        if out.get("spec_net") is not None and p.get("spec_net") is not None:
            out["spec_net_change"] = out["spec_net"] - p["spec_net"]
        if out.get("open_interest") and p.get("open_interest"):
            out["oi_change_pct"] = round(
                (out["open_interest"] / p["open_interest"] - 1) * 100, 2)
    return label, out


def collect_cot(patterns, max_workers=6):
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        return {k: v for k, v in ex.map(_cot_one, patterns.items()) if v}


# ---------------------------------------------------------------- 선물 커브
def _curve_one(args):
    label, root, exch, months = args
    syms = [(m_label, f"{root}{code}.{exch}") for code, m_label in months]

    def one(t):
        m_label, sym = t
        j = fetch_json(YAHOO.format(s=quote(sym), r="5d"))
        try:
            p = j["chart"]["result"][0]["meta"].get("regularMarketPrice")
        except (TypeError, KeyError, IndexError):
            return None
        return {"label": m_label, "symbol": sym, "price": p} if p else None

    with ThreadPoolExecutor(max_workers=5) as ex:
        pts = [p for p in ex.map(one, syms) if p]
    return label, pts


def collect_curves(spec, front_prices, max_workers=4):
    """근월(매크로에서 이미 받은 가격) + 원월들로 커브를 만든다.

    콘탱고(원월>근월) = 보관비용 정상 or 공급 여유
    백워데이션(근월>원월) = 현물이 급하다 = 공급 타이트
    """
    tasks = [(label, root, exch, months)
             for label, (root, exch, months) in spec.items()]
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        raw = dict(ex.map(_curve_one, tasks))

    out = {}
    for label, pts in raw.items():
        front = front_prices.get(label)
        if not front or not pts:
            continue
        far = pts[-1]
        spread_pct = round((far["price"] / front - 1) * 100, 2)
        rec = {
            "front_price": front,
            "points": pts,
            "far_label": far["label"],
            "far_price": far["price"],
            "spread_pct": spread_pct,
            "shape": "콘탱고" if spread_pct > 0.5 else
                     ("백워데이션" if spread_pct < -0.5 else "평탄"),
        }
        # 단조성 확인 — 계절성 상품은 커브가 오르내린다
        prices = [front] + [p["price"] for p in pts]
        rising = all(prices[i] <= prices[i + 1] for i in range(len(prices) - 1))
        falling = all(prices[i] >= prices[i + 1] for i in range(len(prices) - 1))
        rec["monotonic"] = rising or falling
        out[label] = rec
    return out


# ---------------------------------------------------------------- ETF
def collect_etf(etfs, max_workers=6):
    """원자재 ETF 거래량. 자금 흐름의 대용 지표다.
    선물 가격이 안 움직여도 ETF 거래가 급증하면 관심이 몰렸다는 뜻이다."""
    def one(kv):
        label, sym = kv
        j = fetch_json(YAHOO.format(s=sym, r="3mo"))
        try:
            res = j["chart"]["result"][0]
            meta = res["meta"]
            q = res["indicators"]["quote"][0]
        except (TypeError, KeyError, IndexError):
            return label, None
        closes = [c for c in (q.get("close") or []) if c is not None]
        vols = [v for v in (q.get("volume") or []) if v is not None]
        price = meta.get("regularMarketPrice")
        rec = {"symbol": sym, "price": price}
        if price and len(closes) >= 2:
            rec["change_pct"] = round((price / closes[-2] - 1) * 100, 2)
        if len(vols) >= 20:
            avg = sum(vols[-20:]) / 20
            if avg:
                rec["volume_ratio"] = round(vols[-1] / avg, 2)
        if price and len(closes) >= 21 and closes[-21]:
            rec["change_20d_pct"] = round((price / closes[-21] - 1) * 100, 2)
        return label, rec

    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        return {k: v for k, v in ex.map(one, etfs.items()) if v}


# ---------------------------------------------------------------- 해석 보조
def cot_extremes(cot, ratio_high=3.0, ratio_low=0.6, top=6):
    """투기 포지션이 한쪽으로 극단적으로 쏠린 것들.
    코인 펀딩비 극단과 같은 성격 — 반전 시 청산이 연쇄한다."""
    rows = []
    for label, d in cot.items():
        r = d.get("spec_ratio")
        if r is None:
            continue
        if r >= ratio_high:
            rows.append({"name": label, "side": "롱 쏠림", "ratio": r,
                         "net": d.get("spec_net"),
                         "net_pct_oi": d.get("spec_net_pct_oi"),
                         "change": d.get("spec_net_change")})
        elif r <= ratio_low:
            rows.append({"name": label, "side": "숏 쏠림", "ratio": r,
                         "net": d.get("spec_net"),
                         "net_pct_oi": d.get("spec_net_pct_oi"),
                         "change": d.get("spec_net_change")})
    rows.sort(key=lambda x: -abs(x.get("net_pct_oi") or 0))
    return rows[:top]
