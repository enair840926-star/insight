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
import subprocess
import datetime as dt

from core import history, pick, read, regime, session
from pathlib import Path

# 주의: stdout 재설정은 모듈 최상단에 두면 안 된다.
# run.py가 이 모듈을 import할 때 실행되면서 run.py가 이미 감싼
# stdout의 buffer를 다시 감싸고, 원본이 닫혀 ValueError가 난다.
# 직접 실행할 때만 __main__ 블록에서 설정한다.

ROOT = Path(__file__).parent
DATA = ROOT / "data"
INSIGHTS = ROOT / "insights"      # 커밋되는 곳. core/store.py 주석 참고.
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


def card(title, body, sub="", fold=False, note=""):
    """fold=True면 접힌 상태로 시작한다.

    폰에서 한 탭이 12~15화면이었다. 매번 필요한 건 그중 일부인데
    전부 펼쳐 두면 원하는 걸 찾는 데만 스크롤을 한참 해야 한다.
    자주 안 보는 것은 접어 두고 제목만 남긴다.

    note는 접힌 상태에서도 보이는 한 줄 요약이다 — 펼칠지 말지를
    제목만으로 정하기 어려울 때 쓴다.
    """
    s = f'<div class="csub">{esc(sub)}</div>' if sub else ""
    if not fold:
        return f'<section class="card"><h2>{esc(title)}</h2>{s}{body}</section>'
    n = f'<span class="fnote">{note}</span>' if note else ""
    return (f'<details class="card fold"><summary><h2>{esc(title)}</h2>{n}'
            f'</summary>{s}{body}</details>')


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


import html as _html
import re as _re

# 아침에 실제로 필요한 건 앞의 세 섹션이다. 나머지는 접어 두고
# 필요할 때 펼친다 — 인사이트만 5~6화면이라 그대로 두면 훑기가 어렵다.
_OPEN_SECTIONS = ("개장 전 브리핑", "오늘의 픽", "오늘 주목할 것")

# 맨 위 칩으로 올릴 섹션. 앞의 것이 있으면 그것만 쓴다 — 픽이 결론이고
# '주목할 것'은 그 아래 맥락이라, 둘을 섞으면 칩이 8개가 되어 훑는 의미가
# 없어진다. 픽 섹션이 없는 예전 글은 자동으로 뒤엣것으로 물러선다.
_CHIP_SECTIONS = (("오늘의 픽", "p"), ("주목할 것", "w"))


def short_name(full):
    """칩에 넣을 짧은 이름. 글의 소제목과 픽 라벨이 같은 규칙을 써야
    둘을 맞대어 앵커를 찾을 수 있다."""
    # 'A — B' 형식이면 앞이 대상이다. 구분자가 없으면 제목 전체가
    # 문장일 수 있으니 칩에서만 줄여 쓴다.
    short = _re.split(r"\s[—–-]\s", full)[0].strip(" -–—:")
    # 칩은 16자뿐이다. 종목코드·티커 괄호가 그 절반을 먹으면 정작
    # 이름이 잘린다 ('한화에어로스페이스 (0124…').
    short = _re.sub(r"\s*\([^)]*\)\s*$", "", short).strip() or short
    return short[:15] + "…" if len(short) > 16 else short


def fold_insight(html, market=""):
    """<h3>로 나뉜 인사이트를 섹션별 접기로 바꾼다.

    반환: (본문HTML, [(짧은이름, 전체제목, 앵커id), ...])
    """
    parts = _re.split(r"(<h3>.*?</h3>)", html)
    if len(parts) < 3:
        return html, []

    out, found = parts[0], {}
    for i in range(1, len(parts), 2):
        head, body = parts[i], parts[i + 1] if i + 1 < len(parts) else ""
        title = _re.sub(r"<[^>]+>", "", head).strip()
        keep_open = any(k in title for k in _OPEN_SECTIONS)

        # 이 섹션 안의 h4 제목이 곧 오늘의 지목 대상이다. 맨 위 칩으로
        # 끌어올리고, 칩에서 본문으로 뛸 수 있게 id를 심는다.
        key = next((k for k, _ in _CHIP_SECTIONS if k in title), None)
        if key:
            tag = dict(_CHIP_SECTIONS)[key]
            n = [0]

            def anchor(m, _t=tag):
                n[0] += 1
                return f'<h4 id="{market}-{_t}{n[0]}">{m.group(1)}</h4>'

            body = _re.sub(r"<h4>(.*?)</h4>", anchor, body)
            picked = []
            for k, m in enumerate(_re.finditer(r"<h4[^>]*>(.*?)</h4>", body), 1):
                t = _re.sub(r"<[^>]+>", "", m.group(1))
                # md가 이미 이스케이프한 문자를 되돌린다. 안 하면 esc()가
                # 한 번 더 걸려 S&amp;P500처럼 보인다.
                full = _re.sub(r"^\d+[.)]\s*", "", _html.unescape(t).strip())
                short = short_name(full)
                if short:
                    picked.append((short, full, f"{market}-{tag}{k}"))
            found[key] = picked

        out += (f'<details class="sec"{" open" if keep_open else ""}>'
                f'<summary>{title}</summary>{body}</details>')

    # 앞의 것을 먼저 쓴다. 픽이 있으면 픽만, 없으면 '주목할 것'으로 물러선다.
    watch = next((found[k] for k, _ in _CHIP_SECTIONS if found.get(k)), [])
    return out, watch


def _written_at(path):
    """인사이트가 실제로 쓰인 시각.

    **파일 수정 시각(mtime)을 쓰면 안 된다.** 클라우드가 대시보드를
    다시 구울 때마다 저장소를 새로 내려받으므로 mtime이 그때로 찍힌다.
    그러면 일주일 전 인사이트도 '방금 작성'으로 보인다. 마지막 커밋
    시각을 쓰면 실제로 쓰인 때가 나온다.

    저장소 밖이거나 git이 없으면 mtime으로 물러선다.
    """
    try:
        r = subprocess.run(
            ["git", "log", "-1", "--format=%cI", "--", str(path)],
            capture_output=True, text=True, timeout=10, cwd=str(ROOT))
        s = (r.stdout or "").strip()
        if s:
            return dt.datetime.fromisoformat(s).astimezone().replace(tzinfo=None)
    except (OSError, ValueError, subprocess.SubprocessError):
        pass
    try:
        return dt.datetime.fromtimestamp(path.stat().st_mtime)
    except OSError:
        return None


def _behind_note(when, collected):
    """글이 화면의 숫자보다 오래됐으면 그렇게 말하는 줄. 아니면 ''.

    **글의 나이만으로는 이걸 못 말한다.** 카드에 이미 '3일 전'이 뜨는데,
    주말을 낀 사흘 전 글은 정상이라 그것만으로는 고장인지 알 수 없다.
    말해야 하는 것은 나이가 아니라 **간격**이다 — 지금 화면에 뜬 스냅샷이
    이 글보다 나중 것이면, 이 글은 저 숫자를 안 보고 쓴 것이다.

    실제로 2026-08-18~21에 루틴이 사흘 내리 실패했는데 화면은 옛 글을
    그대로 보여 줬고, 아무것도 그 사실을 말하지 않았다. 수집은 정상이라
    '수집 갱신 필요'도 안 떴다 — 숫자는 새것이고 글만 옛것이었기 때문이다.
    """
    if not (when and collected):
        return ""
    try:
        c = dt.datetime.fromisoformat(str(collected))
    except (TypeError, ValueError):
        return ""
    if c.tzinfo is not None:
        c = c.astimezone().replace(tzinfo=None)
    gap = (c - when).total_seconds() / 3600
    if gap < session.MAX_INSIGHT_AGE_H:
        return ""      # 같은 세션 안이다. 곧 다시 쓰거나 이미 최신이다.
    return ('<div class="warn">이 글은 위 숫자보다 <b>'
            f'{_ago_text(gap).replace(" 전", "")}</b> 앞서 쓰였습니다 — '
            '새 데이터로 아직 다시 쓰지 않았습니다. '
            '숫자와 픽은 최신이고 <b>글만 옛것</b>입니다.</div>')


