# -*- coding: utf-8 -*-
"""미장 수집기 — 실행 진입점

    python collect_us.py

7,113개 전종목 스냅샷 → 동적 선별 30개 → 상세 보강 → 뉴스 → 캘린더.
선별에서 빠진 나머지는 버리지 않고 섹터 집계로 남긴다.
"""
import io
import json
import sys
import time
import datetime as dt
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import us_universe as U
from collectors import us_market, us_news, macro
from core import history, pick, regime, screen, session

DATA_DIR = Path(__file__).parent / "data"
DATA_DIR.mkdir(exist_ok=True)


def bn(v):
    """시총을 읽기 쉽게"""
    if not v:
        return "-"
    if v >= 1e12:
        return f"{v/1e12:.2f}T"
    if v >= 1e9:
        return f"{v/1e9:.0f}B"
    return f"{v/1e6:.0f}M"


def pct(v, w=6):
    return f"{v:+{w}.2f}%" if v is not None else " " * w


def run():
    t0 = time.time()
    now = dt.datetime.now()
    print(f"미장 데이터 수집 시작 — {now:%Y-%m-%d %H:%M}\n")

    print("[1/5] 전종목 스냅샷 …", end=" ", flush=True)
    rows = us_market.screener_snapshot(U.SCREENER_URL)
    if not rows:
        print("실패 — 스크리너 응답 없음")
        return None
    print(f"{len(rows):,}개")

    print("[2/5] 동적 선별 …", end=" ", flush=True)
    # 결과를 아직 못 채운 픽을 워치리스트에 얹는다. 미장 스크리너는 급등·
    # 급락으로 뽑아서 어제 픽이 오늘 목록에서 사라진다(실측: 최근 세 쌍이
    # 1/3, 1/3, 0/3). 워치리스트는 조용해도 항상 포함되므로 그 자리를 쓴다.
    open_ = history.open_keys("us")
    watch = tuple(U.WATCHLIST) + tuple(k for k in open_ if k not in U.WATCHLIST)
    selected, sel_stats = screen.select(rows, watchlist=watch, **U.SELECT)
    agg = screen.aggregate(rows, U.AGG_MIN_CAP)
    print(f"{len(selected)}개 선별 "
          f"(파생 {sel_stats['derivative']:,} / 시총없음 {sel_stats['no_cap']:,} 제외, "
          f"유효 {sel_stats['usable']:,}"
          + (f", 미결 픽 {len(open_)}개 포함" if open_ else "") + ")")

    print("[3/5] 선별 종목 상세 + 지수 …", end=" ", flush=True)
    us_market.enrich_details(selected, U.DETAIL_RANGE, U.MAX_WORKERS)
    # 야후 quoteSummary가 401이라 미장에는 펀더멘털이 없다. 나스닥 실적
    # 서프라이즈가 그 자리를 메운다 (러너에서도 되는 것을 probe로 확인).
    us_market.enrich_surprise(selected, U.MAX_WORKERS)
    # 수집이 개장 1시간 전이라 프리마켓은 이미 4시간 반이 지나 있다. 일봉으로는
    # 안 보여 분봉을 따로 받는다 (30개에 2초).
    n_pre = us_market.enrich_premarket(selected, U.MAX_WORKERS)
    indices = us_market.get_indices(U.INDICES)
    n_sur = sum(1 for r in selected if r.get("surprise"))
    print(f"{len(selected)}종목 (실적 서프라이즈 {n_sur}개 / 프리마켓 {n_pre}개)"
          f" / 지수 {len(indices)}개")

    print("[4/5] 뉴스 …", end=" ", flush=True)
    picked, deduped, news_stats = us_news.collect(
        U.RSS_FEEDS, U.GOOGLE_NEWS_QUERIES, selected, U.YAHOO_TICKER_RSS,
        U.SECTOR_KEYWORDS, U.NEWS_PER_STOCK, U.NEWS_RECENT_DAYS, U.NEWS_LIMIT)
    print(f"{news_stats['collected']}건 → {news_stats['selected_for_llm']}건")

    print("[5/5] 캘린더·센티먼트 …", end=" ", flush=True)
    earnings = us_market.earnings_calendar(U.EARNINGS_URL, symbols=U.WATCHLIST)
    econ = us_market.econ_calendar(U.ECON_URL)
    sent = macro.get_sentiment()
    print(f"실적 {len(earnings)} / 지표 {len(econ)}\n")

    bundle = {
        "collected_at": now.isoformat(timespec="seconds"),
        "market": "US",
        "indices": indices,
        "selected": selected,
        "select_stats": sel_stats,
        "aggregate": agg,
        "earnings": earnings,
        "econ": econ,
        "sentiment": sent,
        "news_stats": news_stats,
        "news_selected": picked,
        "news_all": deduped,
    }

    stamp = f"{now:%Y%m%d_%H%M}"
    out = DATA_DIR / f"us_{stamp}.json"
    out.write_text(json.dumps(bundle, ensure_ascii=False, indent=1), encoding="utf-8")
    prompt = build_prompt(bundle)
    pout = DATA_DIR / f"prompt_us_{stamp}.txt"
    pout.write_text(prompt, encoding="utf-8")

    done, made = history.track("us", bundle)
    if done or made:
        print(f"기록: 결과 {done}건 채움 / 픽 {made}건 남김")

    report(bundle)
    print(f"\n원자료  : {out}")
    print(f"LLM재료 : {pout}  ({len(prompt):,}자)")
    print(f"소요    : {time.time() - t0:.1f}초")
    return bundle


