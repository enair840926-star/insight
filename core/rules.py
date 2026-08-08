# -*- coding: utf-8 -*-
"""1단 필터 — 규칙 기반 뉴스 스코어링 및 중복 제거

목적은 정확한 감성 판정이 아니라 **LLM에 보낼 것을 골라내는 것**이다.
일 500~2000건에서 90%를 여기서 걸러야 Claude API 비용이 통제된다.
애매한 건 버리지 말고 score=0으로 두고 넘긴다 (판단은 2단에서).
"""
import re
import datetime as dt
from collections import Counter

# 가중치가 큰 것 = 방향이 명확하고 주가 영향이 즉각적인 표현
POSITIVE = {
    # 강한 신호
    "어닝서프라이즈": 3, "사상 최대": 3, "사상최대": 3, "신고가": 3, "상한가": 3,
    "흑자전환": 3, "최대 실적": 3, "역대 최대": 3, "어닝 서프라이즈": 3,
    # 중간
    "호실적": 2, "실적 호조": 2, "목표주가 상향": 2, "수주": 2, "계약 체결": 2,
    "공급 계약": 2, "순매수": 2, "급등": 2, "매수 우위": 2, "상향 조정": 2,
    "수혜": 2, "돌파": 2, "턴어라운드": 2, "자사주 매입": 2, "배당 확대": 2,
    # 약한
    "상승": 1, "강세": 1, "반등": 1, "개선": 1, "성장": 1, "확대": 1,
    "호조": 1, "기대": 1, "증가": 1, "회복": 1, "낙관": 1, "선방": 1,
}

NEGATIVE = {
    # 강한 신호
    "어닝쇼크": -3, "어닝 쇼크": -3, "적자전환": -3, "하한가": -3, "신저가": -3,
    "상장폐지": -3, "횡령": -3, "배임": -3, "회계부정": -3, "거래정지": -3,
    "압수수색": -3, "파산": -3, "디폴트": -3,
    # 중간
    "폭락": -2, "급락": -2, "실적 부진": -2, "목표주가 하향": -2, "순매도": -2,
    "적자": -2, "손실": -2, "제재": -2, "소송": -2, "리콜": -2, "감산": -2,
    "구조조정": -2, "하향 조정": -2, "매도 우위": -2, "유상증자": -2,
    "공매도": -2, "철수": -2, "조사 착수": -2,
    # 약한
    "하락": -1, "약세": -1, "부진": -1, "우려": -1, "감소": -1, "축소": -1,
    "리스크": -1, "위험": -1, "규제": -1, "둔화": -1, "경고": -1, "불확실": -1,
}

# 이 단어가 있으면 시장 전체에 영향 — 개별 종목 태그가 없어도 살린다
MACRO_KEYWORDS = [
    "금리", "연준", "FOMC", "CPI", "물가", "환율", "관세", "무역",
    "한국은행", "기준금리", "국채", "경기침체", "고용지표", "GDP",
]


def score_text(text):
    """반환: (점수, 매칭된 근거 리스트)

    점수는 -N~+N 범위이며 정규화하지 않는다.
    상대 비교와 정렬에만 쓰기 때문에 절대값에 의미를 두지 않는다.
    """
    if not text:
        return 0, []
    score = 0
    hits = []
    for word, w in POSITIVE.items():
        if word in text:
            score += w
            hits.append(f"+{word}")
    for word, w in NEGATIVE.items():
        if word in text:
            score += w
            hits.append(f"-{word}")
    return score, hits


# ---------------------------------------------------------------- 공시
# **공시 제목에 위 뉴스 어휘를 쓰면 안 된다.** 실측(고유 제목 133개)에서
# 점수가 붙은 21개 중 절반이 오탐이었다.
#
#   '주식선물ㆍ옵션 가격제한폭 확대요건 도달(상승)'  → +2  파생 절차 안내다
#   '투자위험종목 지정해제'                        → -1  해제는 호재인데 뒤집혔다
#   '주권매매거래정지(무상증자)'                    → -3  절차적 정지다
#
# 정작 '단일판매ㆍ공급계약 해지'는 0점이었다 — 뉴스 어휘의 '계약 체결'·
# '공급 계약'에는 공백이 있는데 공시 제목에는 없기 때문이다.
#
# 공시 제목은 정형화돼 있어 오히려 좁은 규칙이 잘 맞는다. 애매한 것은
# 점수를 주지 말고 0으로 둔다 — 틀린 방향보다 없는 편이 낫다.

