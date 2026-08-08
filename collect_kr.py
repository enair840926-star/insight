# -*- coding: utf-8 -*-
"""국장 수집기 — 실행 진입점

    python collect_kr.py

L1(시세) + L2(뉴스) + L3(수급) + L4(센티먼트)를 모아
data/kr_YYYYMMDD_HHMM.json 으로 저장하고,
LLM(L6)에 넣을 프롬프트 재료를 data/prompt_*.txt 로 뽑는다.
"""
import io
import json
import sys
import time
import datetime as dt
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import config
from collectors import kr_market, kr_news, macro, dart, kr_screen, ecos
from core import rules, env, pick, screen, session

DATA_DIR = Path(__file__).parent / "data"
DATA_DIR.mkdir(exist_ok=True)


def fmt_num(n, unit=""):
    if n is None:
        return "-"
    if isinstance(n, float):
        return f"{n:,.2f}{unit}"
    return f"{n:,}{unit}"


def fmt_signed(n, unit=""):
    if n is None:
        return "-"
    return f"{n:+,}{unit}"


def streak_txt(n):
    """'-1일 연속'처럼 부호로 쓰면 방향이 안 읽힌다. 말로 푼다."""
    if not n:
        return "연속성 없음"
    return f"{abs(n)}일 연속 {'순매수' if n > 0 else '순매도'}"


