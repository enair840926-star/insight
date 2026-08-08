# -*- coding: utf-8 -*-
"""장 시간 계산 — 인사이트를 '대비용'으로 만들기 위한 시간 맥락

인사이트가 회고형이면 쓸모가 없다. 이미 끝난 장을 복기해봐야
할 수 있는 게 없기 때문이다. 곧 열릴 장을 겨냥하려면 LLM이
"지금이 개장 몇 시간 전인가"를 알아야 한다.

한국 시간 기준으로 계산하며, 미국 서머타임은 zoneinfo가 처리한다.
"""
import datetime as dt

try:
    from zoneinfo import ZoneInfo
    KST = ZoneInfo("Asia/Seoul")
    NY = ZoneInfo("America/New_York")
except Exception:                      # zoneinfo가 없으면 고정 오프셋
    KST = dt.timezone(dt.timedelta(hours=9))
    NY = None

# 한국 공휴일까지는 다루지 않는다. 주말만 거른다 —
# 휴장일에 실행해도 데이터는 직전 영업일 것이 그대로 오므로
# 인사이트가 틀리지는 않고, "다음 개장"만 하루 밀린다.
SESSIONS = {
    "kr": {"label": "국내 증시(코스피·코스닥)", "open": (9, 0), "close": (15, 30)},
    "us": {"label": "미국 증시", "ny_open": (9, 30), "ny_close": (16, 0)},
    "coin": {"label": "암호화폐", "always": True},
    "macro": {"label": "글로벌 매크로", "follows": ("kr", "us")},
}


def _now():
    return dt.datetime.now(KST)


def _next_weekday_at(now, hh, mm):
    """다음 평일 hh:mm (오늘이 이미 지났으면 다음 영업일)"""
    t = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
    if t <= now:
        t += dt.timedelta(days=1)
    while t.weekday() >= 5:            # 토(5)·일(6)
        t += dt.timedelta(days=1)
    return t


def _us_open_kst(now):
    """미국 정규장 개장을 한국 시간으로. 서머타임에 따라 22:30 또는 23:30."""
    if NY is None:
        return _next_weekday_at(now, 23, 30)
    for d in range(0, 6):
        ny_day = (now.astimezone(NY) + dt.timedelta(days=d)).date()
        if ny_day.weekday() >= 5:
            continue
        ny_open = dt.datetime.combine(ny_day, dt.time(9, 30), tzinfo=NY)
        kst_open = ny_open.astimezone(KST)
        if kst_open > now:
            return kst_open
    return _next_weekday_at(now, 23, 30)


def _kr_state(now):
    o = now.replace(hour=9, minute=0, second=0, microsecond=0)
    c = now.replace(hour=15, minute=30, second=0, microsecond=0)
    if now.weekday() < 5 and o <= now <= c:
        return "장중", c
    return "장마감", _next_weekday_at(now, 9, 0)


def _us_state(now):
    if NY is None:
        return "장마감", _next_weekday_at(now, 23, 30)
    ny = now.astimezone(NY)
    o = ny.replace(hour=9, minute=30, second=0, microsecond=0)
    c = ny.replace(hour=16, minute=0, second=0, microsecond=0)
    if ny.weekday() < 5 and o <= ny <= c:
        return "장중", c.astimezone(KST)
    return "장마감", _us_open_kst(now)


def session_open(market, now=None):
    """지금 장중이면 이번 세션이 열린 시각. 장중이 아니면 None.

    '개장 전 스냅샷을 받았는가'를 판정할 때 쓴다. 데이터가 이 시각보다
    오래됐으면 이번 장을 놓친 것이다. 단순히 '몇 시간 낡았나'로 재면
    하루 한 번 열리는 장에서 20시간 낡은 정상 상태와 구분이 안 된다.
    """
    now = now or _now()
    if market == "kr":
        state, _ = _kr_state(now)
        if state != "장중":
            return None
        return now.replace(hour=9, minute=0, second=0, microsecond=0)
    if market == "us":
        state, _ = _us_state(now)
        if state != "장중":
            return None
        if NY is None:
            return now.replace(hour=23, minute=30, second=0, microsecond=0)
        ny = now.astimezone(NY)
        return ny.replace(hour=9, minute=30, second=0,
                          microsecond=0).astimezone(KST)
    return None


