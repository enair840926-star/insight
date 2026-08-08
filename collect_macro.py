# -*- coding: utf-8 -*-
"""매크로 수집기 — 실행 진입점

    python collect_macro.py

원자재 / 지수선물 / 채권금리 / 환율 / 변동성 / 글로벌지수 40개.
개별 등락보다 **금리 커브**와 **자산 간 괴리**가 핵심 산출물이다.
"""
import io
import json
import sys
import time
import datetime as dt
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import universe
from collectors import macro_market, macro_news, macro, commodity, eia, ecb
from core import env, history, pick, session

DATA_DIR = Path(__file__).parent / "data"
DATA_DIR.mkdir(exist_ok=True)

UNIT_SUFFIX = {"pct": "%", "usx": "¢", "usd": "", "idx": ""}


def fmt_price(r):
    p = r.get("price")
    if p is None:
        return "-"
    unit = r.get("unit", "usd")
    if unit == "pct":
        return f"{p:,.3f}%"
    if p >= 1000:
        return f"{p:,.0f}"
    if p >= 10:
        return f"{p:,.2f}"
    return f"{p:,.4f}"


def fmt_pct(v, width=6):
    return f"{v:+{width}.2f}%" if v is not None else " " * width


def run():
    t0 = time.time()
    now = dt.datetime.now()
    n = universe.symbol_count()
    print(f"매크로 데이터 수집 시작 — {now:%Y-%m-%d %H:%M}  (심볼 {n}개)\n")

    print("[1/3] 시세·추세 …", end=" ", flush=True)
    records = macro_market.collect(universe.all_symbols,
                                   universe.FETCH_RANGE, universe.MAX_WORKERS)
    ok = [r for r in records if not r.get("error")]
    print(f"{len(ok)}/{len(records)}개")

    print("[2/3] 파생 지표 (커브·괴리·이상치) …", end=" ", flush=True)
    curve = macro_market.yield_curve(records, universe.CURVE_PAIRS)
    diverg = macro_market.divergences(records, universe.MACRO_RELATIONS)
    tops = macro_market.outliers(records)
    broken = sum(1 for d in diverg if d["broken"])
    # 유로존 10년물 — 야후에 독일 국채 심볼이 없어 ECB에서 따로 받는다.
    # 미-유로존 금리차 계산에 쓴다.
    eu10 = ecb.get_10y()
    print(f"커브 {len(curve)} / 관계 {len(diverg)}(깨짐 {broken})"
          + (f" / 유로존10Y {eu10['price']}%" if eu10 else " / 유로존10Y 실패"))

    print("[3/4] 원자재 심화 (COT·선물커브·ETF) …", end=" ", flush=True)
    front = {r["name"]: r["price"] for r in records
             if not r.get("error") and r.get("price")}
    cot = commodity.collect_cot(universe.COT_PATTERNS)
    curves = commodity.collect_curves(universe.CURVE_SPEC, front)
    etfs = commodity.collect_etf(universe.COMMODITY_ETFS)
    cot_ext = commodity.cot_extremes(cot, universe.COT_RATIO_HIGH,
                                     universe.COT_RATIO_LOW)
    # EIA 재고 — 키가 없으면 통째로 건너뛴다
    eia_key = env.get("EIA_API_KEY")
    inventories = eia.collect(universe.EIA_SERIES, eia_key)
    inv_read = eia.readings(inventories, universe.EIA_TIGHT_PCT,
                            universe.EIA_LOOSE_PCT)
    inv_msg = (f" / 재고 {len(inventories)}" if inventories
               else " / 재고 건너뜀(EIA_API_KEY 없음)")
    print(f"COT {len(cot)} / 커브 {len(curves)} / ETF {len(etfs)}"
          f" (쏠림 {len(cot_ext)}건){inv_msg}")

    print("[4/4] 뉴스·센티먼트 …", end=" ", flush=True)
    selected, deduped, news_stats = macro_news.collect(
        universe.MACRO_RSS, universe.MACRO_GOOGLE_QUERIES,
        universe.MACRO_TOPICS, universe.NEWS_RECENT_DAYS)
    sent = macro.get_sentiment()
    print(f"{news_stats['collected']}건 → {news_stats['selected_for_llm']}건 선별\n")

    bundle = {
        "collected_at": now.isoformat(timespec="seconds"),
        "market": "MACRO",
        "records": records,
        "yield_curve": curve,
        "divergences": diverg,
        "outliers": tops,
        "eurozone_10y": eu10,
        "cot": cot,
        "cot_extremes": cot_ext,
        "curves": curves,
        "commodity_etfs": etfs,
        "inventories": inventories,
        "inventory_readings": inv_read,
        "sentiment": sent,
        "news_stats": news_stats,
        "news_selected": selected,
        "news_all": deduped,
    }

    stamp = f"{now:%Y%m%d_%H%M}"
    out = DATA_DIR / f"macro_{stamp}.json"
    out.write_text(json.dumps(bundle, ensure_ascii=False, indent=1),
                   encoding="utf-8")
    prompt = build_prompt(bundle)
    pout = DATA_DIR / f"prompt_macro_{stamp}.txt"
    pout.write_text(prompt, encoding="utf-8")

    done, made = history.track("macro", bundle)
    if done or made:
        print(f"기록: 결과 {done}건 채움 / 픽 {made}건 남김")

    report(bundle)
    print(f"\n원자료  : {out}")
    print(f"LLM재료 : {pout}  ({len(prompt):,}자)")
    print(f"소요    : {time.time() - t0:.1f}초")
    return bundle