# ---------------------------------------------------------------- 콘솔
def report(b):
    print("=" * 78)
    print("지수")
    print("=" * 78)
    for name, r in b["indices"].items():
        print(f"  {name:14s} {r['price']:>11,.2f} {pct(r.get('change_pct'))}"
              f"  |20일 {pct(r.get('change_20d_pct'))} |52주위치 {r.get('pos_52w','-')}")

    a = b["aggregate"]
    if a:
        br = a["breadth"]
        print("\n" + "=" * 78)
        print("시장 폭")
        print("=" * 78)
        print(f"  상승 {br['up']:,} / 하락 {br['down']:,} / 보합 {br['flat']:,}"
              f"  (상승비율 {br['up_ratio']}%, 집계 {br['counted']:,}개)")
        print(f"  시총가중 등락률 {a['market_cap_weighted_pct']:+.2f}%")
        print("\n  섹터 (시총가중 등락률 / 상승비율 / 거래대금):")
        for s in a["sectors"]:
            print(f"    {s['sector'][:24]:26s} {s['cap_weighted_pct']:+6.2f}%"
                  f"  상승 {s['up_ratio']:5.1f}%  ${s['turnover_bil']:7,.1f}B"
                  f"  ({s['count']}개)")

    print("\n" + "=" * 78)
    print(f"선별 종목 {len(b['selected'])}개")
    print("=" * 78)
    for r in b["selected"]:
        why = ",".join(r["reasons"])[:34]
        print(f"  {r['symbol']:6s} {r['name'][:26]:28s} {pct(r.get('change_pct'))}"
              f" ${bn(r['market_cap']):>7s} |20MA {pct(r.get('vs_ma20_pct'))}"
              f" |52주 {str(r.get('pos_52w','-')):>5} |거래량 {r.get('volume_ratio','-')}")
        print(f"         {why}  · {r.get('sector') or '-'}")

    if b["earnings"]:
        print("\n" + "=" * 78)
        print("실적 발표 예정")
        print("=" * 78)
        for e in b["earnings"][:10]:
            mark = "★" if e["watched"] else " "
            print(f"  {mark} {e['date']} {e['symbol']:6s} {(e['name'] or '')[:30]:32s}"
                  f" {e['time']:14s} 예상EPS {e['eps_forecast']}")

    if b["econ"]:
        print("\n" + "=" * 78)
        print("경제지표")
        print("=" * 78)
        for e in b["econ"][:8]:
            print(f"  {e['date']} {(e['country'] or '')[:14]:16s} {(e['event'] or '')[:40]:42s}"
                  f" 실제 {e['actual'] or '-'} / 예상 {e['consensus'] or '-'}")

    ns = b["news_stats"]
    print("\n" + "=" * 78)
    print("뉴스")
    print("=" * 78)
    print(f"  수집 {ns['collected']}건 → 기간외 {ns['stale_removed']} / 중복 "
          f"{ns['duplicates_removed']} 제거 → {ns['after_dedupe']}건 → 선별 "
          f"{ns['selected_for_llm']}건 (티커 태깅 {ns['ticker_tagged']}건)")
    print(f"  종목 커버리지: {len(ns.get('covered') or [])}/"
          f"{len(b['selected'])}개"
          + (f"  ← 뉴스 없음: {', '.join(ns['uncovered'])}"
             if ns.get("uncovered") else ""))
    for n in b["news_selected"][:12]:
        t = ",".join(n.get("tickers") or []) or ",".join(n.get("sectors") or []) or "-"
        d = (n.get("published") or "")[:10]
        print(f"   {d} [{n['label']:4s}] x{n.get('dup_count',1)} {n['title'][:50]}")
        print(f"              {t[:40]} | {n['source']}")