def insight_slot(market_name, collected=None):
    """생성된 인사이트가 있으면 렌더링하고, 없으면 안내를 띄운다.

    insights/에서 먼저 찾는다. 인사이트는 PC에서 만들고 수집은 클라우드가
    하는데, data/는 .gitignore 대상이라 러너에 없다. 거기 두면 클라우드가
    대시보드를 다시 구울 때마다 인사이트가 빈 자리로 덮인다.

    `collected`를 주면 글이 그 스냅샷보다 오래됐는지 함께 말한다.
    """
    src = INSIGHTS / f"insight_{market_name}.md"
    if not src.exists():
        src = DATA / f"insight_{market_name}.md"     # 예전 위치
    if src.exists():
        from core import md
        text = src.read_text(encoding="utf-8").strip()
        if text:
            when = _written_at(src)
            stamp = f"{when:%m월 %d일 %H:%M} 작성" if when else "작성 시각 미상"
            old = ""
            if when:
                # 수집 시각과 같은 이유로 브라우저가 다시 센다.
                hrs = (dt.datetime.now() - when).total_seconds() / 3600
                hide = "" if hrs >= 18 else " hidden"
                ts = esc(when.isoformat(timespec="seconds"))
                old = (f' <span class="old" data-warn="{ts}"{hide}>'
                       f'<span class="ago" data-ts="{ts}">{_ago_text(hrs)}</span>'
                       f'</span>')
            body, watch = fold_insight(md.render(text), market_name)
            behind = _behind_note(when, collected)
            return (f'<section class="card insight has"><h2>인사이트</h2>'
                    f'<div class="csub">{stamp}{old} · '
                    f'방향 판정은 규칙 계산이며 결과를 보장하지 않습니다</div>'
                    f'{behind}'
                    f'<div class="md">{body}</div></section>'), watch
    return (f'<section class="card insight"><h2>인사이트</h2>'
            f'<div class="empty"><p>아직 없습니다.</p>'
            f'<p class="dim">Claude에게 <code>/인사이트</code>라고 하면 '
            f'최신 데이터로 써서 1분 안에 여기 반영됩니다.</p></div></section>'), []


def regime_card(market, j):
    """장 자체가 어떤 상태인가. 픽 위에 놓인다.

    **픽과 섞지 않는다.** 점수에 곱하지 않았으므로 화면에서도 따로 세운다 —
    "장은 이런 상태다, 그 위에서 저 셋이 뽑혔다"로 읽혀야 한다.
    """
    try:
        r = regime.judge(market, j)
    except Exception as e:
        return card("장 상태",
                    f'<p class="dim">판정 실패 — {esc(type(e).__name__)}: '
                    f'{esc(str(e)[:80])}</p>')

    if r["state"] == "알 수 없음":
        return card("장 상태",
                    '<p class="dim">판정할 재료가 없습니다. 이번 스냅샷에서 '
                    '시장 수준 신호가 하나도 걸리지 않았습니다 — 장이 잠잠한 '
                    '것이 아니라 <b>재지 못한 것</b>일 수 있습니다.</p>')

    cls = {"우호": "up", "비우호": "down"}.get(r["state"], "flat")
    head = (f'<div class="kv"><span class="k">판정</span>'
            f'<span class="v {cls}">{esc(r["state"])}</span></div>'
            f'<div class="kv"><span class="k">신호</span>'
            f'<span class="v">{r["n"]}개 · 합계 {r["score"]:+d}</span></div>')
    items = "".join(
        f'<li><span class="{"up" if s > 0 else "down"}">{s:+d}</span> '
        f'{esc(t)}</li>' for s, t in r["signed"])
    basis = (f'<p class="dim">{esc(r["basis"])}</p>' if r["basis"] else "")
    return card("장 상태",
                f'<div class="grid">{head}</div>{basis}'
                f'<ul class="sig">{items}</ul>'
                '<p class="dim">이 판정은 아래 \'오늘의 픽\' 점수에 들어가 '
                '있지 않습니다. 픽은 종목 자체의 근거로만 뽑혔고, 이것은 그 '
                '위에 놓이는 배경입니다. 임계값은 아직 실측이 아니라 추정이라 '
                '판정도 함께 기록해 두고 있습니다.</p>')


def picks_scorecard(market):
    """픽이 맞았는지. 집계는 core/history.py 가 하고 여기서는 보이기만 한다.

    **적중률을 크게 띄우지 않는다.** 지금 표본이 자산군당 8~12건이라 동전
    던지기와 구별되지 않는데, 숫자만 크게 보이면 우연을 실력으로 읽는다.
    그래서 표본 경고를 숫자 바로 옆에 붙이고, 접힌 상태의 한 줄 요약에도
    '아직 판단 못 함'을 적는다.

    결과가 나쁘게 나올 수 있다. 그건 실패가 아니라 이 기록의 성공이다 —
    그전에는 아예 모르는 채로 쓰고 있었다.
    """
    try:
        s = history.summary([market])
    except Exception as e:
        # 조용히 빠지면 패널이 없는 것과 구별이 안 된다. 무엇이 실패했는지 남긴다.
        return card("픽 성적",
                    f'<p class="dim">집계 실패 — {esc(type(e).__name__)}: '
                    f'{esc(str(e)[:80])}</p>', fold=True, note="집계 실패")

    d = (s.get("markets") or {}).get(market)
    if not d:
        return card("픽 성적",
                    '<p class="dim">결과가 채워진 픽이 아직 없습니다. 픽 하나는 '
                    f'다음 세션({history.MIN_HOURS}시간 뒤)이 지나야 채점됩니다.</p>',
                    fold=True, note="기록 없음")

    h, c, ab, cu = d.get("hit"), d.get("calib"), d.get("abs"), d.get("cum")
    n = (ab or h or c or {}).get("n", 0)
    body = ""

    # 절대 등락을 위에 둔다. 초과수익은 지수를 함께 공매도해야 손에 쥐는
    # 값이라 계좌에 찍히는 숫자가 아니다 — 크게 띄우면 실제 손익으로 읽힌다.
    if ab:
        rate = (f'{ab["pct"]}% <span class="dim">({ab["hits"]}/{ab["denom"]})</span>'
                if ab["denom"] else '<span class="dim">방향 0건</span>')
        rows_ = [("근거대로 움직인 비율", rate),
                 ("평균 등락", f'{ab["mean"]:+.2f}%')]
        if cu:
            rows_.append(("누적 손익 · 지수 무관",
                          f'{cu["total"]:+.2f}% '
                          f'<span class="dim">({cu["n_days"]}일)</span>'))
        body += kv_grid(rows_)
        if ab["flat"]:
            body += (f'<p class="dim">횡보 {ab["flat"]}건은 분모에서 뺐습니다 — '
                     '그 종목 평소 하루 변동폭의 절반 안쪽이라 방향이 아니라 '
                     '잡음입니다.</p>')
        if ab["gap"]:
            body += f'<p class="dim">{esc(ab["gap"])}</p>'

    if cu:
        # 누적은 하루가 한 점이다. 마지막 값만 내면 어떻게 왔는지 안 보여
        # 한 번의 큰 날과 꾸준함이 같아 보인다.
        line = " · ".join(f'{day[5:]} {avg:+.2f}%' for day, _, avg, _ in
                          cu["days"][-5:])
        body += (f'<p class="dim">최근 {min(5, cu["n_days"])}일 '
                 f'{esc(line)} — {cu["n_days"]}일 중 플러스 {cu["wins"]}일. '
                 '그날 픽에 돈을 똑같이 나눠 넣었다고 보고 평균낸 값입니다.</p>')

    if h:
        bench = "코스피" if market == "kr" else "S&P500" if market == "us" \
            else "코인 총시총" if market == "coin" else None
        if h["vs_bench"] and bench:
            body += (f'<p class="dim">참고 — {bench} 대비로 재면 '
                     f'{h["pct"]}% ({h["hits"]}/{h["n"]}), '
                     f'평균 초과 {h["excess"]:+.2f}%. 시장이 다 오른 날의 '
                     '상승을 빼고 본 값이라 규칙이 값을 하는지에 답합니다.</p>')
    if c:
        body += (f'<p class="dim">\'오늘 볼 선\'이 실제로 깨진 비율 '
                 f'{c["pct"]}% ({c["broke"]}/{c["n"]}) — 하루 변동폭 1배라 '
                 f'정규분포라면 15.9%다.</p>')
    if not (ab and ab["enough"]):
        warn = ('이 숫자로 규칙을 고치지 마라. '
                f'{s["need"]["score"]}건은 모여야 점수가 값을 하는지 알 수 있고, '
                f"'오늘 볼 선'은 {s['need']['calib']}건이면 대략 답이 나온다.")
        if cu and not cu["enough"]:
            # 누적은 하루가 한 점이라 건수로 세면 실제보다 다 찬 것처럼 보인다.
            warn += (f' 누적은 {history.CUM_DAYS}일치가 있어야 하는데 지금 '
                     f'{cu["n_days"]}일이다.')
        body += f'<p class="warn">{warn}</p>'
    if s.get("mixed_rules"):
        body += ('<p class="warn">규칙 버전이 섞여 있습니다 — '
                 f'{esc(", ".join(s["versions"]))}. 직접 비교하면 안 됩니다.</p>')

    # 접힌 줄에도 절대 등락을 먼저 낸다. 펼치기 전에 보이는 한 줄이
    # 벤치마크 대비면, 펼쳤을 때와 다른 숫자를 말하는 셈이 된다.
    if cu:
        note = f'누적 {cu["total"]:+.2f}%'
        if ab and ab["pct"] is not None:
            note += f' · {ab["pct"]}%'
        note += f' ({n}건)'
    elif ab and ab["pct"] is not None:
        note = f'{ab["pct"]}% ({n}건)'
    else:
        note = f"{n}건"
    if not (ab and ab["enough"]):
        note += " · 아직 판단 못 함"
    return card("픽 성적", body, fold=True, note=note)


