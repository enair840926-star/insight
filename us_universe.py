# -*- coding: utf-8 -*-
"""미장 수집 설정

국장과 결정적으로 다른 점: 나스닥 스크리너가 7,113개 전 종목의
시총·거래량·등락률·섹터를 **단일 호출**로 준다. 종목 리스트를 따로
확보할 필요도, 종목마다 API를 때릴 필요도 없다.
"""

# 나스닥 스크리너 — 미장의 전종목 스냅샷 (2.2MB, 7,113개)
SCREENER_URL = ("https://api.nasdaq.com/api/screener/stocks"
                "?tableonly=false&limit=25000&download=true")

# 항상 상세히 볼 종목. 조용한 날에도 리포트에 들어간다.
WATCHLIST = [
    "NVDA", "AAPL", "MSFT", "GOOGL", "AMZN", "META", "TSLA", "AVGO",
]

INDICES = {
    "S&P500": "^GSPC",
    "나스닥": "^IXIC",
    "다우": "^DJI",
    "러셀2000": "^RUT",
    "필라델피아반도체": "^SOX",
    "VIX": "^VIX",
}

# ---------------------------------------------------------------- 선별 파라미터
SELECT = {
    "min_market_cap": 5e9,   # 급등락 후보 시총 하한 (소형주 노이즈 차단)
    "movers_n": 10,          # 급등/급락 각 상위 N
    "turnover_n": 12,        # 거래대금 상위 N
    "sector_reps": True,     # 섹터별 대표 1개씩
    "max_total": 30,         # 최종 상세 종목 수
}
AGG_MIN_CAP = 1e9            # 섹터 집계에 포함할 시총 하한

DETAIL_RANGE = "3mo"         # 선별 종목 히스토리 조회 기간
NEWS_PER_STOCK = 6           # 종목당 야후 RSS 건수
NEWS_RECENT_DAYS = 3
NEWS_LIMIT = 40
MAX_WORKERS = 8

# ---------------------------------------------------------------- 뉴스
# docs/data-sources.md 2-3장에서 검증된 것만
RSS_FEEDS = [
    ("CNBC마켓", "https://www.cnbc.com/id/20910258/device/rss/rss.html", None),
    ("CNBC속보", "https://www.cnbc.com/id/100003114/device/rss/rss.html", None),
    ("MarketWatch", "https://feeds.content.dowjones.io/public/rss/mw_topstories", None),
    ("MarketWatch실시간", "https://feeds.content.dowjones.io/public/rss/mw_realtimeheadlines", None),
    ("SeekingAlpha", "https://seekingalpha.com/market_currents.xml", None),
    ("FT마켓", "https://www.ft.com/markets?format=rss", None),
    ("Investing주식", "https://www.investing.com/rss/news_25.rss", None),
]

# 야후 종목별 RSS — 티커만 갈아끼우면 된다
YAHOO_TICKER_RSS = ("https://feeds.finance.yahoo.com/rss/2.0/headline"
                    "?s={ticker}&region=US&lang=en-US")

GOOGLE_NEWS_QUERIES = [
    "US stocks market today",
    "earnings report beat miss",
    "federal reserve stocks",
]

# 섹터 뉴스 연결. 종목명이 없어도 섹터 전체에 영향을 준다.
SECTOR_KEYWORDS = {
    "semiconductor": "Technology",
    "chip": "Technology",
    "artificial intelligence": "Technology",
    "cloud computing": "Technology",
    "biotech": "Health Care",
    "fda approval": "Health Care",
    "drug trial": "Health Care",
    "oil price": "Energy",
    "crude": "Energy",
    "opec": "Energy",
    "bank earnings": "Finance",
    "interest rate": "Finance",
    "retail sales": "Consumer Discretionary",
    "housing": "Real Estate",
    "mortgage rate": "Real Estate",
    "utilities": "Utilities",
}

# ---------------------------------------------------------------- 이벤트
EARNINGS_URL = "https://api.nasdaq.com/api/calendar/earnings?date={date}"
ECON_URL = "https://api.nasdaq.com/api/calendar/economicevents?date={date}"
SEC_TICKER_MAP = "https://www.sec.gov/files/company_tickers_exchange.json"
SEC_FILINGS = ("https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany"
               "&CIK={cik}&type=8-K&dateb=&owner=include&count=5&output=atom")
# SEC는 User-Agent에 연락처를 요구한다 (정책)
SEC_UA = "AssetInsight/0.1 (contact: enair840926@gmail.com)"
