# -*- coding: utf-8 -*-
"""매크로 유니버스 — 원자재 / 지수선물 / 채권금리 / 환율 / 변동성 / 글로벌지수

전부 실측 검증된 심볼이다 (2026-08-04, 48/49 성공).
개수가 적어서(40개) 선별 없이 전량을 프롬프트에 넣는다.
"""

# (표시명, 야후심볼, 단위힌트)
#   단위힌트: "usd" 달러 / "usx" 센트(100으로 나눠야 달러) / "pct" 퍼센트 / "idx" 지수
MACRO_UNIVERSE = {
    "금속": [
        ("금", "GC=F", "usd"),
        ("은", "SI=F", "usd"),
        ("구리", "HG=F", "usd"),
        ("백금", "PL=F", "usd"),
        ("팔라듐", "PA=F", "usd"),
        ("알루미늄", "ALI=F", "usd"),
    ],
    "에너지": [
        ("WTI원유", "CL=F", "usd"),
        ("브렌트유", "BZ=F", "usd"),
        ("천연가스", "NG=F", "usd"),
        ("휘발유", "RB=F", "usd"),
        ("난방유", "HO=F", "usd"),
    ],
    "농산물": [
        # 야후가 센트 단위로 준다. 100으로 나눠야 달러다.
        ("옥수수", "ZC=F", "usx"),
        ("밀", "ZW=F", "usx"),
        ("대두", "ZS=F", "usx"),
        ("커피", "KC=F", "usx"),
        ("설탕", "SB=F", "usx"),
        ("코코아", "CC=F", "usd"),
        ("면화", "CT=F", "usx"),
    ],
    "지수선물": [
        ("S&P500선물", "ES=F", "idx"),
        ("나스닥선물", "NQ=F", "idx"),
        ("다우선물", "YM=F", "idx"),
        ("러셀2000선물", "RTY=F", "idx"),
        ("니케이선물", "NKD=F", "idx"),
    ],
    "채권금리": [
        # ^IRX/^FVX/^TNX/^TYX는 가격이 아니라 수익률(%)이다.
        ("미2년물", "^IRX", "pct"),
        ("미5년물", "^FVX", "pct"),
        ("미10년물", "^TNX", "pct"),
        ("미30년물", "^TYX", "pct"),
        ("미국채선물", "ZN=F", "usd"),
    ],
    "환율": [
        ("원달러", "KRW=X", "usd"),
        ("유로달러", "EURUSD=X", "usd"),
        ("달러엔", "JPY=X", "usd"),
        ("파운드달러", "GBP=X", "usd"),
        ("달러위안", "CNY=X", "usd"),
        ("달러인덱스", "DX-Y.NYB", "idx"),
    ],
    "변동성": [
        ("VIX", "^VIX", "idx"),
        ("나스닥VIX", "^VXN", "idx"),
    ],
    "글로벌지수": [
        ("S&P500", "^GSPC", "idx"),
        ("나스닥", "^IXIC", "idx"),
        ("다우", "^DJI", "idx"),
        ("니케이225", "^N225", "idx"),
        ("항셍", "^HSI", "idx"),
        ("상하이종합", "000001.SS", "idx"),
        ("독일DAX", "^GDAXI", "idx"),
    ],
}

# 자산군 간 관계. LLM이 괴리를 찾을 때 쓰는 사전 지식이다.
# "정상적으로는 이렇게 움직인다"를 알려줘야 "그런데 오늘은 반대다"가 나온다.
MACRO_RELATIONS = [
    ("달러인덱스", "금", "역", "달러 강세는 통상 금 가격을 누른다"),
    ("달러인덱스", "원자재", "역", "원자재는 달러 표시라 달러 강세 시 하락 압력"),
    ("미10년물", "금", "역", "실질금리 상승은 무이자 자산인 금에 불리"),
    ("WTI원유", "미10년물", "정", "유가 상승은 인플레 기대를 통해 금리를 밀어올린다"),
    ("VIX", "S&P500", "역", "변동성 지수와 주가는 반대로 움직인다"),
    ("구리", "글로벌경기", "정", "구리는 경기 선행 지표로 읽힌다(닥터 코퍼)"),
    ("달러엔", "니케이225", "정", "엔 약세는 일본 수출주에 유리"),
    ("원달러", "코스피 외국인", "역", "원화 강세 시 외국인 순매수 경향 (최근 깨지는 중)"),
]

