# -*- coding: utf-8 -*-
"""데이터 소스 접속 검증 — 이 IP에서 어디까지 닿는가

    python tools/probe.py            # 표로 출력
    python tools/probe.py --md 파일  # 마크다운 리포트 저장

GitHub Actions 러너는 미국에 있다. 한국 사이트(네이버·DART·한국은행)가
해외 IP를 막는지, 바이낸스가 미국 IP를 막는지(451)를 실제로 두들겨 봐야
클라우드 자동 갱신이 가능한지 알 수 있다. 추측하지 말고 측정한다.

각 소스마다 '없으면 뭐가 죽는지'를 적어 뒀다. 일부가 막혀도 나머지로
돌릴 수 있는지 판단하려면 그 정보가 필요하다.
"""
import argparse
import json
import os
import platform
import sys
import time
import datetime as dt

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests
from core.http import UA, _referer_for

TIMEOUT = 25

# DART list.json은 날짜 범위를 안 주면 오늘치만 본다. 오늘 공시가 없는
# 회사면 '데이터 없음'이 와서 접속 성공을 실패로 오인한다.
_D30 = (dt.date.today() - dt.timedelta(days=30)).strftime("%Y%m%d")

# (그룹, 이름, URL, 없으면 죽는 것, 성공 판정 키워드)
# 성공 판정 키워드가 None이면 HTTP 200만 본다.
TARGETS = [
    # ---------------------------------------------------------------- 국장
    ("국장", "네이버 시세(모바일)",
     "https://m.stock.naver.com/api/index/KOSPI/basic",
     "코스피·코스닥 지수 전체", "closePrice"),
    ("국장", "네이버 시가총액 목록",
     "https://m.stock.naver.com/api/stocks/marketValue/KOSPI?page=1&pageSize=5",
     "종목 유니버스 4,295개 · 동적 선별 전체", "stocks"),
    ("국장", "네이버 업종",
     "https://m.stock.naver.com/api/stocks/industry",
     "업종별 등락", None),
    ("국장", "네이버 테마",
     "https://m.stock.naver.com/api/stocks/theme?page=1&pageSize=5",
     "테마별 등락(국장 특유 신호)", None),
    ("국장", "네이버 일별시세 API",
     "https://api.finance.naver.com/siseJson.naver"
     "?symbol=005930&requestType=1&startTime=20260701&endTime=20260804&timeframe=day",
     "종목별 과거 시세·이동평균", None),
    # DART는 엔드포인트마다 따로 재야 한다. 실측에서 공시 목록은 되는데
    # 내부자거래·5%룰만 비는 일이 있었다.
    # 성공 판정 키워드는 '성공 응답에만 있는 것'이라야 한다. DART는 오류도
    # 200 + {"status":"..."}로 주므로 status로 재면 오류를 성공으로 센다.
    ("국장", "DART 공시목록(list)",
     "https://opendart.fss.or.kr/api/list.json"
     "?crtfc_key={DART_API_KEY}&corp_code=00126380"
     f"&bgn_de={_D30}&page_count=1",
     "종목별 최근 공시", "rcept_no"),
    ("국장", "DART 내부자거래(elestock)",
     "https://opendart.fss.or.kr/api/elestock.json"
     "?crtfc_key={DART_API_KEY}&corp_code=00126380",
     "임원·주요주주 매매 (★ 동시매수/매도 신호)", "rcept_no"),
    ("국장", "DART 5%룰(majorstock)",
     "https://opendart.fss.or.kr/api/majorstock.json"
     "?crtfc_key={DART_API_KEY}&corp_code=00126380",
     "대량보유 변동 (국민연금·블랙록 등)", "rcept_no"),
    ("국장", "DART 고유번호 ZIP(corpCode)",
     "https://opendart.fss.or.kr/api/corpCode.xml?crtfc_key={DART_API_KEY}",
     "종목코드→DART코드 매핑. 없으면 위 셋이 전부 죽는다", "PK"),
    ("국장", "DART 웹",
     "https://dart.fss.or.kr/dsab007/main.do",
     "공시 원문 링크", None),
    ("국장", "한국은행 ECOS",
     "https://ecos.bok.or.kr/api/StatisticSearch/{ECOS_API_KEY}"
     "/json/kr/1/1/722Y001/M/202601/202607/0101000",
     "국내 거시지표(금리·물가·수출)", "StatisticSearch"),

    # ---------------------------------------------------------------- 미장
    ("미장", "나스닥 스크리너",
     "https://api.nasdaq.com/api/screener/stocks?tableonly=true&limit=5&download=true",
     "미국 전종목 7,113개 · 동적 선별 전체", "rows"),
    ("미장", "나스닥 실적 캘린더",
     "https://api.nasdaq.com/api/calendar/earnings?date=2026-08-05",
     "실적 발표 일정", None),
    # SEC는 UA에 연락처를 요구한다 (정책). us_universe.SEC_UA를 그대로 쓴다.
    ("미장", "SEC 회사 목록",
     "https://www.sec.gov/files/company_tickers_exchange.json",
     "티커 보조 매핑", None),

    # ------------------------------------------------------------ 공통 시세
    ("시세", "야후 파이낸스 차트",
     "https://query1.finance.yahoo.com/v8/finance/chart/AAPL?range=5d&interval=1d",
     "지수·원자재·환율·금리 전부(매크로의 심장)", "chart"),
    ("시세", "야후 티커 RSS",
     "https://feeds.finance.yahoo.com/rss/2.0/headline?s=AAPL&region=US&lang=en-US",
     "종목별 뉴스", None),

    # ---------------------------------------------------------------- 매크로
    ("매크로", "CFTC COT",
     "https://publicreporting.cftc.gov/resource/6dca-aqww.json?$limit=1",
     "원자재 투기 포지셔닝(코인 펀딩비의 원자재판)", None),
    ("매크로", "EIA 재고",
     "https://api.eia.gov/v2/petroleum/stoc/wstk/data/"
     "?api_key={EIA_API_KEY}&frequency=weekly&data[0]=value&length=1",
     "원유·휘발유 재고 (재고·커브·COT 3축 중 1축)", "response"),
    # 매크로 데스크가 '미확인·보류'로 남겨 둔 세 항목. 이 PC에서는
    # FRED가 타임아웃인데 러너에서는 열릴 수 있어 따로 잰다.
    ("매크로", "FRED 기대인플레(BEI)",
     "https://fred.stlouisfed.org/graph/fredgraph.csv?id=T10YIE",
     "매크로데스크 inflation 팩터 (bp)", "T10YIE"),
    ("매크로", "FRED 실질금리(TIPS)",
     "https://fred.stlouisfed.org/graph/fredgraph.csv?id=DFII10",
     "매크로데스크 realYield 팩터 (bp)", "DFII10"),
    ("매크로", "ECB 독일 10년물",
     "https://data-api.ecb.europa.eu/service/data/YC/"
     "B.U2.EUR.4F.G_N_A.SV_C_YM.SR_10Y?lastNObservations=2&format=csvdata",
     "매크로데스크 rateDiff 팩터 (미-유로존 금리차)", "OBS_VALUE"),
    ("매크로", "독일 국채 (야후 대체)",
     "https://query1.finance.yahoo.com/v8/finance/chart/"
     "BUND.EX?range=5d&interval=1d",
     "ECB가 막힐 때의 2차 대안", "chart"),

    ("매크로", "CNN 공포탐욕",
     "https://production.dataviz.cnn.io/index/fearandgreed/graphdata",
     "미 증시 심리 지표", None),

    # ---------------------------------------------------------------- 코인
    ("코인", "바이낸스 선물 (미국 IP 차단 여부)",
     "https://fapi.binance.com/fapi/v1/premiumIndex?symbol=BTCUSDT",
     "펀딩비·미결제약정·롱숏비 전부 — 코인 패널의 핵심", "lastFundingRate"),
    ("코인", "바이낸스 롱숏비",
     "https://fapi.binance.com/futures/data/globalLongShortAccountRatio"
     "?symbol=BTCUSDT&period=1h&limit=1",
     "전체계좌·상위계좌 롱숏 분화", None),
    ("코인", "업비트 시세",
     "https://api.upbit.com/v1/ticker?markets=KRW-BTC",
     "김치프리미엄", None),
    ("코인", "코인게코",
     "https://api.coingecko.com/api/v3/global",
     "시총·도미넌스·상위 100 코인", "data"),
    ("코인", "얼터너티브 공포탐욕",
     "https://api.alternative.me/fng/?limit=1",
     "코인 심리 지표", None),

    # 바이낸스가 451이면 여기서 같은 지표를 가져와야 한다.
    # 우회가 아니라 대체 소스다 — 바이낸스 약관을 건드리지 않는다.
    ("코인대체", "OKX 펀딩비",
     "https://www.okx.com/api/v5/public/funding-rate?instId=BTC-USDT-SWAP",
     "펀딩비 대체", "fundingRate"),
    ("코인대체", "OKX 미결제약정",
     "https://www.okx.com/api/v5/public/open-interest"
     "?instType=SWAP&instId=BTC-USDT-SWAP",
     "미결제약정 대체", "oiCcy"),
    ("코인대체", "OKX 전체계좌 롱숏비",
     "https://www.okx.com/api/v5/rubik/stat/contracts/"
     "long-short-account-ratio-contract?instId=BTC-USDT-SWAP&period=1H",
     "전체계좌 롱숏비 대체", None),
    ("코인대체", "OKX 상위트레이더 롱숏비",
     "https://www.okx.com/api/v5/rubik/stat/contracts/"
     "long-short-account-ratio-contract-top-trader?instId=BTC-USDT-SWAP&period=1H",
     "상위계좌 롱숏비 대체 (소매-고래 분화)", None),
    ("코인대체", "OKX 테이커 매수/매도",
     "https://www.okx.com/api/v5/rubik/stat/taker-volume"
     "?ccy=BTC&instType=SPOT&period=1H",
     "테이커 비율 대체", None),
    ("코인대체", "OKX 티커 전체",
     "https://www.okx.com/api/v5/market/tickers?instType=SWAP",
     "코인별 24시간 등락", None),
    ("코인대체", "바이비트 티커(펀딩+OI 한번에)",
     "https://api.bybit.com/v5/market/tickers?category=linear&symbol=BTCUSDT",
     "OKX도 막힐 때의 2차 대안", "fundingRate"),
    ("코인대체", "바이비트 롱숏비",
     "https://api.bybit.com/v5/market/account-ratio"
     "?category=linear&symbol=BTCUSDT&period=1h&limit=1",
     "OKX도 막힐 때의 2차 대안", None),

    # ---------------------------------------------------------------- 뉴스
    ("뉴스", "구글뉴스 RSS(한국어)",
     "https://news.google.com/rss/search?q=%EC%BD%94%EC%8A%A4%ED%94%BC&hl=ko&gl=KR&ceid=KR:ko",
     "국장·코인 뉴스 수집의 주력", None),
    ("뉴스", "연합뉴스 RSS",
     "https://www.yna.co.kr/rss/economy.xml", "국내 경제 뉴스", None),
    ("뉴스", "머니투데이 RSS",
     "https://rss.mt.co.kr/mt_news_stock.xml", "국내 증권 뉴스", None),
    ("뉴스", "매일경제 RSS",
     "https://www.mk.co.kr/rss/30100041/", "국내 증권 뉴스", None),
    ("뉴스", "조선비즈 RSS",
     "https://biz.chosun.com/arc/outboundfeeds/rss/category/economy/?outputType=xml",
     "국내 경제 뉴스", None),
    ("뉴스", "블록미디어 RSS",
     "https://www.blockmedia.co.kr/feed", "국내 코인 뉴스", None),
    ("뉴스", "코인데스크 RSS",
     "https://www.coindesk.com/arc/outboundfeeds/rss/", "해외 코인 뉴스", None),
    ("뉴스", "CNBC RSS",
     "https://www.cnbc.com/id/100003114/device/rss/rss.html", "미국 시장 뉴스", None),
    ("뉴스", "오일프라이스 RSS",
     "https://oilprice.com/rss/main", "에너지 뉴스", None),
]


