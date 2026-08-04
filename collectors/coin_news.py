# -*- coding: utf-8 -*-
"""코인 뉴스 — 심볼 + 정식명칭 + 주제 태깅

코인은 티커(BTC)로 안 쓰고 이름(Bitcoin/비트코인)으로 쓴다.
그래서 별칭 사전이 국장보다 더 중요하다.
"""
import re
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import quote

from core import rules
from collectors.kr_news import _from_feed, collect_rss, collect_google, filter_recent

# 코인별 뉴스. 미장은 야후 티커 RSS가 있는데 코인은 없어서 구글로 대신한다.
# CryptoPanic은 403이라 못 쓴다 (docs/data-sources.md 2-3장).
COIN_NEWS_URL = ("https://news.google.com/rss/search?q={q}"
                 "&hl=en-US&gl=US&ceid=US:en")


def collect_coin_news(selected, aliases, per_coin=5, max_workers=8):
    """선별된 코인마다 개별 검색. 티커가 아니라 정식 명칭으로 찾는다 —
    'ADA'로 검색하면 무관한 결과가 섞이지만 'Cardano'는 정확하다."""
    def job(c):
        sym = c["symbol"]
        names = aliases.get(sym) or []
        # 영문 정식명 우선 (구글뉴스 영문 검색이라)
        name = next((n for n in names if n.isascii()), None) or c.get("name") or sym
        q = quote(f"{name} crypto")
        items = _from_feed(f"구글:{sym}", COIN_NEWS_URL.format(q=q), None, "google")
        for it in items[:per_coin]:
            it["coins"] = [sym]
        return items[:per_coin]

    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        return [it for batch in ex.map(job, selected) for it in batch]


def tag(items, selected, aliases, topics):
    lookup = []
    for c in selected:
        sym = c["symbol"]
        names = list(aliases.get(sym) or [])
        if c.get("name"):
            names.append(c["name"].lower())
        lookup.append((sym, names))

    for it in items:
        text = f"{it['title']} {it.get('summary', '')}"
        low = text.lower()
        coins = set()
        for sym, names in lookup:
            if any(n and n in low for n in names):
                coins.add(sym)
                continue
            # 티커 직접 언급 — 3글자 이상만 (SOL/BTC는 되지만 짧은 건 오탐)
            if len(sym) >= 3 and re.search(rf"\b{re.escape(sym)}\b", text):
                coins.add(sym)

        hit_topics = sorted({label for kw, label in topics.items() if kw in low})

        score, hits = rules.score_text(text)
        it["score"] = score
        it["score_hits"] = hits[:8]
        it["label"] = rules.label(score)
        it["coins"] = sorted(coins)
        it["topics"] = hit_topics
        it["is_macro"] = rules.is_macro(text)
    return items


def priority(it):
    return (abs(it.get("score", 0)) * 2
            + it.get("dup_count", 1) * 1.5
            + rules.recency_bonus(it)
            + (4 if it.get("coins") else 0)
            + len(it.get("topics") or []) * 1.5)


def track(it):
    if it.get("coins"):
        return "coin"
    return "topic" if it.get("topics") else "other"


def select(items, selected_coins, limit=35, per_coin_cap=2):
    """코인 트랙은 라운드로빈으로 커버리지를 보장한다.
    BTC/ETH 기사가 물량이 압도적이라 그냥 두면 자리를 다 먹는다."""
    quotas = {"coin": 20, "topic": 10, "other": 5}
    tracks = {"coin": [], "topic": [], "other": []}
    for it in items:
        tracks[track(it)].append(it)

    syms = [c["symbol"] for c in selected_coins]
    picked, used, cov = rules.select_with_coverage(
        tracks["coin"], syms, "coins", quotas["coin"], per_coin_cap, priority)

    for name in ("topic", "other"):
        pool = [it for it in tracks[name] if id(it) not in used]
        for it in sorted(pool, key=priority, reverse=True)[:quotas[name]]:
            picked.append(it)
            used.add(id(it))
    if len(picked) < limit:
        rest = sorted((it for it in items if id(it) not in used),
                      key=priority, reverse=True)
        picked.extend(rest[:limit - len(picked)])

    order = {"coin": 0, "topic": 1, "other": 2}
    picked.sort(key=lambda it: (order[track(it)], -priority(it)))
    return picked[:limit], cov


def collect(feeds, queries, selected, aliases, topics,
            recent_days=3, limit=35):
    raw = collect_rss(feeds) + collect_google(queries)
    raw += collect_coin_news(selected, aliases)
    total = len(raw)
    recent, stale, undated = filter_recent(raw, recent_days)
    tag(recent, selected, aliases, topics)
    deduped, dropped = rules.dedupe(recent)
    picked, cov = select(deduped, selected, limit)

    stats = {
        "collected": total,
        "stale_removed": stale,
        "undated": undated,
        "duplicates_removed": dropped,
        "after_dedupe": len(deduped),
        "coin_tagged": sum(1 for it in deduped if it.get("coins")),
        "selected_for_llm": len(picked),
        "selected_coin": sum(1 for it in picked if it.get("coins")),
        "covered": sorted(cov["covered"]),
        "uncovered": sorted(cov["uncovered"]),
        "label_dist": rules.summarize_scores(deduped),
    }
    return picked, deduped, stats
