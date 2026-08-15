# -*- coding: utf-8 -*-
"""알림 발송 — 지금은 잠들어 있다

**설정이 없으면 아무것도 하지 않는다.** 이 저장소에 토큰을 넣지 않았으므로
`send()`는 "설정 없음"만 돌려주고 끝난다. 시중에 낼 때 GitHub Secrets에
값을 넣으면 그때부터 돈다 — **코드는 다시 안 고쳐도 된다.**

    NOTIFY_TELEGRAM_TOKEN + NOTIFY_TELEGRAM_CHAT   텔레그램 봇
    NOTIFY_DISCORD_WEBHOOK                         디스코드 웹훅

둘 다 넣으면 둘 다 간다. 왜 이 둘이냐면 **서버가 필요 없기 때문이다.**
웹 푸시(PWA)는 푸시 서버를 따로 띄워야 하는데 이 프로젝트는 GitHub Pages라
띄울 곳이 없다. 봇·웹훅은 POST 한 번이라 Actions 안에서 끝난다.

## 무엇을 보내나

폰 알림은 한 화면이다. 그래서 **오늘 것만** 보낸다 — 장 상태 한 줄, 픽,
어제 결과 한 줄. 나머지는 링크로 넘긴다.

## 무엇을 안 보내나

화면·글과 같은 규칙을 그대로 받는다. 알림이라고 느슨해지면 안 된다.

- **사라·팔라·목표가·손절가를 쓰지 않는다.** 개인 거래규칙은
  `notes/trading-rules.md` 에 있고 그건 읽는 사람 몫이다.
- **방향은 픽에만 붙인다.** `core/pick.py` 가 계산한 것을 옮기기만 한다.
- **못 받은 것은 못 받았다고 쓴다.** 자산군이 빠지면 조용히 빼지 않는다 —
  안 그러면 "오늘은 코인에 별일 없었다"로 읽힌다.
"""
import os

import requests

from core import history

# 알림에 넣을 순서. 화면 탭과 같은 순서라야 눌렀을 때 헷갈리지 않는다.
MARKETS = [("kr", "국장"), ("us", "미장"), ("macro", "매크로"), ("coin", "코인")]

SITE = "https://enair840926-star.github.io/insight/"

TIMEOUT = 15


def configured():
    """설정된 채널 이름 목록. 비어 있으면 알림은 잠들어 있는 것이다."""
    out = []
    if os.getenv("NOTIFY_TELEGRAM_TOKEN") and os.getenv("NOTIFY_TELEGRAM_CHAT"):
        out.append("telegram")
    if os.getenv("NOTIFY_DISCORD_WEBHOOK"):
        out.append("discord")
    return out


def _newest_per_market(records):
    """자산군별로 `at`이 가장 늦은 레코드 하나. 반환: {market: record}."""
    out = {}
    for r in records:
        m, at = r.get("market"), r.get("at") or ""
        if not m or not at:
            continue
        if m not in out or at > (out[m].get("at") or ""):
            out[m] = r
    return out


def _latest_by_market():
    """자산군별 가장 최근 픽 묶음과 장 상태. 반환: ({m: (at, [pick])}, {m: regime}).

    `history` 를 읽는다. 스냅샷을 다시 계산하지 않는 이유는, **화면과 알림이
    다른 숫자를 말하면 안 되기 때문이다.** 기록된 것이 곧 그때 낸 판단이다.

    `load_regimes()` 는 id로 키를 잡으므로 자산군별 최신으로 다시 묶는다.
    """
    picks, _ = history.load()
    newest = _newest_per_market(picks.values())
    latest = {}
    for m, r in newest.items():
        at = r["at"]
        ps = [p for p in picks.values()
              if p.get("market") == m and p.get("at") == at]
        ps.sort(key=lambda x: x.get("rank") or 99)
        latest[m] = (at, ps)
    return latest, _newest_per_market(history.load_regimes().values())


