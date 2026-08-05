# -*- coding: utf-8 -*-
"""매크로 데스크용 숫자 피드

매크로 데스크(enair840926-star/-)는 자체 엔진으로 방향을 판정한다.
그 엔진의 MacroFactorInput은 두 가지를 받는다.

    stance  -2~+2   누가 봐도 판단이다. 넣으면 엔진이 그대로 쓴다.
    value   숫자    엔진이 자기 밴드로 조회해 stance를 만든다.

**여기서는 value만 만든다.** stance를 넣으면 매크로 데스크의
스코어보드가 채점하는 대상이 자기 룰셋이 아니라 이쪽 판단이 되어,
그동안 쌓은 캘리브레이션 이력이 뜻을 잃는다. 정보는 공유하되
판단은 각자 한다.

수치형 팩터 8개 중 여기서 채울 수 있는 것:
    usRates       미10년물 전일 대비 (bp)
    riskAppetite  VIX 전일 대비 (pt)
    breadth       S&P500 상승 종목 비율 (%)
    dollar        달러인덱스 전일 대비 (%)
    inventory     EIA 원유 재고 주간 증감 (백만 배럴)

못 채우는 것 — realYield·inflation(FRED), rateDiff(독일 10년물).
소스가 이 환경에서 막혀 있다. 넣을 수 없는 것을 추측으로 채우지
않는다. 빠진 팩터는 매크로 데스크가 지금처럼 직접 구하면 된다.
"""
import datetime as dt
import json

SCHEMA = 1


def _rec(records, name):
    for r in records or []:
        if r.get("name") == name and not r.get("error"):
            return r
    return None


def _bp(rec):
    """금리의 전일 대비 변화를 bp로. 4.625 - 4.627 = -0.2bp"""
    if not rec or rec.get("prev_close") in (None, 0):
        return None
    return round((rec["price"] - rec["prev_close"]) * 100, 1)


def _pt(rec):
    """지수의 전일 대비 변화를 포인트로. VIX 16.92 - 16.50 = +0.42pt"""
    if not rec or rec.get("prev_close") in (None, 0):
        return None
    return round(rec["price"] - rec["prev_close"], 2)


def _f(v, digits=2):
    return None if v is None else round(v, digits)


def _mbbl(s):
    """'2.690M' · '-2.000M' · '7,167' → 백만 배럴 float"""
    if s is None:
        return None
    t = str(s).replace(",", "").strip()
    mult = 1.0
    if t.upper().endswith("M"):
        t = t[:-1]
    elif t.upper().endswith("K"):
        t, mult = t[:-1], 0.001
    try:
        return float(t) * mult
    except ValueError:
        return None


def _crude_surprise(econ):
    """원유 재고 발표에서 컨센서스 대비 서프라이즈를 뽑는다.

    매크로 데스크 밴드가 '컨센서스 대비 서프라이즈(백만 배럴)'를 받는다.
    주간 증감 원값과는 다른 값이라 섞으면 안 된다.

    EIA(공식)가 있으면 그쪽을, 없으면 API(민간 선행)를 쓴다. 출처를
    적어 받는 쪽이 어느 조사인지 알게 한다.
    """
    picks = []
    for e in econ:
        name = (e.get("event") or "")
        low = name.lower()
        if "crude" not in low or "stock" not in low:
            continue
        a, c = _mbbl(e.get("actual")), _mbbl(e.get("consensus"))
        if a is None or c is None:
            continue
        src = "EIA" if "eia" in low else ("API" if "api" in low else name[:20])
        picks.append({
            "value": round(a - c, 3),
            "fact": f"{name} 실제 {e.get('actual')} / 예상 {e.get('consensus')} "
                    f"→ 서프라이즈 {a - c:+.2f}백만 배럴",
            "source": src, "date": e.get("date"),
            "rank": 0 if src == "EIA" else 1,
        })
    if not picks:
        return None
    picks.sort(key=lambda x: (x["rank"], x["date"] or ""))
    return picks[0]


