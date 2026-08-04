# -*- coding: utf-8 -*-
"""전체 실행 — 수집 + 인사이트 + 대시보드 + 배포

    python run.py                # 4개 자산군 전부
    python run.py kr             # 국장만 (개장 1시간 전에 돌리는 용도)
    python run.py us macro coin  # 미장 저녁 묶음
    python run.py --auto         # 곧 열릴 장을 알아서 골라 갱신
    python run.py --skip-collect # 수집 건너뛰고 대시보드만 다시 굽기
    python run.py --no-deploy    # 푸시 안 함

자산군을 지정해도 대시보드는 항상 4개 전부 다시 굽는다. 갱신 안 한
자산군은 직전 데이터가 그대로 쓰이고, 패널마다 수집 시각이 찍히므로
어느 게 오래됐는지 폰에서 바로 보인다.

만들어진 HTML은 자기완결형이다 (CSS·JS·데이터 전부 인라인, 외부 요청 0건).
"""
import io
import subprocess
import sys
import time
import datetime as dt
import shutil
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

ROOT = Path(__file__).parent
DATA = ROOT / "data"

COLLECTORS = {
    "kr":    ("collect_kr.py", "국장"),
    "us":    ("collect_us.py", "미장"),
    "macro": ("collect_macro.py", "매크로"),
    "coin":  ("collect_coin.py", "코인"),
}
ORDER = ["kr", "us", "macro", "coin"]

# 자주 쓰는 조합에 이름을 붙여 둔다. 예약 실행에서 인자를 짧게 쓰려고.
GROUPS = {
    "아침": ["kr", "macro"],            # 국장 08:00 (개장 1시간 전)
    "저녁": ["us", "macro", "coin"],    # 미장 21:30 (서머타임 기준 1시간 전)
    "morning": ["kr", "macro"],
    "evening": ["us", "macro", "coin"],
}

# --auto가 "개장 임박"으로 보는 창. 미국 서머타임이 바뀌면 개장이 한 시간
# 밀리므로 넉넉히 잡는다. 예약을 21:30에 걸어 두면 여름·겨울 모두 걸린다.
AUTO_WINDOW_H = 2.5


def auto_markets(now=None):
    """개장이 임박한 시장을 고른다. 예약 실행용.

    아무 장도 임박하지 않았으면 빈 리스트를 돌려준다 — 잘못 걸린 예약이
    전체 수집을 돌려 버리는 것보다 아무것도 안 하는 게 낫다.
    """
    from core import session
    picked = []
    for m in ("kr", "us"):
        d = session.describe(m, now)
        if d["state"] != "장중" and d["hours_until"] <= AUTO_WINDOW_H:
            picked.append(m)
    if picked:
        picked.append("macro")          # 매크로는 두 장 모두의 배경
        if "us" in picked:
            picked.append("coin")       # 코인은 미국 세션과 같이 움직인다
    return [m for m in ORDER if m in picked]


def resolve(args):
    """인자 → 자산군 목록. 반환: (markets, 설명)"""
    if "--auto" in args:
        m = auto_markets()
        if not m:
            return [], "개장 임박한 장 없음"
        return m, "자동 선택"
    named, given = [], 0
    for a in args:
        if a.startswith("--"):
            continue
        given += 1
        if a in GROUPS:
            named += GROUPS[a]
        elif a in COLLECTORS:
            named.append(a)
        else:
            print(f"  ! 모르는 자산군 '{a}' "
                  f"({', '.join(ORDER)} 또는 아침/저녁)")
    if given and not named:
        # 예약 실행에서 인자를 오타내면 전체가 돌아간다. 그건 비싸다.
        return [], "인자 오류"
    if not named:
        return list(ORDER), "전체"
    return [m for m in ORDER if m in named], "지정"


def run_one(script, label):
    """수집기 하나 실행. 실패해도 나머지는 계속한다."""
    t0 = time.time()
    print(f"  {label:6s} … ", end="", flush=True)
    try:
        r = subprocess.run(
            [sys.executable, str(ROOT / script)],
            capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=300, cwd=str(ROOT))
    except subprocess.TimeoutExpired:
        print("시간 초과 (5분)")
        return False
    dt_s = time.time() - t0
    if r.returncode != 0:
        print(f"실패 ({dt_s:.0f}초)")
        tail = (r.stderr or r.stdout or "").strip().splitlines()[-3:]
        for line in tail:
            print(f"          {line[:100]}")
        return False

    # 수집기가 찍는 요약 줄만 뽑아 보여준다
    info = []
    for line in (r.stdout or "").splitlines():
        s = line.strip()
        if s.startswith("LLM재료"):
            info.append(s.split("(")[-1].rstrip(")"))
        elif "커버리지" in s:
            info.append(s.split(":", 1)[-1].strip().split("←")[0].strip())
    print(f"완료 {dt_s:5.1f}초   {' · '.join(info)}")
    return True


