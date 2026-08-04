# -*- coding: utf-8 -*-
"""숫자를 사람 말로 옮긴다

화면에 숫자만 있으면 "그래서 뭐?"가 남는다. 52주위치 99.9가 좋은
건지 나쁜 건지, 백워데이션이 무슨 뜻인지 매번 떠올려야 하면 폰에서
훑어보는 용도로는 실패다.

여기 모으는 이유는 같은 판정이 화면과 프롬프트 양쪽에 필요하고,
규칙이 흩어지면 둘이 어긋나기 때문이다.

**투자 판단이 아니라 데이터가 말하는 바를 옮기는 것까지가 범위다.**
사라/팔라가 아니라 "공급이 빠듯하다"까지만 쓴다.
"""
import re

# ---------------------------------------------------------------- 52주 위치
def pos_52w(v):
    """0=52주 최저, 100=52주 최고. 숫자만 보면 뜻이 안 읽힌다."""
    if v is None:
        return ""
    if v >= 95:
        return "연고점"
    if v >= 80:
        return "고점권"
    if v >= 60:
        return "상단"
    if v > 40:
        return "중간"
    if v > 20:
        return "하단"
    if v > 5:
        return "저점권"
    return "연저점"


# ---------------------------------------------------------------- 금리 커브
CURVE_WORDS = {
    "플래트닝": "장단기 금리차 축소",
    "스티프닝": "장단기 금리차 확대",
}


def curve_move(shape_move):
    """'오늘 플래트닝 (-1.90%p)' → '금리차 축소 (-1.90%p)'"""
    if not shape_move:
        return ""
    s = shape_move
    for jargon, plain in CURVE_WORDS.items():
        s = s.replace(jargon, plain)
    return s.replace("오늘 ", "")


def curve_meaning(label, spread_bp, inverted):
    """스프레드가 무엇을 시사하는지 한 줄."""
    if inverted:
        return "단기가 장기보다 높음 — 침체 신호로 읽는 구간"
    if spread_bp is None:
        return ""
    if "10Y-2Y" in label:
        if spread_bp < 20:
            return "역전에 근접"
        return "정상 (장기가 높음)"
    if "30Y-10Y" in label:
        if spread_bp > 80:
            return "장기 인플레·재정 우려가 반영된 폭"
        return "정상 범위"
    return "정상 (장기가 높음)"


# ---------------------------------------------------------------- 선물 커브
def curve_shape(shape, spread_pct):
    """선물 커브를 수급 판정으로 옮긴다.

    **원월이 비싼 것 자체는 신호가 아니다.** 보관비와 이자가 붙으니
    대부분의 저장 가능한 원자재는 평상시에도 그렇다. 실측에서도
    13개 중 12개가 그랬다. 전부 '공급 여유'로 찍으면 정보가 아니라
    배경이 된다. 폭을 봐야 뜻이 생긴다.

    반환: (판정, 근거설명, 색분류)
    """
    if spread_pct is None:
        return shape or "", "", ""
    if spread_pct < -5:
        return "공급 빠듯", "지금 물건이 나중보다 크게 비쌈", "warn"
    if spread_pct < 0:
        return "공급 다소 빠듯", "지금이 나중보다 비쌈", "warn"
    if spread_pct <= 8:
        # 보관비·이자 수준. 정상이라는 말이 정확한 정보다.
        return "정상", "보관비 수준의 차이", "flat"
    if spread_pct <= 25:
        return "공급 여유", "나중이 뚜렷하게 비쌈", "flat"
    return "공급 과잉", "나중이 훨씬 비쌈 — 지금 물건이 남음", "bad"


# ---------------------------------------------------------------- EIA 재고
def inventory_state(state, vs_5y):
    """'타이트' → '재고 부족'처럼 바로 읽히는 말로."""
    if state == "타이트":
        return "재고 부족", "공급자 우위"
    if state == "과잉":
        return "재고 넘침", "수요자 우위"
    if vs_5y is None:
        return "", ""
    return "평년 수준", ""