# ---------------------------------------------------------------- 수집
def run():
    t0 = time.time()
    now = dt.datetime.now()
    print(f"국장 데이터 수집 시작 — {now:%Y-%m-%d %H:%M}\n")

    cfg = {
        "trend_days": config.TREND_DAYS,
        "ohlcv_days": config.OHLCV_DAYS,
        "disclosure_limit": config.DISCLOSURE_PER_STOCK,
    }

    print("[1/7] 지수 …", end=" ", flush=True)
    indices = [ix for ix in (kr_market.get_index(c) for c in config.INDICES) if ix]
    print(f"{len(indices)}건")

    print("[2/7] 전종목 스냅샷 → 동적 선별 …", end=" ", flush=True)
    rows, snap_stats = kr_screen.snapshot(config.MARKETS, config.MAX_WORKERS)
    picked, sel_stats = screen.select(
        rows, watchlist=[c for c, _n in config.WATCHLIST],
        exclude_fn=kr_screen.is_excluded, **config.SELECT)
    kr_screen.fix_turnover(picked, rows)
    agg = screen.aggregate(rows, config.AGG_MIN_CAP,
                           exclude_fn=kr_screen.is_excluded)
    print(f"{snap_stats['fetched']:,}개 → 유효 {sel_stats['usable']:,}개"
          f" → {len(picked)}종목")

    print("[3/7] 업종·테마 …", end=" ", flush=True)
    industries = kr_screen.groups("industry", config.GROUP_PAGES)
    themes = kr_screen.groups("theme", config.GROUP_PAGES)
    ind_map = kr_screen.industry_map(industries)
    print(f"업종 {len(industries)} / 테마 {len(themes)}")

    print("[4/7] 선별 종목 상세 (수급·펀더멘털·공시) …", end=" ", flush=True)
    watch = [(c["symbol"], c["name"]) for c in picked]
    stocks = kr_market.collect_all(watch, cfg, config.MAX_WORKERS)
    ok = [s for s in stocks if not s.get("error")]
    # 스냅샷의 선별 사유·시총·거래대금을 상세 결과에 얹는다
    by_code = {c["symbol"]: c for c in picked}
    for s in stocks:
        src = by_code.get(s["code"])
        if src:
            s["reasons"] = src["reasons"]
            s["market_cap"] = src["market_cap"]
            s["turnover"] = src.get("turnover")
            s["market"] = src.get("market")
            s["snapshot_change_pct"] = src.get("change_pct")
        s["industry"] = ind_map.get(s.get("industry_code"))
    print(f"{len(ok)}/{len(stocks)}종목")

    print("[5/7] 뉴스 …", end=" ", flush=True)
    selected, deduped, news_stats = kr_news.collect(
        config.RSS_FEEDS, config.GOOGLE_NEWS_QUERIES,
        watch, config.NEWS_PER_STOCK, config.NEWS_RECENT_DAYS,
        aliases=config.ALIASES, exclude=config.ALIAS_EXCLUDE,
        sectors=config.SECTOR_KEYWORDS, quotas=config.NEWS_QUOTAS)
    print(f"{news_stats['collected']}건 수집 → {news_stats['after_dedupe']}건")

    print("[6/7] 매크로·센티먼트 …", end=" ", flush=True)
    mac = macro.get_macro(config.MACRO_SYMBOLS, config.MAX_WORKERS)
    sent = macro.get_sentiment()
    kr_macro = ecos.collect(config.ECOS_SERIES, env.get("ECOS_API_KEY"),
                            config.ECOS_MONTHS)
    ok_kr = sum(1 for v in kr_macro.values() if v and not v.get("error"))
    print(f"해외 {len(mac)}개 / 국내 {ok_kr}개"
          + ("" if kr_macro else " (ECOS_API_KEY 없음)"))

    print("[7/7] DART 공시·내부자거래 …", end=" ", flush=True)
    dart_data = {}
    if not config.DART_ENABLED:
        print("건너뜀 (DART_ENABLED=False)")
    elif not env.has("DART_API_KEY"):
        print("건너뜀 (.env에 DART_API_KEY 없음)")
    else:
        try:
            corp_map = dart.load_corp_codes()
            dart_data = dart.collect_for_watchlist(
                watch, corp_map,
                days=config.DART_FILING_DAYS, max_workers=4)
            n = sum(1 for v in dart_data.values() if not v.get("error"))
            print(f"{n}/{len(watch)}종목 (상장사 DB {len(corp_map):,}개)")
        except Exception as e:
            # DART가 죽어도 나머지 수집물은 살린다
            print(f"실패 — {type(e).__name__}: {str(e)[:60]}")
    print()

    bundle = {
        "collected_at": now.isoformat(timespec="seconds"),
        "market": "KR",
        "indices": indices,
        "stocks": stocks,
        "select_stats": {**snap_stats, **sel_stats},
        "aggregate": agg,
        "industries": industries,
        "themes": themes,
        "macro": mac,
        "kr_macro": kr_macro,
        "sentiment": sent,
        "dart": dart_data,
        "news_stats": news_stats,
        "news_selected": selected,
        "news_all": deduped,
    }

    stamp = f"{now:%Y%m%d_%H%M}"
    out = DATA_DIR / f"kr_{stamp}.json"
    out.write_text(json.dumps(bundle, ensure_ascii=False, indent=1),
                   encoding="utf-8")

    prompt = build_prompt(bundle)
    pout = DATA_DIR / f"prompt_kr_{stamp}.txt"
    pout.write_text(prompt, encoding="utf-8")

    report(bundle)
    print(f"\n원자료  : {out}")
    print(f"LLM재료 : {pout}  ({len(prompt):,}자)")
    print(f"소요    : {time.time() - t0:.1f}초")
    return bundle


