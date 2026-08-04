# -*- coding: utf-8 -*-
"""모바일 대시보드 생성기

    python dashboard.py            # data/latest.html 생성
    python dashboard.py --serve    # 생성 후 폰에서 볼 수 있게 서버까지

의존성 0. 표준 라이브러리만 쓴다 (Node.js도 FastAPI도 필요 없다).
수집기가 만든 JSON 4개를 읽어 단일 HTML로 굽는다.
"""
import io
import json
import glob
import os
import sys
import socket
import datetime as dt
from pathlib import Path

# 주의: stdout 재설정은 모듈 최상단에 두면 안 된다.
# run.py가 이 모듈을 import할 때 실행되면서 run.py가 이미 감싼
# stdout의 buffer를 다시 감싸고, 원본이 닫혀 ValueError가 난다.
# 직접 실행할 때만 __main__ 블록에서 설정한다.

ROOT = Path(__file__).parent
DATA = ROOT / "data"
OUT = DATA / "latest.html"

MARKETS = [
    ("kr", "국장", "🇰🇷"),
    ("us", "미장", "🇺🇸"),
    ("macro", "매크로", "🌍"),
    ("coin", "코인", "₿"),
]


# ---------------------------------------------------------------- 유틸
def latest_json(prefix):
    """로컬 수집분과 클라우드 수집분 중 최신. core/store.py 참고."""
    from core import store
    p = store.latest(f"{prefix}_2*.json")
    if not p:
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return None