# 이 말이 들어가면 통째로 중립. 방향 판정보다 먼저 본다.
DISCLOSURE_SKIP = (
    "가격제한폭",      # 파생상품 가격제한폭 확대 안내
    "해제",            # 지정'해제'는 호재인데 '지정'으로 읽히면 부호가 뒤집힌다
    "무상증자",        # 권리락으로 가격이 조정된다. 방향이 아니다
    "IR 개최", "안내공시", "예고", "기업설명회",
    "추가상장",        # DR·스톡옵션 행사 등 절차
)

DISCLOSURE_WEIGHTS = {
    # 악재 — 확정 사실이라 뉴스보다 무겁다
    "상장폐지": -3, "횡령": -3, "배임": -3, "회생절차": -3, "관리종목": -3,
    "감자결정": -3, "부도": -3,
    # '지정'만 잡으면 '연장'을 놓친다. 해제는 위 SKIP이 막는다.
    "유상증자결정": -2, "공매도 과열종목": -2, "계약 해지": -2,
    "소송": -2, "가처분": -2, "불성실공시": -2, "조회공시 요구": -1,
    # 호재
    "자기주식소각": 3, "자기주식 소각": 3,
    "자기주식취득": 2, "자기주식 취득": 2,
    "공급계약체결": 2, "계약 체결": 2, "수주": 2,
    "배당 결정": 1, "배당결정": 1,
}


def score_disclosure(title):
    """공시 제목 → (점수, 근거). 뉴스 어휘를 쓰지 않는다.

    **가장 센 것 하나만 센다.** 공시 하나는 한 사건이라 더하면 같은 사실이
    두 번 세진다 — '자기주식취득 신탁계약 체결'이 자기주식취득(+2)과
    계약 체결(+2)에 걸려 +4가 나왔다.
    """
    if not title:
        return 0, []
    if any(s in title for s in DISCLOSURE_SKIP):
        return 0, []
    hits = [(w, word) for word, w in DISCLOSURE_WEIGHTS.items() if word in title]
    if not hits:
        return 0, []
    w, word = max(hits, key=lambda h: abs(h[0]))
    return w, [f"{'+' if w > 0 else ''}{word}"]


def label(score):
    if score >= 3:
        return "긍정"
    if score <= -3:
        return "부정"
    if score >= 1:
        return "약긍정"
    if score <= -1:
        return "약부정"
    return "중립"


def tag_assets(text, watchlist, aliases=None, exclude=None, sectors=None):
    """본문에서 관심종목 언급을 찾는다. 반환: [(코드, 이름, 근거), ...]

    3단계로 찾는다:
      1) 정식 명칭
      2) 약칭 ("삼전", "하이닉스") — 단 계열사 오탐은 제외
      3) 섹터 키워드 ("HBM", "양극재") — 직접 언급이 없을 때만
    """
    if not text:
        return []
    aliases = aliases or {}
    exclude = exclude or {}
    sectors = sectors or {}

    found = {}
    for code, name in watchlist:
        names = aliases.get(code) or [name]
        # 긴 이름부터 본다. "SK하이닉스"가 "하이닉스"보다 우선.
        for alias in sorted(names, key=len, reverse=True):
            if alias not in text:
                continue
            # 계열사 오탐 방지: 제외어에 걸린 부분을 지우고 다시 확인
            probe = text
            for bad in exclude.get(code, []):
                probe = probe.replace(bad, "")
            if alias in probe:
                found[code] = (code, name, "직접")
            break

    # 직접 언급이 하나도 없을 때만 섹터로 연결한다.
    # 그러지 않으면 "삼성전자, 반도체 호조" 같은 기사가 하이닉스까지 끌고 온다.
    if not found:
        for kw, codes in sectors.items():
            if kw not in text:
                continue
            for code in codes:
                nm = next((n for c, n in watchlist if c == code), None)
                if nm and code not in found:
                    found[code] = (code, nm, f"섹터:{kw}")

    return list(found.values())


