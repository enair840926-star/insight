# -*- coding: utf-8 -*-
"""코인 수집기 — 실행 진입점

    python collect_coin.py

국장·미장에 없는 세 축: 펀딩비 / 미결제약정 / 김치프리미엄.
"""
import io
import json
import sys
import time
import datetime as dt
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import coin_universe as U
from collectors import coin_market as cm, coin_news, coin_okx as okx
from core import pick, session

DATA_DIR = Path(__file__).parent / "data"
DATA_DIR.mkdir(exist_ok=True)

POS_CFG = {
    "oi": U.BINANCE_OI, "oi_hist": U.BINANCE_OI_HIST,
    "ls_account": U.BINANCE_LS_ACCOUNT, "ls_top": U.BINANCE_LS_TOP,
    "taker": U.BINANCE_TAKER,
}


def money(v, unit="$"):
    if not v:
        return "-"
    if v >= 1e12:
        return f"{unit}{v/1e12:.2f}T"
    if v >= 1e9:
        return f"{unit}{v/1e9:.1f}B"
    if v >= 1e6:
        return f"{unit}{v/1e6:.0f}M"
    return f"{unit}{v:,.0f}"


def pct(v, w=6):
    return f"{v:+{w}.2f}%" if v is not None else " " * w


def fund_bp(v):
    """펀딩비는 소수라 읽기 어렵다. bp(0.01%)로 바꾼다."""
    return f"{v*10000:+.2f}bp" if v is not None else "-"


def run():
    t0 = time.time()
    now = dt.datetime.now()
    print(f"코인 데이터 수집 시작 — {now:%Y-%m-%d %H:%M}\n")

    print("[1/5] 시총 상위 + 무기한선물 전체 …", end=" ", flush=True)
    coins = cm.coingecko_universe(U.COINGECKO_MARKETS, U.EXCLUDE_SYMBOLS)
    if not coins:
        print("실패 — 코인게코 응답 없음")
        return None

    # 바이낸스는 미국 IP에 451(약관상 지역 제한)을 준다. 우회하지 않고
    # 같은 지표를 주는 OKX로 넘어간다. 어느 쪽에서 왔는지는 기록해 둔다 —
    # 거래소가 다르면 펀딩비·롱숏비의 절대 수준도 다르므로, 어제와 오늘을
    # 비교할 때 출처가 바뀐 사실을 모르면 없는 변화를 읽게 된다.
    source = "binance"
    perp = cm.binance_futures(U.BINANCE_FUT_24H, U.BINANCE_FUNDING)
    if not perp:
        perp = okx.futures()
        if perp:
            source = "okx"
            # OKX는 펀딩비 일괄 조회가 없다. 선별 기준(펀딩비 극단)을
            # 살리려면 시총 상위권만이라도 미리 받아 둬야 한다.
            top = [c["symbol"] for c in coins[:U.OKX_FUNDING_PREFETCH]]
            okx.fill_funding(perp, top, U.MAX_WORKERS)
    cm.merge(coins, perp)

    label = {"binance": "바이낸스", "okx": "OKX(바이낸스 차단)"}[source]
    if not perp:
        print("무기한선물 조회 실패 — 가격만으로 진행합니다")
    else:
        print(f"코인 {len(coins)}개 / 무기한선물 {len(perp)}개 · {label}")

    print("[2/5] 동적 선별 …", end=" ", flush=True)
    selected = cm.select(coins, watchlist=U.WATCHLIST,
                         funding_extreme=U.FUNDING_EXTREME, **U.SELECT)
    agg = cm.aggregate(coins, [c["symbol"] for c in selected])
    print(f"{len(selected)}개")

    print("[3/5] 포지셔닝 (미결제약정·롱숏·테이커) …", end=" ", flush=True)
    if source == "okx":
        okx.enrich_positioning(selected, U.MAX_WORKERS)
        # 선별된 것 중 아직 펀딩비가 없는 코인을 마저 채운다
        okx.fill_funding(
            {c["symbol"]: c for c in selected if c.get("has_perp")},
            [c["symbol"] for c in selected
             if c.get("has_perp") and c.get("funding_rate") is None],
            U.MAX_WORKERS)
    else:
        cm.enrich_positioning(selected, POS_CFG, U.MAX_WORKERS)
    n_pos = sum(1 for c in selected if c.get("open_interest"))
    print(f"{n_pos}/{len(selected)}개")

    print("[4/5] 김치프리미엄 …", end=" ", flush=True)
    fx, kimp = cm.kimchi_premium(selected, U.UPBIT_TICKER, U.USDKRW, U.UPBIT_MARKETS)
    print(f"환율 {fx:,.2f}원 / 업비트 상장 {len(kimp)}개" if fx else "환율 조회 실패")

    print("[5/5] 뉴스·시장지표 …", end=" ", flush=True)
    picked, deduped, news_stats = coin_news.collect(
        U.RSS_FEEDS, U.GOOGLE_NEWS_QUERIES, selected,
        U.NAME_ALIASES, U.TOPIC_KEYWORDS, U.NEWS_RECENT_DAYS, U.NEWS_LIMIT)
    glob = cm.global_stats(U.COINGECKO_GLOBAL)
    fg = cm.fear_greed(U.FEAR_GREED)
    print(f"{news_stats['collected']}건 → {news_stats['selected_for_llm']}건\n")

    bundle = {
        "collected_at": now.isoformat(timespec="seconds"),
        "market": "CRYPTO",
        "derivatives_source": source,
        "usdkrw": fx,
        "global": glob,
        "fear_greed": fg,
        "selected": selected,
        "aggregate": agg,
        "kimchi": kimp,
        "news_stats": news_stats,
        "news_selected": picked,
        "news_all": deduped,
    }

    stamp = f"{now:%Y%m%d_%H%M}"
    out = DATA_DIR / f"coin_{stamp}.json"
    out.write_text(json.dumps(bundle, ensure_ascii=False, indent=1), encoding="utf-8")
    prompt = build_prompt(bundle)
    pout = DATA_DIR / f"prompt_coin_{stamp}.txt"
    pout.write_text(prompt, encoding="utf-8")

    report(bundle)
    print(f"\n원자료  : {out}")
    print(f"LLM재료 : {pout}  ({len(prompt):,}자)")
    print(f"소요    : {time.time() - t0:.1f}초")
    return bundle