def _yesterday_line():
    """어제 픽이 어떻게 됐는지 한 줄. 없으면 None.

    적중률을 여기서 자랑하지 않는다 — 표본이 차기 전에는 그 숫자가
    동전과 구별되지 않는다(`score_picks.py`가 매번 그렇게 말한다).
    '몇 종 중 몇 종이 방향대로'까지만 쓴다.
    """
    rows = history.pairs()
    if not rows:
        return None
    day = max((p.get("at") or "")[:10] for p, _ in rows)
    same = [(p, o) for p, o in rows if (p.get("at") or "")[:10] == day]
    verdicts = [v for p, o in same for v in [history.abs_verdict(p, o)] if v]
    hit = sum(1 for v in verdicts if v == "맞음")
    flat = sum(1 for v in verdicts if v == "횡보")
    d = len(verdicts) - flat
    if not d:
        return f"직전 픽 {len(verdicts)}종 — 전부 횡보(방향이라 할 만한 움직임 없음)"
    return (f"직전 픽 {d}종 중 {hit}종이 방향대로"
            + (f" · 횡보 {flat}종" if flat else ""))


def build(markets=None):
    """보낼 본문을 만든다. 설정과 무관하게 언제나 만들 수 있다(미리보기용)."""
    want = [m for m in (markets or [k for k, _ in MARKETS])]
    latest, regimes = _latest_by_market()

    lines = ["📊 자산 인사이트"]
    for key, label in MARKETS:
        if key not in want:
            continue
        got = latest.get(key)
        if not got:
            # 조용히 빼면 '별일 없었다'로 읽힌다. 빠졌다고 쓴다.
            lines.append(f"\n[{label}] 오늘 기록 없음 — 수집이 안 됐거나 픽이 안 나왔습니다")
            continue
        at, ps = got
        r = regimes.get(key)
        head = f"\n[{label}] {at[5:16].replace('T', ' ')}"
        if r and r.get("state"):
            head += f" · 장 상태 {r['state']}"
        lines.append(head)
        for p in ps:
            kind = p.get("kind") or ""
            name = (p.get("label") or p.get("key") or "").split(" — ")[0]
            lines.append(f"  {p.get('rank')}. {name} · {kind} ({p.get('score'):+d}점)")

    y = _yesterday_line()
    if y:
        lines.append(f"\n{y}")

    lines.append(f"\n{SITE}")
    # 점수는 오를 확률이 아니다. 알림만 보고 오해하지 않도록 매번 붙인다.
    lines.append("점수는 오를 확률이 아니라 근거가 얼마나 쌓였는지입니다.")
    return "\n".join(lines)


def _telegram(text):
    tok = os.getenv("NOTIFY_TELEGRAM_TOKEN")
    chat = os.getenv("NOTIFY_TELEGRAM_CHAT")
    try:
        r = requests.post(f"https://api.telegram.org/bot{tok}/sendMessage",
                          json={"chat_id": chat, "text": text,
                                "disable_web_page_preview": True},
                          timeout=TIMEOUT)
        return r.status_code == 200, f"HTTP {r.status_code}"
    except requests.RequestException as e:
        return False, str(e)[:120]


def _discord(text):
    url = os.getenv("NOTIFY_DISCORD_WEBHOOK")
    try:
        r = requests.post(url, json={"content": text[:1900]}, timeout=TIMEOUT)
        return r.status_code in (200, 204), f"HTTP {r.status_code}"
    except requests.RequestException as e:
        return False, str(e)[:120]


_SENDERS = {"telegram": _telegram, "discord": _discord}


def send(text=None, markets=None):
    """설정된 채널로 보낸다. 반환: {채널: (성공, 메모)}.

    **설정이 없으면 빈 dict를 돌려주고 아무것도 안 한다.** 수집 워크플로가
    이걸 매번 불러도 지금은 아무 일도 일어나지 않는다는 뜻이다.

    보내기 실패가 수집을 죽이면 안 된다. `core/http.py` 와 같은 이유로
    예외를 밖으로 내보내지 않는다.
    """
    chans = configured()
    if not chans:
        return {}
    body = text if text is not None else build(markets)
    return {c: _SENDERS[c](body) for c in chans}
