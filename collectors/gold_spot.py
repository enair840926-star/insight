# -*- coding: utf-8 -*-
"""금 현물 시세 — 화면·피드의 참고값

## 왜 있나

`config.MACRO_SYMBOLS["금"]`은 `GC=F`(COMEX 선물)이다. 실측에서 계약월이
`Gold Dec 26`이었고, 사용자가 실제로 거래하는 것은 FOREX.com의 **현물
XAUUSD**다. 둘은 같은 금이지만 값이 다르다 — 제보 실측(2026-08-10~14)에서
격차가 30.6~73.2포인트로 흔들렸고 하루는 일간 방향까지 반대였다.

## 왜 선물을 그대로 두나

**현물로 갈아탈 수 있는 소스가 없다.** 러너에서 다 재 봤다(2026-08-24):

    야후 XAUUSD=X          HTTP 404  "symbol may be delisted"
    야후 XAU=X             HTTP 404
    stooq 일봉 CSV          자바스크립트 요구 페이지 (봇 차단)
    exchangerate.host      API 키 필요
    LBMA 오후 고시           OK — 다만 하루 한 번 고시라 저녁 수집(12:15 UTC)
                              시점에는 그날 값이 아직 없다
    gold-api               OK — 현재가만, 이력이 없다

픽은 20일선·20일 변동성·5일/20일 추세를 **종가 시계열**에서 뽑는다.
현재가만 주는 소스로는 그 자리를 못 채우고, LBMA로 바꾸면 저녁 스냅샷의
'당일 등락'이 하루 묵은 값이 된다 — 지금보다 나빠진다.

그래서 **픽 계열은 선물 그대로 두고, 현물은 참고값으로 따로 낸다.**

## 어떻게 읽나

같은 스냅샷 안에서 선물과 나란히 놓고 **격차만** 본다. 어제 격차와
오늘 격차를 비교하지 마라 — 만기가 가까워지면 줄고 롤오버 때 튄다.
"""
from core.http import fetch_json

URL = "https://api.gold-api.com/price/XAU"

LABEL = "금 현물"


def get():
    """반환: {"name", "price", "source", "asof"} 또는 None.

    실패하면 None이다. 참고값이므로 없다고 수집이 실패한 것은 아니다 —
    부르는 쪽이 그냥 안 싣는다.
    """
    j = fetch_json(URL, timeout=20)
    if not isinstance(j, dict):
        return None
    price = j.get("price")
    try:
        price = float(price)
    except (TypeError, ValueError):
        return None
    if price <= 0:
        return None
    return {
        "name": LABEL,
        "price": round(price, 2),
        "source": "gold-api.com XAU",
        "asof": j.get("updatedAt") or j.get("updated_at"),
    }