# 금리 커브: 장단기 스프레드는 개별 금리보다 정보량이 많다
CURVE_PAIRS = [
    ("10Y-2Y", "^TNX", "^IRX", "역전 시 침체 신호로 읽힌다"),
    ("30Y-10Y", "^TYX", "^TNX", "확대 시 장기 인플레 우려 또는 재정 우려"),
]

# 매크로 뉴스 소스 — docs/data-sources.md에서 검증된 것만
MACRO_RSS = [
    ("OilPrice", "https://oilprice.com/rss/main", None),
    ("Mining.com", "https://www.mining.com/feed/", None),
    ("Investing원자재", "https://www.investing.com/rss/news_11.rss", None),
    ("CNBC마켓", "https://www.cnbc.com/id/20910258/device/rss/rss.html", None),
    ("MarketWatch", "https://feeds.content.dowjones.io/public/rss/mw_topstories", None),
    ("FT마켓", "https://www.ft.com/markets?format=rss", None),
]

MACRO_GOOGLE_QUERIES = [
    "federal reserve rate decision",
    "gold price outlook",
    "oil price OPEC",
    "treasury yields",
    "dollar index",
]

# 매크로 뉴스는 종목이 아니라 '주제'로 태깅한다.
#
# 키워드를 고를 때 기준은 국장 SECTOR_KEYWORDS와 같다 — 그 주제에서만 쓰는
# 말인가. 처음엔 "dollar"를 넣었는데 "spent tens of thousands of dollars on
# home remodeling"이 환율 뉴스로 잡혔다. 통화 얘기의 'dollar'는 거의 항상
# 수식어를 달고 나오므로 구(phrase)로 좁힌다.
MACRO_TOPICS = {
    # --- 통화정책 / 금리 ---
    "federal reserve": ["채권금리", "환율", "지수선물"],
    "fomc": ["채권금리", "환율", "지수선물"],
    "rate cut": ["채권금리", "환율", "지수선물"],
    "rate hike": ["채권금리", "환율", "지수선물"],
    "interest rate": ["채권금리", "환율"],
    "기준금리": ["채권금리", "환율", "지수선물"],
    "금리인하": ["채권금리", "환율", "지수선물"],
    "금리인상": ["채권금리", "환율", "지수선물"],
    "연준": ["채권금리", "환율", "지수선물"],
    "한국은행": ["채권금리", "환율"],
    # --- 물가 ---
    "inflation": ["채권금리", "금속"],
    "cpi": ["채권금리", "금속"],
    "물가": ["채권금리", "금속"],
    "인플레": ["채권금리", "금속"],
    # --- 채권 ---
    "treasury yield": ["채권금리"],
    "bond yield": ["채권금리"],
    "long bonds": ["채권금리"],
    "국채": ["채권금리"],
    "수익률 곡선": ["채권금리"],
    # --- 환율 ---
    "dollar index": ["환율", "금속"],
    "greenback": ["환율", "금속"],
    "currency": ["환율"],
    "exchange rate": ["환율"],
    "환율": ["환율"],
    "달러인덱스": ["환율", "금속"],
    "원화": ["환율"],
    "엔화": ["환율"],
    # --- 에너지 ---
    "opec": ["에너지"],
    "crude": ["에너지"],
    "oil price": ["에너지"],
    "barrel": ["에너지"],
    "natural gas": ["에너지"],
    "refinery": ["에너지"],
    "국제유가": ["에너지"],
    "원유": ["에너지"],
    "감산": ["에너지"],
    # --- 금속 ---
    "gold price": ["금속"],
    "bullion": ["금속"],
    "copper": ["금속"],
    "silver price": ["금속"],
    "금값": ["금속"],
    "구리": ["금속"],
    # --- 농산물 ---
    "harvest": ["농산물"],
    "drought": ["농산물"],
    "crop": ["농산물"],
    "wheat": ["농산물"],
    "soybean": ["농산물"],
    "coffee price": ["농산물"],
    "곡물": ["농산물"],
    # --- 거시 전반 ---
    "recession": ["채권금리", "지수선물", "금속"],
    "tariff": ["농산물", "금속", "지수선물"],
    "경기침체": ["채권금리", "지수선물", "금속"],
    "관세": ["농산물", "금속", "지수선물"],
}

FETCH_RANGE = "3mo"        # 이동평균·변동성 계산용
NEWS_RECENT_DAYS = 3
MAX_WORKERS = 8

