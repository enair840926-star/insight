# -*- coding: utf-8 -*-
"""미장 뉴스 — 종목별 야후 RSS + 일반 매체 + 구글

국장과 다른 점: 티커라는 확실한 식별자가 있다. 야후 종목별 RSS는
티커만 갈아끼우면 되므로 태깅이 애초에 정확하다.
"""
import re
from concurrent.futures import ThreadPoolExecutor

from core import rules
from collectors.kr_news import _from_feed, collect_rss, collect_google, filter_recent

# 회사명에서 법인격 접미사를 떼고 핵심어만 남긴다
_SUFFIX = re.compile(
    r"\b(inc|corp|corporation|company|co|ltd|limited|plc|holdings?|group|"
    r"technologies|technology|systems|international|n\.v|s\.a)\b\.?", re.I)


def core_name(name):
    """'NVIDIA Corporation' -> 'nvidia', 'Meta Platforms' -> 'meta platforms'"""
    t = _SUFFIX.sub("", name or "")
    t = re.sub(r"[^\w\s&]", " ", t)
    t = re.sub(r"\s+", " ", t).strip().lower()
    return t


def collect_ticker_news(selected, url_tpl, per_stock=6, max_workers=8):
    """선별된 종목의 야후 RSS. 태그가 확실하다는 게 장점."""
    def job(rec):
        items = _from_feed(f"Yahoo:{rec['symbol']}",
                           url_tpl.format(ticker=rec["symbol"]),
                           None, "yahoo_ticker")
        for it in items[:per_stock]:
            it["tickers"] = [rec["symbol"]]
            it["sectors"] = [rec["sector"]] if rec.get("sector") else []
        return items[:per_stock]

    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        return [it for batch in ex.map(job, selected) for it in batch]


def tag(items, selected, sector_keywords):
    """일반 뉴스에 티커·섹터를 붙인다.

    티커 문자열 매칭은 오탐이 심하다("A", "IT", "ON" 같은 티커가 실재한다).
    그래서 3글자 이상 티커만 단어 경계로 찾고, 회사명 매칭을 우선한다.
    """
    lookup = []
    for r in selected:
        sym = r["symbol"]
        cn = core_name(r.get("name"))
        lookup.append((sym, cn, r.get("sector")))

    for it in items:
        text = f"{it['title']} {it.get('summary', '')}"
        low = text.lower()
        tickers, sectors = set(it.get("tickers") or []), set(it.get("sectors") or [])

        for sym, cn, sec in lookup:
            hit = False
            if cn and len(cn) >= 4 and cn in low:
                hit = True
            elif len(sym) >= 3 and re.search(rf"\b{re.escape(sym)}\b", text):
                hit = True
            if hit:
                tickers.add(sym)
                if sec:
                    sectors.add(sec)

        # 섹터 키워드 (종목 언급이 없을 때만 — 안 그러면 다 걸린다)
        if not tickers:
            for kw, sec in sector_keywords.items():
                if kw in low:
                    sectors.add(sec)

        score, hits = rules.score_text(text)
        it["score"] = score
        it["score_hits"] = hits[:8]
        it["label"] = rules.label(score)
        it["tickers"] = sorted(tickers)
        it["sectors"] = sorted(s for s in sectors if s)
        it["is_macro"] = rules.is_macro(text)
    return items


def priority(it):
    return (abs(it.get("score", 0)) * 2
            + it.get("dup_count", 1) * 1.5
            + rules.recency_bonus(it)
            + (4 if it.get("tickers") else 0)
            + (1 if it.get("sectors") else 0))


def _track(it):
    if it.get("tickers"):
        return "ticker"
    return "sector" if it.get("sectors") else "other"


def select(items, selected_stocks, limit=40, quotas=None, per_ticker_cap=2):
    """티커 커버리지를 먼저 보장하고 남은 자리를 점수순으로 채운다.

    순수 점수 정렬이면 매그니피센트7 기사가 티커 자리를 다 먹는다.
    실측: FERG의 'S&P500 편입', AZN의 '4천억달러 합병설'이 전부 잘렸었다.
    """
    quotas = dict(quotas or {"ticker": 24, "sector": 10, "other": 6})
    tickers = [s["symbol"] for s in selected_stocks]

    # 1) 티커별 라운드로빈
    picked, used, cov = rules.select_with_coverage(
        items, tickers, "tickers", quotas["ticker"], per_ticker_cap, priority)

    # 2) 섹터·기타 트랙
    for name in ("sector", "other"):
        pool = [it for it in items
                if _track(it) == name and id(it) not in used]
        for it in sorted(pool, key=priority, reverse=True)[:quotas[name]]:
            picked.append(it)
            used.add(id(it))

    # 3) 남은 자리
    if len(picked) < limit:
        rest = sorted((it for it in items if id(it) not in used),
                      key=priority, reverse=True)
        picked.extend(rest[:limit - len(picked)])

    order = {"ticker": 0, "sector": 1, "other": 2}
    picked.sort(key=lambda it: (order[_track(it)], -priority(it)))
    return picked[:limit], cov


def collect(feeds, queries, selected, ticker_rss, sector_keywords,
            per_stock=6, recent_days=3, limit=40):
    raw = collect_rss(feeds)
    raw += collect_google(queries)
    raw += collect_ticker_news(selected, ticker_rss, per_stock)

    total = len(raw)
    recent, stale, undated = filter_recent(raw, recent_days)
    tag(recent, selected, sector_keywords)
    deduped, dropped = rules.dedupe(recent)
    picked, cov = select(deduped, selected, limit)

    stats = {
        "collected": total,
        "stale_removed": stale,
        "undated": undated,
        "duplicates_removed": dropped,
        "after_dedupe": len(deduped),
        "ticker_tagged": sum(1 for it in deduped if it.get("tickers")),
        "selected_for_llm": len(picked),
        "selected_ticker": sum(1 for it in picked if it.get("tickers")),
        # 선별 종목 중 뉴스 근거를 못 찾은 것 — LLM에 명시해야 한다
        "covered": sorted(cov["covered"]),
        "uncovered": sorted(cov["uncovered"]),
        "label_dist": rules.summarize_scores(deduped),
    }
    return picked, deduped, stats