def describe(market, now=None):
    """LLM 프롬프트에 넣을 시간 맥락.

    반환: {"now", "state", "next_open", "hours_until", "text"}
    """
    now = now or _now()
    spec = SESSIONS.get(market, {})

    if spec.get("always"):
        return {
            "now": now, "state": "24시간 거래", "next_open": None,
            "hours_until": None,
            "text": (f"현재 {now:%Y-%m-%d %H:%M} (한국시간). "
                     f"암호화폐는 24시간 거래되지만, 아시아 세션이 "
                     f"{'진행 중' if 8 <= now.hour < 17 else '아직'}이고 "
                     f"미국 세션은 한국시간 밤에 시작된다."),
        }

    if market == "macro":
        kr_state, _ = _kr_state(now)
        us_state, _ = _us_state(now)
        # _kr_state/_us_state는 장중이면 '마감 시각'을 돌려준다. 다음 개장을
        # 알고 싶은 것이므로 개장 시각을 따로 구한다 — 안 그러면 미국 장중에
        # "다음 개장 05:00"(사실은 마감)이라고 쓰게 된다.
        kr_open = _next_weekday_at(now, 9, 0)
        us_open = _us_open_kst(now)
        nearest = min(kr_open, us_open)
        which = "국내 증시" if nearest == kr_open else "미국 증시"
        hrs = (nearest - now).total_seconds() / 3600
        live = [m for m, s in (("국장", kr_state), ("미장", us_state))
                if s == "장중"]
        live_txt = (f"지금은 {'·'.join(live)}이 열려 있다. " if live else "")
        return {
            "now": now, "state": f"국장 {kr_state} / 미장 {us_state}",
            "next_open": nearest, "hours_until": hrs,
            "text": (f"현재 {now:%Y-%m-%d %H:%M} (한국시간). "
                     f"국내 증시는 {kr_state}, 미국 증시는 {us_state}. "
                     f"{live_txt}"
                     f"다음 개장은 {which}이며 약 {hrs:.1f}시간 뒤"
                     f"({nearest:%m-%d %H:%M})다. 매크로는 두 시장 모두의 "
                     f"배경이므로 양쪽 관점을 함께 다뤄라."),
        }

    state, nxt = (_kr_state(now) if market == "kr" else _us_state(now))
    label = spec.get("label", market)
    if state == "장중":
        hrs = (nxt - now).total_seconds() / 3600
        text = (f"현재 {now:%Y-%m-%d %H:%M} (한국시간). {label}는 **장중**이며 "
                f"약 {hrs:.1f}시간 뒤 마감된다. 남은 장에서 확인할 것을 중심으로 써라.")
    else:
        hrs = (nxt - now).total_seconds() / 3600
        text = (f"현재 {now:%Y-%m-%d %H:%M} (한국시간). {label}는 **마감** 상태이고, "
                f"다음 개장까지 약 {hrs:.1f}시간 남았다"
                f"(개장 {nxt:%m-%d %H:%M} 한국시간).")
    return {"now": now, "state": state, "next_open": nxt,
            "hours_until": hrs, "text": text}