def watch_strip(items):
    """오늘 지목된 대상을 맨 위에 칩으로 띄운다.

    인사이트 안에 묻혀 있으면 스크롤을 한참 해야 보인다. 결론부터
    보이는 게 폰에서는 맞다.

    칩은 글의 해당 항목으로 뛰는 링크다. 폰에서는 긴 제목이 잘릴 수밖에
    없으므로, 누르면 본문에서 전체를 읽게 한다 — 칩의 역할은 요약이
    아니라 이정표다. **글에 그 항목이 없으면 링크가 아니라 그냥 칩이다**
    (앵커가 없는데 링크를 걸면 눌러도 아무 일이 안 일어난다).
    """
    if not items:
        return ""
    chips = ""
    for short, full, aid in items[:6]:
        if aid:
            chips += (f'<a class="wc" href="#{esc(aid)}" '
                      f'title="{esc(full)}">{esc(short)}</a>')
        else:
            chips += f'<span class="wc" title="{esc(full)}">{esc(short)}</span>'
    sub = ("눌러서 자세히 보기" if any(a for _, _, a in items[:6])
           else "인사이트 글이 아직 이 대상을 안 다룹니다")
    return (f'<section class="card watch"><h2>오늘 주목</h2>'
            f'<div class="wchips">{chips}</div>'
            f'<div class="csub">{sub}</div></section>')


def picks_card(market, j, anchors=()):
    """규칙이 계산한 오늘의 픽. **글이 없어도 나온다.**

    그전에는 픽이 시장 탭에 오르는 길이 손으로 쓴 인사이트 글뿐이었다
    (`fold_insight`가 글의 h4를 뽑는다). 그래서 루틴을 놓친 날이나 규칙이
    바뀐 직후에는 화면이 옛 글을 그대로 보여 줬다 — 실측: 매크로 대상을
    넷으로 늘렸는데 08-14에 쓰인 글 때문에 화면에는 계속 둘만 보였다.

    글은 서술이고 픽은 계산이다. 계산 쪽을 화면의 정본으로 둔다.
    """
    picks, err = _today_picks(market, j)
    if err:
        return card("오늘의 픽", f'<p class="dim">계산 실패 — {esc(err)}</p>')
    if not picks:
        return card("오늘의 픽",
                    '<p class="dim">뽑힌 것이 없습니다 — 점수가 0 근처면 '
                    '근거가 없거나 서로 맞선다는 뜻이라 빠집니다.</p>')
    by_short = {s: a for s, _f, a in anchors}
    items = ""
    for i, p in enumerate(picks, 1):
        name = p.get("label") or p.get("key") or ""
        k = p.get("kind") or ""
        kc = {"상승": "up", "하락": "down", "피할 것": "down"}.get(k, "flat")
        aid = by_short.get(short_name(name))
        label = (f'<a href="#{esc(aid)}">{esc(name)}</a>' if aid
                 else esc(name))
        cau = "".join(f'<div class="dim">⚠ {esc(c)}</div>'
                      for c in (p.get("caution") or []))
        items += (f'<li><span class="rank">{i}</span> {label} '
                  f'<span class="{kc}">{esc(k)}</span> '
                  f'<span class="dim">{p.get("score"):+d}점 · '
                  f'근거 {len(p.get("why") or [])}개</span>{cau}</li>')
    return card("오늘의 픽", f'<ol class="picks">{items}</ol>',
                "규칙이 계산한 값입니다. 점수는 오를 확률이 아니라 "
                "근거가 얼마나 쌓였는지입니다")