# ---------------------------------------------------------------- 프롬프트
def build_prompt(b):
    L = []
    A = L.append
    A(f"# 미국 증시 데이터 스냅샷 ({b['collected_at']})\n")

    A("## 지수")
    for name, r in b["indices"].items():
        A(f"- {name}: {r['price']:,.2f} ({pct(r.get('change_pct'),0)}),"
          f" 20일 {pct(r.get('change_20d_pct'),0)}, 52주위치 {r.get('pos_52w','-')}")

    a = b["aggregate"]
    if a:
        br = a["breadth"]
        A("\n## 시장 폭")
        A(f"- 상승 {br['up']:,} / 하락 {br['down']:,} / 보합 {br['flat']:,}"
          f" (상승비율 {br['up_ratio']}%, 집계 {br['counted']:,}개)")
        A(f"- 시총가중 등락률 {a['market_cap_weighted_pct']:+.2f}%"
          f"  ← 지수와 상승비율이 어긋나면 대형주 편중이라는 뜻이다")
        A("\n### 섹터별 (시총가중 등락률)")
        for s in a["sectors"]:
            A(f"- {s['sector']}: {s['cap_weighted_pct']:+.2f}%,"
              f" 상승비율 {s['up_ratio']}%, 거래대금 ${s['turnover_bil']:,.1f}B"
              f" ({s['count']}개)")

    st = b["select_stats"]
    A(f"\n## 선별 종목 {len(b['selected'])}개")
    A(f"전종목 {st['total']:,}개에서 파생증권 {st['derivative']:,}개·시총미상"
      f" {st['no_cap']:,}개를 제외한 {st['usable']:,}개 중에서 골랐다.")
    A("선별 사유: 관심종목(항상 포함) / 거래대금상위 / 급등 / 급락 / 섹터대표")
    A("**사유를 보고 판단하라** — '급등'으로 뽑힌 종목과 '거래대금상위'로")
    A("뽑힌 종목은 의미가 다르다. 전자는 이벤트, 후자는 자금 집중이다.")
    A("")
    A("**프리마켓 값에는 거래량이 없다.** 야후가 프리마켓 5분봉에 거래량을")
    A("채우지 않아(실측: 55개 봉 전부 0) 그 등락이 실제 수급인지 얇은 호가에")
    A("한 번 튄 것인지 구분할 수가 없다. 대신 **체결된 5분 구간 수**를 함께")
    A("냈다 — 같은 시간인데 55개인 종목이 있고 20개인 종목이 있다. 구간이")
    A("적으면 띄엄띄엄 거래된 것이므로 그 등락률을 얇게 읽어라. 이 값은")
    A("'오늘의 픽' 점수에 들어가 있지 않다.")
    for r in b["selected"]:
        A(f"\n### {r['symbol']} — {r['name']}")
        A(f"- 사유: {', '.join(r['reasons'])} | 섹터: {r.get('sector') or '-'}"
          f" | 업종: {r.get('industry') or '-'}")
        A(f"- 주가 ${r.get('price') or 0:,.2f} ({pct(r.get('change_pct'),0)}),"
          f" 시총 ${bn(r['market_cap'])}, 거래대금 ${r['turnover']/1e9:,.2f}B")
        if r.get("pre_change_pct") is not None:
            A(f"- 프리마켓 {r['pre_change_pct']:+.2f}% (직전 정규장 종가 대비,"
              f" 체결 구간 {r['pre_bars']}개)")
        parts = []
        for key, label in (("change_5d_pct", "5일"), ("change_20d_pct", "20일"),
                           ("vs_ma20_pct", "20일선대비"), ("vs_ma60_pct", "60일선대비")):
            if r.get(key) is not None:
                parts.append(f"{label} {r[key]:+.2f}%")
        if parts:
            A("- 추세: " + ", ".join(parts))
        pos = []
        if r.get("pos_52w") is not None:
            pos.append(f"52주위치 {r['pos_52w']}")
        if r.get("from_52w_high_pct") is not None:
            pos.append(f"52주고점 대비 {r['from_52w_high_pct']:+.1f}%")
        if r.get("volume_ratio") is not None:
            pos.append(f"거래량 20일평균의 {r['volume_ratio']}배")
        if r.get("volatility_20d") is not None:
            pos.append(f"20일 변동성 {r['volatility_20d']}%")
        if pos:
            A("- 위치: " + ", ".join(pos))
        # 미장 유일의 사실 기반 펀더멘털. 애널리스트 목표주가와 달리
        # 실제 발표 숫자와 발표 전 예상의 대조라 사후 검증이 된 값이다.
        s = r.get("surprise")
        if s:
            qs = ", ".join(f"{q['quarter']} {q['surprise_pct']:+.1f}%"
                           for q in s["quarters"])
            A(f"- 실적 서프라이즈: 최근 {s['count']}분기 중 {s['beats']}번"
              f" 컨센서스 상회 ({qs})")
        # 야후 quoteSummary가 401이라 미장에는 밸류에이션이 없었다. 위
        # 분기 EPS 넷을 합쳐 후행 12개월로 낸 값이다 — 선행 추정치가
        # 아니므로 국장의 추정PER과 같은 뜻이 아니다.
        if r.get("per"):
            A(f"- 밸류: PER {r['per']}배 (후행 12개월 EPS ${r['ttm_eps']})")
        elif r.get("ttm_eps") is not None:
            A(f"- 밸류: 후행 12개월 EPS ${r['ttm_eps']} — 적자라 PER 없음")

    if b["earnings"]:
        A("\n## 실적 발표 예정 (오늘~내일)")
        for e in b["earnings"][:15]:
            mark = " ★관심종목" if e["watched"] else ""
            A(f"- {e['date']} {e['symbol']} ({e['name']}) {e['time']},"
              f" 예상EPS {e['eps_forecast']}, 시총 ${bn(e['market_cap'])}{mark}")

    if b["econ"]:
        A("\n## 경제지표 (오늘~내일)")
        for e in b["econ"][:12]:
            A(f"- {e['date']} [{e['country']}] {e['event']}"
              f" — 실제 {e['actual'] or '미발표'} / 예상 {e['consensus'] or '-'}"
              f" / 이전 {e['previous'] or '-'}")

    s = b.get("sentiment") or {}
    if s.get("us_fear_greed"):
        f = s["us_fear_greed"]
        A(f"\n## 센티먼트\n- 공포탐욕 지수: {f['score']} ({f['rating']}),"
          f" 전일 {f['prev_close']} / 1주 전 {f['week_ago']}")

    ns = b["news_stats"]
    A(f"\n## 뉴스 (최근 {U.NEWS_RECENT_DAYS}일)")
    A(f"전체 {ns['collected']}건에서 기간외·중복 제외 후 {ns['selected_for_llm']}건 선별"
      f" (티커 태깅 {ns['selected_ticker']}건 포함).")
    if ns.get("uncovered"):
        A(f"**뉴스 근거를 못 찾은 종목: {', '.join(ns['uncovered'])}**")
        A("이 종목들은 아래 뉴스 목록에 관련 기사가 없다. 움직임의 이유를")
        A("추측하지 말고 '뉴스에 근거 없음'이라고 명시하라.")
    A("형식: (날짜) [규칙판정] x보도매체수 <티커 또는 섹터> 제목")
    for n in b["news_selected"]:
        t = ",".join(n.get("tickers") or [])
        if not t:
            t = ",".join(n.get("sectors") or [])
        tag = f" <{t}>" if t else ""
        d = (n.get("published") or "")[:10] or "날짜미상"
        A(f"- ({d}) [{n['label']}] x{n.get('dup_count',1)}{tag} {n['title']}")
        if n.get("summary"):
            A(f"    {n['summary'][:160]}")

    A(regime.text("us", b))
    A(pick.block("us", b))

    A(session.request_block("us", extra_sections="""
### 참고 — 이 시장에서만 볼 수 있는 것
- **선별 사유별로 다르게 읽어라.** '급등'/'급락'은 이벤트이므로 뉴스에서
  근거를 찾되, 못 찾으면 "뉴스에 근거 없음"이라고 명시하라 — 그것도 정보다.
  '거래대금상위'는 방향과 무관하게 자금이 몰렸다는 뜻이다.
  '관심종목'은 조용해도 상태를 확인해 보고하라.
- **섹터 로테이션**을 거래대금과 시총가중 등락률로 함께 보라. 거래대금이
  큰데 등락이 마이너스면 자금은 도는데 성과가 안 나오는 것이다.
- **실적·경제지표 캘린더**가 위에 있다. 이번 장에 발표되는 것을
  '예정된 이벤트'에 반드시 반영하라."""))
    return "\n".join(L)


if __name__ == "__main__":
    run()