# ---------------------------------------------------------------- 공통 요청문
def request_block(market, extra_sections=""):
    """4개 수집기가 공유하는 '대비형' 요청 블록.

    회고형("오늘 무슨 일이 있었나")이 아니라 대비형("곧 열릴 장에서
    무엇을 볼 것인가)으로 쓴다. 그래야 개장 전에 읽고 행동할 수 있다.
    """
    ctx = describe(market)
    return f"""
---
## 요청

{ctx['text']}

**이미 지나간 장을 복기하지 마라.** 무슨 일이 있었는지 나열하는 글은
쓸모가 없다. 위 데이터를 근거로 **다가올 장에서 무엇을 볼 것인지**를 써라.
과거 수치는 그 판단의 근거로만 인용하라.

### 1. 개장 전 브리핑
3~4문장. 직전 세션 이후 바뀐 것 중 이번 장에 영향을 줄 것만.
숫자 나열이 아니라 "그래서 이번 장은 어떤 상태에서 시작하는가"를 써라.

### 2. 오늘의 픽
**위 '오늘의 픽' 블록에 계산된 것을 그대로 쓴다.** 순서를 바꾸거나 다른
대상으로 갈아치우지 마라. 고르는 일은 이미 규칙이 했다 — 여기서 할 일은
그 결과를 사람 말로 옮기는 것이다. **각 픽은 `###` 제목으로 시작한다**
(화면이 이 제목을 맨 위 칩으로 끌어올린다).

### 1. [대상] — [상승 근거 / 하락 근거 / 피할 것]
- 왜 이것인가: 계산된 근거를 숫자와 함께 한두 문장
- 확인할 것: 이번 장에서 무엇을 보면 이 판단이 맞았는지 알 수 있는가
- 오늘 볼 선: 블록의 '오늘 볼 선'을 **그대로 옮겨라** (가격까지)
- (뒤에 깨지는 것이 있으면 한 줄로 덧붙이되, **한 장에 닿을 자리가
  아니라는 사실을 반드시 함께 적어라**)

지켜야 할 것:

- **'피할 것'을 상승 픽처럼 쓰지 마라.** 그건 오를 종목이 아니라 내릴
  근거가 두꺼운 종목이고, 상승 후보가 모자라 채운 자리다. 제목에서부터
  구분되게 쓰고 상승 픽과 섞어서 나열하지 마라.
- **반대 근거가 함께 있으면 양쪽을 다 적어라.** 블록의 근거 목록에는
  부호가 붙어 있다. 플러스만 옮기면 글이 데이터보다 세진다.
- **`※`로 붙은 경고를 빠뜨리지 마라.** 거래량이 한산하다·근거가 두어
  개뿐이다·곧 실적이 나온다 같은 것들이고, 그게 빠지면 얇은 근거가
  두꺼운 근거처럼 읽힌다.
- **점수는 상승 확률이 아니라 근거의 두께다.** "오를 확률이 높다"가 아니라
  "오를 근거가 이만큼 쌓였다"로 쓴다. 이 데이터는 설명치지 예측치가 아니다.
- **'오늘 볼 선'은 손절선이 아니다.** 그 값이 무너지면 이 픽을 세운
  근거 하나가 사라진다는 뜻이지, 팔라는 신호가 아니다. "159.40 아래로
  빠지면 평소 하루 변동폭을 벗어난 하락입니다"까지 쓰고, 그때 무엇을
  할지는 읽는 분 몫으로 남겨라. 손절가·목표가·비중은 쓰지 않는다.
- **이동평균선을 오늘 볼 선처럼 쓰지 마라.** 많이 올라온 종목은 20일선까지
  -20%가 남는데 그건 하루 변동폭의 서너 배라 한 장에 닿지 않는다. 블록이
  '한 장에는 멀다'로 표시해 두었으니 그 말을 빼먹지 마라. 이건 오늘의
  픽이고, 오늘 볼 선이 따로 있다.

블록에 3종이 아니라 그보다 적게 나왔으면 **그만큼만 쓰고 이유를 한 줄로
적어라.** 자리를 채우려고 없는 근거를 만들지 마라.

### 3. 오늘 주목할 것 (3~5개)
**이것이 이 글의 핵심이다.** 각 항목을 아래 형식으로 써라.

- **[대상]** — 왜 봐야 하는가 (데이터 근거 1~2개 숫자 인용)
  · 확인할 것: 이번 장에서 구체적으로 무엇을 보면 되는가
  · 갈림길: 어떻게 되면 어떻게 읽을 것인가

대상은 종목·자산·지표 무엇이든 되지만, **반드시 위 데이터에 있는 것**이어야
한다. 데이터에 없는 종목을 지어내지 마라. 선별 사유(급등/급락/거래대금상위/
관심종목 등)와 포지셔닝 지표를 우선 근거로 삼아라.

### 4. 시나리오
"A가 나오면 B로 읽는다" 형태로 2~3개. 조건은 이번 장에서 실제로 관찰
가능한 것이어야 한다(가격대·거래량·수급 방향 등).

### 5. 예정된 이벤트
실적 발표·경제지표 등 이번 장에 영향을 줄 일정. 데이터에 없으면 "데이터 없음".

### 6. 경계할 것
포지션 쏠림, 과열 구간, 관계가 깨진 지점 등 틀어질 수 있는 부분.
{extra_sections}
---

**작성 규칙**
- 각 주장에 위 데이터의 구체적 숫자를 인용하라.
- 데이터에 없는 내용은 추측하지 말고 "데이터 없음"이라고 명시하라.
- 규칙 기반 뉴스 판정은 단순 키워드 매칭이니 숫자와 배치되면 숫자를 따르라.
- **방향은 '오늘의 픽'에 계산된 것만 쓴다.** 그 블록에 없는 대상에
  방향을 붙이지 마라. 나머지 항목은 여전히 "무엇을 보라"까지가 범위다.
- **사라·팔라·비중을 쓰지 마라.** 진입가·목표가·손절가·비중도 쓰지 마라.
  방향 판정은 "이 데이터가 어느 쪽을 가리키는가"이지 매매 지시가 아니다.
  '상승 우세'는 써도 되고 '지금 사십시오'는 안 된다.
- 방향에는 반드시 **틀렸다고 볼 조건**을 함께 적어라. 조건 없는 방향은
  나중에 맞았는지 틀렸는지 아무도 못 재고, 그러면 다음 판정이 나아지지 않는다.
- 문체는 존댓말(~습니다)로 쓴다. 폰에서 읽으므로 문단은 짧게,
  숫자 대조는 표로 정리하라.

**용어 규칙 — 전문용어를 그대로 쓰지 마라**
폰에서 훑어보는 글이다. 용어를 떠올려야 읽히는 문장은 실패한 문장이다.
아래는 뜻으로 바꿔 쓴다. 굳이 용어를 남기려면 괄호에 넣어라.

| 쓰지 마라 | 이렇게 |
|---|---|
| 플래트닝 | 장단기 금리차 축소 |
| 스티프닝 | 장단기 금리차 확대 |
| 백워데이션 | 지금 물건이 나중보다 비쌈 (공급 빠듯) |
| 콘탱고 | 나중이 더 비쌈 (공급 여유) |
| 재고가 타이트 | 재고 부족 |
| 롱숏비 5.85 | 롱이 숏의 5.85배 |
| 미결제약정(OI) | 미결제약정(=열려 있는 포지션 총량) 첫 등장 때만 풀어 쓴다 |
| 52주위치 71 | 1년 범위에서 상단 (또는 고점권/저점권) |

**숫자를 쓸 때는 그 숫자가 좋은지 나쁜지도 함께 적어라.**
"ISM 55.6 (예상 54.0)"으로 끝내지 말고 "예상을 넘겨 경기가 강하다는
뜻이고, 그만큼 금리 인하 기대는 뒤로 밀립니다"까지 쓴다.
"""