# ---------------------------------------------------------------- 콘솔
def report(b):
    g, fg, a = b["global"], b["fear_greed"], b["aggregate"]
    print("=" * 80)
    print("시장 전체")
    print("=" * 80)
    print(f"  총 시총 {money(g['total_market_cap_usd'])}"
          f" ({pct(g['market_cap_change_24h_pct'])} 24h)"
          f" | 거래대금 {money(g['total_volume_usd'])}")
    print(f"  BTC 도미넌스 {g['btc_dominance']}% | ETH {g['eth_dominance']}%"
          f" | 활성 코인 {g['active_coins']:,}개")
    if fg:
        extra = f" (전일 {fg.get('prev')}, 1주전 {fg.get('week_ago')})" if fg.get("prev") else ""
        print(f"  공포탐욕 {fg['value']} ({fg['rating']}){extra}")
    if a:
        print(f"  상위 100 중 상승 {a['up']} / 하락 {a['down']} ({a['up_ratio']}%)"
              f" | 중간값 {pct(a['median_change_pct'])}")
        if a.get("avg_funding_bp") is not None:
            print(f"  평균 펀딩비 {a['avg_funding_bp']:+.2f}bp"
                  f" | 양(+)의 펀딩비 비율 {a['positive_funding_ratio']}%"
                  f"  ← 100%에 가까울수록 시장 전체가 롱 편향")
    if b["usdkrw"]:
        print(f"  원달러 {b['usdkrw']:,.2f}원 (김프 계산 기준)")

    print("\n" + "=" * 80)
    print(f"선별 코인 {len(b['selected'])}개")
    print("=" * 80)
    for c in b["selected"]:
        k = c.get("kimchi") or {}
        print(f"  {c['symbol']:6s} #{c.get('rank') or '-':<3} {pct(c.get('change_pct'))}"
              f" |7일 {pct(c.get('change_7d'))} |시총 {money(c.get('market_cap')):>7s}"
              f" |거래대금 {money(c.get('turnover')):>7s}")
        line = (f"         펀딩 {fund_bp(c.get('funding_rate')):>9s}"
                f" |롱숏 {c.get('long_short_account') or '-'}"
                f" |상위계좌롱 {c.get('long_top_pct') or '-'}%"
                f" |OI 7일 {pct(c.get('oi_change_7d_pct'))}")
        if k:
            line += f" |김프 {k['premium_pct']:+.2f}%"
        print(line)
        print(f"         {','.join(c['reasons'])}  · ATH대비 {pct(c.get('ath_change_pct'))}")

    ns = b["news_stats"]
    print("\n" + "=" * 80)
    print("뉴스")
    print("=" * 80)
    print(f"  수집 {ns['collected']}건 → 기간외 {ns['stale_removed']} / 중복 "
          f"{ns['duplicates_removed']} 제거 → {ns['after_dedupe']}건 → 선별 "
          f"{ns['selected_for_llm']}건 (코인 태깅 {ns['coin_tagged']}건)")
    print(f"  코인 커버리지: {len(ns.get('covered') or [])}/{len(b['selected'])}개"
          + (f"  ← 뉴스 없음: {', '.join(ns['uncovered'])}"
             if ns.get("uncovered") else ""))
    for n in b["news_selected"][:12]:
        t = ",".join(n.get("coins") or []) or ",".join(n.get("topics") or []) or "-"
        d = (n.get("published") or "")[:10]
        print(f"   {d} [{n['label']:4s}] x{n.get('dup_count',1)} {n['title'][:52]}")
        print(f"              {t[:42]} | {n['source']}")


