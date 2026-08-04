# -*- coding: utf-8 -*-
"""동적 종목 선별 — 넓게 모아서 좁게 보낸다

고정 워치리스트는 오늘 30% 오른 종목을 놓치고, 순수 동적은 내가 들고 있는
종목이 조용한 날 빠뜨린다. 둘 다 필요하다.

  Tier A  관심종목      항상 포함, 상세
  Tier B  오늘 움직인 것  동적 선별, 중간
  Tier C  나머지 전체    집계만

이 모듈은 자산군에 독립적이다. 미장·국장·코인 모두 같은 로직을 쓴다.
"""
import re

# 워런트·권리·유닛·우선주는 주식이 아니다. 등락률이 극단으로 튀어서
# 선별 상위를 통째로 차지한다 (실측: GENVR +86%가 1위, 알고 보니 CVR).
_DERIVATIVE_WORDS = (
    "warrant", "right", "unit", "preferred", "depositary",
    "contingent value", "subordinated", "debenture", "trust preferred",
    "notes due", "%",
)
# 나스닥 5자리 심볼의 마지막 글자 규약
_DERIVATIVE_SUFFIX = {"W": "워런트", "R": "권리", "U": "유닛"}


def is_derivative(symbol, name):
    low = (name or "").lower()
    if any(w in low for w in _DERIVATIVE_WORDS):
        return True
    s = (symbol or "").upper()
    if len(s) == 5 and s[-1] in _DERIVATIVE_SUFFIX and s.isalpha():
        return True
    return False


def to_num(s):
    """'$139.80' / '1.033%' / '39,483,985,771.00' / '($0.26)' -> float"""
    if s is None:
        return None
    if isinstance(s, (int, float)):
        return float(s)
    t = str(s).strip()
    if not t or t in ("N/A", "--", "-"):
        return None
    neg = t.startswith("(") and t.endswith(")")
    t = re.sub(r"[$,%()\s]", "", t)
    if not t:
        return None
    try:
        v = float(t)
    except ValueError:
        return None
    return -v if neg else v


# ---------------------------------------------------------------- 선별
def select(rows, *, watchlist=(), min_market_cap=5e9, movers_n=10,
           turnover_n=12, sector_reps=True, max_total=30, exclude_fn=None):
    """반환: (선별 리스트, 제외 통계)

    각 항목에 왜 뽑혔는지(`reasons`)를 붙인다. LLM이 "이건 거래대금 때문에
    올라온 거고 저건 급등 때문"을 구분할 수 있어야 판단이 정확해진다.

    exclude_fn(symbol, name) -> bool 로 시장별 제외 규칙을 갈아끼운다.
    미국은 워런트/CVR, 한국은 우선주/스팩으로 형태가 다르다.
    """
    wl = {s.upper() for s in watchlist}
    stats = {"total": len(rows), "derivative": 0, "no_cap": 0, "usable": 0}
    drop = exclude_fn or is_derivative

    live = []
    for r in rows:
        sym = (r.get("symbol") or "").upper()
        name = r.get("name") or ""
        if drop(sym, name):
            stats["derivative"] += 1
            continue
        mc = to_num(r.get("marketCap"))
        price = to_num(r.get("lastsale"))
        vol = to_num(r.get("volume"))
        pct = to_num(r.get("pctchange"))
        if not mc or mc <= 0:
            stats["no_cap"] += 1
            continue
        live.append({
            "symbol": sym,
            "name": re.sub(r"\s+(Common Stock|Class [A-Z] .*|Ordinary Shares.*)$",
                           "", name).strip(),
            "market_cap": mc,
            "price": price,
            "volume": vol,
            "change_pct": pct,
            "turnover": (vol or 0) * (price or 0),
            "sector": (r.get("sector") or "").strip() or None,
            "industry": (r.get("industry") or "").strip() or None,
            "country": r.get("country"),
            "reasons": [],
        })
    stats["usable"] = len(live)

    by_symbol = {r["symbol"]: r for r in live}
    picked = {}

    def add(rec, reason):
        cur = picked.setdefault(rec["symbol"], rec)
        if reason not in cur["reasons"]:
            cur["reasons"].append(reason)

    # Tier A — 관심종목은 조용해도 항상
    for sym in wl:
        if sym in by_symbol:
            add(by_symbol[sym], "관심종목")

    # Tier B-1 — 거래대금 상위 (실제로 돈이 몰린 곳)
    for r in sorted(live, key=lambda x: -x["turnover"])[:turnover_n]:
        add(r, "거래대금상위")

    # Tier B-2 — 시총 하한 이상 중 등락률 이상치
    big = [r for r in live
           if r["market_cap"] >= min_market_cap and r["change_pct"] is not None]
    for r in sorted(big, key=lambda x: -x["change_pct"])[:movers_n]:
        add(r, "급등")
    for r in sorted(big, key=lambda x: x["change_pct"])[:movers_n]:
        add(r, "급락")

    # Tier B-3 — 섹터별 대표 (섹터 전체가 통째로 움직일 때를 놓치지 않는다)
    if sector_reps:
        best = {}
        for r in big:
            s = r["sector"]
            if not s:
                continue
            if s not in best or abs(r["change_pct"]) > abs(best[s]["change_pct"]):
                best[s] = r
        for s, r in best.items():
            add(r, f"섹터대표:{s}")

    selected = list(picked.values())

    def priority(r):
        # 관심종목은 무조건 살린다. 나머지는 뽑힌 사유 수 + 규모로 정렬.
        return (
            100 if "관심종목" in r["reasons"] else 0,
            len(r["reasons"]),
            abs(r["change_pct"] or 0) + r["turnover"] / 1e10,
        )

    selected.sort(key=priority, reverse=True)
    return selected[:max_total], stats