KEY_NAMES = ("DART_API_KEY", "ECOS_API_KEY", "EIA_API_KEY")
EXPECTED_LEN = {"DART_API_KEY": 40, "ECOS_API_KEY": 20, "EIA_API_KEY": 40}


def key_shapes():
    """키가 실제로 어떤 모양으로 도착했는지. 값은 절대 드러내지 않는다.

    '안 넣었다 / 이름까지 같이 넣었다 / 공백이 붙었다 / 제대로 들어왔다'를
    길이와 포함 문자만으로 구분할 수 있다. 값을 보지 않고 원인을 좁히려면
    이 정도는 재야 한다.
    """
    from core import env
    out = []
    for name in KEY_NAMES:
        v = os.environ.get(name)          # .env가 아니라 환경변수만 본다
        exp = EXPECTED_LEN[name]
        if not v:
            out.append((name, 0, "없음 — 시크릿이 전달되지 않았습니다"))
            continue
        notes = []
        if name in v:
            notes.append(f"값 안에 '{name}'이 들어 있음 (이름까지 붙여넣음)")
        for ch, label in ((":", "콜론"), ("=", "등호"), ('"', "따옴표"),
                          ("'", "따옴표")):
            if ch in v:
                notes.append(f"{label} 포함")
        if v != v.strip():
            notes.append("앞뒤 공백/줄바꿈 있음")
        if len(v) != exp and not notes:
            notes.append(f"길이가 예상({exp}자)과 다름")
        out.append((name, len(v), " · ".join(notes) or f"정상 ({exp}자)"))
    return out