# ---------------------------------------------------------------- 프롬프트
def build_prompt(b):
    L = []
    A = L.append
    g, fg, a = b["global"], b["fear_greed"], b["aggregate"]

    A(f"# 암호화폐 시장 스냅샷 ({b['collected_at']})\n")

    A("## 시장 전체")
    A(f"- 총 시총 {money(g['total_market_cap_usd'])}"
      f" (24시간 {pct(g['market_cap_change_24h_pct'],0)}),"
      f" 거래대금 {money(g['total_volume_usd'])}")
    A(f"- BTC 도미넌스 {g['btc_dominance']}%, ETH 도미넌스 {g['eth_dominance']}%")
    if fg:
        line = f"- 공포탐욕 지수 {fg['value']} ({fg['rating']})"
        if fg.get("prev") is not None:
            line += f", 전일 {fg['prev']}"
        if fg.get("week_ago") is not None:
            line += f", 1주 전 {fg['week_ago']}"
        A(line)
    if a:
        A(f"- 시총 상위 100 중 상승 {a['up']} / 하락 {a['down']}"
          f" (상승비율 {a['up_ratio']}%), 등락률 중간값 {pct(a['median_change_pct'],0)}")
        if a.get("avg_funding_bp") is not None:
            A(f"- 평균 펀딩비 {a['avg_funding_bp']:+.2f}bp,"
              f" 양(+)의 펀딩비 비율 {a['positive_funding_ratio']}%")
            A("  ※ 펀딩비는 무기한 선물에서 롱이 숏에게 내는 비용이다(8시간 주기).")
            A("    양수면 롱 우위, 극단적으로 높으면 롱 과열로 청산 위험이 커진다.")
    if b["usdkrw"]:
        A(f"- 원달러 {b['usdkrw']:,.2f}원 (김치프리미엄 계산 기준)")

    # 파생 지표의 출처를 명시한다. 거래소가 다르면 펀딩비·롱숏비의 절대
    # 수준이 달라지므로, 출처가 바뀐 걸 모르면 없는 변화를 읽게 된다.
    src = b.get("derivatives_source", "binance")
    if src == "okx":
        A("\n### 파생 지표 출처: OKX")
        A("바이낸스가 이 환경에서 막혀(451, 약관상 지역 제한) OKX로 받았다.")
        A("**어제 인사이트가 바이낸스 기준이었다면 절대 수준을 직접 비교하지 마라.**")
        A("OKX는 바이낸스보다 거래대금이 작아 펀딩비·롱숏비의 진폭이 다르다.")
        A("방향과 순위는 유효하지만 수치의 크기는 거래소 안에서만 비교하라.")
        A("또 OI 7일 변화는 OKX가 해당 코인의 모든 파생상품을 합산한 값이라")
        A("바이낸스의 USDT 무기한 단일 종목 기준과 다를 수 있다.")
    else:
        A("\n### 파생 지표 출처: 바이낸스 USDT 무기한선물")

    A(f"\n## 선별 코인 {len(b['selected'])}개")
    A("선별 사유: 관심코인 / 급등 / 급락 / 거래대금상위 / 펀딩비극단")
    A("**사유별로 다르게 읽어라.** '펀딩비높음'은 가격이 안 올랐어도 포지션이")
    A("쏠렸다는 뜻이고, '거래대금상위'는 방향과 무관하게 자금이 몰렸다는 뜻이다.")
    for c in b["selected"]:
        A(f"\n### {c['symbol']} — {c.get('name')} (시총 {c.get('rank')}위)")
        A(f"- 사유: {', '.join(c['reasons'])}")
        A(f"- 가격 ${c.get('price'):,}" if c.get("price") else "- 가격 데이터 없음")
        A(f"- 등락: 1시간 {pct(c.get('change_1h'),0)}, 24시간 {pct(c.get('change_pct'),0)},"
          f" 7일 {pct(c.get('change_7d'),0)}, 사상최고 대비 {pct(c.get('ath_change_pct'),0)}")
        A(f"- 시총 {money(c.get('market_cap'))}, 현물 거래량 {money(c.get('volume_24h'))},"
          f" 선물 거래대금 {money(c.get('turnover'))}")
        if c.get("funding_rate") is not None:
            A(f"- 펀딩비 {fund_bp(c['funding_rate'])} (8시간 기준)")
        pos = []
        if c.get("open_interest"):
            pos.append(f"미결제약정 {c['open_interest']:,.0f}개")
        if c.get("oi_change_7d_pct") is not None:
            pos.append(f"7일 변화 {c['oi_change_7d_pct']:+.2f}%")
        if c.get("long_short_account"):
            pos.append(f"전체계좌 롱숏비 {c['long_short_account']}"
                       f"(롱 {c.get('long_account_pct')}%)")
        if c.get("long_short_top"):
            pos.append(f"상위계좌 롱숏비 {c['long_short_top']}"
                       f"(롱 {c.get('long_top_pct')}%)")
        if c.get("taker_buy_sell"):
            pos.append(f"테이커 매수/매도 {c['taker_buy_sell']}")
        if pos:
            A("- 포지셔닝: " + ", ".join(pos))
        k = c.get("kimchi")
        if k:
            A(f"- 김치프리미엄 {k['premium_pct']:+.2f}%"
              f" (업비트 {k['upbit_krw']:,.0f}원 vs 환산 {k['global_krw']:,}원),"
              f" 업비트 24h {pct(k['upbit_change_pct'],0)},"
              f" 업비트 거래대금 {money(k.get('upbit_turnover_krw'), '')}원")

    ns = b["news_stats"]
    A(f"\n## 뉴스 (최근 {U.NEWS_RECENT_DAYS}일)")
    A(f"전체 {ns['collected']}건에서 기간외·중복 제외 후 {ns['selected_for_llm']}건 선별"
      f" (코인 태깅 {ns['selected_coin']}건 포함).")
    if ns.get("uncovered"):
        A(f"**뉴스 근거를 못 찾은 코인: {', '.join(ns['uncovered'])}**")
        A("이 코인들은 아래 목록에 관련 기사가 없다. 움직임의 이유를 추측하지 말고")
        A("'뉴스에 근거 없음'이라고 명시하라.")
    A("형식: (날짜) [규칙판정] x보도매체수 <코인 또는 주제> 제목")
    for n in b["news_selected"]:
        t = ",".join(n.get("coins") or []) or ",".join(n.get("topics") or [])
        tag = f" <{t}>" if t else ""
        d = (n.get("published") or "")[:10] or "날짜미상"
        A(f"- ({d}) [{n['label']}] x{n.get('dup_count',1)}{tag} {n['title']}")
        if n.get("summary"):
            A(f"    {n['summary'][:160]}")

    A(pick.block("coin", b))

    A(session.request_block("coin", extra_sections="""
### 참고 — 이 데이터에서만 보이는 것
**가격 등락률 나열은 하지 마라.** 이 데이터의 가치는 가격이 아니라
포지셔닝에 있다.

- **가격과 미결제약정의 조합**을 각 코인마다 판단하라.
  · 가격↑ + OI↑ = 신규 자금 유입
  · 가격↑ + OI↓ = 숏 커버링 (지속성이 약하다)
  · 가격↓ + OI↑ = 물타기 (가장 위험하다)
  · 가격↓ + OI↓ = 디레버리징 (건전한 정리)
- **펀딩비가 극단인 코인**은 롱이 과밀하다는 뜻이고, 그 상태에서 가격이
  빠지면 연쇄 청산이 붙는다. 위험 구간의 코인을 지목하라.
- **상위계좌와 전체계좌 롱 비율의 차이**를 보라. 전체계좌는 소매,
  상위계좌는 큰손이다. 둘이 크게 벌어진 코인이 이 데이터의 알맹이다.
  단, **이 격차는 거래소마다 기준이 달라 절대 수준을 다른 거래소와
  비교하면 안 된다.** 같은 스냅샷 안에서 코인끼리 비교하라.
  테이커 매수/매도 비율과 함께 보면 방향이 더 분명해진다.
- **심리와 포지션의 괴리**를 찾아라. 공포탐욕이 낮은데 롱 비율이 높으면
  "심리는 얼었는데 포지션은 롱에 몰려 있다"는 뜻이다. 없으면 "없음"이라고 명시하라.
- **김치프리미엄** 절대값이 3%를 넘으면 이상 신호다. 그 아래면 원달러
  움직임을 감안해 해석하라.
- **BTC 도미넌스** 방향이 알트 자금 흐름을 시사한다."""))
    return "\n".join(L)


if __name__ == "__main__":
    run()