def is_macro(text):
    return any(k in (text or "") for k in MACRO_KEYWORDS)


# ---------------------------------------------------------------- 중복 제거
_STOP = re.compile(r"[^\w가-힣]+")


def _norm(title):
    """제목 정규화 — 매체명 접미사, 기호, 공백 제거"""
    t = re.sub(r"\s*-\s*[^-]{2,20}$", "", title or "")   # ' - 조선일보' 꼬리
    t = _STOP.sub("", t)
    return t.lower()


def _shingles(s, n=4):
    if len(s) < n:
        return {s} if s else set()
    return {s[i:i + n] for i in range(len(s) - n + 1)}


def dedupe(items, key="title", threshold=0.5):
    """구글뉴스는 같은 사건을 매체별로 중복 배포한다.
    자카드 유사도로 묶고 각 그룹의 대표 1건만 남긴다.

    O(n^2)이지만 일 2000건 규모에서는 문제없다.
    """
    kept = []
    kept_sh = []
    dropped = 0
    for it in items:
        s = _shingles(_norm(it.get(key, "")))
        if not s:
            continue
        dup = False
        for i, prev in enumerate(kept_sh):
            inter = len(s & prev)
            if not inter:
                continue
            if inter / len(s | prev) >= threshold:
                dup = True
                # 중복 카운트는 '얼마나 많이 보도됐나' = 중요도 신호다
                kept[i]["dup_count"] = kept[i].get("dup_count", 1) + 1
                break
        if dup:
            dropped += 1
            continue
        it["dup_count"] = 1
        kept.append(it)
        kept_sh.append(s)
    return kept, dropped


def is_direct(it):
    """종목명이 실제로 언급됐는가. 섹터 연관은 제외."""
    return any(len(a) > 2 and a[2] == "직접" for a in (it.get("assets") or []))


def priority(it):
    """트랙 안에서의 우선순위.

    중립이라도 여러 매체가 동시에 다루면 올린다 — 규칙 사전이
    못 잡는 새로운 사건일 가능성이 높기 때문이다.
    """
    return (
        abs(it.get("score", 0)) * 2
        + it.get("dup_count", 1) * 1.5
        + recency_bonus(it)
        + (4 if is_direct(it) else 0)
        + (1 if it.get("is_macro") else 0)
    )


def _track_of(it):
    """섹터 연관만으로는 관심종목 트랙에 넣지 않는다.
    자리는 22개뿐이고, 직접 언급된 기사가 밀리면 안 된다."""
    if is_direct(it):
        return "watchlist"
    return "macro" if it.get("is_macro") else "other"


def select_for_llm(items, limit=40, quotas=None, codes=None, per_code_cap=2):
    """2단(LLM)으로 넘길 뉴스 선별.

    단순 점수 정렬은 실패한다. 관심종목과 무관한 소형주 실적 기사가
    "사상 최대"(+3) 같은 강한 어휘를 달고 상위를 다 차지하기 때문이다.
    트랙별 쿼터로 구성을 강제하고, 종목 트랙 안에서는 라운드로빈으로
    종목별 커버리지를 보장한다.
    """
    quotas = dict(quotas or {"watchlist": 22, "macro": 12, "other": 6})

    tracks = {"watchlist": [], "macro": [], "other": []}
    for it in items:
        tracks[_track_of(it)].append(it)

    selected, used = [], set()
    cov = {"covered": [], "uncovered": []}

    if codes:
        # 종목 트랙: 라운드로빈으로 종목마다 최소 1건 확보
        for it in tracks["watchlist"]:
            it["_codes"] = [a[0] for a in (it.get("assets") or [])
                            if len(a) > 2 and a[2] == "직접"]
        selected, used, cov = select_with_coverage(
            tracks["watchlist"], list(codes), "_codes",
            quotas["watchlist"], per_code_cap, priority)
        tracks["watchlist"] = [it for it in tracks["watchlist"]
                               if id(it) not in used]
        remaining = ("macro", "other")
    else:
        remaining = ("watchlist", "macro", "other")

    for track in remaining:
        ranked = sorted(tracks[track], key=priority, reverse=True)
        for it in ranked[:quotas[track]]:
            selected.append(it)
            used.add(id(it))

    # 쿼터를 못 채운 트랙이 있으면 남은 자리를 전체 상위로 메운다
    if len(selected) < limit:
        rest = sorted((it for it in items if id(it) not in used),
                      key=priority, reverse=True)
        selected.extend(rest[:limit - len(selected)])

    # 최종 정렬: 관심종목 → 매크로 → 기타, 각 트랙 안에서는 점수순
    order = {"watchlist": 0, "macro": 1, "other": 2}
    selected.sort(key=lambda it: (order[_track_of(it)], -priority(it)))
    return selected[:limit], cov


