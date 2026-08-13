# -*- coding: utf-8 -*-
"""루틴이 겹쳐 도는 것을 막는 파일 락.

    python tools/lock.py acquire   # 락을 잡는다. 이미 잡혀 있으면 종료코드 1
    python tools/lock.py release   # 락을 놓는다

아침·저녁 루틴이 30분마다 같은 저장소를 건드리는데, Claude 앱이 이전
실행이 끝나기 전에 다음 실행을 또 띄우면 두 프로세스가 같은 워킹
디렉터리를 동시에 건드린다 — git stash·checkout이 서로의 중간 상태를
밟는다(실측 2026-08-13 22:4x, core/regime.py가 부분 병합 상태로 남을
뻔했고 docs/ 빌드 산출물이 두 번 겹쳐 만들어졌다).

STALE_MIN을 넘긴 락은 죽은 것으로 보고 그냥 가져간다 — 프로세스가
죽어 release가 안 불린 경우까지 영영 막히면 안 된다. 정상 실행은
길어야 몇 분이므로 10분이면 넉넉하다.
"""
import datetime as dt
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOCK = os.path.join(ROOT, ".routine.lock")
STALE_MIN = 10


def acquire():
    if os.path.exists(LOCK):
        age_min = (dt.datetime.now().timestamp() - os.path.getmtime(LOCK)) / 60
        if age_min < STALE_MIN:
            print(f"다른 루틴이 이미 진행 중이다 ({age_min:.1f}분 전 시작) — 건너뛴다.")
            return 1
        print(f"락이 {age_min:.1f}분째 안 풀려 죽은 것으로 보고 가져간다.")
    with open(LOCK, "w", encoding="utf-8") as f:
        f.write(dt.datetime.now().isoformat())
    return 0


def release():
    try:
        os.remove(LOCK)
    except FileNotFoundError:
        pass
    return 0


def main():
    if len(sys.argv) != 2 or sys.argv[1] not in ("acquire", "release"):
        print("usage: python tools/lock.py acquire|release", file=sys.stderr)
        return 2
    return acquire() if sys.argv[1] == "acquire" else release()


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    sys.exit(main())
