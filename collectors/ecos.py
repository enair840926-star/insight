# -*- coding: utf-8 -*-
"""한국은행 ECOS — 국내 거시지표

국장 수집기가 그동안 본 매크로는 전부 해외 것(미10년물·달러인덱스·VIX)이었다.
정작 코스피를 움직이는 국내 기준금리·물가·수출은 없었다.

주의 두 가지:
  1. ECOS는 **오름차순**으로 준다. 최신값은 rows[-1]이다.
  2. 물가·수출은 지수(2020=100)라 절대값이 의미 없다. 전년동월비를 계산해야 한다.
"""
import datetime as dt
from concurrent.futures import ThreadPoolExecutor

from core.http import fetch_json

BASE = "https://ecos.bok.or.kr/api/StatisticSearch"


def _fetch(args):
    label, code, cycle, item, key, months, is_index = args
    today = dt.date.today()
    start = f"{today.year - (months // 12) - 1}{today.month:02d}"
    end = f"{today:%Y%m}"

    url = f"{BASE}/{key}/json/kr/1/300/{code}/{cycle}/{start}/{end}/{item}"
    j = fetch_json(url, timeout=30)
    if not isinstance(j, dict) or "RESULT" in j:
        msg = (j or {}).get("RESULT", {}).get("MESSAGE", "조회 실패")
        return label, {"error": msg[:60]}

    rows = j.get("StatisticSearch", {}).get("row") or []
    pts = []
    for r in rows:
        try:
            pts.append((r.get("TIME"), float(r.get("DATA_VALUE"))))
        except (TypeError, ValueError):
            continue
    if not pts:
        return label, None

    # ECOS는 오름차순 — 최신이 마지막
    period, value = pts[-1]
    rec = {
        "period": period,
        "value": value,
        "unit": rows[-1].get("UNIT_NAME"),
        "item": rows[-1].get("ITEM_NAME1"),
    }
    if len(pts) >= 2:
        rec["change_1m"] = round(value - pts[-2][1], 3)
    if is_index and len(pts) >= 13:
        prev = pts[-13][1]
        if prev:
            rec["yoy_pct"] = round((value / prev - 1) * 100, 2)
            rec["year_ago_period"] = pts[-13][0]
    if len(pts) >= 7:
        rec["change_6m"] = round(value - pts[-7][1], 3)
    return label, rec


def collect(spec, api_key, months=24, max_workers=6):
    """spec: {라벨: (통계코드, 주기, 항목코드, 지수여부)}"""
    if not api_key:
        return {}
    tasks = [(label, code, cycle, item, api_key, months, is_idx)
             for label, (code, cycle, item, is_idx) in spec.items()]
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        return {k: v for k, v in ex.map(_fetch, tasks) if v}


def summarize(data):
    """LLM이 바로 읽을 수 있는 한 줄 요약들"""
    out = []
    for label, d in data.items():
        if not d or d.get("error"):
            continue
        unit = (d.get("unit") or "").strip()
        parts = [f"{d['value']:,.2f}" + (f" {unit}" if unit else "")]
        if d.get("yoy_pct") is not None:
            parts.append(f"전년동월비 {d['yoy_pct']:+.2f}%")
        if d.get("change_1m") is not None:
            parts.append(f"전월대비 {d['change_1m']:+,.2f}")
        if d.get("change_6m") is not None:
            parts.append(f"6개월 {d['change_6m']:+,.2f}")
        out.append({"name": label, "period": d["period"],
                    "text": ", ".join(parts)})
    return out
