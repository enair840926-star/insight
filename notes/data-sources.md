# 자산 인사이트 앱 — 데이터 소스 조사 결과

> 조사일: 2026-08-03 / 방법: 실제 HTTP 호출로 60개 엔드포인트 생존·품질 테스트 (문서 참조 아님)
> 환경: Windows 10, Python 3.13.11, Node.js 없음

---

## 0. 결론 3줄

1. **무료만으로 5개 자산군(국장·미장·코인·선물·원자재) 전부 커버 가능하다.** 시세는 Yahoo + 네이버금융 + 바이낸스 조합으로 빈틈이 없다.
2. **차별화 포인트는 뉴스가 아니라 "수급·포지셔닝 데이터"다.** 외국인/기관 순매수, 펀딩비, 미결제약정, 롱숏비율이 전부 무료로 열려있는데 일반 뉴스앱은 이걸 안 다룬다.
3. **뉴스 본문 전문(全文)은 긁지 않는 설계로 간다.** 제목+요약+링크만 쓴다. 저작권 문제를 피하면서 감성분석 품질도 충분하다. (근거는 6장)

---

## 1. 시세 데이터 — 전부 해결됨

### 1-1. Yahoo Finance Chart API (무료·무키·레이트리밋 없음)

```
https://query1.finance.yahoo.com/v8/finance/chart/{심볼}?range=5d&interval=1d
```

**연속 20회 호출 9초, 실패 0건.** 스로틀링 없음 → 폴링 주기를 공격적으로 잡아도 된다.

심볼 커버리지 실측 (2026-08-03 종가 기준):

| 자산군 | 심볼 예시 | 실측값 | 통화 |
|---|---|---|---|
| 국장 개별 | `005930.KS` (삼성전자) | O | KRW |
| 코스닥 개별 | `247540.KQ` (에코프로비엠) | O | KRW |
| 국내 지수 | `^KS11` / `^KQ11` | 737.35 | KRW |
| 미장 개별 | `AAPL`, `NVDA` | O | USD |
| 지수선물 | `ES=F` / `NQ=F` | 7595.25 / 28632.75 | USD |
| 금 / 은 | `GC=F` / `SI=F` | 4087.0 / 57.36 | USD |
| WTI원유 | `CL=F` | 79.27 | USD |
| 천연가스 | `NG=F` | 2.754 | USD |
| 구리 | `HG=F` | 6.4695 | USD |
| 곡물 | `ZC=F` (옥수수) | 466.0 | USX(센트) |
| 달러인덱스 | `DX-Y.NYB` | 99.828 | - |
| 미10년물 | `^TNX` | 4.684 | % |
| VIX | `^VIX` | 15.88 | - |
| 원달러 | `KRW=X` | 1427.63 | KRW |
| 코인 | `BTC-USD` | 63,719.64 | USD |

→ **하나의 API로 5개 자산군을 전부 처리한다.** 어댑터를 자산군별로 나눌 필요가 없다는 뜻이고, 설계가 크게 단순해진다.

주의: 곡물류는 통화가 `USX`(센트)로 온다. 100으로 나눠야 달러다. 이거 놓치면 옥수수가 금보다 비싸 보인다.

### 1-2. 네이버 금융 API — 국장 전용 심화 (무료·무키)

Yahoo가 못 주는 국장 디테일을 전부 준다. **`Referer: https://m.stock.naver.com/` 헤더 필수.**

| 용도 | 엔드포인트 | 검증 |
|---|---|---|
| 실시간 시세 | `polling.finance.naver.com/api/realtime/domestic/stock/{코드}` | O |
| 지수 실시간 | `polling.finance.naver.com/api/realtime/domestic/index/KOSPI` | O |
| 종목 기본정보 | `m.stock.naver.com/api/stock/{코드}/basic` | O |
| 일별 시세 | `api.finance.naver.com/siseJson.naver?symbol={코드}&requestType=1&startTime=YYYYMMDD&endTime=YYYYMMDD&timeframe=day` | O |
| **투자자별 매매동향** | `m.stock.naver.com/api/stock/{코드}/trend` | O |
| 종목별 뉴스 | `m.stock.naver.com/api/news/stock/{코드}?pageSize=5&page=1` | O |
| 종목별 공시 | `m.stock.naver.com/api/stock/{코드}/disclosure` | O |

**투자자별 매매동향이 이 앱의 핵심 자산이다.** 실측 응답:

```json
{"bizdate":"20260803","foreignerPureBuyQuant":"-3,896,489",
 "foreignerHoldRatio":"46.63%","organPureBuyQuant":"-5,039,954"}
```

외국인 -389만주 + 기관 -503만주 동반 순매도 → 뉴스 100개보다 이 한 줄이 더 많은 걸 말한다. 일별 시세도 `외국인소진율`을 같이 준다.