# ---------------------------------------------------------------- 콘솔 리포트
def report(b):
    print("=" * 72)
    print("지수")
    print("=" * 72)
    for ix in b["indices"]:
        print(f"  {ix['name']:8s} {fmt_num(ix['close']):>12s}  "
              f"{ix['change_pct']:+6.2f}%   ({ix['market_status']})")

    print("\n" + "=" * 72)
    print("매크로")
    print("=" * 72)
    for name, r in b["macro"].items():
        pct = r.get("change_pct")
        tail = f"{pct:+6.2f}%" if pct is not None else ""
        print(f"  {name:10s} {fmt_num(r['price']):>12s}  {tail}")

    km = b.get("kr_macro") or {}
    if km:
        print("\n" + "=" * 72)
        print("국내 거시 (한국은행 ECOS)")
        print("=" * 72)
        for r in ecos.summarize(km):
            print(f"  {r['name']:16s} ({r['period']})  {r['text']}")
        for name, d in km.items():
            if d and d.get("error"):
                print(f"  {name:16s} 조회 실패: {d['error']}")

    s = b["sentiment"]
    if s:
        print("\n" + "=" * 72)
        print("센티먼트")
        print("=" * 72)
        if "us_fear_greed" in s:
            f = s["us_fear_greed"]
            print(f"  미 증시 공포탐욕  {f['score']:>5} ({f['rating']})  "
                  f"전일 {f['prev_close']} / 1주전 {f['week_ago']}")
        if "crypto_fear_greed" in s:
            f = s["crypto_fear_greed"]
            print(f"  코인 공포탐욕     {f['score']:>5} ({f['rating']})")

    a = b.get("aggregate")
    if a:
        br = a["breadth"]
        print("\n" + "=" * 72)
        print("시장 폭")
        print("=" * 72)
        print(f"  상승 {br['up']:,} / 하락 {br['down']:,} / 보합 {br['flat']:,}"
              f"  (상승비율 {br['up_ratio']}%, 집계 {br['counted']:,}개)")
        print(f"  시총가중 등락률 {a['market_cap_weighted_pct']:+.2f}%")
        for s in a["sectors"]:
            print(f"    {s['sector']:8s} {s['cap_weighted_pct']:+6.2f}%"
                  f"  상승 {s['up_ratio']:5.1f}%"
                  f"  거래대금 {s['turnover_bil']:,.0f}십억  ({s['count']}개)")

    for key, label in (("industries", "업종"), ("themes", "테마")):
        rows = b.get(key) or []
        if not rows:
            continue
        print("\n" + "=" * 72)
        print(f"{label}  (상위 5 / 하위 5)")
        print("=" * 72)
        for r in rows[:5] + rows[-5:]:
            print(f"  {r['name'][:22]:24s} {r['change_pct']:+6.2f}%"
                  f"  상승 {r['rise']:>3}/{r['count']:<3}"
                  f" ({r['up_ratio'] if r['up_ratio'] is not None else '-'}%)")

    print("\n" + "=" * 72)
    print(f"선별 종목 {len(b['stocks'])}개  (수급 = 최근 5일 누적 순매수)")
    print("=" * 72)
    for st in b["stocks"]:
        if st.get("error"):
            print(f"  {st['name']:14s} 수집 실패: {st['error']}")
            continue
        f = st.get("fundamentals", {})
        g = st.get("signals", {})
        t = (st.get("trend") or [{}])[0]
        chg = t.get("change")
        close = t.get("close")
        pct = (chg / (close - chg) * 100) if (chg and close and close != chg) else None

        why = ",".join(st.get("reasons") or [])[:34]
        mc = st.get("market_cap")
        print(f"\n  ● {st['name']} ({st['code']})   {fmt_num(close)}원  "
              f"{f'{pct:+.2f}%' if pct is not None else ''}"
              f"   시총 {mc/1e12:.2f}조" if mc else "")
        print(f"      [{why}]  {st.get('industry') or st.get('market') or '-'}")
        print(f"      PER {fmt_num(f.get('per'))}배 / 추정PER {fmt_num(f.get('est_per'))}배"
              f" / PBR {fmt_num(f.get('pbr'))}배"
              f" / 배당 {fmt_num(f.get('dividend_yield'))}%")
        print(f"      외국인 5일 {fmt_signed(g.get('foreign_net_5d'))}주"
              f" (연속 {g.get('foreign_streak', 0):+d}일)"
              f" | 기관 5일 {fmt_signed(g.get('organ_net_5d'))}주"
              f" (연속 {g.get('organ_streak', 0):+d}일)")
        print(f"      외국인지분 {fmt_num(f.get('foreign_ratio'))}%"
              f" (10일 {fmt_signed(g.get('foreign_ratio_delta'))}%p)"
              f" | 20일선 대비 {fmt_num(g.get('vs_ma20_pct'))}%"
              f" | 거래량 {fmt_num(g.get('volume_ratio'))}배")
        print(f"      52주고점 대비 {fmt_num(g.get('from_52w_high_pct'))}%"
              f" | 20일 변동성 {fmt_num(g.get('volatility_20d'))}%")
        for d in (st.get("disclosures") or [])[:2]:
            print(f"      [공시] {d['datetime'][:10]} {d['title'][:52]}")

        dd = (b.get("dart") or {}).get(st["code"]) or {}
        ins = dd.get("insider_summary") or {}
        if ins.get("report_count"):
            print(f"      [내부자] 90일 매수 {ins['buy_count']}건 / 매도 "
                  f"{ins['sell_count']}건 / 순 {ins['net_shares']:+,}주")
            for c in ins.get("clusters", [])[:2]:
                print(f"          ★ {c['date']} {c['count']}명 동시 "
                      f"{'매수' if c['net'] > 0 else '매도'} {c['net']:+,}주")
        for m in (dd.get("major") or [])[:1]:
            print(f"      [5%룰] {m['date']} {m['holder'][:14]} {m['ratio']}% "
                  f"({m['ratio_delta']:+}%p, {m['shares_delta']:+,}주)")

    ns = b["news_stats"]
    print("\n" + "=" * 72)
    print("뉴스")
    print("=" * 72)
    print(f"  수집 {ns['collected']}건 → 기간외 {ns['stale_removed']}건 제거 "
          f"→ 중복 {ns['duplicates_removed']}건 제거 → {ns['after_dedupe']}건 "
          f"→ LLM 선별 {ns['selected_for_llm']}건")
    print(f"  (날짜 미상 {ns['undated']}건은 보존)")
    print(f"  관심종목 태깅 {ns['watchlist_tagged']}건 → 선별에 "
          f"{ns['selected_watchlist']}건 포함")
    print(f"  종목 커버리지: {len(ns.get('covered') or [])}/"
          f"{len([s for s in b['stocks'] if not s.get('error')])}개"
          + (f"  ← 뉴스 없음: {', '.join(ns['uncovered'])}"
             if ns.get("uncovered") else ""))
    print(f"  분포: {ns['label_dist']}")
    print("\n  선별된 뉴스 (관심종목 → 매크로 → 기타 순):")
    for n in b["news_selected"][:16]:
        assets = n.get("assets") or []
        if assets:
            tag = ",".join(a[1] for a in assets)
            via = assets[0][2] if len(assets[0]) > 2 else "직접"
            tag = f"{tag}({via})"
        else:
            tag = "매크로" if n.get("is_macro") else "-"
        d = (n.get("published") or "??")[:10]
        print(f"   {d} [{n['label']:4s}] ({n['score']:+d}) x{n.get('dup_count',1)} "
              f"{n['title'][:46]}")
        print(f"              {tag} | {n['source']}")


