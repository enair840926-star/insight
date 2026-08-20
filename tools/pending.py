# -*- coding: utf-8 -*-
"""인사이트를 다시 써야 하는 자산군 찾기

    python tools/pending.py          # 자산군 이름만 출력 (없으면 빈 줄)
    python tools/pending.py -v       # 이유까지

루틴이 시각만 보고 돌면 수집보다 먼저 돌아 헛돈다. GitHub 예약이
한 시간까지 밀리기 때문이다. 대신 '데이터가 인사이트보다 새로운가'를
보면 순서에 상관없이 옳게 동작한다 — 수집이 늦어도 그다음 루틴이
받아 간다.

비교 기준:
  수집 시각   파일명에 박힌 값 (mtime은 git이 받을 때 바뀌어 못 쓴다)
  작성 시각   insights/ 파일의 마지막 커밋 시각
"""
import argparse
import datetime as dt
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import session, store

ROOT = store.ROOT
MARKETS = ["kr", "us", "macro", "coin"]
LABELS = {"kr": "국장", "us": "미장", "macro": "매크로", "coin": "코인"}


def collected_at(market):
    """최신 수집 시각. 파일명에서 읽는다."""
    p = store.latest(f"prompt_{market}_2*.txt")
    if not p:
        return None
    m = store._STAMP.search(p.name)
    if not m:
        return None
    try:
        return dt.datetime.strptime(m.group(1), "%Y%m%d_%H%M")
    except ValueError:
        return None


def written_at(market):
    """인사이트를 마지막으로 쓴 시각. 커밋 시각을 쓴다 —
    파일 수정 시각은 git이 받아올 때 갱신돼 못 쓴다."""
    f = ROOT / "insights" / f"insight_{market}.md"
    if not f.exists():
        return None
    try:
        r = subprocess.run(["git", "log", "-1", "--format=%cI", "--", str(f)],
                           capture_output=True, text=True, timeout=15,
                           cwd=str(ROOT))
        s = (r.stdout or "").strip()
        if s:
            return dt.datetime.fromisoformat(s).astimezone().replace(tzinfo=None)
    except (OSError, ValueError, subprocess.SubprocessError):
        pass
    return None


# 각 자산군이 어느 장의 개장을 따르는가. 매크로는 두 장의 배경이라
# 더 가까운 쪽, 코인은 미국 세션과 같이 움직인다.
FOLLOWS = {"kr": "kr", "us": "us", "macro": None, "coin": "us"}

# --auto가 개장 몇 시간 전부터 수집하는가. 값은 core/session.py가 갖는다 —
# run.py와 여기가 각자 숫자를 들고 있으면 한쪽만 고쳤을 때, 수집은 앞당겨졌는데
# 루틴은 그 데이터를 '이번 세션 것이 아니다'로 보고 계속 기다리게 된다.
WINDOW_H = session.PRE_OPEN_WINDOW_H


def waiting_for_collection(market, now=None):
    """이번 세션 수집이 아직 안 왔으면 True — 쓰지 말고 다음 루틴에 넘긴다.

    GitHub 예약은 예측 불가하게 밀린다(실측: 21:20 예약이 21:31,
    07:20 예약이 10:34). 루틴 시각을 고정해 두면 수집을 앞지르는 회차가
    생기고, 그 회차가 쓴 글은 곧 도착하는 새 데이터에 덮여 버려진다.

    실제로 08-07에 그랬다 — 21:12 루틴이 18:55 데이터로 코인을 썼는데
    21:31에 수집이 도착해 22:12 루틴이 다시 썼다.

    그래서 '개장 전 수집 창 안에 있는데 이번 세션 데이터가 아직 없다'면
    기다린다. 장이 열리면 더 기다리지 않고 쓴다 — 수집이 아예 안 왔을
    수도 있으므로 무한정 미루면 안 된다.
    """
    ref = FOLLOWS.get(market, market)
    if ref is None:                       # 매크로 — 더 가까운 개장을 따른다
        cands = [session.describe(k, now) for k in ("kr", "us")]
        cands = [d for d in cands if d.get("next_open")]
        if not cands:
            return False
        d = min(cands, key=lambda x: x["next_open"])
    else:
        d = session.describe(ref, now)
        if d["state"] == "장중":           # 이미 열렸으면 기다릴 이유가 없다
            return False
        if not d.get("next_open"):
            return False

    now = now or dt.datetime.now().astimezone()
    open_at = d["next_open"]
    start = open_at - dt.timedelta(hours=WINDOW_H)
    if not (start <= now < open_at):      # 수집 창 밖이면 기다리지 않는다
        return False

    c = collected_at(market)
    if c is None:
        return True
    # 파일명 시각은 naive(KST). 창 시작과 비교하려면 tz를 떼어 맞춘다.
    return c < start.replace(tzinfo=None)


# 개장을 안 지났어도 이만큼 묵었으면 쓰지 않는다. 값과 그 근거는
# `core/session.py`가 갖는다 — `dashboard.py`도 같은 값을 봐야 해서
# (화면이 "글이 데이터보다 오래됐다"를 같은 기준으로 말한다) 한곳에 뒀다.
#
# 개장 판정만으로는 두 가지가 샌다 — 코인은 24시간 거래라 지나갈 개장이
# 없고, 주말을 낀 금요일 데이터는 '다음 개장'이 월요일이라 30시간이 지나도
# 개장 전으로 잡힌다(us 08-09 02:05 → 08-10 08:11).
MAX_AGE_H = session.MAX_INSIGHT_AGE_H


def too_late(market, now=None):
    """대비하던 장이 이미 지났으면 True — 그 글은 이제 회고가 된다."""
    return bool(too_late_why(market, now))