일별 시세 응답이 JSON이 아니라 **작은따옴표 섞인 유사 JS 배열**이라 `json.loads`가 실패한다. 전처리 필요.

### 1-3. 코인 (무료·무키)

| 용도 | 엔드포인트 | 검증 |
|---|---|---|
| 현물 24h | `api.binance.com/api/v3/ticker/24hr?symbol=BTCUSDT` | O |
| **펀딩비** | `fapi.binance.com/fapi/v1/premiumIndex?symbol=BTCUSDT` | O |
| **미결제약정 추이** | `fapi.binance.com/futures/data/openInterestHist` | O |
| **롱숏 계좌비율** | `fapi.binance.com/futures/data/globalLongShortAccountRatio` | 1.9403 |
| **상위계좌 포지션비율** | `fapi.binance.com/futures/data/topLongShortPositionRatio` | 롱 61.93% |
| 전체 선물 심볼 | `fapi.binance.com/fapi/v1/ticker/24hr` | O (270KB) |
| 업비트 | `api.upbit.com/v1/ticker?markets=KRW-BTC` | O |
| 업비트 전체마켓 | `api.upbit.com/v1/market/all` | O (한글명 포함) |
| 빗썸 | `api.bithumb.com/public/ticker/BTC_KRW` | O |

→ 업비트 KRW가 + 바이낸스 USDT가 + 원달러(`KRW=X`) 조합으로 **김치프리미엄을 직접 계산**할 수 있다. 이것도 무료 소스로 만드는 고유 지표다.

---

## 2. 뉴스 소스 — 살아있는 것만 추림

### 2-1. 국내 (실측 items 수)

| 매체 | URL | items | 비고 |
|---|---|---|---|
| 연합뉴스 경제 | `yna.co.kr/rss/economy.xml` | 120 | **요약 충실, 시간 정확** — 1순위 |
| 뉴시스 경제 | `newsis.com/RSS/economy.xml` | 100 | O |
| 아시아경제 증권 | `asiae.co.kr/rss/stock.htm` | 100 | O |
| 머니투데이 증권 | `rss.mt.co.kr/mt_news_stock.xml` | 100 | **EUC-KR 디코딩 필수** |
| 조선비즈 | `biz.chosun.com/arc/outboundfeeds/rss/?outputType=xml` | 58 | O |
| 매일경제 증권 | `mk.co.kr/rss/50200011/` | 50 | O |
| 인포스탁데일리 | `infostockdaily.co.kr/rss/allArticle.xml` | 50 | O |

**차단·불가 (우회 시도하지 말 것):**
- 한국경제 — 403, 브라우저 헤더/Referer 붙여도 완강히 거부. 명시적 거부 의사로 봐야 한다.
- 이데일리 — TCP 연결 강제 종료(10054)
- 서울경제, 파이낸셜뉴스 — 404 (RSS 폐지된 듯)

### 2-2. 구글뉴스 RSS — 사실상 무제한 확장

```
https://news.google.com/rss/search?q={키워드}&hl=ko&gl=KR&ceid=KR:ko
```

**요청당 100~104개.** 키워드·언어·국가 전부 파라미터라 "삼성전자", "federal reserve rate", "gold price" 무엇이든 된다. 위에서 차단당한 매체 기사도 여기 제목으로는 들어온다.

**단, `<description>`이 요약이 아니라 관련기사 `<a>` 링크 덩어리다.** 실측:
```html
<ol><li><a href="https://news.google.com/rss/articles/CBMiT0FVX3lxTE1a...
```
→ **제목만 쓸 수 있다.** 이게 감성분석 설계를 좌우한다 (6장 참조).

### 2-3. 해외

| 분류 | 매체 | items | 요약 품질 |
|---|---|---|---|
| 미장 | **Yahoo 종목별** `feeds.finance.yahoo.com/rss/2.0/headline?s={티커}` | 20 | 좋음 |
| 미장 | CNBC Markets `cnbc.com/id/20910258/device/rss/rss.html` | 30 | 좋음 |
| 미장 | MarketWatch `feeds.content.dowjones.io/public/rss/mw_topstories` | 10 | 보통 |
| 미장 | Seeking Alpha `seekingalpha.com/market_currents.xml` | 7 | 보통 |
| 미장 | FT Markets `ft.com/markets?format=rss` | 25 | 보통 |
| 코인 | **CoinDesk** `coindesk.com/arc/outboundfeeds/rss/` | 25 | **매우 좋음** |
| 코인 | Cointelegraph `cointelegraph.com/rss` | 30 | 좋음 |
| 코인 | Decrypt `decrypt.co/feed` | 38 | 좋음 |
| 코인 | The Block `theblock.co/rss.xml` | 20 | 좋음 |
| 코인 | 블록미디어(한글) `blockmedia.co.kr/feed` | 10 | 좋음 |
| 원자재 | OilPrice `oilprice.com/rss/main` | 15 | 좋음 |
| 원자재 | Mining.com `mining.com/feed/` | 34 | 좋음 |
| 원자재 | Investing Commodities `investing.com/rss/news_11.rss` | 10 | **요약 없음(제목만)** |