# ---------------------------------------------------------------- 원자재 종합
# 시세 쪽 이름과 EIA 재고 쪽 이름이 다르다. 매핑이 없으면 가장 중요한
# 원유에서 재고·커브 교차가 조용히 안 걸린다.
INV_ALIAS = {
    "WTI원유": "원유",
    "브렌트유": "원유",
    "휘발유": "휘발유",
    "난방유": "중간유분",
    "천연가스": "천연가스",
}


def inventory_for(name, states):
    """시세 이름으로 EIA 재고 판정을 찾는다."""
    return states.get(name) or states.get(INV_ALIAS.get(name, ""), None)


def supply_lean(bias):
    """수급 판정을 '어느 쪽으로 기울었나' 한 단어로.

    저평가/고평가라는 말은 쓰지 않는다. 커브가 벌어진 것은 물건이
    남는다는 뜻이라 오히려 약세 신호인데, 그걸 저평가로 부르면 뜻이
    정확히 뒤집힌다. 실제로 천연가스가 그 자리에 있다.

    가격이 오른다는 예측이 아니라 수급이 어느 쪽을 받치고 있는지다.
    """
    return {
        "공급 부족": ("상방 우위", "good"),
        "공급 빠듯": ("상방 우위", "good"),
        "재고 부족": ("상방 우위", "good"),
        "공급 과잉": ("하방 우위", "bad"),
        "재고 넘침": ("하방 우위", "bad"),
        "공급 여유": ("하방 우위", "bad"),
        "엇갈림": ("혼재", "warn"),
        "정상": ("중립", "flat"),
    }.get(bias, ("", ""))


def commodity_bias(inv_state=None, curve_spread_pct=None):
    """재고(사실) × 커브(기대)를 교차한 수급 판정.

    둘이 같은 방향을 가리킬 때만 분명하게 쓴다. 엇갈리면 엇갈렸다고
    말하는 것이 정보다 — 억지로 한 방향을 고르면 없는 확신을 만든다.

    커브 기준은 curve_shape()와 같아야 한다. 두 카드가 다른 잣대를
    쓰면 같은 품목에 다른 말이 붙는다.

    반환: (판정, 근거) 또는 ("", "")
    """
    tight = inv_state == "타이트"
    loose = inv_state == "과잉"
    s = curve_spread_pct
    back = s is not None and s < 0            # 지금이 더 비쌈
    wide = s is not None and s > 8            # 보관비를 넘는 여유

    if tight and back:
        return "공급 부족", "재고도 적고 지금 물건이 더 비쌈"
    if loose and wide:
        return "공급 과잉", "재고도 넘치고 나중이 훨씬 비쌈"
    if tight and wide:
        return "엇갈림", "재고는 적은데 커브는 여유 — 실물보다 심리"
    if loose and back:
        return "엇갈림", "재고는 넘치는데 지금이 비쌈 — 일시적 병목"
    if back:
        return "공급 빠듯", "지금 물건이 더 비쌈"
    if loose:
        return "재고 넘침", ""
    if tight:
        return "재고 부족", ""
    return "", ""


# ---------------------------------------------------------------- COT
def cot_reading(ratio, net_pct_oi, net_change):
    """투기 포지션이 한쪽으로 쏠렸는지."""
    if ratio is None:
        return ""
    if ratio >= 4:
        base = "롱 과밀"
    elif ratio >= 2:
        base = "롱 우위"
    elif ratio <= 0.5:
        base = "숏 과밀"
    elif ratio <= 0.8:
        base = "숏 우위"
    else:
        base = "중립"
    if net_change is not None and abs(net_change) > 20000:
        base += " · 이번 주 크게 " + ("증가" if net_change > 0 else "감소")
    return base


# ---------------------------------------------------------------- 코인
def coin_flow(change_pct, oi_change_pct):
    """가격과 미결제약정의 조합. 코인에서 가장 정보량이 큰 축이다.

    같은 상승이라도 신규 자금이 들어온 것과 숏이 도망친 것은
    지속성이 전혀 다르다.

    반환: (판정, 설명, 색분류)
    """
    if change_pct is None or oi_change_pct is None:
        return "", "", ""
    up, oi_up = change_pct > 0, oi_change_pct > 0
    if up and oi_up:
        return "신규 자금", "가격도 포지션도 늘어남", "good"
    if up and not oi_up:
        return "숏 커버링", "오르지만 포지션은 줄어 지속성 약함", "warn"
    if not up and oi_up:
        return "물타기", "빠지는데 포지션이 늘어 청산 위험", "bad"
    return "디레버리징", "빠지면서 포지션도 정리 중", "flat"