# ---------------------------------------------------------------- 콘솔
def report(b):
    by_group = {}
    for r in b["records"]:
        by_group.setdefault(r["group"], []).append(r)

    for group, items in by_group.items():
        print("=" * 74)
        print(group)
        print("=" * 74)
        for r in items:
            if r.get("error"):
                print(f"  [X] {r['name']:12s} {r['error']}")
                continue
            print(f"  {r['name']:12s} {fmt_price(r):>12s} {fmt_pct(r.get('change_pct'))}"
                  f"  |5일 {fmt_pct(r.get('change_5d_pct'))}"
                  f" |20일 {fmt_pct(r.get('change_20d_pct'))}"
                  f" |20MA {fmt_pct(r.get('vs_ma20_pct'))}"
                  f" |52주위치 {str(r.get('pos_52w', '-')):>5}")
        print()

    if b["yield_curve"]:
        print("=" * 74)
        print("금리 커브")
        print("=" * 74)
        for c in b["yield_curve"]:
            tag = " ⚠역전" if c["inverted"] else ""
            shape = f"  → {c['shape_move']} ({c['shape_gap']:+.2f}%p)" if c.get("shape_move") else ""
            print(f"  {c['label']:9s} {c['spread_bp']:+8.1f}bp{tag}{shape}")
            print(f"      {c['long']['name']} {fmt_pct(c['long']['change_pct'])}"
                  f" / {c['short']['name']} {fmt_pct(c['short']['change_pct'])}")
        print()

    if b["divergences"]:
        print("=" * 74)
        print("자산 간 관계  (★ = 통상 관계가 깨진 것)")
        print("=" * 74)
        for d in sorted(b["divergences"], key=lambda x: not x["broken"]):
            mark = "★" if d["broken"] else " "
            print(f"  {mark} {d['pair']:28s} {d['a']['change_pct']:+6.2f}% / "
                  f"{d['b']['change_pct']:+6.2f}%  (통상 {d['expected']})")
        print()

    if b.get("cot"):
        print("=" * 74)
        print("COT 투기 포지셔닝  (CFTC 주간 보고, ★ = 극단 쏠림)")
        print("=" * 74)
        ext = {e["name"] for e in b.get("cot_extremes") or []}
        for name, d in sorted(b["cot"].items(),
                              key=lambda kv: -abs(kv[1].get("spec_net_pct_oi") or 0)):
            mark = "★" if name in ext else " "
            chg = d.get("spec_net_change")
            chg_s = f"{chg:+,}" if chg is not None else "-"
            print(f"  {mark} {name:8s} 롱숏비 {d.get('spec_ratio') or '-':>6}"
                  f" | 순포지션 {d.get('spec_net') or 0:>+9,}"
                  f" (OI의 {d.get('spec_net_pct_oi') or 0:+5.1f}%)"
                  f" | 전주대비 {chg_s:>9s}")
        rd = next(iter(b["cot"].values())).get("report_date")
        print(f"    보고 기준일 {rd} (매주 화요일 집계, 금요일 발표)")
        print()

    if b.get("curves"):
        print("=" * 74)
        print("선물 커브  (근월 대비 최원월)")
        print("=" * 74)
        for name, c in sorted(b["curves"].items(), key=lambda kv: kv[1]["spread_pct"]):
            season = "" if c["monotonic"] else "  ※계절성(비단조)"
            print(f"  {name:8s} {c['shape']:6s} {c['spread_pct']:+6.2f}%"
                  f"  근월 {c['front_price']:>9,.2f} → {c['far_label']} {c['far_price']:>9,.2f}{season}")
        print()

    if b.get("inventories"):
        print("=" * 74)
        rd = next(iter(b["inventories"].values())).get("period")
        print(f"EIA 주간 재고  (기준 {rd}, ★ = 평년 대비 이탈)")
        print("=" * 74)
        state_of = {r["name"]: r for r in (b.get("inventory_readings") or [])}
        for name, d in b["inventories"].items():
            r = state_of.get(name)
            mark = "★" if r and r["state"] != "평년수준" else " "
            v5 = d.get("vs_5y_avg_pct")
            yo = d.get("vs_year_ago_pct")
            print(f"  {mark} {name:14s} {d['value']:>11,.0f} {d['unit']:<6s}"
                  f" 주간 {d.get('change_1w', 0):>+9,.0f}"
                  f" | 평년대비 {f'{v5:+6.1f}%' if v5 is not None else '   -  '}"
                  f" | 전년대비 {f'{yo:+6.1f}%' if yo is not None else '   -  '}"
                  f"  {r['state'] if r else ''}")
        print()

    if b.get("commodity_etfs"):
        print("=" * 74)
        print("원자재 ETF  (거래량 = 20일 평균 대비)")
        print("=" * 74)
        for name, e in sorted(b["commodity_etfs"].items(),
                              key=lambda kv: -(kv[1].get("volume_ratio") or 0)):
            print(f"  {name:12s} {e['symbol']:5s} {fmt_pct(e.get('change_pct'))}"
                  f"  |20일 {fmt_pct(e.get('change_20d_pct'))}"
                  f"  |거래량 {e.get('volume_ratio', '-')}배")
        print()

    print("=" * 74)
    print("오늘의 이상치")
    print("=" * 74)
    for key, label in (("biggest_moves", "당일 등락"), ("trend_20d", "20일 추세"),
                       ("stretched", "20일선 이격")):
        rows = b["outliers"].get(key) or []
        if rows:
            top = "  ".join(f"{r['name']} {r['value']:+.1f}%" for r in rows[:5])
            print(f"  {label:10s} {top}")

    s = b.get("sentiment") or {}
    if s.get("us_fear_greed"):
        f = s["us_fear_greed"]
        print(f"\n  미 증시 공포탐욕 {f['score']} ({f['rating']}), 1주 전 {f['week_ago']}")

    ns = b["news_stats"]
    print("\n" + "=" * 74)
    print("뉴스")
    print("=" * 74)
    print(f"  수집 {ns['collected']}건 → 기간외 {ns['stale_removed']} / 중복 "
          f"{ns['duplicates_removed']} 제거 → {ns['after_dedupe']}건 "
          f"→ 선별 {ns['selected_for_llm']}건 (주제 태깅 {ns['topic_tagged']}건)")
    for n in b["news_selected"][:10]:
        g = ",".join(n.get("groups") or []) or "-"
        d = (n.get("published") or "")[:10]
        print(f"   {d} [{n['label']:4s}] x{n.get('dup_count',1)} {n['title'][:52]}")
        print(f"              {g} | {n['source']}")