Yahoo 종목별 RSS는 **티커만 갈아끼우면 되므로** 관심종목 기능과 그대로 붙는다.

차단: CryptoPanic(403), Reuters 구 피드(DNS 소멸), Kitco(404).

---

## 3. 이벤트 / 공시 / 캘린더

| 용도 | 소스 | 키 | 검증 |
|---|---|---|---|
| **미국 실적 캘린더** | `api.nasdaq.com/api/calendar/earnings?date=YYYY-MM-DD` | 불필요 | O (78KB) |
| **미국 경제지표 캘린더** | `api.nasdaq.com/api/calendar/economicevents?date=` | 불필요 | O (35KB, 실제치/예상치 포함) |
| 배당 캘린더 | `api.nasdaq.com/api/calendar/dividends?date=` | 불필요 | O |
| IPO 캘린더 | `api.nasdaq.com/api/ipo/calendar?date=YYYY-MM` | 불필요 | O |
| **미국 공시(8-K 등)** | `sec.gov/cgi-bin/browse-edgar?...&output=atom` | 불필요 | O (UA에 연락처 필수) |
| 국내 공시(간이) | 네이버 `/api/stock/{코드}/disclosure` | 불필요 | O |
| 국내 공시(정식) | DART OpenAPI | **무료 키** | 일 20,000건 |
| 한국 거시지표 | 한국은행 ECOS | **무료 키** | 키 없으면 거부 확인 |
| 미국 물가 원자료 | `api.bls.gov/publicAPI/v2/...` | 불필요 | O |
| 미국 국채금리 | `api.fiscaldata.treasury.gov/...` | 불필요 | O |

전부 `Referer: https://www.nasdaq.com/` 필요(나스닥 계열).

**실패:** TradingEconomics 게스트 계정(410 — 폐지), CME FedWatch(403), FRED(키 필요), Stooq(봇차단 페이지 반환).

---

## 4. 센티먼트 지표 — 실측값 확보

| 지표 | 소스 | 2026-08-03 실측 |
|---|---|---|
| 증시 공포탐욕 | `production.dataviz.cnn.io/index/fearandgreed/graphdata` | **44.6 (fear)** |
| 코인 공포탐욕 | `api.alternative.me/fng/` | **28 (Fear)** |
| BTC 롱숏비율 | Binance | **1.9403** |
| BTC 상위계좌 롱비중 | Binance | **61.93%** |

CNN 것은 `Referer: https://edition.cnn.com/` 필요하고, 응답에 **과거 시계열까지 176KB**로 들어있어 추세 차트를 바로 그릴 수 있다.

읽는 법 한 가지: 지금 공포탐욕 28(공포)인데 롱숏비율 1.94(롱 쏠림)면 **심리는 얼어붙었는데 포지션은 롱에 몰려있는** 상태다. 이런 괴리가 인사이트의 재료다. 뉴스만 봐서는 절대 안 나온다.

---

## 5. 인사이트 취득 구조 — 6개 층위

"인사이트를 수집한다"는 걸 뉴스 수집으로 좁히면 실패한다. 실제로는 층위가 다르고, **아래로 갈수록 희소하고 가치가 높다.**

```
L1  시세·거래량          ← 누구나 있음. 차별화 0
L2  뉴스 텍스트           ← 흔함. 네이버·구글이 이미 잘함
L3  수급·포지셔닝         ← 무료로 열려있는데 아무도 안 씀  ★핵심
      외국인/기관 순매수, 외국인소진율, 펀딩비,
      미결제약정, 롱숏비율, 김치프리미엄
L4  센티먼트 지표         ← 공포탐욕 지수류
L5  이벤트 캘린더         ← 실적·경제지표·공시 (예측 가능한 미래)
L6  종합 판단            ← L1~L5를 LLM이 교차 해석  ★결과물
```

**L3가 이 앱의 존재 이유다.** L1·L2만 하면 그냥 뉴스 리더고, 이미 무료로 널려있다.

L6 프롬프트에 들어갈 재료 예시:
```
삼성전자 / 2026-08-03
L1  종가 314,500 (-6.0%), 거래량 2,497만주 (20일 평균 대비 +180%)
L3  외국인 -389만주, 기관 -503만주 (동반 순매도 3일째)
    외국인소진율 46.88% → 46.63% (-0.25%p)
L4  코스피 관련 심리 지표
L5  8/7 미 CPI 발표 예정
L2  최근 뉴스 12건 (제목 기준)
→ 당일 / 단기 / 장기 관점을 각각 생성
```

