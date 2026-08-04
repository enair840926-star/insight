# -*- coding: utf-8 -*-
"""매크로 뉴스 — 종목이 아니라 '주제'로 태깅한다

국장 뉴스는 "삼성전자"로 태깅하면 되지만 매크로는 그런 고유명사가 없다.
"OPEC 감산" 기사는 에너지 그룹에, "Fed 금리" 기사는 채권금리·환율·지수선물
셋 모두에 걸린다. 그래서 주제→그룹 다대다 매핑을 쓴다.
"""
from core import rules
from collectors.kr_news import collect_rss, collect_google, filter_recent


def tag_topics(text, topics):
    """반환: (매칭된 주제 리스트, 영향받는 그룹 집합)"""
    if not text:
        return [], set()
    low = text.lower()
    hit_topics, groups = [], set()
    for kw, gs in topics.items():
        # 영문 키워드는 대소문자 무시, 한글은 그대로
        found = kw.lower() in low if kw.isascii() else kw in text
        if found:
            hit_topics.append(kw)
            groups.update(gs)
    return hit_topics, groups


def enrich(items, topics):
    for it in items:
        text = f"{it['title']} {it.get('summary', '')}"
        score, hits = rules.score_text(text)
        it["score"] = score
        it["score_hits"] = hits[:8]
        it["label"] = rules.label(score)
        t, g = tag_topics(text, topics)
        it["topics"] = t[:6]
        it["groups"] = sorted(g)
        it["is_macro"] = True          # 정의상 전부 매크로다
    return items


def select(items, limit=30):
    """주제가 붙은 기사를 우선하되, 그룹별로 최소 한 건은 남긴다.
    에너지 뉴스가 많다고 농산물 뉴스가 통째로 잘리면 안 된다."""
    def priority(it):
        return (abs(it.get("score", 0)) * 2
                + it.get("dup_count", 1) * 1.5
                + len(it.get("groups") or []) * 2)

    ranked = sorted(items, key=priority, reverse=True)
    selected, used = [], set()

    # 1차: 그룹별 대표 1건씩 확보
    seen_groups = set()
    for it in ranked:
        for g in (it.get("groups") or []):
            if g not in seen_groups:
                seen_groups.add(g)
                if id(it) not in used:
                    selected.append(it)
                    used.add(id(it))
                break

    # 2차: 남은 자리를 점수순으로
    for it in ranked:
        if len(selected) >= limit:
            break
        if id(it) not in used:
            selected.append(it)
            used.add(id(it))

    selected.sort(key=priority, reverse=True)
    return selected[:limit]


def collect(feeds, queries, topics, recent_days=3, limit=30):
    raw = collect_rss(feeds)
    raw += collect_google(queries)

    total = len(raw)
    recent, stale, undated = filter_recent(raw, recent_days)
    enrich(recent, topics)
    deduped, dropped = rules.dedupe(recent)
    selected = select(deduped, limit)

    stats = {
        "collected": total,
        "stale_removed": stale,
        "undated": undated,
        "duplicates_removed": dropped,
        "after_dedupe": len(deduped),
        "selected_for_llm": len(selected),
        "topic_tagged": sum(1 for it in deduped if it.get("topics")),
        "label_dist": rules.summarize_scores(deduped),
    }
    return selected, deduped, stats