# ---------------------------------------------------------------- 프롬프트
def build_prompt(b):
    L = []
    A = L.append
    A(f"# 매크로 시장 스냅샷 ({b['collected_at']})")
    A("원자재 / 지수선물 / 채권금리 / 환율 / 변동성 / 글로벌지수\n")

    by_group = {}
    for r in b["records"]:
        by_group.setdefault(r["group"], []).append(r)

    A("## 시세")
    A("형식: 이름 | 현재가 | 당일 | 5일 | 20일 | 20일선대비 | 52주위치(0=최저,100=최고) | 20일변동성")
    for group, items in by_group.items():
        A(f"\n### {group}")
        for r in items:
            if r.get("error"):
                A(f"- {r['name']}: 조회 실패")
                continue
            A(f"- {r['name']}: {fmt_price(r)} | {fmt_pct(r.get('change_pct'),0)}"
              f" | 5일 {fmt_pct(r.get('change_5d_pct'),0)}"
              f" | 20일 {fmt_pct(r.get('change_20d_pct'),0)}"
              f" | 20MA대비 {fmt_pct(r.get('vs_ma20_pct'),0)}"
              f" | 52주위치 {r.get('pos_52w','-')}"
              f" | 변동성 {r.get('volatility_20d','-')}")

    if b["yield_curve"]:
        A("\n## 금리 커브")
        A("장단기 스프레드는 개별 금리보다 정보량이 크다. 부호와 방향을 함께 보라.")
        for c in b["yield_curve"]:
            line = f"- {c['label']}: {c['spread_bp']:+.1f}bp"
            if c["inverted"]:
                line += " (역전 상태)"
            if c.get("shape_move"):
                line += f" — 오늘 {c['shape_move']} ({c['shape_gap']:+.2f}%p)"
            A(line)
            A(f"    {c['long']['name']} {fmt_pct(c['long']['change_pct'],0)},"
              f" {c['short']['name']} {fmt_pct(c['short']['change_pct'],0)} / {c['note']}")

    if b["divergences"]:
        A("\n## 자산 간 관계 점검")
        A("아래는 '통상적으로 이렇게 움직인다'는 경험칙과 오늘 실제 움직임의 대조다.")
        A("[깨짐]은 통상 관계와 반대로 움직였다는 뜻이며, 그 자체가 신호다.")
        for d in sorted(b["divergences"], key=lambda x: not x["broken"]):
            state = "깨짐" if d["broken"] else "정상"
            A(f"- [{state}] {d['pair']}: {d['a']['change_pct']:+.2f}% vs"
              f" {d['b']['change_pct']:+.2f}% (통상 {d['expected']}관계) — {d['note']}")

    if b.get("cot"):
        rd = next(iter(b["cot"].values())).get("report_date")
        A(f"\n## COT 투기 포지셔닝 (CFTC 주간 보고, 기준일 {rd})")
        A("CFTC가 매주 발표하는 실제 포지션 보고다. 추정치가 아니라 법적")
        A("보고 의무에 따른 수치라 신뢰도가 높다.")
        A("- 투기(noncommercial) = 헤지펀드·CTA. 방향성 베팅.")
        A("- 상업(commercial) = 생산자·정유사. 실물 헤지라 통상 투기의 반대편.")
        A("- 투기 롱숏비가 극단이면 반전 시 청산이 연쇄한다 (코인 펀딩비와 같은 성격).")
        A("- 순포지션의 전주 대비 변화가 절대 수준보다 중요할 때가 많다.")
        for name, d in sorted(b["cot"].items(),
                              key=lambda kv: -abs(kv[1].get("spec_net_pct_oi") or 0)):
            chg = d.get("spec_net_change")
            A(f"- {name} ({d.get('contract')}): 투기 롱 {d.get('spec_long'):,} /"
              f" 숏 {d.get('spec_short'):,} (비율 {d.get('spec_ratio')}),"
              f" 순 {d.get('spec_net'):+,} = 미결제약정의 {d.get('spec_net_pct_oi')}%"
              + (f", 전주 대비 {chg:+,}" if chg is not None else "")
              + f" | 상업 순 {d.get('comm_net'):+,}"
              + (f", 미결제약정 {d.get('oi_change_pct'):+.2f}%"
                 if d.get("oi_change_pct") is not None else ""))

    if b.get("cot_extremes"):
        A("\n### 투기 포지션 극단 쏠림")
        for e in b["cot_extremes"]:
            A(f"- {e['name']}: {e['side']} (롱숏비 {e['ratio']},"
              f" 순포지션이 미결제약정의 {e['net_pct_oi']}%)"
              + (f", 전주 대비 {e['change']:+,}" if e.get("change") is not None else ""))

    if b.get("curves"):
        A("\n## 선물 커브")
        A("근월이 원월보다 비싸면 백워데이션 = 현물이 급하다 = 공급 타이트.")
        A("원월이 비싸면 콘탱고 = 보관비용 정상 또는 공급 여유.")
        A("※ 비단조 표시가 있으면 계절성 상품이라 단순 판정이 안 된다.")
        for name, c in sorted(b["curves"].items(), key=lambda kv: kv[1]["spread_pct"]):
            pts = " → ".join(f"{p['label']} {p['price']:,.2f}" for p in c["points"])
            A(f"- {name}: {c['shape']} ({c['spread_pct']:+.2f}%)"
              f"{'' if c['monotonic'] else ' [비단조·계절성]'}")
            A(f"    근월 {c['front_price']:,.2f} → {pts}")

    if b.get("inventories"):
        rd = next(iter(b["inventories"].values())).get("period")
        A(f"\n## EIA 주간 재고 (기준 {rd})")
        A("재고는 계절성이 강해 절대값만으로는 판단할 수 없다. 겨울에 천연가스가")
        A("줄고 여름에 휘발유가 주는 건 정상이다. **평년(5년 평균) 대비**를 보라.")
        A("- 평년 대비 -5% 이하: 타이트 / +5% 이상: 과잉")
        A("- 재고는 '사실', 선물커브는 '기대', COT는 '포지션'이다. 셋을 교차하라.")
        state_of = {r["name"]: r for r in (b.get("inventory_readings") or [])}
        for name, d in b["inventories"].items():
            r = state_of.get(name)
            parts = [f"{d['value']:,.0f}{d['unit']}"]
            if d.get("change_1w") is not None:
                parts.append(f"주간 {d['change_1w']:+,.0f}")
            if d.get("change_4w") is not None:
                parts.append(f"4주 {d['change_4w']:+,.0f}")
            if d.get("vs_5y_avg_pct") is not None:
                parts.append(f"평년대비 {d['vs_5y_avg_pct']:+.1f}%")
            if d.get("vs_year_ago_pct") is not None:
                parts.append(f"전년대비 {d['vs_year_ago_pct']:+.1f}%")
            A(f"- {name}: " + ", ".join(parts)
              + (f"  → {r['state']}" if r else ""))

    if b.get("commodity_etfs"):
        A("\n## 원자재 ETF (거래량은 자금 관심도의 대용 지표)")
        for name, e in sorted(b["commodity_etfs"].items(),
                              key=lambda kv: -(kv[1].get("volume_ratio") or 0)):
            A(f"- {name}({e['symbol']}): {fmt_pct(e.get('change_pct'),0)},"
              f" 20일 {fmt_pct(e.get('change_20d_pct'),0)},"
              f" 거래량 20일평균의 {e.get('volume_ratio','-')}배")

    A("\n## 오늘의 이상치")
    for key, label in (("biggest_moves", "당일 등락 상위"),
                       ("trend_20d", "20일 추세 상위"),
                       ("stretched", "20일선 이격 상위"),
                       ("high_vol", "변동성 상위")):
        rows = b["outliers"].get(key) or []
        if rows:
            A(f"- {label}: " + ", ".join(
                f"{r['name']} {r['value']:+.1f}" for r in rows[:6]))

    s = b.get("sentiment") or {}
    if s:
        A("\n## 센티먼트")
        if s.get("us_fear_greed"):
            f = s["us_fear_greed"]
            A(f"- 미 증시 공포탐욕: {f['score']} ({f['rating']}),"
              f" 전일 {f['prev_close']} / 1주 전 {f['week_ago']}")
        if s.get("crypto_fear_greed"):
            f = s["crypto_fear_greed"]
            A(f"- 코인 공포탐욕: {f['score']} ({f['rating']})")

    ns = b["news_stats"]
    A(f"\n## 뉴스 (최근 {universe.NEWS_RECENT_DAYS}일)")
    A(f"전체 {ns['collected']}건에서 기간외·중복을 제외하고 {ns['selected_for_llm']}건 선별.")
    A("형식: (날짜) [규칙판정] x보도매체수 <영향 그룹> 제목")
    for n in b["news_selected"]:
        g = ",".join(n.get("groups") or [])
        tag = f" <{g}>" if g else ""
        d = (n.get("published") or "")[:10] or "날짜미상"
        A(f"- ({d}) [{n['label']}] x{n.get('dup_count',1)}{tag} {n['title']}")
        if n.get("summary"):
            A(f"    {n['summary'][:160]}")

    A(pick.block("macro", b))

    A(session.request_block("macro", extra_sections="""
### 참고 — 이 데이터에서만 보이는 것
**개별 자산의 등락률 나열은 하지 마라.** 그건 어디서나 볼 수 있다.
43개 자산을 나란히 놓았을 때만 보이는 것을 써라.

- **깨진 관계**([깨짐] 표시)를 최우선으로 다뤄라. 통상 관계가 깨졌다면
  (a) 일시적 노이즈인지 (b) 국면 전환인지 판단하고 근거를 대라.
  깨진 관계가 없으면 "없음"이라고 명시하라 — 그것도 정보다.
- **원자재 3축을 교차하라.** COT는 포지션, 선물커브는 기대, 재고는 사실이다.
  · 재고가 평년 대비 타이트한데 커브도 백워데이션이면 실물 수급 문제다.
    이 경우 가격 하락은 되돌려질 여지가 있다.
  · 재고는 평년 수준인데 커브만 백워데이션이면 지정학·심리 프리미엄이고,
    그 요인이 풀리면 커브가 먼저 무너진다.
  · COT 순포지션의 **전주 대비 변화**를 보라. 절대 수준보다 방향 전환이 빠르다.
- **금리 커브**의 부호와 오늘 방향(스티프닝/플래트닝)을 함께 읽어라.
- **원자재 내부 분화** — 금속·에너지·농산물이 갈렸다면 무엇이 그 차이를
  만드는지 짚어라. 한 덩어리로 보면 안 된다.
- 계절성 표시([비단조])가 붙은 커브는 단순 판정을 하지 마라."""))
    return "\n".join(L)


if __name__ == "__main__":
    run()
