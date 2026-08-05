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

from core import store

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


def pending(markets=MARKETS):
    """(자산군, 사유) 목록. 다시 쓸 게 없으면 빈 목록."""
    out = []
    for m in markets:
        c, w = collected_at(m), written_at(m)
        if not c:
            continue                       # 수집된 적이 없으면 쓸 재료가 없다
        if not w:
            out.append((m, "인사이트 없음"))
            continue
        if c > w:
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
            print(f"{LABELS[m]:<5} 수집 {c and c.strftime('%m-%d %H:%M') or '-':<12}"
                  f" 작성 {w and w.strftime('%m-%d %H:%M') or '-':<12}"
                  f" {'다시 써야 함' if need else '최신'}")
        print()
    print(" ".join(m for m, _ in rows))
    return 0


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    sys.exit(main())