def main():
    args = sys.argv[1:]
    t0 = time.time()
    now = dt.datetime.now()
    markets, why = resolve(args)

    labels = " · ".join(COLLECTORS[m][1] for m in markets) or "-"
    print(f"\n자산 인사이트 — {now:%Y-%m-%d %H:%M}")
    print(f"대상: {labels}  ({why})\n")

    if not markets:
        if why == "인자 오류":
            print(f"  쓸 수 있는 값: {' '.join(ORDER)} / 아침 / 저녁 / --auto\n")
        else:
            print("  다음 개장까지 여유가 있어 아무것도 하지 않았습니다.")
            print(f"  강제로 돌리려면: python run.py {' '.join(ORDER)}\n")
        return

    ok = 0
    if "--skip-collect" not in args:
        print("[1/4] 데이터 수집")
        for m in markets:
            script, label = COLLECTORS[m]
            ok += run_one(script, label)
        print()
    else:
        print("[1/4] 수집 건너뜀 (--skip-collect)\n")
        ok = len(markets)

    if "--no-insight" not in args:
        print("[2/4] 인사이트 생성")
        try:
            import insight
            from core import env
            if env.get("ANTHROPIC_API_KEY"):
                insight.run(markets=markets)
            else:
                print("  건너뜀 (.env에 ANTHROPIC_API_KEY 없음 — 과금 없음)")
        except Exception as e:
            print(f"  실패 — {type(e).__name__}: {str(e)[:70]}")
            print("  (데이터 수집은 끝났으니 대시보드는 그대로 만들어집니다)")
        print()
    else:
        print("[2/4] 인사이트 건너뜀 (--no-insight)\n")

    print("[3/4] 대시보드 생성")
    import dashboard
    path, size = dashboard.build()

    # 날짜별 사본도 남긴다 — 어제 것과 비교할 수 있게
    stamped = DATA / f"dashboard_{now:%Y%m%d_%H%M}.html"
    shutil.copy2(path, stamped)
    print(f"  {stamped.name}  ({stamped.stat().st_size/1024:,.0f}KB)")

    index, isize, _assets = dashboard.build_pwa()
    print(f"  docs/index.html  ({isize:,}자)  ← 폰 앱용\n")

    print("[4/4] 배포")
    if "--no-deploy" in args:
        print("  건너뜀 (--no-deploy)")
    else:
        deploy(now, "+".join(COLLECTORS[m][1] for m in markets) or "데이터")

    print(f"\n총 {time.time() - t0:.0f}초, 수집 {ok}/{len(markets)}개 성공")
    print(f"\n  로컬 파일: {path}")
    print(f"  폰 앱    : {SITE_URL}\n")

    if "--open" in args and sys.platform == "win32":
        subprocess.run(["explorer", "/select,", str(path)])


SITE_URL = "https://enair840926-star.github.io/insight/"


def deploy(now, tag="데이터"):
    """docs/ 변경분을 커밋하고 푸시한다. 실패해도 로컬 결과물은 남는다."""
    def git(*a, **kw):
        return subprocess.run(["git", *a], capture_output=True, text=True,
                              encoding="utf-8", errors="replace",
                              cwd=str(ROOT), **kw)

    st = git("status", "--porcelain", "docs")
    if not (st.stdout or "").strip():
        print("  변경 없음 — 푸시 생략")
        return

    git("add", "docs")
    c = git("commit", "-m", f"{tag} 갱신 {now:%Y-%m-%d %H:%M}")
    if c.returncode != 0:
        print(f"  커밋 실패: {(c.stderr or c.stdout).strip()[:90]}")
        return

    p = git("push", "origin", "main")
    if p.returncode == 0:
        print("  푸시 완료 — 1~2분 뒤 폰에 반영됩니다")
    else:
        err = (p.stderr or p.stdout).strip().splitlines()
        print("  푸시 실패:")
        for line in err[:3]:
            print(f"    {line[:96]}")
        print("  (커밋은 됐습니다. 인증 후 'git push'로 다시 시도하세요)")


if __name__ == "__main__":
    main()
