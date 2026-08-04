# -*- coding: utf-8 -*-
"""국장 전종목 스냅샷 — 미장 나스닥 스크리너의 국내 대응물

미장은 단일 호출로 7,113개가 나오는데 국장은 그런 게 없다.
네이버 시총순위 API가 100개씩 페이지네이션으로 주는 게 최선이고,
KOSPI 2,475 + KOSDAQ 1,820 = 4,295개를 44회 병렬 호출로 받는다.

응답에 `...Raw` 필드가 있어서 '240,000' 같은 문자열을 파싱할 필요가 없다.
"""
import re
from concurrent.futures import ThreadPoolExecutor

from core.http import fetch_json

LIST_URL = ("https://m.stock.naver.com/api/stocks/marketValue/{market}"
            "?page={page}&pageSize=100")
PAGE_SIZE = 100          # 500을 넣으면 400. 100이 상한이다.


# ---------------------------------------------------------------- 제외 규칙
# 미국은 워런트·CVR이 문제였는데 한국은 우선주·스팩·리츠가 그 자리다.
# 우선주는 본주와 중복이고, 스팩은 합병 전까지 가격이 정보를 담지 않는다.
_EXCLUDE_NAME = re.compile(
    r"(스팩|기업인수목적|\d+호)"          # SPAC
    r"|(\d*우[BC]?$)"                    # 우선주: 삼성전자우, 현대차2우B
    r"|(우선주)"
)


def is_excluded(symbol, name):
    """국장용 제외 규칙. screen.select(exclude_fn=)에 넘긴다."""
    n = (name or "").strip()
    if not n:
        return True
    if _EXCLUDE_NAME.search(n):
        return True
    # 보통주 종목코드는 끝자리가 0이다. 5/7/9는 우선주 계열.
    s = (symbol or "").strip()
    if len(s) == 6 and s.isdigit() and s[-1] in "5679":
        return True
    return False


# ---------------------------------------------------------------- 수집
def _page(args):
    market, page = args
    j = fetch_json(LIST_URL.format(market=market, page=page))
    if not isinstance(j, dict):
        return market, page, [], 0
    return market, page, j.get("stocks") or [], j.get("totalCount") or 0


def snapshot(markets=("KOSPI", "KOSDAQ"), max_workers=8, max_pages=None):
    """전종목 스냅샷. 반환: (나스닥 호환 행 리스트, 통계)

    screen.select가 미장 형식(symbol/name/marketCap/lastsale/volume/pctchange)을
    기대하므로 그 모양으로 변환해서 돌려준다. 그래야 선별 로직을 공유한다.
    """
    # 1페이지로 총 개수를 먼저 확인
    heads = {}
    with ThreadPoolExecutor(max_workers=len(markets)) as ex:
        for m, _p, stocks, total in ex.map(_page, [(m, 1) for m in markets]):
            heads[m] = (stocks, total)

    tasks = []
    for m, (_stocks, total) in heads.items():
        pages = (total + PAGE_SIZE - 1) // PAGE_SIZE
        if max_pages:
            pages = min(pages, max_pages)
        tasks += [(m, p) for p in range(2, pages + 1)]

    raw = []
    for m, (stocks, _t) in heads.items():
        raw += [(m, s) for s in stocks]
    if tasks:
        with ThreadPoolExecutor(max_workers=max_workers) as ex:
            for m, _p, stocks, _t in ex.map(_page, tasks):
                raw += [(m, s) for s in stocks]

    stats = {"markets": {m: t for m, (_s, t) in heads.items()},
             "fetched": len(raw), "non_stock": 0}

    rows = []
    for market, s in raw:
        # ETF/ETN/펀드는 개별 기업이 아니다
        if s.get("stockEndType") != "stock":
            stats["non_stock"] += 1
            continue
        rows.append({
            "symbol": s.get("itemCode"),
            "name": s.get("stockName"),
            # Raw 필드가 숫자로 온다 — 문자열 파싱 불필요
            "lastsale": s.get("closePriceRaw"),
            "pctchange": s.get("fluctuationsRatio"),
            "volume": s.get("accumulatedTradingVolumeRaw"),
            "marketCap": s.get("marketValueRaw"),
            "turnover_raw": s.get("accumulatedTradingValueRaw"),
            "sector": market,        # 네이버는 업종을 안 준다. 시장으로 대체.
            "industry": None,
            "country": "KR",
            "market": market,
        })
    stats["usable_rows"] = len(rows)
    return rows, stats


# ---------------------------------------------------------------- 업종·테마
GROUP_URL = "https://m.stock.naver.com/api/stocks/{kind}?page={page}&pageSize=20"


def _group_page(args):
    kind, page = args
    j = fetch_json(GROUP_URL.format(kind=kind, page=page))
    if not isinstance(j, dict):
        return [], 0
    return j.get("groups") or [], j.get("totalCount") or 0


def groups(kind="industry", pages=None, max_workers=6):
    """업종/테마별 등락률.

    미장은 섹터 집계를 직접 계산했는데 국장은 네이버가 해서 준다 —
    등락률뿐 아니라 상승/하락 종목 수까지 들어있다.
    kind: 'industry'(업종) | 'theme'(테마)
    """
    first, total = _group_page((kind, 1))
    n_pages = (total + 19) // 20
    if pages:
        n_pages = min(n_pages, pages)

    rows = list(first)
    if n_pages > 1:
        with ThreadPoolExecutor(max_workers=max_workers) as ex:
            for g, _t in ex.map(_group_page,
                                [(kind, p) for p in range(2, n_pages + 1)]):
                rows += g

    out = []
    for g in rows:
        rise = g.get("riseCount") or 0
        fall = g.get("fallCount") or 0
        steady = g.get("steadyCount") or 0
        n = rise + fall + steady
        try:
            rate = float(g.get("changeRate"))
        except (TypeError, ValueError):
            continue
        out.append({
            "code": g.get("no"),
            "name": g.get("name"),
            "change_pct": rate,
            "count": g.get("totalCount") or n,
            "rise": rise, "fall": fall, "steady": steady,
            "up_ratio": round(rise / n * 100, 1) if n else None,
        })
    out.sort(key=lambda x: -x["change_pct"])
    return out


def industry_map(groups_rows):
    """industryCode -> 업종명.

    타입이 엇갈린다: 업종 목록의 `no`는 int인데 종목 integration의
    `industryCode`는 str이다 (실측: 288 vs '278'). 양쪽 키를 다 넣는다.
    """
    m = {}
    for g in groups_rows:
        code, name = g.get("code"), g.get("name")
        if code is None or not name:
            continue
        m[code] = name
        m[str(code)] = name
    return m


# ---------------------------------------------------------------- 거래대금 보정
def fix_turnover(selected, rows):
    """screen.select는 turnover를 volume×price로 계산하는데,
    네이버는 실제 거래대금을 직접 준다. 정확한 값으로 덮어쓴다."""
    by_symbol = {r["symbol"]: r for r in rows}
    for c in selected:
        src = by_symbol.get(c["symbol"])
        if src and src.get("turnover_raw"):
            c["turnover"] = float(src["turnover_raw"])
            c["market"] = src.get("market")
    return selected