def redact(text):
    """응답 본문에서 키 값을 지운다.

    리포트는 공개 리포에 커밋된다. 지금까지 확인한 응답들은 키를 되돌려
    주지 않지만, 소스가 바뀌면 언제든 그럴 수 있다. 새어 나간 뒤에
    알아차리는 것보다 미리 막는 편이 싸다.
    """
    if not text:
        return text
    from core import env
    for name in ("DART_API_KEY", "ECOS_API_KEY", "EIA_API_KEY",
                 "ANTHROPIC_API_KEY", "USDA_API_KEY"):
        v = env.get(name)
        if v and len(v) >= 8:
            text = text.replace(v, f"<{name}>")
    return text


def resolve_url(url):
    """{EIA_API_KEY} 같은 자리표시자를 .env·환경변수 값으로 바꾼다.

    반환: (url, 건너뛸 사유 또는 None)
    """
    if "{" not in url:
        return url, None
    from core import env
    import re as _re
    for name in _re.findall(r"\{(\w+)\}", url):
        val = env.get(name)
        if not val:
            return url, f"키 없음({name})"
        url = url.replace("{" + name + "}", val)
    return url, None


def probe(url):
    """반환: (상태문자열, HTTP코드, 바이트, 초, 본문앞부분)"""
    h = {"User-Agent": UA, "Accept": "*/*",
         "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8"}
    if "sec.gov" in url:
        # SEC는 연락처가 담긴 UA를 요구한다. 브라우저 UA로 가면 403이다.
        import us_universe
        h["User-Agent"] = us_universe.SEC_UA
    ref = _referer_for(url)
    if ref:
        h["Referer"] = ref
    t0 = time.time()
    try:
        r = requests.get(url, headers=h, timeout=TIMEOUT)
    except requests.RequestException as e:
        return f"연결실패({type(e).__name__})", None, 0, time.time() - t0, ""
    el = time.time() - t0
    body = redact(r.content[:400].decode("utf-8", "replace"))
    if r.status_code == 200:
        return "OK", 200, len(r.content), el, body
    if r.status_code == 451:
        return "차단(451 법적사유)", 451, len(r.content), el, body
    if r.status_code == 403:
        return "차단(403)", 403, len(r.content), el, body
    if r.status_code == 429:
        return "속도제한(429)", 429, len(r.content), el, body
    return f"HTTP {r.status_code}", r.status_code, len(r.content), el, body


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--md", help="마크다운 리포트 저장 경로")
    ap.add_argument("--json", help="JSON 결과 저장 경로")
    a = ap.parse_args()

    # 러너 위치를 남긴다 — 한국 사이트 차단 여부를 해석할 때 필요하다.
    where = {}
    try:
        j = requests.get("https://ipinfo.io/json", timeout=10).json()
        where = {k: j.get(k) for k in ("ip", "city", "region", "country", "org")}
    except Exception:
        where = {"country": "확인 실패"}

    print(f"\n접속 검증 — {dt.datetime.now():%Y-%m-%d %H:%M}")
    print(f"위치: {where.get('country')} / {where.get('city')} "
          f"/ {where.get('org')}")
    print(f"파이썬 {platform.python_version()} · {platform.system()}\n")

    shapes = key_shapes()
    print("API 키 상태 (값은 표시하지 않습니다)")
    for name, n, note in shapes:
        print(f"  {name:<16} 길이 {n:>3}자   {note}")
    print()
    print(f"{'그룹':<6}{'소스':<34}{'결과':<20}{'크기':>9}{'초':>7}")
    print("-" * 78)

    rows, ok_n, skipped = [], 0, 0
    for group, name, url, breaks, key in TARGETS:
        real, skip = resolve_url(url)
        if skip:
            # 키가 없으면 접속 가능 여부를 판정할 수 없다. 실패로 세지 않는다.
            skipped += 1
            print(f"{group:<6}{name:<34}- {skip:<18}{'':>8} {'':>6}")
            rows.append({"group": group, "name": name, "url": url,
                         "breaks": breaks, "status": skip, "code": None,
                         "bytes": 0, "sec": 0, "ok": None, "body": ""})
            continue
        status, code, size, el, body = probe(real)
        # 200이어도 내용이 비어 있으면 실패다. 오류를 200으로 주는 곳이 많다
        # (DART는 {"status":"012",...}, 차단 페이지도 200인 경우가 있다).
        # 크기 조건은 걸지 않는다 — 90바이트 오류를 성공으로 세는 원인이었다.
        if status == "OK" and key and key not in body:
            status = "내용없음"
        ok = status == "OK"
        ok_n += ok
        mark = "✓" if ok else "✗"
        print(f"{group:<6}{name:<34}{mark} {status:<18}"
              f"{size:>8,}B{el:>6.1f}s")
        rows.append({"group": group, "name": name, "url": url,
                     "breaks": breaks, "status": status, "code": code,
                     "bytes": size, "sec": round(el, 2), "ok": ok,
                     "body": body[:200]})

    tested = len(TARGETS) - skipped
    print("-" * 78)
    print(f"{ok_n}/{tested} 성공" + (f" (키 없어 건너뜀 {skipped})" if skipped else "") + "\n")

    failed = [r for r in rows if r["ok"] is False]
    if failed:
        print("실패한 소스와 그 영향:")
        for r in failed:
            print(f"  ✗ {r['name']} ({r['status']})")
            print(f"      → {r['breaks']}")
        print()

    if a.json:
        payload = {"at": dt.datetime.now().isoformat(timespec="seconds"),
                   "where": where, "ok": ok_n, "total": tested,
                   "skipped": skipped, "results": rows}
        with open(a.json, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=1)
        print(f"JSON 저장: {a.json}")

    if a.md:
        with open(a.md, "w", encoding="utf-8") as f:
            f.write(md_report(rows, where, ok_n, shapes))
        print(f"리포트 저장: {a.md}")

    return 0