# ---------------------------------------------------------------- LLM 재료
def build_prompt(b):
    """L1~L5를 압축해 LLM 입력으로 만든다.

    원칙: 숫자는 맥락과 함께 준다. '외국인 -389만주'가 아니라
    '외국인 5일 누적 -389만주, 3일 연속 순매도, 지분율 -0.25%p'로.
    """
    L = []
    A = L.append
    A(f"# 국내 증시 데이터 스냅샷 ({b['collected_at']})\n")

    A("## 지수")
    for ix in b["indices"]:
        A(f"- {ix['name']}: {ix['close']:,} ({ix['change_pct']:+.2f}%)")

    A("\n## 매크로")
    for name, r in b["macro"].items():
        pct = r.get("change_pct")
        A(f"- {name}: {r['price']:,} ({pct:+.2f}%)" if pct is not None
          else f"- {name}: {r['price']}")

    km = b.get("kr_macro") or {}
    if km:
        A("\n## 국내 거시 (한국은행 ECOS)")
        A("지수형 지표(물가·수출)는 절대값이 아니라 전년동월비를 보라.")
        A("발표 시차가 있어 최신 월이 1~2개월 전일 수 있다.")
        rows = ecos.summarize(km)
        for r in rows:
            A(f"- {r['name']} ({r['period']}): {r['text']}")
        # 조회에 실패한 지표를 명시한다. 빈 목록을 그냥 두면 '값이 없다'와
        # '못 받았다'를 구분할 수 없어, 지표가 없는 것을 안정으로 읽는다.
        bad = [n for n, d in km.items() if not d or d.get("error")]
        if bad:
            A(f"- **조회 실패: {', '.join(bad)}** — 값이 없는 게 아니라"
              f" 받지 못한 것이다. 이 지표들은 판단 근거로 쓰지 마라.")
    else:
        A("\n## 국내 거시 (한국은행 ECOS)")
        A("**수집 실패 — 국내 금리·물가·수출 지표가 전부 없다.**")
        A("이 항목들을 언급하지 말고, 필요하면 '데이터 없음'이라고 명시하라.")

    s = b.get("sentiment") or {}
    if s.get("us_fear_greed"):
        f = s["us_fear_greed"]
        A(f"- 미 증시 공포탐욕: {f['score']} ({f['rating']}), "
          f"1주 전 {f['week_ago']}")

    a = b.get("aggregate")
    if a:
        br = a["breadth"]
        A("\n## 시장 폭")
        A(f"- 상승 {br['up']:,} / 하락 {br['down']:,} / 보합 {br['flat']:,}"
          f" (상승비율 {br['up_ratio']}%, 집계 {br['counted']:,}개)")
        A(f"- 시총가중 등락률 {a['market_cap_weighted_pct']:+.2f}%")
        A("  ← 지수와 상승비율이 어긋나면 대형주 편중이라는 뜻이다")
        for s in a["sectors"]:
            A(f"- {s['sector']}: 시총가중 {s['cap_weighted_pct']:+.2f}%,"
              f" 상승비율 {s['up_ratio']}%, 거래대금 {s['turnover_bil']:,.0f}십억원"
              f" ({s['count']}개)")

    for key, label, note in (
            ("industries", "업종", "네이버 업종 분류. 상승/하락 종목 수까지 집계된 값이다."),
            ("themes", "테마", "국장 특유의 테마주 묶음. 업종과 달리 이슈 단위로 묶인다.")):
        rows = b.get(key) or []
        if not rows:
            continue
        top, bot = config.GROUP_TOP, config.GROUP_BOTTOM
        A(f"\n## {label}별 등락 (전체 {len(rows)}개 중 상위 {top} / 하위 {bot})")
        A(note)
        for r in rows[:top]:
            A(f"- {r['name']}: {r['change_pct']:+.2f}%"
              f" (상승 {r['rise']}/{r['count']}, {r['up_ratio']}%)")
        A("  …")
        for r in rows[-bot:]:
            A(f"- {r['name']}: {r['change_pct']:+.2f}%"
              f" (상승 {r['rise']}/{r['count']}, {r['up_ratio']}%)")

    # DART가 통째로 실패하면 공시·내부자거래·5%룰이 조용히 사라진다.
    # 그러면 '내부자 매매가 없었다'로 읽히는데, 사실은 못 받은 것이다.
    dart_all = b.get("dart") or {}
    dart_ok = sum(1 for v in dart_all.values() if v and not v.get("error"))
    if not dart_ok:
        A("\n## DART 수집 실패")
        A("**공시·내부자거래·5%룰 데이터가 전부 없다.**")
        A("내부자 매매나 대량보유 변동이 '없었다'고 서술하지 마라 —")
        A("일어나지 않은 것이 아니라 조회하지 못한 것이다.")
        A("이 축은 판단에서 빼고, 필요하면 '데이터 없음'이라고 명시하라.")
    elif dart_ok < len(dart_all):
        missing = [c for c, v in dart_all.items()
                   if not v or v.get("error")]
        A(f"\n## DART 부분 실패")
        A(f"다음 종목은 공시·내부자거래·5%룰을 받지 못했다: "
          f"{', '.join(missing)}")
        A("이 종목들에 대해 '내부자 매매 없음'이라고 쓰지 마라.")

    st_ = b.get("select_stats") or {}
    A(f"\n## 선별 종목 {len([s for s in b['stocks'] if not s.get('error')])}개")
    if st_:
        A(f"전종목 {st_.get('fetched', 0):,}개(KOSPI+KOSDAQ)에서 ETF/ETN"
          f" {st_.get('non_stock', 0):,}개·우선주/스팩 {st_.get('derivative', 0):,}개를"
          f" 제외한 {st_.get('usable', 0):,}개 중에서 골랐다.")
    A("선별 사유: 관심종목(항상 포함) / 거래대금상위 / 급등 / 급락 / 섹터대표")
    A("**사유를 보고 판단하라** — '급등'으로 뽑힌 종목과 '거래대금상위'로")
    A("뽑힌 종목은 의미가 다르다. 전자는 이벤트, 후자는 자금 집중이다.")

    A("\n## 종목별 지표")
    for st in b["stocks"]:
        if st.get("error"):
            continue
        f = st.get("fundamentals", {})
        g = st.get("signals", {})
        t = (st.get("trend") or [{}])[0]
        A(f"\n### {st['name']} ({st['code']})")
        why = ", ".join(st.get("reasons") or []) or "-"
        mc = st.get("market_cap")
        A(f"- 사유: {why} | 업종: {st.get('industry') or '-'}"
          f" | 시장: {st.get('market') or '-'}"
          + (f" | 시총 {mc/1e12:.2f}조원" if mc else "")
          + (f" | 거래대금 {st['turnover']/1e8:,.0f}억원" if st.get("turnover") else ""))
        A(f"- 종가 {fmt_num(t.get('close'))}원, 거래량 {fmt_num(t.get('volume'))}주"
          f" (20일 평균 대비 {fmt_num(g.get('volume_ratio'))}배)")
        val = (f"- 밸류: PER {fmt_num(f.get('per'))}배 / 추정PER {fmt_num(f.get('est_per'))}배"
               f" / PBR {fmt_num(f.get('pbr'))}배 / 배당수익률 {fmt_num(f.get('dividend_yield'))}%")
        if g.get("per_gap_pct") is not None:
            gap = g["per_gap_pct"]
            hint = "이익 증가 전망" if gap < -10 else ("이익 감소 전망" if gap > 10 else "")
            val += f"  → 추정PER이 현재PER 대비 {gap:+.1f}%{' (' + hint + ')' if hint else ''}"
        A(val)
        A(f"- 수급: 외국인 5일 누적 {fmt_signed(g.get('foreign_net_5d'))}주"
          f" ({streak_txt(g.get('foreign_streak'))}),"
          f" 기관 5일 누적 {fmt_signed(g.get('organ_net_5d'))}주"
          f" ({streak_txt(g.get('organ_streak'))})")
        A(f"- 외국인 지분율 {fmt_num(f.get('foreign_ratio'))}%"
          f" (10일간 {fmt_signed(g.get('foreign_ratio_delta'))}%p)")
        A(f"- 위치: 20일선 대비 {fmt_num(g.get('vs_ma20_pct'))}%,"
          f" 52주 고점 대비 {fmt_num(g.get('from_52w_high_pct'))}%,"
          f" 20일 변동성 {fmt_num(g.get('volatility_20d'))}%")
        ds = st.get("disclosures") or []
        if ds:
            A("- 최근 공시:")
            for d in ds[:3]:
                A(f"    ({d['datetime'][:10]}) {d['title']}")

        dd = (b.get("dart") or {}).get(st["code"]) or {}
        ins = dd.get("insider_summary") or {}
        if ins.get("report_count"):
            A(f"- 내부자 거래(최근 90일): 매수 {ins['buy_count']}건,"
              f" 매도 {ins['sell_count']}건, 순 {ins['net_shares']:+,}주"
              f" (최근 보고 {ins.get('latest_date')})")
            for c in ins.get("clusters", []):
                A(f"    ★ {c['date']} 임원 {c['count']}명이 동시에"
                  f" {'매수' if c['net'] > 0 else '매도'} ({c['net']:+,}주)"
                  f" — {', '.join(c['people'][:4])}")
        mj = dd.get("major") or []
        if mj:
            A("- 대량보유(5%룰) 변동:")
            for m in mj[:3]:
                A(f"    ({m['date']}) {m['holder']} {m['ratio']}%"
                  f" [{m['ratio_delta']:+}%p, {m['shares_delta']:+,}주] {m['reason'][:40]}")

    ns = b["news_stats"]
    A(f"\n## 주요 뉴스 (최근 {config.NEWS_RECENT_DAYS}일, 규칙 기반 1차 선별)")
    A(f"전체 {ns['collected']}건 중 기간외 {ns['stale_removed']}건·중복 "
      f"{ns['duplicates_removed']}건을 제외하고 {ns['selected_for_llm']}건을 골랐다"
      f" (관심종목 {ns['selected_watchlist']}건 포함).")
    if ns.get("uncovered"):
        A(f"**뉴스 근거를 못 찾은 종목: {', '.join(ns['uncovered'])}**")
        A("이 종목들은 아래 목록에 관련 기사가 없다. 움직임의 이유를 추측하지 말고")
        A("'뉴스에 근거 없음'이라고 명시하라.")
    A("형식: (날짜) [규칙판정] (점수) x보도매체수 <관련종목> 제목")
    A("<종목(섹터:키워드)>는 종목명이 직접 언급되지 않고 업종 연관으로 "
      "묶인 것이니 관련성을 낮게 보라.")
    for n in b["news_selected"]:
        assets = n.get("assets") or []
        if assets:
            via = assets[0][2] if len(assets[0]) > 2 else "직접"
            names = ",".join(a[1] for a in assets)
            tag = f" <{names}>" if via == "직접" else f" <{names}({via})>"
        else:
            tag = " <매크로>" if n.get("is_macro") else ""
        d = (n.get("published") or "")[:10] or "날짜미상"
        A(f"- ({d}) [{n['label']}] ({n['score']:+d}) x{n.get('dup_count', 1)}{tag} {n['title']}")
        if n.get("summary"):
            A(f"    {n['summary'][:160]}")

    A(pick.block("kr", b))

    A(session.request_block("kr", extra_sections="""
### 참고 — 이 시장에서만 볼 수 있는 것
- **외국인/기관 수급**이 가장 중요한 축이다. 5일 누적과 연속 일수가
  어긋나면 최근 손바뀜이 있었다는 뜻이니 그 방향을 짚어라.
- **내부자 거래**는 임원 개인의 소량 매매를 단독으로 해석하지 마라.
  스톡옵션·우리사주일 수 있다. 여러 명이 같은 날 같은 방향으로 움직인
  경우(★ 표시)만 신호로 취급하라.
- **업종·테마**는 네이버가 상승 종목 수까지 집계해서 준다. 전 종목이
  오른 테마는 개별 펀더멘털이 아니라 자금 유입 신호로 읽어라.
- **뉴스의 날짜를 확인하라.** 며칠 전 기사가 섞여 있다. 과거 기사를
  방금 일어난 일로 서술하지 마라."""))
    return "\n".join(L)


if __name__ == "__main__":
    run()
