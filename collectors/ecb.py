# -*- coding: utf-8 -*-
"""ECB 유로존 금리 — 미-유로존 금리차용

매크로 데스크의 rateDiff 팩터가 미 10년물과 독일(유로존 AAA) 10년물의
차이를 bp로 받는다. 그동안 "정확한 일간 bp 미확인으로 rateDiff는 이번
회차 보류"라고 적혀 있던 항목이다.

야후에는 독일 국채 심볼이 없다(^GDBR10·BUND.EX 모두 404). ECB의 공개
데이터 API는 키 없이 열리고 러너에서도 통과했다.

주의: 이 계열은 유로존 AAA 국채 수익률 곡선이라 독일 분트와 완전히
같지는 않다. 사실상 독일이 대부분을 차지하지만, 출처를 그대로 적어
받는 쪽이 무엇인지 알게 한다.
"""
import csv
import io

from core.http import fetch

# YC = 수익률 곡선, B.U2 = 유로존, SR_10Y = 10년 spot rate
URL = ("https://data-api.ecb.europa.eu/service/data/YC/"
       "B.U2.EUR.4F.G_N_A.SV_C_YM.SR_10Y"
       "?lastNObservations={n}&format=csvdata")

LABEL = "유로존 10년물(AAA)"


def get_10y(n=5):
    """반환: {"price", "prev_close", "period", "prev_period"} 또는 None"""
    txt = fetch(URL.format(n=max(2, n)), timeout=30)
    if not txt:
        return None
    try:
        rows = [r for r in csv.DictReader(io.StringIO(txt))
                if (r.get("OBS_VALUE") or "").strip()]
    except Exception:
        return None
    if len(rows) < 2:
        return None
    rows.sort(key=lambda r: r.get("TIME_PERIOD") or "")
    last, prev = rows[-1], rows[-2]
    try:
        return {
            "name": LABEL,
            "price": round(float(last["OBS_VALUE"]), 4),
            "prev_close": round(float(prev["OBS_VALUE"]), 4),
            "period": last.get("TIME_PERIOD"),
            "prev_period": prev.get("TIME_PERIOD"),
            "source": "ECB Data Portal YC B.U2.EUR SR_10Y",
        }
    except (TypeError, ValueError, KeyError):
        return None