# ---------------------------------------------------------------- 집계
def aggregate(rows, min_market_cap=1e9, exclude_fn=None):
    """선별에서 빠진 나머지를 버리지 않고 집계로 남긴다.
    개별 종목은 못 보더라도 '시장 전체가 어느 쪽인가'는 알아야 한다."""
    drop = exclude_fn or is_derivative
    live = []
    for r in rows:
        sym, name = (r.get("symbol") or "").upper(), r.get("name") or ""
        if drop(sym, name):
            continue
        mc, pct = to_num(r.get("marketCap")), to_num(r.get("pctchange"))
        if not mc or mc <= 0 or pct is None:
            continue
        live.append((r.get("sector") or "기타", mc, pct,
                     (to_num(r.get("volume")) or 0) * (to_num(r.get("lastsale")) or 0)))

    if not live:
        return {}

    up = sum(1 for _, _, p, _ in live if p > 0)
    down = sum(1 for _, _, p, _ in live if p < 0)
    flat = len(live) - up - down

    sectors = {}
    for sec, mc, pct, to in live:
        if mc < min_market_cap:
            continue
        d = sectors.setdefault(sec, {"n": 0, "up": 0, "cap": 0.0, "wsum": 0.0,
                                     "turnover": 0.0})
        d["n"] += 1
        d["up"] += pct > 0
        d["cap"] += mc
        d["wsum"] += mc * pct      # 시총 가중
        d["turnover"] += to

    out_sectors = []
    for sec, d in sectors.items():
        if d["cap"] <= 0:
            continue
        out_sectors.append({
            "sector": sec,
            "count": d["n"],
            "up_ratio": round(d["up"] / d["n"] * 100, 1),
            "cap_weighted_pct": round(d["wsum"] / d["cap"], 2),
            "turnover_bil": round(d["turnover"] / 1e9, 1),
        })
    out_sectors.sort(key=lambda x: -x["cap_weighted_pct"])

    total_cap = sum(mc for _, mc, _, _ in live)
    return {
        "breadth": {"up": up, "down": down, "flat": flat,
                    "up_ratio": round(up / len(live) * 100, 1),
                    "counted": len(live)},
        "market_cap_weighted_pct": round(
            sum(mc * p for _, mc, p, _ in live) / total_cap, 2) if total_cap else None,
        "sectors": out_sectors,
    }