def esc(s):
    return (str(s if s is not None else "")
            .replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&quot;"))


def pct(v, digits=2):
    """한국식: 상승 빨강, 하락 파랑"""
    if v is None:
        return '<span class="dim">-</span>'
    cls = "up" if v > 0 else ("down" if v < 0 else "flat")
    return f'<span class="{cls}">{v:+.{digits}f}%</span>'


def num(v, digits=0):
    if v is None:
        return "-"
    return f"{v:,.{digits}f}"


def money_krw(v):
    if not v:
        return "-"
    if v >= 1e12:
        return f"{v/1e12:.1f}조"
    if v >= 1e8:
        return f"{v/1e8:,.0f}억"
    return f"{v:,.0f}"


def money_usd(v):
    if not v:
        return "-"
    if v >= 1e12:
        return f"${v/1e12:.2f}T"
    if v >= 1e9:
        return f"${v/1e9:.0f}B"
    if v >= 1e6:
        return f"${v/1e6:.0f}M"
    return f"${v:,.0f}"


def card(title, body, sub=""):
    s = f'<div class="csub">{esc(sub)}</div>' if sub else ""
    return f'<section class="card"><h2>{esc(title)}</h2>{s}{body}</section>'


def kv_grid(pairs):
    """[(라벨, HTML값), ...] -> 격자"""
    cells = "".join(f'<div class="kv"><span class="k">{esc(k)}</span>'
                    f'<span class="v">{v}</span></div>' for k, v in pairs)
    return f'<div class="grid">{cells}</div>'


def rows_table(headers, rows, aligns=None):
    aligns = aligns or ["l"] * len(headers)
    th = "".join(f'<th class="a{a}">{esc(h)}</th>' for h, a in zip(headers, aligns))
    body = ""
    for r in rows:
        tds = "".join(f'<td class="a{a}">{c}</td>' for c, a in zip(r, aligns))
        body += f"<tr>{tds}</tr>"
    return f'<div class="scroll"><table><thead><tr>{th}</tr></thead><tbody>{body}</tbody></table></div>'


def badges(items):
    return "".join(f'<span class="badge">{esc(x)}</span>' for x in items)


# 이벤트로 뽑힌 종목은 좌측 스트라이프로도 표시한다 — 색만으로 구분하지 않는다
_HOT = ("급등", "급락", "펀딩비높음", "펀딩비낮음")


def hot_class(reasons):
    return " hot" if any(any(h in r for h in _HOT) for r in (reasons or [])) else ""


def news_list(items, limit=15):
    out = ""
    for n in items[:limit]:
        tag = (",".join(n.get("tickers") or n.get("coins") or
                        [a[1] for a in (n.get("assets") or []) if len(a) > 1] or
                        n.get("groups") or n.get("topics") or n.get("sectors") or []))
        lab = n.get("label") or ""
        lc = {"긍정": "up", "약긍정": "up", "부정": "down", "약부정": "down"}.get(lab, "flat")
        d = (n.get("published") or "")[:10]
        dup = n.get("dup_count", 1)
        dup_s = f'<span class="dup">×{dup}</span>' if dup > 1 else ""
        link = esc(n.get("link") or "#")
        out += (f'<a class="news" href="{link}" target="_blank" rel="noopener">'
                f'<div class="nmeta"><span class="{lc}">{esc(lab)}</span>'
                f'<span class="dim">{esc(d)}</span>{dup_s}'
                f'{f"<span class=tag>{esc(tag)}</span>" if tag else ""}</div>'
                f'<div class="ntitle">{esc(n.get("title"))}</div>'
                f'<div class="nsrc">{esc(n.get("source"))}</div></a>')
    return f'<div class="newswrap">{out}</div>'


def insight_slot(market_name):
    """생성된 인사이트가 있으면 렌더링하고, 없으면 안내를 띄운다."""
    src = DATA / f"insight_{market_name}.md"
    if src.exists():
        from core import md
        text = src.read_text(encoding="utf-8").strip()
        if text:
            when = dt.datetime.fromtimestamp(src.stat().st_mtime)
            return (f'<section class="card insight has"><h2>인사이트</h2>'
                    f'<div class="csub">{when:%m월 %d일 %H:%M} 생성 · '
                    f'투자 권유가 아닌 정보 정리입니다</div>'
                    f'<div class="md">{md.render(text)}</div></section>')
    return (f'<section class="card insight"><h2>인사이트</h2>'
            f'<div class="empty"><p>아직 생성되지 않았습니다.</p>'
            f'<p class="dim">.env에 <code>ANTHROPIC_API_KEY</code>를 넣고 '
            f'<code>python insight.py</code>를 실행하면 여기 표시됩니다.</p>'
            f'<p class="dim">지금은 <code>data/prompt_{esc(market_name)}_*.txt</code> '
            f'파일이 준비된 상태입니다.</p></div></section>')


# ---------------------------------------------------------------- 국장
def render_kr(j):
    h = ""
    idx = [(i["name"], f'{num(i["close"], 2)} {pct(i.get("change_pct"))}')
           for i in j.get("indices", [])]
    a = j.get("aggregate") or {}
    br = a.get("breadth") or {}
    if br:
        idx.append(("상승/하락", f'<span class="up">{br["up"]:,}</span> / '
                                 f'<span class="down">{br["down"]:,}</span>'))
        idx.append(("상승비율", f'{br["up_ratio"]}%'))
        idx.append(("시총가중", pct(a.get("market_cap_weighted_pct"))))
    h += card("지수 · 시장폭", kv_grid(idx))

    h += insight_slot("kr")

    km = j.get("kr_macro") or {}
    if km:
        rows = []
        for name, d in km.items():
            if not d or d.get("error"):
                continue
            extra = ""
            if d.get("yoy_pct") is not None:
                extra = f'전년동월비 {pct(d["yoy_pct"])}'
            elif d.get("change_1m") is not None:
                extra = f'전월 {d["change_1m"]:+,.2f}'
            rows.append([esc(name), f'{num(d["value"], 2)} <span class="dim">'
                                    f'{esc(d.get("unit") or "")}</span>',
                         extra, f'<span class="dim">{esc(d["period"])}</span>'])
        h += card("국내 거시 (한국은행)",
                  rows_table(["지표", "값", "변화", "기준"], rows, ["l", "r", "r", "r"]))

    for key, title in (("industries", "업종"), ("themes", "테마")):
        g = j.get(key) or []
        if not g:
            continue
        top = g[:6]
        bot = g[-4:]
        rows = [[esc(x["name"]), pct(x["change_pct"]),
                 f'{x["rise"]}/{x["count"]}',
                 f'<span class="dim">{x["up_ratio"]}%</span>'] for x in top + bot]
        h += card(f"{title} 등락", rows_table(
            ["이름", "등락", "상승", "비율"], rows, ["l", "r", "r", "r"]),
            f"상위 6 · 하위 4 (전체 {len(g)}개)")

    stocks = j.get("stocks") or []
    if stocks:
        body = ""
        for s in stocks:
            if s.get("error"):
                continue
            f_ = s.get("fundamentals") or {}
            g_ = s.get("signals") or {}
            t = (s.get("trend") or [{}])[0]
            close = t.get("close")
            chg = s.get("snapshot_change_pct")
            body += (
                f'<div class="stock{hot_class(s.get("reasons"))}"><div class="srow">'
                f'<div><span class="sname">{esc(s["name"])}</span> '
                f'<span class="dim">{esc(s["code"])}</span></div>'
                f'<div class="sprice">{num(close)}원 {pct(chg)}</div></div>'
                f'<div class="sbadges">{badges(s.get("reasons") or [])}'
                f'<span class="badge sec">{esc(s.get("industry") or "-")}</span></div>'
                f'<div class="sstats">'
                f'<span>시총 {money_krw(s.get("market_cap"))}</span>'
                f'<span>PER {num(f_.get("per"), 2)}배</span>'
                f'<span>추정 {num(f_.get("est_per"), 2)}배</span>'
                f'<span>외국인5일 {num(g_.get("foreign_net_5d"))}</span>'
                f'<span>기관5일 {num(g_.get("organ_net_5d"))}</span>'
                f'<span>20MA {pct(g_.get("vs_ma20_pct"))}</span>'
                f'</div></div>')
        h += card(f"선별 종목 {len(stocks)}개", body,
                  f"전종목 {j.get('select_stats', {}).get('fetched', 0):,}개에서 동적 선별")

    ns = j.get("news_stats") or {}
    sub = f"{ns.get('collected', 0):,}건 수집 → {ns.get('selected_for_llm', 0)}건 선별"
    if ns.get("uncovered"):
        sub += f" · 뉴스 없음: {', '.join(ns['uncovered'])}"
    h += card("뉴스", news_list(j.get("news_selected") or []), sub)
    return h


# ---------------------------------------------------------------- 미장
def render_us(j):
    h = ""
    idx = [(k, f'{num(v.get("price"), 2)} {pct(v.get("change_pct"))}')
           for k, v in (j.get("indices") or {}).items()]
    a = j.get("aggregate") or {}
    br = a.get("breadth") or {}
    if br:
        idx.append(("상승/하락", f'<span class="up">{br["up"]:,}</span> / '
                                 f'<span class="down">{br["down"]:,}</span>'))
        idx.append(("시총가중", pct(a.get("market_cap_weighted_pct"))))
    h += card("지수 · 시장폭", kv_grid(idx))
    h += insight_slot("us")

    secs = a.get("sectors") or []
    if secs:
        rows = [[esc(s["sector"]), pct(s["cap_weighted_pct"]),
                 f'{s["up_ratio"]}%', f'${s["turnover_bil"]:,.0f}B']
                for s in secs]
        h += card("섹터", rows_table(["섹터", "시총가중", "상승비율", "거래대금"],
                                    rows, ["l", "r", "r", "r"]))

    sel = j.get("selected") or []
    if sel:
        body = ""
        for s in sel:
            body += (
                f'<div class="stock{hot_class(s.get("reasons"))}"><div class="srow">'
                f'<div><span class="sname">{esc(s["symbol"])}</span> '
                f'<span class="dim">{esc((s.get("name") or "")[:26])}</span></div>'
                f'<div class="sprice">${num(s.get("price"), 2)} {pct(s.get("change_pct"))}</div>'
                f'</div>'
                f'<div class="sbadges">{badges(s.get("reasons") or [])}'
                f'<span class="badge sec">{esc(s.get("sector") or "-")}</span></div>'
                f'<div class="sstats">'
                f'<span>시총 {money_usd(s.get("market_cap"))}</span>'
                f'<span>거래대금 {money_usd(s.get("turnover"))}</span>'
                f'<span>20MA {pct(s.get("vs_ma20_pct"))}</span>'
                f'<span>52주 {num(s.get("pos_52w"), 1)}</span>'
                f'<span>거래량 {num(s.get("volume_ratio"), 2)}배</span>'
                f'</div></div>')
        h += card(f"선별 종목 {len(sel)}개", body,
                  f"전종목 {j.get('select_stats', {}).get('total', 0):,}개에서 동적 선별")

    ea = j.get("earnings") or []
    if ea:
        rows = [[f'{"★ " if e.get("watched") else ""}{esc(e["symbol"])}',
                 esc((e.get("name") or "")[:22]), esc(e.get("time")),
                 esc(e.get("eps_forecast")), f'<span class="dim">{esc(e["date"])}</span>']
                for e in ea[:12]]
        h += card("실적 발표", rows_table(
            ["티커", "회사", "시점", "예상EPS", "날짜"], rows, ["l", "l", "l", "r", "r"]))

    ec = j.get("econ") or []
    if ec:
        rows = [[esc((e.get("event") or "")[:34]), esc(e.get("actual") or "-"),
                 esc(e.get("consensus") or "-"), esc(e.get("previous") or "-")]
                for e in ec[:10]]
        h += card("경제지표", rows_table(["지표", "실제", "예상", "이전"],
                                       rows, ["l", "r", "r", "r"]))

    ns = j.get("news_stats") or {}
    sub = f"{ns.get('collected', 0):,}건 수집 → {ns.get('selected_for_llm', 0)}건 선별"
    if ns.get("uncovered"):
        sub += f" · 뉴스 없음: {', '.join(ns['uncovered'])}"
    h += card("뉴스", news_list(j.get("news_selected") or []), sub)
    return h


# ---------------------------------------------------------------- 매크로
def render_macro(j):
    h = ""
    recs = j.get("records") or []
    groups = {}
    for r in recs:
        if not r.get("error"):
            groups.setdefault(r["group"], []).append(r)

    yc = j.get("yield_curve") or []
    if yc:
        rows = [[esc(c["label"]), f'{c["spread_bp"]:+,.1f}bp',
                 esc(c.get("shape_move") or "-"),
                 f'<span class="dim">{"역전" if c["inverted"] else ""}</span>']
                for c in yc]
        h += card("금리 커브", rows_table(["구간", "스프레드", "오늘", ""],
                                        rows, ["l", "r", "r", "r"]))
    h += insight_slot("macro")

    dv = j.get("divergences") or []
    if dv:
        rows = [[('<span class="brk">★</span> ' if d["broken"] else "") + esc(d["pair"]),
                 pct(d["a"]["change_pct"]), pct(d["b"]["change_pct"]),
                 f'<span class="dim">통상 {esc(d["expected"])}</span>']
                for d in sorted(dv, key=lambda x: not x["broken"])]
        h += card("자산 간 관계", rows_table(["쌍", "A", "B", ""], rows,
                                          ["l", "r", "r", "r"]),
                  "★ = 통상 관계가 깨진 것")

    for g, items in groups.items():
        rows = [[esc(r["name"]), num(r.get("price"), 2), pct(r.get("change_pct")),
                 pct(r.get("change_20d_pct")),
                 f'<span class="dim">{num(r.get("pos_52w"), 0)}</span>']
                for r in items]
        h += card(g, rows_table(["이름", "현재가", "당일", "20일", "52주"],
                                rows, ["l", "r", "r", "r", "r"]))

    inv = j.get("inventories") or {}
    if inv:
        state = {r["name"]: r for r in (j.get("inventory_readings") or [])}
        rows = []
        for name, d in inv.items():
            st = state.get(name, {})
            s_ = st.get("state", "")
            # 재고 판정은 등락이 아니다. 등락 색(적/청)과 섞지 않고 의미색을 쓴다.
            cell = (f'<span class="chip">{esc(s_)}</span>' if s_ in ("타이트", "과잉")
                    else f'<span class="dim">{esc(s_)}</span>')
            rows.append([esc(name), f'{num(d["value"])} <span class="dim">{esc(d["unit"])}</span>',
                         f'{d.get("change_1w", 0):+,.0f}',
                         pct(d.get("vs_5y_avg_pct"), 1), cell])
        rd = next(iter(inv.values())).get("period")
        h += card("EIA 주간 재고", rows_table(
            ["항목", "재고", "주간", "평년대비", "판정"], rows,
            ["l", "r", "r", "r", "r"]), f"기준 {rd}")

    cot = j.get("cot") or {}
    if cot:
        ext = {e["name"] for e in (j.get("cot_extremes") or [])}
        rows = []
        for name, d in sorted(cot.items(),
                              key=lambda kv: -abs(kv[1].get("spec_net_pct_oi") or 0)):
            mark = '<span class="brk">★</span> ' if name in ext else ""
            rows.append([mark + esc(name), num(d.get("spec_ratio"), 2),
                         f'{d.get("spec_net", 0):+,}',
                         f'{d.get("spec_net_pct_oi", 0):+.1f}%',
                         f'{d.get("spec_net_change", 0):+,}'])
        rd = next(iter(cot.values())).get("report_date")
        h += card("COT 투기 포지셔닝", rows_table(
            ["품목", "롱숏비", "순포지션", "OI대비", "전주대비"], rows,
            ["l", "r", "r", "r", "r"]), f"CFTC 기준일 {rd} · ★ = 극단 쏠림")

    cv = j.get("curves") or {}
    if cv:
        rows = [[esc(n), esc(c["shape"]), f'{c["spread_pct"]:+.2f}%',
                 f'<span class="dim">{"" if c["monotonic"] else "계절성"}</span>']
                for n, c in sorted(cv.items(), key=lambda kv: kv[1]["spread_pct"])]
        h += card("선물 커브", rows_table(["품목", "형태", "근월대비", ""],
                                       rows, ["l", "l", "r", "r"]))

    ns = j.get("news_stats") or {}
    h += card("뉴스", news_list(j.get("news_selected") or []),
              f"{ns.get('collected', 0):,}건 수집 → {ns.get('selected_for_llm', 0)}건 선별")
    return h


# ---------------------------------------------------------------- 코인
def render_coin(j):
    h = ""
    g = j.get("global") or {}
    fg = j.get("fear_greed") or {}
    a = j.get("aggregate") or {}
    pairs = [
        ("총 시총", f'{money_usd(g.get("total_market_cap_usd"))} '
                   f'{pct(g.get("market_cap_change_24h_pct"))}'),
        ("거래대금", money_usd(g.get("total_volume_usd"))),
        ("BTC 도미넌스", f'{g.get("btc_dominance")}%'),
        ("ETH 도미넌스", f'{g.get("eth_dominance")}%'),
    ]
    if fg:
        pairs.append(("공포탐욕", f'{fg["value"]} <span class="dim">{esc(fg["rating"])}</span>'))
    if a:
        pairs.append(("상승/하락", f'<span class="up">{a["up"]}</span> / '
                                  f'<span class="down">{a["down"]}</span>'))
        if a.get("positive_funding_ratio") is not None:
            pairs.append(("양(+)펀딩비", f'{a["positive_funding_ratio"]}%'))
    if j.get("usdkrw"):
        pairs.append(("원달러", f'{num(j["usdkrw"], 2)}원'))
    h += card("시장 전체", kv_grid(pairs))
    h += insight_slot("coin")

    sel = j.get("selected") or []
    if sel:
        body = ""
        for c in sel:
            k = c.get("kimchi") or {}
            fr = c.get("funding_rate")
            fr_s = f'{fr*10000:+.2f}bp' if fr is not None else "-"
            body += (
                f'<div class="stock{hot_class(c.get("reasons"))}"><div class="srow">'
                f'<div><span class="sname">{esc(c["symbol"])}</span> '
                f'<span class="dim">#{c.get("rank")} {esc((c.get("name") or "")[:16])}</span></div>'
                f'<div class="sprice">${num(c.get("price"), 4)} {pct(c.get("change_pct"))}</div>'
                f'</div>'
                f'<div class="sbadges">{badges(c.get("reasons") or [])}</div>'
                f'<div class="sstats">'
                f'<span>7일 {pct(c.get("change_7d"))}</span>'
                f'<span>펀딩 {fr_s}</span>'
                f'<span>롱숏 {num(c.get("long_short_account"), 2)}</span>'
                f'<span>OI7일 {pct(c.get("oi_change_7d_pct"))}</span>'
                + (f'<span>김프 {pct(k.get("premium_pct"))}</span>' if k else "")
                + f'<span>ATH {pct(c.get("ath_change_pct"), 1)}</span>'
                f'</div></div>')
        h += card(f"선별 코인 {len(sel)}개", body)

    ns = j.get("news_stats") or {}
    sub = f"{ns.get('collected', 0):,}건 수집 → {ns.get('selected_for_llm', 0)}건 선별"
    if ns.get("uncovered"):
        sub += f" · 뉴스 없음: {', '.join(ns['uncovered'])}"
    h += card("뉴스", news_list(j.get("news_selected") or []), sub)
    return h


RENDERERS = {"kr": render_kr, "us": render_us,
             "macro": render_macro, "coin": render_coin}


# ---------------------------------------------------------------- 조립
CSS = """
*{box-sizing:border-box;margin:0;padding:0}

/* 토큰만 테마별로 재정의한다. 컴포넌트는 토큰을 통해서만 색을 참조하므로
   미디어쿼리와 data-theme 토글이 서로 싸우지 않는다. */
:root{
  --bg:#f7f9fa; --surface:#ffffff; --sunken:#eef2f4;
  --line:#dbe3e8; --line-soft:#e8eef1;
  --tx:#0d1418; --dim:#5b6b75;
  --up:#e5484d; --down:#3b82f6; --flat:#8b98a1;
  --acc:#0891b2;            /* 틸 — 등락 적/청과 충돌하지 않는 강조 */
  --warn:#b45309;           /* 경고(극단·타이트) — 강조색과 분리된 의미색 */
  --warn-bg:#fdf3e3;
  --shadow:0 1px 2px rgba(13,20,24,.06);
}
@media(prefers-color-scheme:dark){
  :root{
    --bg:#0b0f14; --surface:#131a22; --sunken:#0e141a;
    --line:#222c36; --line-soft:#1a232b;
    --tx:#e3edf3; --dim:#8496a3;
    --up:#ff6b6b; --down:#60a5fa; --flat:#6b7c88;
    --acc:#22d3ee;
    --warn:#f59e0b; --warn-bg:#2a1f0d;
    --shadow:none;
  }
}
/* 뷰어의 테마 토글이 OS 설정을 양방향으로 덮어써야 한다 */
:root[data-theme="light"]{
  --bg:#f7f9fa; --surface:#ffffff; --sunken:#eef2f4;
  --line:#dbe3e8; --line-soft:#e8eef1;
  --tx:#0d1418; --dim:#5b6b75;
  --up:#e5484d; --down:#3b82f6; --flat:#8b98a1;
  --acc:#0891b2; --warn:#b45309; --warn-bg:#fdf3e3;
  --shadow:0 1px 2px rgba(13,20,24,.06);
}
:root[data-theme="dark"]{
  --bg:#0b0f14; --surface:#131a22; --sunken:#0e141a;
  --line:#222c36; --line-soft:#1a232b;
  --tx:#e3edf3; --dim:#8496a3;
  --up:#ff6b6b; --down:#60a5fa; --flat:#6b7c88;
  --acc:#22d3ee; --warn:#f59e0b; --warn-bg:#2a1f0d;
  --shadow:none;
}

body{background:var(--bg);color:var(--tx);
  font:15px/1.5 "Pretendard","Apple SD Gothic Neo",-apple-system,BlinkMacSystemFont,
  "Segoe UI","Malgun Gothic",sans-serif;
  -webkit-text-size-adjust:100%;font-feature-settings:"tnum" 1}
/* 숫자가 주인공인 화면이다. 자릿수가 흔들리면 표를 못 읽는다. */
.v,.sprice,td,.sstats,.kv .v{font-variant-numeric:tabular-nums}

header{position:sticky;top:0;z-index:10;background:var(--bg);
  border-bottom:1px solid var(--line);padding:14px 14px 0}
h1{font-size:16px;font-weight:700;letter-spacing:-.01em}
.stamp{color:var(--dim);font-size:11.5px;margin-top:3px;font-variant-numeric:tabular-nums}
nav{display:flex;gap:2px;margin-top:12px;overflow-x:auto;-webkit-overflow-scrolling:touch;
  scrollbar-width:none}
nav::-webkit-scrollbar{display:none}
nav button{flex:0 0 auto;background:none;border:none;border-bottom:2px solid transparent;
  color:var(--dim);font:600 14.5px/1 inherit;padding:10px 13px;cursor:pointer}
nav button.on{color:var(--tx);border-color:var(--acc)}
nav button:focus-visible,.news:focus-visible{outline:2px solid var(--acc);
  outline-offset:2px;border-radius:3px}

main{padding:12px 12px 44px;max-width:860px;margin:0 auto}
.card{background:var(--surface);border:1px solid var(--line);border-radius:8px;
  padding:14px;margin-bottom:10px;box-shadow:var(--shadow)}
.card h2{font-size:12px;font-weight:700;letter-spacing:.04em;text-transform:uppercase;
  color:var(--dim)}
.csub{color:var(--dim);font-size:11.5px;margin-top:3px}
.card h2+.grid,.card h2+.scroll,.card h2+div,.csub+.grid,.csub+.scroll,.csub+div{margin-top:11px}

.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(132px,1fr));gap:7px}
.kv{background:var(--sunken);border-radius:6px;padding:8px 10px}
.kv .k{display:block;color:var(--dim);font-size:10.5px;letter-spacing:.02em}
.kv .v{display:block;font-size:15px;font-weight:650;margin-top:3px}

.scroll{overflow-x:auto;-webkit-overflow-scrolling:touch}
table{width:100%;border-collapse:collapse;font-size:12.5px;white-space:nowrap}
th{color:var(--dim);font-size:10.5px;font-weight:600;letter-spacing:.03em;
  text-align:left;padding:0 8px 7px;border-bottom:1px solid var(--line)}
td{padding:7px 8px;border-bottom:1px solid var(--line-soft)}
tr:last-child td{border:none}
.al{text-align:left}.ar{text-align:right}

.up{color:var(--up);font-weight:650}
.down{color:var(--down);font-weight:650}
.flat{color:var(--flat)}
.dim{color:var(--dim);font-weight:400}
.brk{color:var(--warn);font-weight:700}
.chip{display:inline-block;background:var(--warn-bg);color:var(--warn);
  border-radius:3px;padding:1px 6px;font-size:11px;font-weight:650}

/* 종목 카드: 좌측 스트라이프로 상태를 형태로도 인코딩한다 */
.stock{border-bottom:1px solid var(--line-soft);padding:11px 0 11px 10px;
  border-left:2px solid transparent;margin-left:-10px}
.stock:last-child{border-bottom:none;padding-bottom:2px}
.stock.hot{border-left-color:var(--warn)}
.srow{display:flex;justify-content:space-between;align-items:baseline;gap:8px}
.sname{font-weight:650;font-size:14.5px}
.sprice{font-size:14px;font-weight:650;white-space:nowrap}
.sbadges{margin:7px 0 6px;display:flex;flex-wrap:wrap;gap:4px}
.badge{background:var(--sunken);border:1px solid var(--line);border-radius:4px;
  color:var(--dim);font-size:10px;padding:2px 6px;letter-spacing:.01em}
.badge.sec{border-color:var(--acc);color:var(--acc);background:transparent}
.sstats{display:flex;flex-wrap:wrap;gap:3px 14px;color:var(--dim);font-size:11.5px}

.newswrap{display:flex;flex-direction:column}
.news{display:block;text-decoration:none;color:inherit;
  border-bottom:1px solid var(--line-soft);padding:10px 0}
.news:last-child{border:none;padding-bottom:0}
.news:hover .ntitle{color:var(--acc)}
.nmeta{display:flex;gap:7px;align-items:center;font-size:10.5px;margin-bottom:4px;
  flex-wrap:wrap}
.dup{background:var(--acc);color:var(--bg);border-radius:3px;padding:0 4px;font-weight:700}
.tag{color:var(--acc)}
.ntitle{font-size:13.5px;line-height:1.45;text-wrap:pretty}
.nsrc{color:var(--dim);font-size:10.5px;margin-top:4px}

.insight .empty{background:var(--sunken);border:1px dashed var(--line);border-radius:6px;
  padding:18px 16px;text-align:center;font-size:12.5px;color:var(--dim)}
.insight .empty p{margin:5px 0}
.insight .empty p:first-child{color:var(--tx);font-weight:600}

/* 생성된 인사이트 — 읽는 글이라 표·목록보다 여백과 행간이 중요하다 */
.insight.has{border-left:2px solid var(--acc)}
.md{font-size:14px;line-height:1.65}
.md>*+*{margin-top:11px}
.md h3{font-size:15px;font-weight:700;letter-spacing:-.01em;margin-top:20px;
  text-wrap:balance}
.md h4,.md h5{font-size:13.5px;font-weight:650;color:var(--dim);
  letter-spacing:.02em;margin-top:16px}
.md h3:first-child,.md h4:first-child{margin-top:0}
.md p{text-wrap:pretty}
.md ul,.md ol{padding-left:20px;display:flex;flex-direction:column;gap:5px}
.md li{line-height:1.6}
.md li::marker{color:var(--dim)}
.md strong{font-weight:700}
.md table{font-size:12.5px}
.md td,.md th{padding:6px 9px}
.md blockquote{border-left:2px solid var(--line);padding:2px 0 2px 12px;
  color:var(--dim);font-size:13px}
.md hr{border:none;border-top:1px solid var(--line);margin:16px 0}
.md code{font-size:12.5px}
.md a{color:var(--acc)}
code{background:var(--line);border-radius:3px;padding:1px 5px;font-size:11.5px;
  font-family:ui-monospace,SFMono-Regular,Menlo,monospace}
.panel{display:none}.panel.on{display:block}
.pstamp{color:var(--dim);font-size:11.5px;padding:10px 2px 0;
  font-variant-numeric:tabular-nums;display:flex;gap:6px;align-items:center}
.pstamp .old{background:var(--warn-bg);color:var(--warn);border-radius:3px;
  padding:1px 6px;font-weight:650}
@media(prefers-reduced-motion:reduce){*{transition:none!important;animation:none!important}}
"""

JS = """
document.querySelectorAll('nav button').forEach(b=>{
  b.onclick=()=>{
    document.querySelectorAll('nav button').forEach(x=>x.classList.remove('on'));
    document.querySelectorAll('.panel').forEach(x=>x.classList.remove('on'));
    b.classList.add('on');
    document.getElementById('p-'+b.dataset.m).classList.add('on');
    window.scrollTo(0,0);
    try{localStorage.setItem('tab',b.dataset.m)}catch(e){}
  };
});
try{
  const t=localStorage.getItem('tab');
  if(t){const b=document.querySelector(`nav button[data-m="${t}"]`); if(b)b.click();}
}catch(e){}
"""


def _age_line(iso):
    """자산군별 수집 시각. 장별로 따로 갱신하면 카드마다 신선도가 다르므로
    패널 상단에 각자의 시각을 적어 준다 — 헤더의 '최종 수집'만 보면
    어제 데이터를 오늘 것으로 착각한다."""
    if not iso:
        return ""
    try:
        when = dt.datetime.fromisoformat(iso)
    except ValueError:
        return f'<div class="pstamp">수집 {esc(iso[:16])}</div>'
    hrs = (dt.datetime.now() - when).total_seconds() / 3600
    if hrs < 1:
        ago = f"{hrs*60:.0f}분 전"
    elif hrs < 48:
        ago = f"{hrs:.0f}시간 전"
    else:
        ago = f"{hrs/24:.0f}일 전"
    warn = '<span class="old">갱신 필요</span>' if hrs >= 18 else ""
    return (f'<div class="pstamp"><span>수집 {when:%m-%d %H:%M} '
            f'({ago})</span>{warn}</div>')


def _body():
    """헤더 + 탭 + 패널. 단독 HTML과 아티팩트가 공유한다."""
    panels, tabs, stamps = "", "", []
    first = True
    for key, label, icon in MARKETS:
        j = latest_json(key)
        on = " on" if first else ""
        tabs += (f'<button data-m="{key}" class="{on.strip()}">'
                 f'{icon} {esc(label)}</button>')
        if j:
            iso = j.get("collected_at", "")
            stamps.append(iso[:16].replace("T", " "))
            body = _age_line(iso) + RENDERERS[key](j)
        else:
            body = card("데이터 없음",
                        f'<p class="dim">collect_{key}.py를 먼저 실행하세요.</p>')
        panels += f'<div class="panel{on}" id="p-{key}">{body}</div>'
        first = False

    stamp = max(stamps) if stamps else "-"
    head = (f'<header><h1>자산 인사이트</h1>'
            f'<div class="stamp">최종 수집 {esc(stamp)} · '
            f'생성 {dt.datetime.now():%m-%d %H:%M}</div>'
            f'<nav>{tabs}</nav></header>')
    return head, panels, stamp


def build():
    """단독 실행용 완전한 HTML 파일"""
    head, panels, _ = _body()
    html = f"""<!doctype html>
<html lang="ko"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="color-scheme" content="dark light">
<title>자산 인사이트</title>
<style>{CSS}</style>
</head><body>
{head}
<main>{panels}</main>
<script>{JS}</script>
</body></html>"""
    # 갓 클론한 리포에는 data/가 없다 (.gitignore 대상이라 커밋되지 않는다).
    # 수집기가 먼저 만들어 주지만, 수집이 실패한 뒤 대시보드만 굽는 경우
    # 여기서 넘어진다 — 클라우드 데이터로 그릴 수 있으면 그려야 한다.
    DATA.mkdir(exist_ok=True)
    OUT.write_text(html, encoding="utf-8")
    return OUT, len(html)


def build_pwa(docs_dir=None):
    """GitHub Pages용. docs/index.html + 매니페스트·서비스워커·아이콘.

    아티팩트와 달리 도메인 루트를 우리가 통제하므로 진짜 PWA가 된다 —
    홈화면 아이콘, 전체화면, 오프라인 캐시가 전부 작동한다.
    """
    import pwa
    docs = Path(docs_dir) if docs_dir else (ROOT / "docs")
    assets = pwa.write_assets(docs)

    head, panels, stamp = _body()
    html = f"""<!doctype html>
<html lang="ko"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="color-scheme" content="dark light">
<title>자산 인사이트</title>
{pwa.HEAD_EXTRA}
<style>{CSS}</style>
</head><body>
{head}
<main>{panels}</main>
<script>{JS}{pwa.REGISTER_SW}</script>
</body></html>"""
    index = docs / "index.html"
    index.write_text(html, encoding="utf-8")
    return index, len(html), assets


def build_artifact(path=None):
    """claude.ai 게시용. <!doctype>/<html>/<head>/<body>는 게시 시점에
    감싸지므로 본문만 쓴다. 외부 요청이 0건이라 CSP 제약도 통과한다."""
    head, panels, stamp = _body()
    out = Path(path) if path else (DATA / "artifact.html")
    html = (f'<title>자산 인사이트 · {esc(stamp[:10])}</title>\n'
            f'<style>{CSS}</style>\n'
            f'{head}\n<main>{panels}</main>\n'
            f'<script>{JS}</script>')
    out.write_text(html, encoding="utf-8")
    return out, len(html)


def local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except OSError:
        return "127.0.0.1"


if __name__ == "__main__":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8",
                                  errors="replace")
    path, size = build()
    print(f"생성 완료: {path}  ({size:,}자)")
    if "--artifact" in sys.argv:
        ap, asize = build_artifact()
        print(f"게시용   : {ap}  ({asize:,}자)")
    if "--pwa" in sys.argv:
        ip, isize, assets = build_pwa()
        print(f"PWA      : {ip}  ({isize:,}자)")
        for name, n in assets:
            print(f"           {name:16s} {n:>8,} bytes")
    if "--serve" in sys.argv:
        import http.server, functools
        port = 8000
        ip = local_ip()
        print(f"\n  PC     http://localhost:{port}/latest.html")
        print(f"  휴대폰  http://{ip}:{port}/latest.html")
        print("\n  같은 와이파이에 연결한 뒤 위 주소로 접속하세요. (Ctrl+C 종료)\n")
        handler = functools.partial(http.server.SimpleHTTPRequestHandler,
                                    directory=str(DATA))
        http.server.ThreadingHTTPServer(("0.0.0.0", port), handler).serve_forever()
