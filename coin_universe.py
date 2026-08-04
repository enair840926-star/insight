# -*- coding: utf-8 -*-
"""코인 수집 설정

국장·미장에 없는 축이 셋 있다.
  1. 펀딩비    — 무기한 선물의 롱/숏 비용. 극단값은 포지션 쏠림이다.
  2. 미결제약정 — 시장에 깔린 포지션 총량. 가격과 조합해서 읽는다.
  3. 김치프리미엄 — 국내 수급 온도계. 한국에만 있는 지표.

전부 무료이고 실측 검증됐다.
"""

# ---------------------------------------------------------------- 소스
# 시총 순위·ATH 대비·7일 변동 — 유니버스의 기준
COINGECKO_MARKETS = ("https://api.coingecko.com/api/v3/coins/markets"
                     "?vs_currency=usd&order=market_cap_desc&per_page=100&page=1"
                     "&price_change_percentage=1h,24h,7d")
COINGECKO_GLOBAL = "https://api.coingecko.com/api/v3/global"

# 바이낸스 — 전부 일괄 조회 (심볼별 호출 불필요)
BINANCE_FUT_24H = "https://fapi.binance.com/fapi/v1/ticker/24hr"      # 728개
BINANCE_FUNDING = "https://fapi.binance.com/fapi/v1/premiumIndex"     # 855개

# 심볼별로만 되는 것들 — 선별된 코인에만 호출
BINANCE_OI = "https://fapi.binance.com/fapi/v1/openInterest?symbol={sym}"
BINANCE_OI_HIST = ("https://fapi.binance.com/futures/data/openInterestHist"
                   "?symbol={sym}&period=1d&limit=8")
BINANCE_LS_ACCOUNT = ("https://fapi.binance.com/futures/data/globalLongShortAccountRatio"
                      "?symbol={sym}&period=1h&limit=2")
BINANCE_LS_TOP = ("https://fapi.binance.com/futures/data/topLongShortPositionRatio"
                  "?symbol={sym}&period=1h&limit=2")
BINANCE_TAKER = ("https://fapi.binance.com/futures/data/takerlongshortRatio"
                 "?symbol={sym}&period=1h&limit=2")

UPBIT_TICKER = "https://api.upbit.com/v1/ticker?markets={markets}"
UPBIT_MARKETS = "https://api.upbit.com/v1/market/all?isDetails=true"
USDKRW = "https://query1.finance.yahoo.com/v8/finance/chart/KRW%3DX?range=5d&interval=1d"
FEAR_GREED = "https://api.alternative.me/fng/?limit=8"

# ---------------------------------------------------------------- 유니버스
WATCHLIST = ["BTC", "ETH", "XRP", "SOL", "DOGE"]

# 스테이블코인·랩드토큰은 가격이 안 움직이거나 원본과 중복이라 제외한다
EXCLUDE_SYMBOLS = {
    "USDT", "USDC", "DAI", "FDUSD", "TUSD", "USDE", "PYUSD", "USDS", "BUSD",
    "WBTC", "WETH", "WEETH", "WSTETH", "STETH", "CBBTC", "RETH", "EZETH",
    "SUSDE", "SUSDS", "LBTC", "BSC-USD", "WBETH", "METH", "RSETH",
}

# ---------------------------------------------------------------- 선별
SELECT = {
    "movers_n": 8,          # 급등/급락 각 상위 N
    "turnover_n": 8,        # 거래대금 상위 N
    "funding_n": 6,         # 펀딩비 극단 상위 N (롱/숏 각각)
    "min_market_cap": 3e8,  # 시총 하한 3억 달러
    "max_total": 18,        # 최종 상세 종목 수
}
# 펀딩비 임계값 (8시간 기준). 0.01%가 중립, 0.05% 넘으면 롱 과열로 본다.
FUNDING_EXTREME = 0.0004    # 0.04%
KIMP_ALERT = 3.0            # 김프 ±3% 넘으면 이상 신호

# ---------------------------------------------------------------- 뉴스
RSS_FEEDS = [
    ("CoinDesk", "https://www.coindesk.com/arc/outboundfeeds/rss/", None),
    ("Cointelegraph", "https://cointelegraph.com/rss", None),
    ("Decrypt", "https://decrypt.co/feed", None),
    ("TheBlock", "https://www.theblock.co/rss.xml", None),
    ("블록미디어", "https://www.blockmedia.co.kr/feed", None),
]
GOOGLE_NEWS_QUERIES = [
    "bitcoin price",
    "ethereum ETF",
    "crypto regulation SEC",
    "비트코인 시세",
]
NEWS_RECENT_DAYS = 3
NEWS_LIMIT = 35
NEWS_PER_COIN = 0        # 코인은 종목별 RSS가 없다 (야후 티커 RSS 미지원)
MAX_WORKERS = 8

# 코인명 → 티커 매핑 보조. 뉴스에 "Bitcoin"이라 쓰지 "BTC"라 안 쓴다.
NAME_ALIASES = {
    "BTC": ["bitcoin", "비트코인"],
    "ETH": ["ethereum", "이더리움", "이더"],
    "XRP": ["ripple", "리플"],
    "SOL": ["solana", "솔라나"],
    "DOGE": ["dogecoin", "도지"],
    "ADA": ["cardano", "카르다노", "에이다"],
    "AVAX": ["avalanche", "아발란체"],
    "LINK": ["chainlink", "체인링크"],
    "DOT": ["polkadot", "폴카닷"],
    "MATIC": ["polygon", "폴리곤"],
    "BNB": ["binance coin", "바이낸스코인"],
    "TRX": ["tron", "트론"],
    "LTC": ["litecoin", "라이트코인"],
    "SUI": ["sui"],
    "TON": ["toncoin", "톤코인"],
}

# 코인 전반에 영향을 주는 주제
TOPIC_KEYWORDS = {
    "etf": "ETF/제도권",
    "sec ": "규제",
    "regulation": "규제",
    "규제": "규제",
    "halving": "반감기",
    "반감기": "반감기",
    "liquidation": "청산",
    "청산": "청산",
    "hack": "보안사고",
    "exploit": "보안사고",
    "해킹": "보안사고",
    "stablecoin": "스테이블코인",
    "스테이블": "스테이블코인",
    "federal reserve": "매크로",
    "interest rate": "매크로",
    "금리": "매크로",
    "institutional": "기관자금",
    "기관": "기관자금",
}