def funding_reading(bp):
    """펀딩비(8시간, bp). 롱이 숏에게 내는 비용.

    **1.00bp를 신호로 읽으면 안 된다.** 대부분 거래소의 기본값이라
    수요가 없어도 그 값이 찍힌다. 실측에서도 14개 중 7개가 정확히
    1.00이었다. 의미가 생기는 건 그보다 확실히 높거나, 음수일 때다.
    음수는 숏이 롱에게 내는 상황이라 드물고 그래서 정보량이 크다.
    """
    if bp is None:
        return "", ""
    if bp >= 5:
        return "롱 과열", "bad"
    if bp >= 2:
        return "롱 우위", "warn"
    if bp <= -3:
        return "숏 과열", "bad"
    if bp <= -0.5:
        return "숏 우위", "warn"
    return "중립", "flat"


def crowd_gap(retail_pct, whale_pct):
    """소매(전체계좌)와 큰손(상위계좌)의 롱 비율 차이.

    같은 거래소 안에서만 비교해야 한다. 거래소마다 상위계좌 정의가
    달라 절대 수준은 옮겨 쓸 수 없다.
    """
    if retail_pct is None or whale_pct is None:
        return "", ""
    d = whale_pct - retail_pct
    if d >= 5:
        return f"큰손이 더 롱 (+{d:.1f}%p)", "good"
    if d <= -5:
        return f"소매만 롱 ({d:.1f}%p)", "bad"
    return "", ""


# ---------------------------------------------------------------- 경제지표
# 지표 성격에 따라 '예상 상회'의 의미가 정반대다. 물가가 예상보다
# 높으면 악재지만 고용이 예상보다 높으면 호재다.
_GROWTH = ("pmi", "gdp", "employment", "payroll", "retail", "orders",
           "production", "confidence", "sentiment", "sales", "housing",
           "starts", "permits", "durable", "income", "spending")
_PRICE = ("price", "cpi", "ppi", "inflation", "pce", "deflator")
_INVERSE = ("jobless", "unemployment", "claims", "deficit")


def _kind(event):
    e = (event or "").lower()
    if any(k in e for k in _INVERSE):
        return "inverse"
    if any(k in e for k in _PRICE):
        return "price"
    if any(k in e for k in _GROWTH):
        return "growth"
    return ""


def _num(s):
    """'55.6', '-0.1%', '24.10M', '3.750%' → float"""
    if s is None:
        return None
    t = str(s).replace(",", "").replace("%", "").strip()
    t = re.sub(r"[MBK]$", "", t)
    m = re.search(r"-?\d+\.?\d*", t)
    return float(m.group()) if m else None


def econ_surprise(event, actual, consensus):
    """실제와 예상의 차이가 무엇을 뜻하는지.

    반환: (놀람, 효과, 색분류)
      놀람 — '예상 상회' / '예상 하회' / '예상대로'
      효과 — 그래서 시장이 어떻게 읽는지 (모르면 빈 문자열)
    """
    a, c = _num(actual), _num(consensus)
    if a is None or c is None:
        return "", "", ""
    if abs(a - c) < 1e-9:
        return "예상대로", "", "flat"

    over = a > c
    surprise = "예상 상회" if over else "예상 하회"
    kind = _kind(event)

    if kind == "price":
        # 물가는 높을수록 부담
        return ((surprise, "인플레 부담 · 금리인하 기대 후퇴", "bad") if over
                else (surprise, "인플레 완화 · 금리인하 기대 강화", "good"))
    if kind == "growth":
        return ((surprise, "경기 강함 · 금리인하 기대 후퇴", "warn") if over
                else (surprise, "경기 둔화 · 금리인하 기대 강화", "warn"))
    if kind == "inverse":
        # 실업·적자는 높을수록 나쁨
        return ((surprise, "경기 둔화 신호", "bad") if over
                else (surprise, "경기 견조 신호", "good"))
    return surprise, "", "flat"