def md_report(rows, where, ok_n, shapes=()):
    tested = sum(1 for r in rows if r["ok"] is not None)
    L = [f"# 데이터 소스 접속 검증",
         "",
         f"- 실행: {dt.datetime.now():%Y-%m-%d %H:%M}",
         f"- 위치: **{where.get('country')}** / {where.get('city')} "
         f"/ {where.get('org')}",
         f"- 결과: **{ok_n}/{tested} 성공**",
         ""]
    if shapes:
        L += ["## API 키 상태", "",
              "값은 표시하지 않습니다. 길이와 포함 문자만 봅니다.", "",
              "| 키 | 길이 | 진단 |", "|---|---|---|"]
        for name, n, note in shapes:
            mark = "✓" if note.startswith("정상") else "**✗**"
            L.append(f"| {mark} `{name}` | {n}자 | {note} |")
    cur = None
    for r in rows:
        if r["group"] != cur:
            cur = r["group"]
            L += ["", f"## {cur}", "",
                  "| | 소스 | 결과 | 크기 | 없으면 |",
                  "|---|---|---|---|---|"]
        mark = {True: "✓", False: "**✗**", None: "–"}[r["ok"]]
        L.append(f"| {mark} | {r['name']} | {r['status']} | "
                 f"{r['bytes']:,}B | {r['breaks']} |")

    failed = [r for r in rows if r["ok"] is False]
    L += ["", "## 판정", ""]
    if not failed:
        L.append("전 소스 접속 가능. 클라우드 자동 갱신에 제약이 없습니다.")
    else:
        L.append(f"{len(failed)}개 소스가 막혔습니다.")
        L.append("")
        for r in failed:
            L.append(f"- **{r['name']}** — {r['status']}")
            L.append(f"  - 잃는 것: {r['breaks']}")
            if r["body"].strip():
                snippet = r["body"].strip().replace("\n", " ")[:150]
                L.append(f"  - 응답: `{snippet}`")
    return "\n".join(L) + "\n"


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    sys.exit(main())