L3 없이 L2만 넣으면 LLM은 "뉴스가 엇갈립니다" 같은 말만 한다. 숫자를 줘야 판단이 나온다.

---

## 6. 뉴스 감성분석 — 설계 제약과 대응

### 제약 1: 본문 전문을 쓸 수 없다

연합뉴스 기사 원문 HTTP 호출은 성공하지만(200), 태그 제거 후 **29,236자 중 대부분이 메뉴·네비게이션 보일러플레이트**다. 기사 본문 컨테이너를 정규식으로 잡으려 했으나 셀렉터가 매체마다 달라 실패했다. `trafilatura` 같은 라이브러리가 필요하다.

**하지만 그 전에 — 전문 수집은 하지 않는 쪽을 권한다.**
- 기사 전문을 긁어 저장·재가공하는 건 저작권 리스크가 실재한다
- 한국경제처럼 **명시적으로 403을 거는 매체를 우회하는 건 하지 말아야 한다**
- 개인용이라도 나중에 배포하면 문제가 된다

### 제약 2: 소스별 텍스트 품질이 3등급으로 갈린다

| 등급 | 소스 | 감성분석 입력 |
|---|---|---|
| A. 제목+요약 | 연합, CNBC, CoinDesk, Yahoo, OilPrice | 충분 |
| B. 제목만 | **구글뉴스**, Investing.com | 제한적 |
| C. 인코딩 이슈 | 머니투데이(EUC-KR) | 디코딩 후 A |

구글뉴스가 물량의 대부분인데 하필 B등급이다.

### 대응: 하이브리드 2단 구조 (선택하신 Claude API 활용)

```
1단  전체 뉴스 (일 500~2000건) — 규칙 기반 사전 스코어링
     · 종목/자산 키워드 매칭으로 태깅
     · 명백한 방향성 어휘 사전 (실적호조/어닝쇼크/금리인상/규제…)
     · 중복 제거 (구글뉴스는 같은 기사가 매체별로 중복됨)
     → 여기서 90% 걸러짐. 비용 0원

2단  살아남은 것 + L3~L5 숫자 → Claude API
     · 개별 뉴스 감성이 아니라 "묶음 → 종합 판단"으로 호출
       (건당 호출하면 비용이 터진다)
     · 자산군당 1회 × 5개군 × 하루 3회 = 일 15회 수준
     → 월 몇 천 원대
```

**핵심: 건당 감성분석이 아니라 자산군 단위 배치 종합.** 뉴스 하나하나의 긍/부정 라벨은 규칙 기반으로 충분하고, LLM은 "이 숫자들과 이 뉴스 묶음이 뭘 뜻하는가"에 써야 값어치를 한다.

---

## 7. 비용

| 항목 | 월 비용 |
|---|---|
| 시세·뉴스·수급·캘린더·센티먼트 전부 | **0원** |
| DART / ECOS 키 | 0원 (가입만) |
| Claude API | 배치 설계 시 수천 원, 건당 호출 시 수십만 원 |
| 서버 | 개인용은 PC에서 돌리면 0원 |

---

## 8. 미해결 / 남은 리스크

1. **펀더멘털(PER·목표주가·애널리스트 등급) 경로 미확보.**
   Yahoo `quoteSummary`가 401을 반환하고, crumb 인증 우회도 이 환경에서 실패했다(`fc.yahoo.com` 404). 대안 필요 — FMP 무료 티어(일 250회) 또는 네이버 종목 페이지 파싱.
2. **비공식 API 의존.** 네이버·나스닥·CNN 엔드포인트는 공식 문서가 없다. 예고 없이 바뀔 수 있으니 **소스별 어댑터를 격리하고 실패해도 앱 전체가 죽지 않게** 설계해야 한다.
3. **지연 시세.** Yahoo는 15분 지연. 단타용으로는 부적합하고, 이 앱의 성격(당일/단기/장기 관점)에는 문제없다.
4. **국장 전종목 리스트 확보 경로 미정.** KRX 공식 API는 403. pykrx 라이브러리로 우회 가능한지 확인 필요.
5. **투자 판단 책임.** LLM 생성 인사이트에 면책 문구가 반드시 필요하다.

---

## 9. 다음 단계 제안

1. 위 소스로 **수집기(collector) 프로토타입**부터 만든다 — 자산군 1개(예: 국장)로 좁혀서 L1+L2+L3를 실제로 모아본다
2. 모인 데이터를 Claude에 한 번 넣어보고 **인사이트 품질이 쓸 만한지 먼저 확인**한다
3. 품질이 확인되면 나머지 4개 자산군으로 확장
4. 그 다음에 모바일 UI

**UI를 먼저 만들면 안 된다.** 이 앱의 가치는 전부 데이터 층에 있고, 거기가 안 되면 화면이 예뻐도 소용없다.
