# -*- coding: utf-8 -*-
"""국장 뉴스 수집 — RSS + 구글뉴스 + 네이버 종목뉴스

수집 후 규칙 기반 스코어링/태깅/중복제거까지 여기서 끝낸다.
LLM에는 선별된 것만 넘어간다.
"""
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import quote

import feedparser

import datetime as dt

from core.http import fetch_bytes, fetch_json
from core.parse import clean_text, parse_naver_datetime, struct_to_date, date_only
from core import rules

GOOGLE_NEWS = ("https://news.google.com/rss/search?q={q}"
               "&hl=ko&gl=KR&ceid=KR:ko")


def _from_feed(name, url, encoding=None, source_type="rss"):
    raw = fetch_bytes(url)
    if not raw:
        return []
    if encoding:
        try:
            raw = raw.decode(encoding).encode("utf-8")
        except (UnicodeDecodeError, LookupError):
            pass
    try:
        parsed = feedparser.parse(raw)
    except Exception:
        return []

    out = []
    for e in parsed.entries:
        title = clean_text(e.get("title"))
        if not title:
            continue
        # 구글뉴스 description은 관련기사 링크 덩어리라 요약으로 못 쓴다.
        summary = "" if source_type == "google" else clean_text(e.get("summary", ""))[:400]
        out.append({
            "source": name,
            "source_type": source_type,
            "title": title,
            "summary": summary,
            "link": e.get("link", ""),
            # RSS의 published 문자열은 포맷이 제각각이라 feedparser가
            # 정규화한 struct_time을 쓴다.
            "published": struct_to_date(e.get("published_parsed")) or clean_text(e.get("published", "")),
        })
    return out


def collect_rss(feeds, max_workers=6):
    def job(f):
        name, url, enc = f
        return _from_feed(name, url, enc)
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        return [it for batch in ex.map(job, feeds) for it in batch]


def collect_google(queries, max_workers=4):
    def job(q):
        return _from_feed(f"구글뉴스:{q}", GOOGLE_NEWS.format(q=quote(q)),
                          None, "google")
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        return [it for batch in ex.map(job, queries) for it in batch]


def collect_stock_news(watchlist, per_stock=10, max_workers=6):
    """네이버 종목별 뉴스 — 종목 태그가 확실하다는 게 장점."""
    def job(item):
        code, name = item
        j = fetch_json("https://m.stock.naver.com/api/news/stock/"
                       f"{code}?pageSize={per_stock}&page=1")
        if not isinstance(j, list):
            return []
        out = []
        for group in j:
            for n in (group.get("items") or []):
                title = clean_text(n.get("titleFull") or n.get("title"))
                if not title:
                    continue
                out.append({
                    "source": f"네이버:{n.get('officeName', '')}",
                    "source_type": "naver_stock",
                    "title": title,
                    "summary": clean_text(n.get("body"))[:400],
                    "link": n.get("mobileNewsUrl", ""),
                    "published": parse_naver_datetime(n.get("datetime")),
                    # 종목 페이지에서 온 기사라 태그가 확실하다
                    "assets": [(code, name, "직접")],
                })
        return out
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        return [it for batch in ex.map(job, watchlist) for it in batch]


def enrich(items, watchlist, aliases=None, exclude=None, sectors=None):
    """규칙 기반 스코어링 + 종목 태깅 + 매크로 판정"""
    for it in items:
        text = f"{it['title']} {it.get('summary', '')}"
        score, hits = rules.score_text(text)
        it["score"] = score
        it["score_hits"] = hits[:8]
        it["label"] = rules.label(score)
        if not it.get("assets"):
            it["assets"] = rules.tag_assets(text, watchlist, aliases,
                                            exclude, sectors)
        it["is_macro"] = rules.is_macro(text)
    return items


def filter_recent(items, days=3):
    """오래된 기사를 걸러낸다.

    RSS 피드에는 몇 주 전 기사가 섞여 들어온다. 이걸 그대로 LLM에
    넘기면 지난달 폭등 기사와 오늘 급락 기사가 뒤섞여 시점을 오판한다.
    날짜를 못 읽은 건은 버리지 않고 남긴다(파싱 실패로 유실되면 안 됨).
    """
    cutoff = (dt.date.today() - dt.timedelta(days=days)).isoformat()
    kept, old, undated = [], 0, 0
    for it in items:
        d = date_only(it.get("published"))
        if not d or len(d) != 10 or d[4] != "-":
            undated += 1
            it["date_unknown"] = True
            kept.append(it)
            continue
        if d < cutoff:
            old += 1
            continue
        kept.append(it)
    return kept, old, undated


def collect(cfg_feeds, cfg_queries, watchlist, per_stock=10, recent_days=3,
            aliases=None, exclude=None, sectors=None, quotas=None):
    """전체 뉴스 파이프라인. 반환: (선별된 뉴스, 전체, 통계)"""
    raw = []
    raw += collect_rss(cfg_feeds)
    raw += collect_google(cfg_queries)
    raw += collect_stock_news(watchlist, per_stock)

    total = len(raw)
    recent, old_dropped, undated = filter_recent(raw, recent_days)
    enrich(recent, watchlist, aliases, exclude, sectors)
    deduped, dropped = rules.dedupe(recent)

    limit = sum((quotas or {"watchlist": 22, "macro": 12, "other": 6}).values())
    codes = [c for c, _n in watchlist]
    selected, cov = rules.select_for_llm(deduped, limit=limit, quotas=quotas,
                                         codes=codes)

    tagged = sum(1 for it in deduped if rules.is_direct(it))
    name_of = dict(watchlist)
    stats = {
        "covered": sorted(name_of.get(c, c) for c in cov["covered"]),
        "uncovered": sorted(name_of.get(c, c) for c in cov["uncovered"]),
        "collected": total,
        "stale_removed": old_dropped,
        "undated": undated,
        "after_dedupe": len(deduped),
        "duplicates_removed": dropped,
        "watchlist_tagged": tagged,
        "selected_for_llm": len(selected),
        "selected_watchlist": sum(1 for it in selected if rules.is_direct(it)),
        "label_dist": rules.summarize_scores(deduped),
    }
    return selected, deduped, stats
