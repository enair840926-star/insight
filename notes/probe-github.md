# 데이터 소스 접속 검증

- 실행: 2026-08-24 02:03
- 위치: **US** / San Jose / AS8075 Microsoft Corporation
- 결과: **43/52 성공**

## API 키 상태

값은 표시하지 않습니다. 길이와 포함 문자만 봅니다.

| 키 | 길이 | 진단 |
|---|---|---|
| ✓ `DART_API_KEY` | 40자 | 정상 (40자) |
| ✓ `ECOS_API_KEY` | 20자 | 정상 (20자) |
| ✓ `EIA_API_KEY` | 40자 | 정상 (40자) |

## 국장

| | 소스 | 결과 | 크기 | 없으면 |
|---|---|---|---|---|
| ✓ | 네이버 시세(모바일) | OK | 3,415B | 코스피·코스닥 지수 전체 |
| ✓ | 네이버 시가총액 목록 | OK | 9,806B | 종목 유니버스 4,295개 · 동적 선별 전체 |
| ✓ | 네이버 업종 | OK | 2,470B | 업종별 등락 |
| ✓ | 네이버 테마 | OK | 738B | 테마별 등락(국장 특유 신호) |
| ✓ | 네이버 일별시세 API | OK | 1,683B | 종목별 과거 시세·이동평균 |
| ✓ | DART 공시목록(list) | OK | 339B | 종목별 최근 공시 |
| ✓ | DART 내부자거래(elestock) | OK | 1,127,896B | 임원·주요주주 매매 (★ 동시매수/매도 신호) |
| ✓ | DART 5%룰(majorstock) | OK | 14,796B | 대량보유 변동 (국민연금·블랙록 등) |
| ✓ | DART 고유번호 ZIP(corpCode) | OK | 3,598,077B | 종목코드→DART코드 매핑. 없으면 위 셋이 전부 죽는다 |
| ✓ | DART 웹 | OK | 112,011B | 공시 원문 링크 |
| ✓ | 한국은행 ECOS | OK | 378B | 국내 거시지표(금리·물가·수출) |

## 미장

| | 소스 | 결과 | 크기 | 없으면 |
|---|---|---|---|---|
| ✓ | 나스닥 스크리너 | OK | 2,246,858B | 미국 전종목 7,113개 · 동적 선별 전체 |
| ✓ | 나스닥 실적 캘린더 | OK | 98,810B | 실적 발표 일정 |
| ✓ | 나스닥 실적 서프라이즈 | OK | 945B | 최근 4분기 EPS 대 컨센서스 — 미장 유일의 사실 기반 펀더멘털 후보 |
| ✓ | 나스닥 애널리스트 목표주가 | OK | 1,755B | 목표주가·매수/보유/매도 수 (사실이 아니라 남의 판정이므로 참고용) |
| ✓ | SEC 회사 목록 | OK | 521,857B | 티커 보조 매핑 |

## 시세

| | 소스 | 결과 | 크기 | 없으면 |
|---|---|---|---|---|
| ✓ | 야후 파이낸스 차트 | OK | 1,630B | 지수·원자재·환율·금리 전부(매크로의 심장) |
| ✓ | 야후 분봉 (프리마켓) | OK | 13,074B | 개장 전 프리마켓 등락 — 미장 수집이 개장 1시간 전이라 필요 |
| **✗** | stooq 금현물 일봉 CSV | 내용없음 | 796B | 금 현물 1순위 — 일별 종가 이력이 통째로 온다 |
| ✓ | LBMA 금 오후 고시 (일별) | OK | 913,461B | 금 현물 2순위 — 연속 시세는 아니고 하루 한 번 고시값 |
| **✗** | exchangerate.host XAU 시계열 | 내용없음 | 193B | 금 현물 3순위 — 무료 키 필요 여부 확인용 |
| ✓ | gold-api 현재가 (현재가만) | OK | 182B | 금 현물 참고 — 이력이 없어 혼자서는 못 쓴다 |
| ✓ | 야후 티커 RSS | OK | 10,802B | 종목별 뉴스 |

## 매크로

| | 소스 | 결과 | 크기 | 없으면 |
|---|---|---|---|---|
| ✓ | CFTC COT | OK | 4,720B | 원자재 투기 포지셔닝(코인 펀딩비의 원자재판) |
| ✓ | EIA 재고 | OK | 845B | 원유·휘발유 재고 (재고·커브·COT 3축 중 1축) |
| **✗** | FRED 기대인플레(BEI) | 연결실패(ReadTimeout) | 0B | 매크로데스크 inflation 팩터 (bp) |
| **✗** | FRED 실질금리(TIPS) | 연결실패(ReadTimeout) | 0B | 매크로데스크 realYield 팩터 (bp) |
| ✓ | ECB 독일 10년물 | OK | 1,559B | 매크로데스크 rateDiff 팩터 (미-유로존 금리차) |
| **✗** | 독일 국채 (야후 대체) | HTTP 404 | 108B | ECB가 막힐 때의 2차 대안 |
| ✓ | CNN 공포탐욕 | OK | 176,322B | 미 증시 심리 지표 |

## 코인