def too_late_why(market, now=None):
    """왜 안 쓰는지 한 줄. 쓸 수 있으면 빈 문자열.

    이유를 문자열로 돌려주는 이유는 `-v`가 그것을 그대로 보이기 때문이다.
    불리언만 돌려주던 동안 `-v`는 걸린 이유와 무관하게 늘 "그 장은
    지났음"이라고 찍었고, 장중 스냅샷이 걸렸을 때 "수집 0.1시간 전,
    그 장은 지났음"이라는 앞뒤가 안 맞는 줄이 나왔다.

    루틴이 밀리는 것을 막지 못했다. 실측(git 이력 24건)에서 11건이 수집
    10시간 뒤에 쓰였고, 국장은 거의 매번 저녁에 쓰였다 — 08-12에는 08:07
    데이터로 21:49에 '개장 1시간 전' 글이 나갔고, 08-07 데이터는 사흘 뒤인
    08-10에 쓰였다(71.4시간).

    아침 루틴이 안 돌면 저녁 루틴이 pending 출력을 그대로 받아 국장까지
    쓰기 때문이다.

    **시간 상한만으로는 못 가른다.** macro 08-05는 01:29에 받아 08:19에
    썼는데(6.8시간) 09:00 개장 전이라 정상이다. 기준은 '얼마나 됐나'가
    아니라 '대비하던 장이 아직 안 열렸나'다.
    """
    c = collected_at(market)
    if c is None:
        return ""
    now = now or dt.datetime.now()
    if getattr(now, "tzinfo", None) is not None:
        now = now.replace(tzinfo=None)

    age = (now - c).total_seconds() / 3600
    # 너무 묵은 것은 개장이 안 지났어도 쓰지 않는다.
    if age > MAX_AGE_H:
        return f"너무 묵음 (수집 {age:.1f}시간 전, 상한 {MAX_AGE_H}시간)"

    # 수집 시점 기준으로 그 프롬프트가 바라보던 개장을 되살린다.
    # 코인은 24시간 거래라 next_open이 없고, 위 시간 상한만 적용된다.
    d = session.describe(market, c.astimezone() if c.tzinfo else
                         c.replace(tzinfo=dt.datetime.now().astimezone().tzinfo))

    # **장중에 받은 스냅샷으로는 대비형 글을 쓰지 않는다.** 그 숫자는 결과가
    # 절반 섞인 값이라(거래량이 덜 차고 등락이 확정 전이다) 대비가 아니라
    # 회고가 된다. 신선도만으로는 안 걸린다 — 실측 2026-08-21 02:23에 미장을
    # 장중에 받았더니 '4분 전 데이터'라 시간 상한을 통과했고, 개장 판정도
    # 다음 개장이 22:30이라 안 걸렸다.
    #
    # 저장소의 다른 자리는 이미 장중을 거른다 — `history`는 장중 픽을
    # 기록하지 않고 `dashboard`는 `partial`로 판정을 접는다. 여기만
    # 열려 있었다.
    #
    # **국장·미장에만 건다.** 매크로는 두 시장의 배경이라 한쪽이 열려
    # 있다고 값이 반토막 나지 않고, 코인은 24시간 거래라 '장중'이 늘 참이다.
    if market in ("kr", "us") and d.get("state") == "장중":
        return f"장중 스냅샷 (수집 {c:%H:%M}에 이미 열려 있었음)"

    nxt = d.get("next_open")
    if nxt is not None and now > nxt.replace(tzinfo=None):
        return f"그 장은 지났음 (대비하던 개장 {nxt:%m-%d %H:%M})"
    return ""


def pending(markets=MARKETS, now=None, wait=True):
    """(자산군, 사유) 목록. 다시 쓸 게 없으면 빈 목록."""
    out = []
    for m in markets:
        c, w = collected_at(m), written_at(m)
        if not c:
            continue                       # 수집된 적이 없으면 쓸 재료가 없다
        if w and c <= w:
            continue                       # 이미 최신
        if wait and waiting_for_collection(m, now):
            continue                       # 곧 올 수집을 기다린다
        if too_late(m, now):
            continue                       # 대비하던 장이 이미 지났다
        if not w:
            out.append((m, "인사이트 없음"))
            continue
        gap = (c - w).total_seconds() / 3600
        out.append((m, f"수집 {c:%m-%d %H:%M} > 작성 {w:%m-%d %H:%M} "
                       f"({gap:.1f}시간 새 데이터)"))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-v", "--verbose", action="store_true")
    ap.add_argument("markets", nargs="*", default=None)
    a = ap.parse_args()

    rows = pending(a.markets or MARKETS)
    if a.verbose:
        for m in (a.markets or MARKETS):
            c, w = collected_at(m), written_at(m)
            need = any(x[0] == m for x in rows)
            if need:
                state = "다시 써야 함"
            elif c and (not w or c > w) and too_late_why(m):
                # 새 데이터가 있는데도 안 쓴다. 이유가 안 보이면 버그로
                # 오해하므로 어느 규칙에 걸렸는지 그대로 보인다.
                state = "안 씀 — " + too_late_why(m)
            elif c and (not w or c > w) and waiting_for_collection(m):
                # '최신'과 구분해야 한다. 새 데이터가 있는데도 안 쓰는
                # 것이므로, 이유를 안 보이면 버그로 오해한다.
                state = "대기 (이번 세션 수집 전)"
            else:
                state = "최신"
            print(f"{LABELS[m]:<5} 수집 {c and c.strftime('%m-%d %H:%M') or '-':<12}"
                  f" 작성 {w and w.strftime('%m-%d %H:%M') or '-':<12} {state}")
        print()
    print(" ".join(m for m, _ in rows))
    return 0


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    sys.exit(main())