def build(macro=None, us=None):
    """수집 결과 → 매크로 데스크가 읽을 숫자 피드.

    macro, us는 각 자산군의 최신 JSON(dict). 없으면 그 부분을 비운다.
    """
    macro = macro or {}
    us = us or {}
    recs = macro.get("records") or []
    now = dt.datetime.now().astimezone()

    factors = {}

    def put(key, value, unit, fact, source, asof):
        # 값이 없으면 키를 만들지 않는다. 빈 값을 0으로 채우면
        # 엔진이 '중립'으로 읽어 없는 근거가 생긴다.
        if value is None:
            return
        factors[key] = {"value": value, "unit": unit, "fact": fact,
                        "source": source, "asof": asof}

    asof_macro = macro.get("collected_at")
    asof_us = us.get("collected_at")

    # --- usRates: 미10년물 전일 대비 bp
    t10 = _rec(recs, "미10년물")
    if t10:
        put("usRates", _bp(t10), "bp",
            f"미 10년물 {t10['price']}% (전일 {t10['prev_close']:.3f}%)",
            "Yahoo ^TNX", asof_macro)

    # --- riskAppetite: VIX 전일 대비 pt
    vix = _rec(recs, "VIX")
    if vix:
        put("riskAppetite", _pt(vix), "pt",
            f"VIX {vix['price']} (전일 {vix['prev_close']:.2f})",
            "Yahoo ^VIX", asof_macro)

    # --- dollar: 달러인덱스 전일 대비 %
    dxy = _rec(recs, "달러인덱스")
    if dxy:
        put("dollar", _f(dxy.get("change_pct")), "%",
            f"달러인덱스 {dxy['price']} (전일 대비 {dxy.get('change_pct'):+.2f}%)",
            "Yahoo DX-Y.NYB", asof_macro)

    # --- breadth: S&P500 상승 종목 비율 %
    br = ((us.get("aggregate") or {}).get("breadth")) or {}
    if br.get("up_ratio") is not None:
        put("breadth", _f(br["up_ratio"], 1), "%",
            f"상승 {br.get('up'):,} / 하락 {br.get('down'):,} "
            f"({br['up_ratio']}%)",
            "Nasdaq screener 전종목", asof_us)

    # --- inventory: 원유 재고 '컨센서스 대비 서프라이즈' (백만 배럴)
    #
    # 주간 증감 원값을 주면 안 된다. 매크로 데스크 밴드는 서프라이즈
    # 단위이고, 원값을 넣으면 엉뚱한 stance가 나온다. 컨센서스가
    # 있는 발표만 쓰고, 없으면 이 팩터를 아예 만들지 않는다.
    sur = _crude_surprise(us.get("econ") or [])
    if sur:
        put("inventory", sur["value"], "Mbbl", sur["fact"],
            f"{sur['source']} {sur['date']}", asof_us)

    # --- rateDiff: 미-유로존 10년물 금리차의 전일 대비 변화 (bp)
    # 수준이 아니라 변화를 준다. 매크로 데스크 밴드가 bp 변화 단위다.
    eu = macro.get("eurozone_10y") or {}
    if t10 and eu.get("price") is not None and eu.get("prev_close") is not None:
        today = (t10["price"] - eu["price"]) * 100
        prev = (t10["prev_close"] - eu["prev_close"]) * 100
        put("rateDiff", round(today - prev, 1), "bp",
            f"미 10년물 {t10['price']}% − 유로존 {eu['price']}% "
            f"= {today:.0f}bp (전일 {prev:.0f}bp)",
            f"Yahoo ^TNX / {eu.get('source')} {eu.get('period')}", asof_macro)

    # --- 자산별 가격. 엔진의 position 계산이 last/prevClose를 쓴다.
    levels = {}
    for md_name, our_name in (("XAUUSD", "금"), ("USOIL", "WTI원유"),
                              ("EURUSD", "유로달러"), ("NAS100", "나스닥선물")):
        r = _rec(recs, our_name)
        if r and r.get("price") is not None:
            levels[md_name] = {
                "last": r["price"], "prevClose": r.get("prev_close"),
                "source": f"Yahoo {r.get('symbol')}", "asof": asof_macro,
                "note": f"{our_name} · 당일 {r.get('change_pct'):+.2f}%"
                        if r.get("change_pct") is not None else our_name,
            }

    # 팩터가 아닌 배경 숫자. factors와 섞으면 단위가 다른 값이 팩터로
    # 들어갈 수 있어 따로 둔다. 서수형 팩터(안전자산·지정학·OPEC+ 등)를
    # 판단할 때 참고하라는 뜻이다.
    context = {}
    inv = (macro.get("inventories") or {}).get("원유") or {}
    if inv:
        context["eiaCrudeLevel"] = {
            "weeklyChangeKbbl": inv.get("change_1w"),
            "vs5yAvgPct": inv.get("vs_5y_avg_pct"),
            "period": inv.get("period"),
            "note": "재고 수준. inventory 팩터(서프라이즈)와 다른 값이다.",
        }
    fg = (macro.get("sentiment") or {}).get("us_fear_greed") or {}
    if fg:
        context["fearGreed"] = {"value": fg.get("score"),
                                "rating": fg.get("rating"),
                                "weekAgo": fg.get("week_ago")}
    yc = macro.get("yield_curve") or []
    if yc:
        context["yieldCurve"] = [
            {"label": c.get("label"), "spreadBp": c.get("spread_bp"),
             "inverted": c.get("inverted")} for c in yc]

    return {
        "schema": SCHEMA,
        "producer": "asset-insight",
        "generatedAt": now.isoformat(timespec="seconds"),
        "collectedAt": {"macro": asof_macro, "us": asof_us},
        "context": context,
        "contract": (
            "숫자만 제공한다. stance·direction 같은 판정은 넣지 않는다. "
            "매크로 데스크 엔진이 자기 밴드로 판정해야 스코어보드가 "
            "자기 룰셋을 채점한다."
        ),
        "factors": factors,
        "levels": levels,
        "missing": _missing(factors),
    }


_NUMERIC_FACTORS = ("usRates", "riskAppetite", "breadth", "dollar",
                    "inventory", "realYield", "inflation", "rateDiff")

# FRED는 이 PC와 GitHub 러너 양쪽에서 타임아웃이다(실측). 대체 소스를
# 찾기 전까지는 매크로 데스크가 지금처럼 직접 구해야 한다.
_WHY_MISSING = {
    "realYield": "FRED DFII10 접속 불가(PC·러너 모두 타임아웃) — 직접 확인 필요",
    "inflation": "FRED T10YIE 접속 불가(PC·러너 모두 타임아웃) — 직접 확인 필요",
    "rateDiff": "유로존 10년물 조회 실패 — 직접 확인 필요",
}


def _missing(factors):
    """무엇이 없는지 명시한다.

    빠진 것을 조용히 두면 받는 쪽이 '값이 0'인지 '못 받았는지'를
    구분할 수 없다. 그 구분이 안 되면 없는 근거가 생긴다.
    """
    return [{"key": k, "reason": _WHY_MISSING.get(k, "수집 실패")}
            for k in _NUMERIC_FACTORS if k not in factors]


def write(path, macro=None, us=None):
    data = build(macro, us)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1),
                    encoding="utf-8")
    return data