def summarize_scores(items):
    c = Counter(label(it.get("score", 0)) for it in items)
    return dict(c)


def recency_bonus(item, max_bonus=5.0):
    """오늘 급등락한 이유는 오늘 기사에 있다.

    이걸 안 넣으면 야후 티커 RSS 20건 중 사흘 전 기사가 뽑힌다 —
    실측: AZN의 '4천억달러 합병설'(당일) 대신 무관한 제휴 기사가 올라왔다.
    """
    d = (item.get("published") or "")[:10]
    if len(d) != 10 or d[4] != "-":
        return 0.0
    try:
        pub = dt.date.fromisoformat(d)
    except ValueError:
        return 0.0
    days = (dt.date.today() - pub).days
    if days <= 0:
        return max_bonus
    if days >= 4:
        return 0.0
    return max_bonus * (1 - days / 4)


# ---------------------------------------------------------------- 커버리지 선별
def select_with_coverage(items, entities, entity_key, limit,
                         per_entity_cap=2, priority_fn=None):
    """엔티티(티커·종목코드·코인)별 커버리지를 보장하는 선별.

    순수 점수 정렬은 실패한다. 실측: 미장에서 매그니피센트7 기사가
    티커 트랙 24자리를 독점해서 FERG의 'S&P500 편입'(거래량 5.95배의
    원인)과 AZN의 '4천억달러 합병설'이 통째로 잘렸다. 기사가 없었던 게
    아니라 밀린 것이다.

    라운드로빈으로 각 엔티티에 최소 1건을 먼저 배정한 뒤, 남은 자리를
    점수순으로 채운다.

    반환: (선별 리스트, {"covered": [...], "uncovered": [...]})
    """
    prio = priority_fn or (lambda it: abs(it.get("score", 0)) * 2
                           + it.get("dup_count", 1) * 1.5)

    # 엔티티 -> 그 엔티티가 언급된 기사들 (점수 높은 순)
    buckets = {e: [] for e in entities}
    for it in items:
        for e in (it.get(entity_key) or []):
            if e in buckets:
                buckets[e].append(it)
    for e in buckets:
        buckets[e].sort(key=prio, reverse=True)

    picked, used = [], set()
    counts = {e: 0 for e in entities}

    # 1~N라운드: 엔티티마다 한 건씩 돌아가며
    for round_i in range(per_entity_cap):
        # 라운드 안에서는 '가장 좋은 기사를 가진 엔티티' 순으로
        order = sorted(entities,
                       key=lambda e: -(prio(buckets[e][0]) if buckets[e] else -1e9))
        for e in order:
            if len(picked) >= limit:
                break
            if counts[e] > round_i:
                continue
            for it in buckets[e]:
                if id(it) in used:
                    continue
                picked.append(it)
                used.add(id(it))
                # 한 기사가 여러 엔티티를 언급하면 모두 채운 것으로 친다
                for e2 in (it.get(entity_key) or []):
                    if e2 in counts:
                        counts[e2] += 1
                break
        if len(picked) >= limit:
            break

    covered = [e for e, n in counts.items() if n > 0]
    uncovered = [e for e, n in counts.items() if n == 0]
    return picked, used, {"covered": covered, "uncovered": uncovered}