def watch_items(market, j, prose):
    """칩 목록. **규칙이 계산한 픽이 정본**이고, 글에 같은 대상이 있으면
    그 자리로 링크한다. 픽을 못 내면 예전처럼 글에서 뽑은 것으로 물러선다.
    """
    picks, err = _today_picks(market, j)
    if err or not picks:
        return prose
    by_short = {s: a for s, _f, a in prose}
    out = []
    for p in picks:
        name = p.get("label") or p.get("key") or ""
        s = short_name(name)
        out.append((s, name, by_short.get(s)))
    return out


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

    ins, prose = insight_slot("kr", j.get("collected_at"))
    # 칩과 픽은 규칙에서 낸다. 글은 서술이라 늦거나 없을 수 있는데,
    # 그때 화면이 옛 픽을 그대로 보여 주면 안 된다.
    h = (watch_strip(watch_items("kr", j, prose))
         + picks_card("kr", j, prose) + h + ins)

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
            # 국장의 핵심 축은 외국인·기관 수급이다. 가격이 오르는데
            # 둘 다 팔고 있으면 개인이 받고 있다는 뜻이다.
            sg = s.get("signals") or {}
            fl, fl_why, fl_cls = read.stock_flow(
                chg, sg.get("foreign_net_5d"), sg.get("organ_net_5d"))
            flow_tag = (f'<div class="sbadges"><span class="rd {fl_cls}" '
                        f'title="{esc(fl_why)}">{esc(fl)}</span></div>'
                        if fl else "")
            body += (
                f'<div class="stock{hot_class(s.get("reasons"))}"><div class="srow">'
                f'<div><span class="sname">{esc(s["name"])}</span> '
                f'<span class="dim">{esc(s["code"])}</span></div>'
                f'<div class="sprice">{num(close)}원 {pct(chg)}</div></div>'
                f'<div class="sbadges">{badges(s.get("reasons") or [])}'
                f'<span class="badge sec">{esc(s.get("industry") or "-")}</span></div>'
                + flow_tag
                + f'<div class="sstats">'
                f'<span>시총 {money_krw(s.get("market_cap"))}</span>'
                f'<span>PER {num(f_.get("per"), 2)}배</span>'
                f'<span>추정 {num(f_.get("est_per"), 2)}배</span>'
                f'<span>외국인5일 {num(g_.get("foreign_net_5d"))}</span>'
                f'<span>기관5일 {num(g_.get("organ_net_5d"))}</span>'
                f'<span>20MA {pct(g_.get("vs_ma20_pct"))}</span>'
                f'</div></div>')
        h += card(f"선별 종목 {len(stocks)}개", body,
                  f"전종목 {j.get('select_stats', {}).get('fetched', 0):,}개에서 동적 선별 · "
                  f"수급 태그는 가격과 외국인·기관 5일 순매수를 묶은 판정")

    ns = j.get("news_stats") or {}
    sub = f"{ns.get('collected', 0):,}건 수집 → {ns.get('selected_for_llm', 0)}건 선별"
    if ns.get("uncovered"):
        sub += f" · 뉴스 없음: {', '.join(ns['uncovered'])}"
    h += card("뉴스", news_list(j.get("news_selected") or []), sub, fold=True, note=f"{ns.get('selected_for_llm', 0)}건")
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
    ins, prose = insight_slot("us", j.get("collected_at"))
    # 칩과 픽은 규칙에서 낸다. 글은 서술이라 늦거나 없을 수 있는데,
    # 그때 화면이 옛 픽을 그대로 보여 주면 안 된다.
    h = (watch_strip(watch_items("us", j, prose))
         + picks_card("us", j, prose) + h + ins)

    secs = a.get("sectors") or []
    if secs:
        rows = [[esc(s["sector"]), pct(s["cap_weighted_pct"]),
                 f'{s["up_ratio"]}%', f'${s["turnover_bil"]:,.0f}B']
                for s in secs]
        h += card("섹터", rows_table(["섹터", "시총가중", "상승비율", "거래대금"],
                                    rows, ["l", "r", "r", "r"]))

    sel = j.get("selected") or []
    if sel:
        # 장중에 수집하면 거래량이 하루치가 아니라 그때까지의 부분치다.
        # 그 상태로 판정하면 전 종목이 '거래 없이 오름'으로 찍힌다.
        #
        # 최대값으로 재면 안 된다. 급등주 하나가 30분 만에 평균을 넘기면
        # (실측: 개장 32분에 PLTR 1.17배) 가드가 안 걸린다. 완결된 장이면
        # 중앙값이 1.0 근처여야 하므로 중앙값으로 판정한다.
        vrs = sorted(s.get("volume_ratio") for s in sel
                     if s.get("volume_ratio") is not None)
        med = vrs[len(vrs) // 2] if vrs else None
        partial = med is not None and med < 0.7
        body = ""
        for s in sel:
            fl, fl_why, fl_cls = ("", "", "") if partial else read.volume_flow(
                s.get("change_pct"), s.get("volume_ratio"))
            flow_tag = (f'<div class="sbadges"><span class="rd {fl_cls}" '
                        f'title="{esc(fl_why)}">{esc(fl)}</span></div>'
                        if fl else "")
            body += (
                f'<div class="stock{hot_class(s.get("reasons"))}"><div class="srow">'
                f'<div><span class="sname">{esc(s["symbol"])}</span> '
                f'<span class="dim">{esc((s.get("name") or "")[:26])}</span></div>'
                f'<div class="sprice">${num(s.get("price"), 2)} {pct(s.get("change_pct"))}</div>'
                f'</div>'
                f'<div class="sbadges">{badges(s.get("reasons") or [])}'
                f'<span class="badge sec">{esc(s.get("sector") or "-")}</span></div>'
                + flow_tag
                + f'<div class="sstats">'
                f'<span>시총 {money_usd(s.get("market_cap"))}</span>'
                f'<span>거래대금 {money_usd(s.get("turnover"))}</span>'
                f'<span>20MA {pct(s.get("vs_ma20_pct"))}</span>'
                f'<span>52주 {esc(read.pos_52w(s.get("pos_52w")))}</span>'
                f'<span>거래량 {num(s.get("volume_ratio"), 2)}배</span>'
                f'</div></div>')
        vsub = ("장중 수집이라 거래량 판정은 생략했습니다" if partial
                else "거래 태그는 가격과 거래량을 묶은 판정")
        h += card(f"선별 종목 {len(sel)}개", body,
                  f"전종목 {j.get('select_stats', {}).get('total', 0):,}개에서 동적 선별 · "
                  f"52주는 1년 가격 범위에서 지금 어디쯤인지 · {vsub}")

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
        rows = []
        for e in ec[:10]:
            surp, effect, cls = read.econ_surprise(
                e.get("event"), e.get("actual"), e.get("consensus"))
            # 예상과 얼마나 어긋났는지보다 '그래서 어떻게 읽히는지'가 먼저다
            note = (f'<span class="{cls}">{esc(surp)}</span>' if surp else "")
            if effect:
                note += f'<br><span class="dim">{esc(effect)}</span>'
            rows.append([esc((e.get("event") or "")[:30]),
                         esc(e.get("actual") or "-"),
                         esc(e.get("consensus") or "-"),
                         note or '<span class="dim">-</span>'])
        h += card("경제지표", rows_table(["지표", "실제", "예상", "해석"],
                                       rows, ["l", "r", "r", "l"]),
                  "예상과 다르면 시장이 어떻게 읽는지 함께 표시합니다")

    ns = j.get("news_stats") or {}
    sub = f"{ns.get('collected', 0):,}건 수집 → {ns.get('selected_for_llm', 0)}건 선별"
    if ns.get("uncovered"):
        sub += f" · 뉴스 없음: {', '.join(ns['uncovered'])}"
    h += card("뉴스", news_list(j.get("news_selected") or []), sub, fold=True, note=f"{ns.get('selected_for_llm', 0)}건")
    return h


# ---------------------------------------------------------------- 매크로
# 접힌 카드의 한 줄 요약에 **반드시** 넣을 지표.
#
# 그전에는 '가장 크게 움직인 둘'만 넣었는데, 그러면 매일 확인하는 기준
# 지표가 **그날 잠잠했다는 이유로** 사라진다. 실측(2026-08-14): 글로벌지수
# 요약이 "항셍 -1.10% · 독일DAX +0.86%"라 나스닥 +0.81%이 안 보였고,
# 환율도 유로달러가 밀렸다. 카드를 펼치기 전에는 없는 것처럼 읽힌다.
#
# 큰 움직임은 여전히 붙인다 — 고정 지표 뒤에 하나. 둘이 겹치면 생략한다.
# 금·WTI원유는 **매크로 픽의 고정 대상**이다(`core/pick.py`). 매일 이 둘의
# 방향을 내면서 정작 요약에서는 그날 다른 것이 더 움직였다는 이유로 빠졌다 —
# 실측: 에너지 요약이 "휘발유 -8.64% · 난방유 -3.59%"라 WTI원유가 없었다.
# 브렌트유가 아니라 WTI인 이유는 브렌트에 선물 커브도 COT도 없어서다.
MACRO_PINNED = {
    "글로벌지수": ("나스닥", "S&P500"),
    "환율": ("원달러", "유로달러"),
    "지수선물": ("나스닥선물", "S&P500선물"),
    "채권금리": ("미10년물",),
    "변동성": ("VIX",),
    "금속": ("금",),
    "에너지": ("WTI원유",),
}


def _macro_note(group, items):
    """접힌 상태에서 보이는 한 줄. 고정 지표 + 가장 크게 움직인 하나."""
    def cell(r):
        return f'{esc(r["name"])} {pct(r["change_pct"])}'

    live = [r for r in items if r.get("change_pct") is not None]
    by_name = {r["name"]: r for r in live}
    pinned = [by_name[n] for n in MACRO_PINNED.get(group, ()) if n in by_name]

    # 고정이 없는 묶음(원자재 등)은 예전처럼 큰 것 둘.
    n_movers = 1 if pinned else 2
    rest = sorted((r for r in live if r not in pinned),
                  key=lambda r: -abs(r["change_pct"]))[:n_movers]
    return " · ".join(cell(r) for r in pinned + rest)


def _gold_spot_card(j, recs):
    """금 선물과 현물을 나란히. 없으면 ''.

    화면의 '금'은 COMEX 선물이다(`config.MACRO_SYMBOLS`가 `GC=F`). 실제로
    거래하는 것이 현물이면 수준이 다르다 — 실측 격차가 30~73포인트로
    흔들렸고 하루는 방향까지 반대였다. 그걸 모르고 보면 앱의 숫자와
    거래 화면의 숫자가 안 맞는 이유를 알 수 없다.

    **격차는 같은 스냅샷 안에서만 본다.** 어제 격차와 이으면 안 된다 —
    만기가 가까워지면 줄고 롤오버 때 튄다.
    """
    gs = j.get("gold_spot") or {}
    if gs.get("price") is None:
        return ""
    fut = next((r for r in recs
                if r.get("name") == "금" and not r.get("error")), None)
    rows = [["현물 <span class=\"dim\">gold-api</span>",
             num(gs["price"], 2), '<span class="dim">거래되는 값</span>']]
    sub = "현물만 받았습니다 — 선물 시세를 못 받았습니다"
    if fut and fut.get("price") is not None:
        gap = fut["price"] - gs["price"]
        rows.insert(0, [
            f'선물 <span class="dim">{esc(fut.get("contract") or "GC=F")}</span>',
            num(fut["price"], 2),
            '<span class="dim">아래 표·픽이 쓰는 값</span>'])
        rows.append(['<b>격차</b>', f'<b>{gap:+,.2f}</b>',
                     '<span class="dim">선물 − 현물</span>'])
        # card()가 sub를 이스케이프하므로 태그를 넣지 않는다.
        sub = ("아래 표와 오늘의 픽은 선물 기준입니다. "
               "격차는 만기·롤오버로 흔들리니 오늘 것끼리만 보십시오")
    return card("금 — 선물과 현물",
                rows_table(["", "가격", ""], rows, ["l", "r", "l"]), sub)


def render_macro(j):
    h = ""
    recs = j.get("records") or []
    groups = {}
    for r in recs:
        if not r.get("error"):
            groups.setdefault(r["group"], []).append(r)

    h += _gold_spot_card(j, recs)

    yc = j.get("yield_curve") or []
    if yc:
        rows = []
        for c in yc:
            mean = read.curve_meaning(c["label"], c.get("spread_bp"),
                                      c.get("inverted"))
            cls = "brk" if c.get("inverted") else "dim"
            rows.append([esc(c["label"]), f'{c["spread_bp"]:+,.1f}bp',
                         esc(read.curve_move(c.get("shape_move")) or "-"),
                         f'<span class="{cls}">{esc(mean)}</span>'])
        h += card("금리 커브", rows_table(["구간", "장단기 차이", "오늘 움직임", "의미"],
                                        rows, ["l", "r", "l", "l"]),
                  "장기금리 − 단기금리. 마이너스가 되면 역전이라 부르고 "
                  "침체 신호로 읽습니다")
    ins, prose = insight_slot("macro", j.get("collected_at"))
    # 칩과 픽은 규칙에서 낸다. 글은 서술이라 늦거나 없을 수 있는데,
    # 그때 화면이 옛 픽을 그대로 보여 주면 안 된다.
    h = (watch_strip(watch_items("macro", j, prose))
         + picks_card("macro", j, prose) + h + ins)

    dv = j.get("divergences") or []
    if dv:
        rows = [[('<span class="brk">★</span> ' if d["broken"] else "") + esc(d["pair"]),
                 pct(d["a"]["change_pct"]), pct(d["b"]["change_pct"]),
                 f'<span class="dim">통상 {esc(d["expected"])}</span>']
                for d in sorted(dv, key=lambda x: not x["broken"])]
        h += card("자산 간 관계", rows_table(["쌍", "A", "B", ""], rows,
                                          ["l", "r", "r", "r"]),
                  "★ = 통상 관계가 깨진 것")

    # 원자재는 재고·커브를 교차한 수급 판정을 붙인다. 가격만으로는
    # 지금 물건이 귀한 건지 남는 건지 안 보인다.
    inv_state = {r["name"]: r.get("state")
                 for r in (j.get("inventory_readings") or [])}
    curves = j.get("curves") or {}
    for g, items in groups.items():
        rows = []
        for r in items:
            n = r["name"]
            bias, why = read.commodity_bias(
                read.inventory_for(n, inv_state),
                (curves.get(n) or {}).get("spread_pct"))
            # 결론(어느 쪽으로 기울었나)을 앞에, 근거(수급 상태)를 뒤에.
            lean, cls = read.supply_lean(bias)
            tail = ""
            if lean:
                tail = f'<span class="rd {cls}">{esc(lean)}</span>'
                if bias:
                    tail += f' <span class="dim">{esc(bias)}</span>'
            # 선물이면 계약월을 이름 옆에 붙인다. '금'만 있으면 현물로
            # 읽히고, 롤오버로 근월물이 바뀌어도 모른 채 어제와 비교한다.
            label = esc(n)
            if r.get("contract"):
                label += f' <span class="dim">{esc(r["contract"])}</span>'
            rows.append([label, num(r.get("price"), 2), pct(r.get("change_pct")),
                         pct(r.get("change_20d_pct")),
                         f'<span class="dim">{esc(read.pos_52w(r.get("pos_52w")))}</span>',
                         tail])
        # 수급 판정이 하나도 없는 묶음(환율·금리 등)은 열을 줄인다
        has_bias = any(r[5] for r in rows)
        # 접힌 상태에서도 무슨 일이 있었는지 보이게 요약한다
        note = _macro_note(g, items)
        if has_bias:
            h += card(g, rows_table(
                ["이름", "현재가", "당일", "20일", "52주", "수급"],
                rows, ["l", "r", "r", "r", "r", "l"]),
                "수급 = 재고와 선물커브를 교차한 판정 · "
                "가격 예측이 아니라 지금 물건이 귀한지 남는지입니다",
                fold=True, note=note)
        else:
            # 수급 열만 뺀다. r[4]가 52주고 r[5]가 수급이다.
            h += card(g, rows_table(
                ["이름", "현재가", "당일", "20일", "52주"],
                [r[:5] for r in rows], ["l", "r", "r", "r", "r"]),
                fold=True, note=note)

    inv = j.get("inventories") or {}
    if inv:
        state = {r["name"]: r for r in (j.get("inventory_readings") or [])}
        rows = []
        for name, d in inv.items():
            st = state.get(name, {})
            plain, side = read.inventory_state(st.get("state"),
                                               d.get("vs_5y_avg_pct"))
            # 재고 판정은 등락이 아니다. 등락 색(적/청)과 섞지 않고 의미색을 쓴다.
            cell = (f'<span class="chip">{esc(plain)}</span>'
                    if plain in ("재고 부족", "재고 넘침")
                    else f'<span class="dim">{esc(plain)}</span>')
            if side:
                cell += f'<br><span class="dim">{esc(side)}</span>'
            rows.append([esc(name), f'{num(d["value"])} <span class="dim">{esc(d["unit"])}</span>',
                         f'{d.get("change_1w", 0):+,.0f}',
                         pct(d.get("vs_5y_avg_pct"), 1), cell])
        rd = next(iter(inv.values())).get("period")
        h += card("EIA 주간 재고", rows_table(
            ["항목", "재고", "주간", "평년대비", "판정"], rows,
            ["l", "r", "r", "r", "l"]),
            f"기준 {rd} · 평년(5년 평균)보다 5% 이상 적으면 재고 부족")

    cot = j.get("cot") or {}
    if cot:
        ext = {e["name"] for e in (j.get("cot_extremes") or [])}
        rows = []
        # 가격과 포지션 변화의 조합은 코인의 가격×미결제약정과 같은 구조다.
        px = {r["name"]: r.get("change_5d_pct")
              for r in (j.get("records") or []) if not r.get("error")}
        for name, d in sorted(cot.items(),
                              key=lambda kv: -abs(kv[1].get("spec_net_pct_oi") or 0)):
            mark = '<span class="brk">★</span> ' if name in ext else ""
            note = read.cot_reading(d.get("spec_ratio"),
                                    d.get("spec_net_pct_oi"),
                                    d.get("spec_net_change"))
            cls = "brk" if name in ext else "dim"
            fl, fl_why, fl_cls = read.cot_flow(px.get(name),
                                               d.get("spec_net_change"))
            tag = (f'<span class="rd {fl_cls}" title="{esc(fl_why)}">'
                   f'{esc(fl)}</span>' if fl else "")
            rows.append([mark + esc(name), num(d.get("spec_ratio"), 2),
                         f'{d.get("spec_net_pct_oi", 0):+.1f}%',
                         f'{d.get("spec_net_change", 0):+,}',
                         tag or f'<span class="{cls}">{esc(note)}</span>'])
        rd = next(iter(cot.values())).get("report_date")
        h += card("COT 투기 포지셔닝", rows_table(
            ["품목", "롱숏비", "OI대비", "전주대비", "자금 성격"], rows,
            ["l", "r", "r", "r", "l"]),
            f"헤지펀드가 어느 쪽에 걸었는지 · 5일 가격과 포지션 변화를 묶은 판정 · "
            f"CFTC 기준일 {rd} · ★ = 한쪽으로 극단 쏠림")

    cv = j.get("curves") or {}
    if cv:
        rows = []
        for n, c in sorted(cv.items(), key=lambda kv: kv[1]["spread_pct"]):
            verdict, why, cls = read.curve_shape(c["shape"], c.get("spread_pct"))
            # 결론을 앞에 둔다. 근거는 뒤에서 뒷받침한다.
            lean, lcls = read.supply_lean(verdict)
            tag = (f'<span class="rd {lcls or cls}">{esc(lean or verdict)}</span>'
                   if verdict else "")
            if lean and verdict != lean:
                tag += f' <span class="dim">{esc(verdict)}</span>'
            note = f'<span class="dim">{esc(why)}</span>' if why else ""
            if not c["monotonic"]:
                note += ' <span class="dim">· 계절성</span>'
            rows.append([esc(n), tag, f'{c["spread_pct"]:+.2f}%', note])
        h += card("선물 커브", rows_table(
            ["품목", "수급", "지금-나중 차이", "근거"], rows,
            ["l", "l", "r", "l"]),
            "지금 물건과 몇 달 뒤 물건의 가격 차이 · "
            "보관비만큼 나중이 비싼 게 정상이고, 지금이 더 비싸면 물건이 귀하다는 뜻")

    ns = j.get("news_stats") or {}
    h += card("뉴스", news_list(j.get("news_selected") or []),
              f"{ns.get('collected', 0):,}건 수집 → {ns.get('selected_for_llm', 0)}건 선별",
              fold=True, note=f"{ns.get('selected_for_llm', 0)}건")
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
    ins, prose = insight_slot("coin", j.get("collected_at"))
    # 칩과 픽은 규칙에서 낸다. 글은 서술이라 늦거나 없을 수 있는데,
    # 그때 화면이 옛 픽을 그대로 보여 주면 안 된다.
    h = (watch_strip(watch_items("coin", j, prose))
         + picks_card("coin", j, prose) + h + ins)

    sel = j.get("selected") or []
    if sel:
        # 파생 지표는 실행 위치에 따라 거래소가 달라진다 (미국 IP에서는
        # 바이낸스가 451이라 OKX로 받는다). 펀딩비·롱숏비의 절대 수준이
        # 거래소마다 다르므로, 어디서 온 값인지 보이지 않으면 어제와
        # 오늘을 비교할 때 없는 변화를 읽게 된다.
        src = j.get("derivatives_source", "binance")
        src_label = {"binance": "바이낸스", "okx": "OKX"}.get(src, src)
        src_sub = (f"펀딩비·미결제약정·롱숏비 출처: {src_label} 무기한선물 · "
                   f"거래소가 다르면 절대 수준을 비교하지 마세요")
        body = ""
        for c in sel:
            k = c.get("kimchi") or {}
            fr = c.get("funding_rate")
            fr_s = f'{fr*10000:+.2f}bp' if fr is not None else "-"
            # 가격과 미결제약정의 조합이 코인에서 가장 정보량이 크다.
            # 같은 상승도 신규 자금이면 이어지고 숏 커버링이면 끊긴다.
            flow, flow_why, flow_cls = read.coin_flow(
                c.get("change_7d"), c.get("oi_change_7d_pct"))
            fund, fund_cls = read.funding_reading(
                fr * 10000 if fr is not None else None)
            gap, gap_cls = read.crowd_gap(c.get("long_account_pct"),
                                          c.get("long_top_pct"))
            tags = ""
            if flow:
                tags += (f'<span class="rd {flow_cls}" title="{esc(flow_why)}">'
                         f'{esc(flow)}</span>')
            if fund and fund != "중립":
                tags += f'<span class="rd {fund_cls}">{esc(fund)}</span>'
            if gap:
                tags += f'<span class="rd {gap_cls}">{esc(gap)}</span>'

            body += (
                f'<div class="stock{hot_class(c.get("reasons"))}"><div class="srow">'
                f'<div><span class="sname">{esc(c["symbol"])}</span> '
                f'<span class="dim">#{c.get("rank")} {esc((c.get("name") or "")[:16])}</span></div>'
                f'<div class="sprice">${num(c.get("price"), 4)} {pct(c.get("change_pct"))}</div>'
                f'</div>'
                f'<div class="sbadges">{badges(c.get("reasons") or [])}</div>'
                + (f'<div class="sbadges">{tags}</div>' if tags else "")
                + f'<div class="sstats">'
                f'<span>7일 {pct(c.get("change_7d"))}</span>'
                f'<span>펀딩 {fr_s}</span>'
                f'<span>롱숏 {num(c.get("long_short_account"), 2)}</span>'
                f'<span>OI7일 {pct(c.get("oi_change_7d_pct"))}</span>'
                + (f'<span>김프 {pct(k.get("premium_pct"))}</span>' if k else "")
                + f'<span>ATH {pct(c.get("ath_change_pct"), 1)}</span>'
                f'</div></div>')
        h += card(f"선별 코인 {len(sel)}개", body,
                  src_sub + " · 7일 가격과 미결제약정을 묶어 자금 성격을 판정합니다")

    ns = j.get("news_stats") or {}
    sub = f"{ns.get('collected', 0):,}건 수집 → {ns.get('selected_for_llm', 0)}건 선별"
    if ns.get("uncovered"):
        sub += f" · 뉴스 없음: {', '.join(ns['uncovered'])}"
    h += card("뉴스", news_list(j.get("news_selected") or []), sub, fold=True, note=f"{ns.get('selected_for_llm', 0)}건")
    return h


RENDERERS = {"kr": render_kr, "us": render_us,
             "macro": render_macro, "coin": render_coin}


# ---------------------------------------------------------------- 조립
CSS = """
*{box-sizing:border-box;margin:0;padding:0}

/* 스크롤 90px에서 헤더 제목줄이 접힌다(아래 .hrow). 문서 높이가 그만큼
   줄어들면 브라우저 스크롤 앵커링이 "보던 자리를 유지"하려고 scrollY를
   자동으로 내린다 — 그러면 90 밑으로 내려가 제목줄이 다시 펴지고,
   문서 높이가 늘어 앵커링이 이번엔 scrollY를 다시 올린다. 이 왕복이
   경계 근처에 머무는 한 안 끝나 "한 칸 내린 채로 계속 떨리는" 것으로
   보인다(실측 2026-08-14, 크롬). 헤더 하나에만 걸면 앵커 후보가 다른
   요소로 잡혀 안 먹으므로 문서 스크롤 컨테이너(html)에서 통째로 끈다. */
html{overflow-anchor:none}

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
  --up-bg:#fdeced; --down-bg:#eaf1fd;   /* 해석 태그 배경 */
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
    --up-bg:#2a1416; --down-bg:#0f1e2e;
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
  --up-bg:#fdeced; --down-bg:#eaf1fd;
  --shadow:0 1px 2px rgba(13,20,24,.06);
}
:root[data-theme="dark"]{
  --bg:#0b0f14; --surface:#131a22; --sunken:#0e141a;
  --line:#222c36; --line-soft:#1a232b;
  --tx:#e3edf3; --dim:#8496a3;
  --up:#ff6b6b; --down:#60a5fa; --flat:#6b7c88;
  --acc:#22d3ee; --warn:#f59e0b; --warn-bg:#2a1f0d;
  --up-bg:#2a1416; --down-bg:#0f1e2e;
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
/* 스크롤하면 제목줄을 접어 탭만 남긴다. 헤더가 111px로 화면의 14%를
   차지하고 있었는데, 스크롤 중에 계속 필요한 건 탭뿐이다. */
header.min{padding-top:6px}
header.min .hrow{max-height:0;opacity:0;overflow:hidden;margin:0}
.hrow{transition:max-height .18s,opacity .18s;max-height:60px}
@media(prefers-reduced-motion:reduce){.hrow{transition:none}}
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
/* 표본이 모자란다는 경고. 적중률 옆에 붙어야 숫자만 떼어 읽히지 않는다 */
/* div도 받는다 — 인사이트 카드의 '글이 숫자보다 오래됐다'가 div로 온다. */
p.warn,div.warn{color:var(--warn);background:var(--warn-bg);border-radius:5px;
  padding:8px 10px;font-size:12px;line-height:1.5;margin:8px 0 0}
/* 장 상태의 신호 목록. 부호를 앞에 세워 무엇이 어느 쪽인지 훑어보게 한다 */
/* '오늘' 탭의 픽 목록. 순위를 앞에 세워 훑을 때 눈이 걸리게 한다. */
ol.picks{list-style:none;margin:8px 0 0;padding:0}
ol.picks li{padding:6px 0;font-size:14px;border-bottom:1px solid var(--line-soft);
  display:flex;align-items:baseline;gap:7px;flex-wrap:wrap}
ol.picks li:last-child{border-bottom:none}
ol.picks .rank{flex:0 0 auto;min-width:18px;font-weight:700;color:var(--acc)}
a.goto{color:var(--acc);text-decoration:none}
a.goto:hover{text-decoration:underline}
ul.sig{list-style:none;margin:8px 0 0;padding:0}
ul.sig li{padding:4px 0;font-size:13px;border-bottom:1px solid var(--line-soft)}
ul.sig li:last-child{border-bottom:none}
ul.sig span{display:inline-block;min-width:26px;font-weight:700;
  font-variant-numeric:tabular-nums}
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
.sstats{display:flex;flex-wrap:wrap;gap:3px 14px;color:var(--dim);font-size:12.5px}

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

/* ---- 접기 ---- */
details.fold>summary,details.sec>summary{cursor:pointer;list-style:none;
  display:flex;align-items:center;gap:8px;min-height:44px}
details.fold>summary::-webkit-details-marker,
details.sec>summary::-webkit-details-marker{display:none}
details.fold>summary::after,details.sec>summary::after{content:"";margin-left:auto;
  width:7px;height:7px;border-right:2px solid var(--dim);border-bottom:2px solid var(--dim);
  transform:rotate(45deg);transition:transform .15s;flex:none}
details.fold[open]>summary::after,details.sec[open]>summary::after{transform:rotate(-135deg)}
details.fold>summary h2{margin:0}
.fnote{color:var(--dim);font-size:11.5px;font-variant-numeric:tabular-nums;
  white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
details.sec{border-top:1px solid var(--line-soft);padding:2px 0}
details.sec:first-child{border-top:none}
details.sec>summary{font-size:14.5px;font-weight:700;color:var(--tx);padding:8px 0}
details.sec[open]>summary{color:var(--acc)}

/* ---- 오늘 주목 ---- */
.watch h2{margin-bottom:8px}
.wchips{display:flex;flex-wrap:wrap;gap:6px}
.wc{background:var(--sunken);border:1px solid var(--line);border-radius:14px;
  padding:8px 12px;font-size:13px;font-weight:650;color:var(--tx);
  text-decoration:none;display:inline-block}
.wc:active{background:var(--line)}
.wc:focus-visible{outline:2px solid var(--acc);outline-offset:2px}
/* 뛰어간 자리를 잠깐 표시한다. 안 그러면 어디로 왔는지 모른다. */
.md h4.hit{background:var(--warn-bg);border-radius:5px;
  box-shadow:0 0 0 6px var(--warn-bg);transition:background .3s,box-shadow .3s}

/* ---- 새로고침 ---- */
.hrow{display:flex;align-items:flex-start;gap:10px}
.hrow>div{min-width:0;flex:1}
#rf{flex:none;width:40px;height:40px;border-radius:10px;border:1px solid var(--line);
  background:var(--surface);color:var(--tx);font-size:17px;line-height:1;cursor:pointer}
#rf:active{background:var(--sunken)}
#rf.spin{animation:sp .8s linear infinite}
@keyframes sp{to{transform:rotate(360deg)}}
#newv{position:fixed;left:50%;transform:translateX(-50%);bottom:calc(16px + env(safe-area-inset-bottom));
  z-index:30;background:var(--acc);color:#fff;border:none;border-radius:20px;
  padding:11px 20px;font-size:13.5px;font-weight:700;box-shadow:0 4px 14px rgba(0,0,0,.25);
  display:none;cursor:pointer}
#newv.on{display:block}
/* 해석 태그 — 등락 색(적/청)과 섞이면 안 되므로 의미색을 따로 쓴다 */
.rd{display:inline-block;border-radius:3px;padding:1px 7px;font-size:11px;
  font-weight:650;border:1px solid transparent}
.rd.good{background:var(--up-bg);color:var(--up)}
.rd.bad{background:var(--down-bg);color:var(--down)}
.rd.warn{background:var(--warn-bg);color:var(--warn)}
.rd.flat{border-color:var(--line);color:var(--dim)}
.pstamp{color:var(--dim);font-size:11.5px;padding:10px 2px 0;
  font-variant-numeric:tabular-nums;display:flex;gap:6px;align-items:center}
.pstamp .old{background:var(--warn-bg);color:var(--warn);border-radius:3px;
  padding:1px 6px;font-weight:650}
@media(prefers-reduced-motion:reduce){*{transition:none!important;animation:none!important}}
"""

JS = """
// 탭마다 스크롤 위치를 따로 기억한다. 한 탭이 12화면이라
// 위치가 섞이면 다른 탭에서 엉뚱한 곳이 보인다.
const POS={};
let cur=document.querySelector('nav button.on')?.dataset.m;

document.querySelectorAll('nav button').forEach(b=>{
  b.onclick=()=>{
    if(cur) POS[cur]=window.scrollY;
    document.querySelectorAll('nav button').forEach(x=>x.classList.remove('on'));
    document.querySelectorAll('.panel').forEach(x=>x.classList.remove('on'));
    b.classList.add('on');
    document.getElementById('p-'+b.dataset.m).classList.add('on');
    cur=b.dataset.m;
    window.scrollTo(0,POS[cur]||0);
    try{localStorage.setItem('tab',cur)}catch(e){}
  };
});
// '오늘' 카드의 "자세히 →"가 해당 시장 탭을 연다. 탭 전환은 nav 버튼이
// 갖고 있으므로(스크롤 위치 기억이 거기 걸려 있다) 그 버튼을 눌러 준다.
document.querySelectorAll('a.goto').forEach(a=>{
  a.onclick=e=>{
    e.preventDefault();
    const b=document.querySelector(`nav button[data-m="${a.dataset.goto}"]`);
    if(b){b.click(); window.scrollTo(0,0);}
  };
});
try{
  const t=localStorage.getItem('tab');
  if(t){const b=document.querySelector(`nav button[data-m="${t}"]`); if(b)b.click();}
}catch(e){}

// ---- 새로고침 ----
// 캐시를 비우고 다시 받는다. 서비스워커가 옛 페이지를 붙들고 있으면
// 그냥 reload로는 바뀐 게 안 보인다.
async function hardReload(){
  const rf=document.getElementById('rf');
  if(rf) rf.classList.add('spin');
  try{
    if(window.caches){const ks=await caches.keys(); await Promise.all(ks.map(k=>caches.delete(k)));}
  }catch(e){}
  location.reload();
}
document.getElementById('rf')?.addEventListener('click',hardReload);
document.getElementById('newv')?.addEventListener('click',hardReload);

// 앱을 다시 열었을 때 새 데이터가 올라와 있으면 알려 준다.
// 자동으로 새로고침하지는 않는다 — 읽던 중이면 끊기니까.
let away=0;
async function checkNew(){
  try{
    const r=await fetch('version.json?'+Date.now(),{cache:'no-store'});
    if(!r.ok) return;
    const v=(await r.json()).build;
    if(v && v!==window.__BUILD__) document.getElementById('newv')?.classList.add('on');
  }catch(e){}
}
document.addEventListener('visibilitychange',()=>{
  if(document.hidden){away=Date.now();return;}
  // 잠깐 전환한 것까지 매번 확인하면 낭비다. 1분 넘게 떠나 있었을 때만.
  if(Date.now()-away>60000) checkNew();
});
if(navigator.onLine) setTimeout(checkNew,3000);

// 오늘 주목 칩 → 본문 항목으로 이동.
// 대상이 접힌 섹션 안에 있으면 먼저 펼쳐야 한다. 그냥 앵커로 두면
// display:none인 곳으로 뛰어 아무 일도 안 일어난 것처럼 보인다.
document.querySelectorAll('a.wc').forEach(a=>{
  a.addEventListener('click',ev=>{
    ev.preventDefault();
    const el=document.getElementById(a.getAttribute('href').slice(1));
    if(!el) return;
    for(let p=el.parentElement;p;p=p.parentElement){
      if(p.tagName==='DETAILS') p.open=true;
    }
    const top=el.getBoundingClientRect().top+window.scrollY
              -(document.querySelector('header')?.offsetHeight||0)-10;
    window.scrollTo({top,behavior:'smooth'});
    el.classList.add('hit');
    setTimeout(()=>el.classList.remove('hit'),1600);
  });
});

// 경과 시간은 여기서 센다. 파이썬이 구울 때 계산해 박아 두면 다시 구울
// 때까지 얼어붙어서, 몇 시간이 지나도 '56분 전'이라 떠 있었다. 폰 앱은
// 한 번 연 화면을 며칠씩 띄워 두므로 특히 오래 어긋난다.
// _ago_text()와 규칙이 같아야 한다 — 한쪽만 고치면 새로 고치기 전후로
// 표기가 달라진다.
function ago(h){
  if(h<1) return Math.round(h*60)+'분 전';
  if(h<48) return Math.round(h)+'시간 전';
  return Math.round(h/24)+'일 전';
}
function freshen(){
  const now=Date.now();
  document.querySelectorAll('.ago[data-ts]').forEach(el=>{
    const t=Date.parse(el.dataset.ts);
    if(isNaN(t)) return;                       // 못 읽으면 구운 값을 그대로 둔다
    el.textContent=ago(Math.max(0,(now-t)/3600000));
  });
  document.querySelectorAll('.old[data-warn]').forEach(el=>{
    const t=Date.parse(el.dataset.warn);
    if(isNaN(t)) return;
    el.hidden=((now-t)/3600000)<18;
  });
}
freshen();
setInterval(freshen,60000);
// 폰에서 앱을 다시 열면 그 사이 흐른 시간을 바로 반영한다.
addEventListener('visibilitychange',()=>{if(!document.hidden)freshen()});

// 스크롤하면 헤더의 제목줄을 접는다. 탭은 계속 보인다.
// 경계 하나(90px)로 켜고 끄면, 제목줄이 접히며 문서 높이가 줄어드는
// 것 자체가 다음 scroll 이벤트를 유발해 그 경계 근처에서 계속
// 왕복한다(위 overflow-anchor 주석 참고). 켜는 값과 끄는 값을 벌려
// 한 번 넘으면 반대쪽 경계를 넘기 전까지 안 흔들리게 한다.
const hd=document.querySelector('header');
let min=false;
addEventListener('scroll',()=>{
  const y=window.scrollY;
  if(!min && y>100) min=true;
  else if(min && y<70) min=false;
  hd?.classList.toggle('min', min);
},{passive:true});
"""


def _ago_text(hrs):
    """경과 시간을 사람 말로. 자바스크립트 쪽 ago()와 규칙이 같아야 한다 —
    한쪽만 고치면 새로 고치기 전후로 표기가 달라진다."""
    if hrs < 1:
        return f"{hrs*60:.0f}분 전"
    if hrs < 48:
        return f"{hrs:.0f}시간 전"
    return f"{hrs/24:.0f}일 전"


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
    # 경과 시간은 브라우저가 다시 센다. 여기서 계산해 문자열로 박으면
    # 다시 구울 때까지 그대로 얼어붙는다 — 몇 시간이 지나도 '56분 전'이라
    # 떠서, 오래된 데이터를 방금 받은 것으로 읽게 된다. '갱신 필요'도
    # 같은 이유로 안 뜬다. 아래 값은 자바스크립트가 꺼졌을 때의 대비책일
    # 뿐이고, 정상 경로에서는 data-ts를 보고 매분 다시 쓴다.
    hrs = (dt.datetime.now() - when).total_seconds() / 3600
    ago = _ago_text(hrs)
    hide = "" if hrs >= 18 else " hidden"
    ts = esc(when.isoformat(timespec="seconds"))
    return (f'<div class="pstamp"><span>수집 {when:%m-%d %H:%M} '
            f'(<span class="ago" data-ts="{ts}">{ago}</span>)</span>'
            f'<span class="old" data-warn="{ts}"{hide}>갱신 필요</span></div>')


def _today_picks(key, j):
    """그 스냅샷에서 규칙이 뽑은 픽. 반환: (픽 리스트, 실패 사유 또는 None).

    **`history`가 아니라 스냅샷에서 다시 계산한다.** 기록을 읽으면 히스토리가
    없는 클론에서 빈 화면이 되고, 무엇보다 지금 화면에 뜬 데이터와 픽이
    다른 스냅샷일 수 있다. 여기서 계산하면 아래 시장 탭이 보여 주는 바로
    그 데이터에서 나온 픽이 된다.

    `pick.block()`이 프롬프트를 만들 때 쓰는 것과 같은 경로다 — 화면과
    프롬프트가 다른 픽을 말하면 안 된다.
    """
    try:
        picks, _dropped = pick.current(key, j)
        return picks, None
    except Exception as e:                      # 한 자산군이 죽어도 나머지는 뜬다
        return [], f"{type(e).__name__}: {str(e)[:60]}"


def _last_result_line():
    """직전 픽이 어떻게 됐는지 한 줄. 없으면 None.

    적중률을 여기서 크게 내지 않는다 — 표본이 차기 전에는 그 숫자가 동전과
    구별되지 않는다(`score_picks.py`가 매번 그렇게 말한다). 자산군별 성적은
    각 탭의 '픽 성적' 카드가 신뢰구간까지 함께 낸다.
    """
    try:
        rows = history.pairs()
        if not rows:
            return None
        day = max((p.get("at") or "")[:10] for p, _ in rows)
        same = [(p, o) for p, o in rows if (p.get("at") or "")[:10] == day]
        vs = [v for p, o in same for v in [history.abs_verdict(p, o)] if v]
        hit = sum(1 for v in vs if v == "맞음")
        flat = sum(1 for v in vs if v == "횡보")
        d = len(vs) - flat
        if not d:
            return (f'{esc(day)} 픽 {len(vs)}종 — 전부 횡보'
                    f'<span class="dim"> (방향이라 할 만한 움직임이 없었음)</span>')
        return (f'{esc(day)} 픽 {d}종 중 <b>{hit}종</b>이 방향대로'
                + (f'<span class="dim"> · 횡보 {flat}종</span>' if flat else ""))
    except Exception:
        return None


def today_panel():
    """4개 자산군을 한 화면에 — 오늘 무엇이 뽑혔고 장이 어떤 상태인가.

    탭 하나가 12~15화면이라 오늘 전체를 보려면 네 번 들어갔다 나와야 했다.
    매일 보는 것은 그중 두 줄뿐이다.

    **여기서 픽을 직접 낸다.** 그전에는 픽이 화면에 오르는 길이 손으로 쓴
    인사이트 글뿐이었다(`fold_insight`가 글의 h4를 칩으로 뽑는다). 그래서
    루틴을 놓친 날은 규칙이 계산해 둔 픽이 아예 안 보였다 — 실측으로 미장
    인사이트가 운영 6일 중 4일만 쓰였다. 글은 못 써도 픽은 나와 있어야 한다.

    **자세한 것은 안 넣는다.** 근거 목록도 뉴스도 지표도 시장 탭에 이미 있다.
    여기 다 옮기면 한 화면이라는 이유가 사라진다.
    """
    h = ""
    last = _last_result_line()
    if last:
        h += card("직전 픽 결과", f'<p>{last}</p>'
                  '<p class="dim">자산군별 성적과 표본이 충분한지는 각 탭의 '
                  '&#39;픽 성적&#39;에 있습니다.</p>')

    for key, label, icon in MARKETS:
        j = latest_json(key)
        if not j:
            h += card(f"{icon} {esc(label)}",
                      '<p class="dim">데이터 없음 — 아직 수집되지 않았습니다.</p>')
            continue

        rows = [_age_line(j.get("collected_at", ""))]

        try:
            r = regime.judge(key, j)
            cls = {"우호": "up", "비우호": "down"}.get(r["state"], "flat")
            rows.append(f'<div class="grid">'
                        f'<div class="kv"><span class="k">장 상태</span>'
                        f'<span class="v {cls}">{esc(r["state"])}</span></div>'
                        f'<div class="kv"><span class="k">신호</span>'
                        f'<span class="v">{r["n"]}개 · 합계 {r["score"]:+d}'
                        f'</span></div></div>')
        except Exception:
            rows.append('<p class="dim">장 상태를 판정하지 못했습니다.</p>')

        picks, err = _today_picks(key, j)
        if err:
            rows.append(f'<p class="dim">픽 계산 실패 — {esc(err)}</p>')
        elif not picks:
            # 빈 것과 못 잰 것은 다르다. 왜 비었는지 밝힌다.
            rows.append('<p class="dim">뽑힌 것이 없습니다 — 점수가 0 근처면 '
                        '근거가 없거나 서로 맞선다는 뜻이라 빠집니다.</p>')
        else:
            items = ""
            for i, p in enumerate(picks, 1):
                k = p.get("kind") or ""
                kc = {"상승": "up", "하락": "down",
                      "피할 것": "down"}.get(k, "flat")
                n = len(p.get("why") or [])
                items += (f'<li><span class="rank">{i}</span> '
                          f'{esc(p.get("label") or p.get("key"))} '
                          f'<span class="{kc}">{esc(k)}</span> '
                          f'<span class="dim">{p.get("score"):+d}점 · '
                          f'근거 {n}개</span></li>')
            rows.append(f'<ol class="picks">{items}</ol>')

        # 탭 전환은 해시가 아니라 nav 버튼이 갖고 있다(위치 기억이 걸려 있다).
        # 그래서 링크가 아니라 그 버튼을 눌러 준다.
        rows.append(f'<p class="dim"><a href="#" class="goto" '
                    f'data-goto="{key}">{esc(label)} 자세히 →</a></p>')
        h += card(f"{icon} {esc(label)}", "".join(rows))

    h += ('<p class="dim" style="padding:0 14px 18px">점수는 오를 확률이 아니라 '
          '<b>오를 근거가 얼마나 두껍게 쌓였는지</b>입니다. '
          '방향이 틀렸다고 볼 조건은 각 탭의 인사이트에 있습니다.</p>')
    return h


def _body():
    """헤더 + 탭 + 패널. 단독 HTML과 아티팩트가 공유한다."""
    panels, tabs, stamps = "", "", []
    # '오늘'을 첫 탭으로 둔다. 매일 여는 화면이 여기여야 한다.
    tabs += '<button data-m="today" class="on">📅 오늘</button>'
    panels += f'<div class="panel on" id="p-today">{today_panel()}</div>'
    first = False
    for key, label, icon in MARKETS:
        j = latest_json(key)
        on = " on" if first else ""
        tabs += (f'<button data-m="{key}" class="{on.strip()}">'
                 f'{icon} {esc(label)}</button>')
        if j:
            iso = j.get("collected_at", "")
            stamps.append(iso[:16].replace("T", " "))
            body = (_age_line(iso) + regime_card(key, j)
                    + RENDERERS[key](j) + picks_scorecard(key))
        else:
            body = card("데이터 없음",
                        f'<p class="dim">collect_{key}.py를 먼저 실행하세요.</p>')
        panels += f'<div class="panel{on}" id="p-{key}">{body}</div>'
        first = False

    stamp = max(stamps) if stamps else "-"
    head = (f'<header><div class="hrow"><div>'
            f'<h1>자산 인사이트</h1>'
            f'<div class="stamp">최종 수집 {esc(stamp)} · '
            f'생성 {dt.datetime.now():%m-%d %H:%M}</div></div>'
            f'<button id="rf" title="새로고침" aria-label="새로고침">↻</button>'
            f'</div><nav>{tabs}</nav></header>')
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
    # 앱이 '새 데이터가 올라왔나'를 물어볼 대상. 페이지에 박은 값과
    # 비교해 다르면 새로고침 버튼을 띄운다. 전체 HTML을 다시 받지
    # 않아도 되므로 앱을 열 때마다 확인해도 부담이 없다.
    build_id = dt.datetime.now().strftime("%Y%m%d%H%M%S")
    (docs / "version.json").write_text(
        json.dumps({"build": build_id, "collected": stamp}, ensure_ascii=False),
        encoding="utf-8")

    # 매크로 데스크가 읽어 갈 숫자 피드. 판정은 넣지 않는다 — core/feed.py 참고.
    from core import feed
    feed.write(docs / "feed.json", latest_json("macro"), latest_json("us"))

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
<button id="newv">새 데이터가 있습니다 · 탭하여 갱신</button>
<script>window.__BUILD__="{build_id}";{JS}{pwa.REGISTER_SW}</script>
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