# ---------------------------------------------------------------- 원자재 심화
# 가격만 보던 원자재에 고유 신호를 붙인다.
# COT = 코인의 롱숏비율에 해당. 선물커브 = 현물 수급 타이트니스.

# CFTC 계약명은 패턴으로 찾는다. 정확한 이름을 하드코딩하면 CFTC가
# 바꿀 때 조용히 깨진다. 매칭 중 미결제약정이 가장 큰 것을 고른다.
COT_PATTERNS = {
    "금": "GOLD",
    "은": "SILVER",
    "구리": "COPPER",
    "백금": "PLATINUM",
    "WTI원유": "CRUDE OIL",
    "천연가스": "NAT GAS",       # 'NATURAL GAS'로는 안 잡힌다 (실측)
    "옥수수": "CORN",
    "밀": "WHEAT-SRW",
    "대두": "SOYBEANS",
    "커피": "COFFEE C",
    "설탕": "SUGAR NO. 11",
    "코코아": "COCOA",
    "면화": "COTTON NO. 2",
}

# 투기 롱숏비 임계. 3배 넘으면 롱 과밀, 0.6 아래면 숏 과밀로 본다.
COT_RATIO_HIGH = 3.0
COT_RATIO_LOW = 0.6

# 선물 커브 — (야후 루트심볼, 거래소, [(월코드, 라벨)])
# 월코드: F1 G2 H3 J4 K5 M6 N7 Q8 U9 V10 X11 Z12 + 연도 2자리
CURVE_SPEC = {
    "WTI원유": ("CL", "NYM", [("Z26", "26년12월"), ("M27", "27년6월"), ("Z27", "27년12월")]),
    "금": ("GC", "CMX", [("Z26", "26년12월"), ("M27", "27년6월"), ("Z27", "27년12월")]),
    "은": ("SI", "CMX", [("Z26", "26년12월"), ("M27", "27년6월"), ("Z27", "27년12월")]),
    "구리": ("HG", "CMX", [("Z26", "26년12월"), ("M27", "27년6월"), ("Z27", "27년12월")]),
    # 천연가스는 계절성이 강해 커브가 단조롭지 않다. monotonic 플래그로 구분한다.
    "천연가스": ("NG", "NYM", [("Z26", "26년12월"), ("M27", "27년6월"), ("Z27", "27년12월")]),
    "옥수수": ("ZC", "CBT", [("Z26", "26년12월"), ("Z27", "27년12월")]),
    "밀": ("ZW", "CBT", [("Z26", "26년12월"), ("Z27", "27년12월")]),
}

# 원자재 ETF — 자금 흐름의 대용 지표
COMMODITY_ETFS = {
    "금ETF": "GLD", "은ETF": "SLV", "원유ETF": "USO", "천연가스ETF": "UNG",
    "농산물ETF": "DBA", "구리ETF": "CPER", "광업주ETF": "XME",
}

# ---------------------------------------------------------------- EIA 재고
# 원자재 3대 축의 마지막. COT=포지션, 커브=기대, 재고=사실.
# EIA_API_KEY가 없으면 통째로 건너뛴다 (DART와 같은 방식).
# {라벨: (라우트, 시리즈ID, 단위)}
EIA_SERIES = {
    "원유": ("petroleum/stoc/wstk", "WCESTUS1", "천배럴"),
    "쿠싱": ("petroleum/stoc/wstk", "W_EPC0_SAX_YCUOK_MBBL", "천배럴"),
    "휘발유": ("petroleum/stoc/wstk", "WGTSTUS1", "천배럴"),
    "중간유분": ("petroleum/stoc/wstk", "WDISTUS1", "천배럴"),
    "전략비축(SPR)": ("petroleum/stoc/wstk", "WCSSTUS1", "천배럴"),
    "천연가스": ("natural-gas/stor/wkly", "NW2_EPG0_SWO_R48_BCF", "Bcf"),
}
# 5년 평균 대비 몇 %를 벗어나면 타이트/과잉으로 볼 것인가
EIA_TIGHT_PCT = -5.0
EIA_LOOSE_PCT = 5.0


def all_symbols():
    """[(그룹, 표시명, 심볼, 단위), ...]"""
    return [(g, n, s, u) for g, items in MACRO_UNIVERSE.items()
            for n, s, u in items]


def symbol_count():
    return sum(len(v) for v in MACRO_UNIVERSE.values())
