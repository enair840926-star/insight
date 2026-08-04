# -*- coding: utf-8 -*-
"""EIA 주간 재고 — 원자재 3대 축의 마지막 하나

  COT     → 누가 어느 쪽에 걸었나 (포지션)
  선물커브 → 현물이 급한가 (기대)
  재고    → 실제로 물건이 있는가 (사실)      ← 이 모듈

재고는 계절성이 강해서 절대값만 보면 아무 의미가 없다.
겨울에 천연가스가 줄고 여름에 휘발유가 주는 건 정상이다.
그래서 **평년(5년 평균) 대비**와 **전년 동기 대비**를 같이 계산한다.

매주 수요일 발표되는 EIA 원유 재고는 유가를 움직이는 단일 최대 변수다.
"""
from concurrent.futures import ThreadPoolExecutor

from core.http import fetch_json

BASE = "https://api.eia.gov/v2"
WEEKS_5Y = 270          # 5년치 주간 데이터 + 여유


def _series(args):
    label, route, series_id, key, unit_hint = args
    url = (f"{BASE}/{route}/data/?api_key={key}&frequency=weekly"
           f"&data[0]=value&facets[series][]={series_id}"
           f"&sort[0][column]=period&sort[0][direction]=desc&length={WEEKS_5Y}")
    j = fetch_json(url, timeout=40)
    try:
        rows = j["response"]["data"]
    except (TypeError, KeyError):
        return label, None
    pts = []
    for r in rows:
        try:
            pts.append((r["period"], float(r["value"])))
        except (TypeError, ValueError, KeyError):
            continue
    if not pts:
        return label, None

    cur_period, cur = pts[0]
    rec = {
        "series": series_id,
        "period": cur_period,
        "value": cur,
        "unit": rows[0].get("units") or unit_hint,
    }

    if len(pts) >= 2:
        rec["change_1w"] = round(cur - pts[1][1], 1)
    if len(pts) >= 5:
        rec["change_4w"] = round(cur - pts[4][1], 1)

    # 전년 동주 (52주 전)
    if len(pts) >= 53:
        yoy = pts[52][1]
        rec["year_ago"] = yoy
        if yoy:
            rec["vs_year_ago_pct"] = round((cur / yoy - 1) * 100, 1)

    # 5년 평균: 52주 간격으로 같은 주차를 뽑는다
    same_week = [pts[i][1] for i in (52, 104, 156, 208, 260) if i < len(pts)]
    if len(same_week) >= 3:
        avg = sum(same_week) / len(same_week)
        rec["avg_5y"] = round(avg, 1)
        if avg:
            rec["vs_5y_avg_pct"] = round((cur / avg - 1) * 100, 1)
    return label, rec


def collect(series_spec, api_key, max_workers=6):
    """series_spec: {라벨: (route, series_id, 단위힌트)}"""
    if not api_key:
        return {}
    tasks = [(label, route, sid, api_key, unit)
             for label, (route, sid, unit) in series_spec.items()]
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        return {k: v for k, v in ex.map(_series, tasks) if v}


# ---------------------------------------------------------------- 해석 보조
def readings(inventories, tight_pct=-5.0, loose_pct=5.0):
    """평년 대비 재고 수준을 타이트/과잉으로 분류한다.

    -5% 이하면 타이트(공급 부족), +5% 이상이면 과잉으로 본다.
    선물 커브가 백워데이션인데 재고까지 타이트하면 진짜 수급 문제이고,
    커브만 백워데이션인데 재고는 평년 수준이면 지정학 프리미엄이다.
    """
    out = []
    for label, d in inventories.items():
        v = d.get("vs_5y_avg_pct")
        if v is None:
            continue
        if v <= tight_pct:
            state = "타이트"
        elif v >= loose_pct:
            state = "과잉"
        else:
            state = "평년수준"
        out.append({
            "name": label,
            "state": state,
            "vs_5y_avg_pct": v,
            "vs_year_ago_pct": d.get("vs_year_ago_pct"),
            "change_1w": d.get("change_1w"),
            "period": d.get("period"),
        })
    out.sort(key=lambda x: x["vs_5y_avg_pct"])
    return out