| | 소스 | 결과 | 크기 | 없으면 |
|---|---|---|---|---|
| **✗** | 바이낸스 선물 (미국 IP 차단 여부) | 차단(451 법적사유) | 224B | 펀딩비·미결제약정·롱숏비 전부 — 코인 패널의 핵심 |
| **✗** | 바이낸스 롱숏비 | 차단(451 법적사유) | 224B | 전체계좌·상위계좌 롱숏 분화 |
| ✓ | 업비트 시세 | OK | 837B | 김치프리미엄 |
| ✓ | 코인게코 | OK | 3,677B | 시총·도미넌스·상위 100 코인 |
| ✓ | 얼터너티브 공포탐욕 | OK | 209B | 코인 심리 지표 |

## 코인대체

| | 소스 | 결과 | 크기 | 없으면 |
|---|---|---|---|---|
| ✓ | OKX 펀딩비 | OK | 524B | 펀딩비 대체 |
| ✓ | OKX 미결제약정 | OK | 189B | 미결제약정 대체 |
| ✓ | OKX 전체계좌 롱숏비 | OK | 3,916B | 전체계좌 롱숏비 대체 |
| ✓ | OKX 상위트레이더 롱숏비 | OK | 3,920B | 상위계좌 롱숏비 대체 (소매-고래 분화) |
| ✓ | OKX 테이커 매수/매도 | OK | 27,667B | 테이커 비율 대체 |
| ✓ | OKX 티커 전체 | OK | 134,162B | 코인별 24시간 등락 |
| **✗** | 바이비트 티커(펀딩+OI 한번에) | 차단(403) | 96B | OKX도 막힐 때의 2차 대안 |
| **✗** | 바이비트 롱숏비 | 차단(403) | 96B | OKX도 막힐 때의 2차 대안 |

## 뉴스

| | 소스 | 결과 | 크기 | 없으면 |
|---|---|---|---|---|
| ✓ | 구글뉴스 RSS(한국어) | OK | 115,422B | 국장·코인 뉴스 수집의 주력 |
| ✓ | 연합뉴스 RSS | OK | 101,222B | 국내 경제 뉴스 |
| ✓ | 머니투데이 RSS | OK | 96,769B | 국내 증권 뉴스 |
| ✓ | 매일경제 RSS | OK | 37,411B | 국내 증권 뉴스 |
| ✓ | 조선비즈 RSS | OK | 753B | 국내 경제 뉴스 |
| ✓ | 블록미디어 RSS | OK | 20,152B | 국내 코인 뉴스 |
| ✓ | 코인데스크 RSS | OK | 30,014B | 해외 코인 뉴스 |
| ✓ | CNBC RSS | OK | 21,387B | 미국 시장 뉴스 |
| ✓ | 오일프라이스 RSS | OK | 15,902B | 에너지 뉴스 |

## 판정

9개 소스가 막혔습니다.

- **stooq 금현물 일봉 CSV** — 내용없음
  - 잃는 것: 금 현물 1순위 — 일별 종가 이력이 통째로 온다
  - 응답: `<!DOCTYPE html><html><head><meta charset="utf-8"><meta name="robots" content="noindex,nofollow"></head><body><noscript>This site requires JavaScript t`
- **exchangerate.host XAU 시계열** — 내용없음
  - 잃는 것: 금 현물 3순위 — 무료 키 필요 여부 확인용
  - 응답: `{   "success": false,   "error": {     "code": 101,     "type": "missing_access_key",     "info": "You have not supplied an API Access Key. [Required `
- **FRED 기대인플레(BEI)** — 연결실패(ReadTimeout)
  - 잃는 것: 매크로데스크 inflation 팩터 (bp)
- **FRED 실질금리(TIPS)** — 연결실패(ReadTimeout)
  - 잃는 것: 매크로데스크 realYield 팩터 (bp)
- **독일 국채 (야후 대체)** — HTTP 404
  - 잃는 것: ECB가 막힐 때의 2차 대안
  - 응답: `{"chart":{"result":null,"error":{"code":"Not Found","description":"No data found, symbol may be delisted"}}}`
- **바이낸스 선물 (미국 IP 차단 여부)** — 차단(451 법적사유)
  - 잃는 것: 펀딩비·미결제약정·롱숏비 전부 — 코인 패널의 핵심
  - 응답: `{   "code": 0,   "msg": "Service unavailable from a restricted location according to 'b. Eligibility' in https://www.binance.com/en/terms. Please cont`
- **바이낸스 롱숏비** — 차단(451 법적사유)
  - 잃는 것: 전체계좌·상위계좌 롱숏 분화
  - 응답: `{   "code": 0,   "msg": "Service unavailable from a restricted location according to 'b. Eligibility' in https://www.binance.com/en/terms. Please cont`
- **바이비트 티커(펀딩+OI 한번에)** — 차단(403)
  - 잃는 것: OKX도 막힐 때의 2차 대안
  - 응답: `{     error:The Amazon CloudFront distribution is configured to block access from your country }`
- **바이비트 롱숏비** — 차단(403)
  - 잃는 것: OKX도 막힐 때의 2차 대안
  - 응답: `{     error:The Amazon CloudFront distribution is configured to block access from your country }`
