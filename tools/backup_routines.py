# -*- coding: utf-8 -*-
"""저장소 밖에 있는 것을 저장소 안으로 백업한다

    python tools/backup_routines.py            # 다른지만 확인
    python tools/backup_routines.py --save     # 실물 → 저장소 (백업)
    python tools/backup_routines.py --restore  # 저장소 → 실물 (복원)

작업 지침은 `~/.claude/CLAUDE.md` 에 있다. 모든 프로젝트에 걸리는 것이라
이 앱과 직접 상관은 없지만, 저장소 밖이라 PC가 죽으면 같이 사라진다.

이 앱이 매일 알아서 도는 구조는 저장소 밖 파일 셋에 더 걸려 있다.

    ~/.claude/skills/인사이트/SKILL.md                 /인사이트 진입점(포인터)
    ~/.claude/scheduled-tasks/asset-insight-morning/   아침 루틴
    ~/.claude/scheduled-tasks/asset-insight-evening/   저녁 루틴

git에 없으므로 PC가 죽으면 사라진다. 코드가 다 있어도 **무엇을 다시
만들어야 하는지**가 어디에도 안 적혀 있으면 복구가 안 된다.

사본을 그냥 두면 스킬 때 겪은 것과 같은 문제가 난다 — 한쪽만 고치고
어긋난 채로 몇 주가 간다. 그래서 사본을 두되 **다른지 재는 것**을
같이 둔다. 바라는 대신 잰다.
"""
import argparse
import os
import shutil
import sys
from pathlib import Path

ROOT = Path(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BACKUP = ROOT / ".claude" / "routines"
HOME = Path.home() / ".claude"

# 작업 지침을 한때 Claude 앱의 **설정 → 지침**으로 옮겼다가 되돌렸다.
# 설정에 넣은 것은 계정에 저장되어 Claude Code 세션에는 실리지 않는다
# (2026-08-09 실측: 저장 7분 뒤 새로 연 세션에서도 "한국어로 답한다"를
# 비롯해 한 줄도 안 들어왔다). 파일이 실물이므로 여기서 잰다.

# (저장소 안 파일명, 실물 경로, 설명, 저장소 쪽 경로)
# 마지막 칸이 None 이면 .claude/routines/<파일명> 을 사본으로 쓴다.
FILES = [
    ("CLAUDE-사용자.md",
     HOME / "CLAUDE.md",
     "모든 프로젝트에 적용되는 공통 작업 지침", None),
    ("인사이트-포인터.md",
     HOME / "skills" / "인사이트" / "SKILL.md",
     "/인사이트 진입점. 저장소의 지침을 읽으라는 포인터.", None),
    # 예약 시각은 여기 적지 않는다. 실제 예약은 Claude 앱 안에 있어 이
    # 도구가 잴 수 없는데(재는 것은 지침 파일이다), 못 재는 값을 사본으로
    # 들고 있으면 조용히 어긋난다 — 실제로 저녁 시각이 21:12·22:12·23:12로
    # 굳어 있는 동안 진짜 예약은 21:00부터 30분마다였다.
    # 정본은 notes/routines.md 의 예약표다.
    ("asset-insight-morning.md",
     HOME / "scheduled-tasks" / "asset-insight-morning" / "SKILL.md",
     "아침 루틴 (시각은 notes/routines.md)", None),
    ("asset-insight-evening.md",
     HOME / "scheduled-tasks" / "asset-insight-evening" / "SKILL.md",
     "저녁 루틴 (시각은 notes/routines.md)", None),
    # 저장소의 .claude/settings.json 과 같은 내용인데 여기에도 둔다.
    # 예약 루틴은 저장소 밖에서 시작해 나중에 cd 로 들어온다. Claude 는
    # 프로젝트 설정을 '시작한 폴더' 기준으로 읽으므로 저장소 안에만 두면
    # 루틴 세션에는 안 실린다 — 팝업에서 '항상 허용'을 눌러도 다음 실행이
    # 또 다른 폴더에서 시작하니 남지 않는다. 매일 누르는데 매일 다시
    # 묻던 것이 이 때문이다.
    # 사본을 .claude/routines/ 에 따로 두면 사본이 셋이 된다. 그때는 계정
    # 파일이 '백업본'과만 비교되어 저장소의 .claude/settings.json 과 어긋난
    # 것을 아무도 못 잰다 — 실측 2026-08-14, 저장소 40개 / 계정 22개로
    # 갈려 있었고 계정에 없던 21개가 Glob·ls·cat 같은 읽기 명령이라 루틴이
    # 매번 승인을 물었다. 그래서 저장소 정본과 **직접** 비교한다.
    ("settings-사용자.json",
     HOME / "settings.json",
     "계정 전체 허용 목록. 저장소의 .claude/settings.json 과 같아야 한다.",
     ROOT / ".claude" / "settings.json"),
]


def _same(p1, p2):
    """줄바꿈 차이는 다른 것으로 세지 않는다.

    git이 체크아웃하면서 저장소 쪽 파일을 CRLF로 바꾸는데(autocrlf) 실물은
    LF 그대로라, 바이트로 비교하면 내용이 같아도 매번 '다름'이 뜬다.
    실측 2026-08-14: settings.json 이 3456 vs 3377바이트로 갈렸고 차이는
    \\r 79개가 전부였다. 늘 켜지는 경보는 안 켜지는 경보만큼 쓸모없다.
    """
    a = p1.read_bytes().replace(b"\r\n", b"\n")
    b = p2.read_bytes().replace(b"\r\n", b"\n")
    return a == b


def _state(repo, live):
    if not live.exists() and not repo.exists():
        return "둘 다 없음"
    if not live.exists():
        return "실물 없음 (복원 필요)"
    if not repo.exists():
        return "백업 없음 (저장 필요)"
    return "같음" if _same(repo, live) else "다름"


def main():
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--save", action="store_true", help="실물 → 저장소")
    g.add_argument("--restore", action="store_true", help="저장소 → 실물")
    a = ap.parse_args()

    BACKUP.mkdir(parents=True, exist_ok=True)
    bad = 0
    for name, live, note, repo in FILES:
        repo = repo or (BACKUP / name)
        st = _state(repo, live)

        if a.save and live.exists():
            shutil.copy2(live, repo)
            st = "저장함"
        elif a.restore and repo.exists():
            live.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(repo, live)
            st = "복원함"

        mark = "✓" if st in ("같음", "저장함", "복원함") else "✗"
        if mark == "✗":
            bad += 1
        print(f"  {mark} {name:26s} {st:18s} {note}")

    if a.restore:
        print("\n복원했습니다. **예약은 파일만으로 살아나지 않습니다** —")
        print("Claude 앱에서 두 루틴이 등록·활성 상태인지 확인하십시오.")
    elif not a.save and bad:
        print(f"\n{bad}건이 어긋났습니다. 실물이 정본이면 --save,")
        print("저장소가 정본이면 --restore 로 맞추십시오.")
    elif not a.save:
        print("\n전부 같습니다.")
    return 1 if (bad and not (a.save or a.restore)) else 0


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    sys.exit(main())
