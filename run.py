# -*- coding: utf-8 -*-
"""전체 실행 — 수집 4개 + 대시보드 생성 + 폰 전송 준비

    python run.py                # 전부 실행하고 탐색기에서 파일 선택
    python run.py --skip-collect # 수집 건너뛰고 대시보드만 다시 굽기
    python run.py --no-open      # 탐색기 안 열기

만들어진 HTML은 자기완결형이다 (CSS·JS·데이터 전부 인라인, 외부 요청 0건).
카톡·메일로 폰에 보내면 오프라인에서 열린다.
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

COLLECTORS = [
    ("collect_kr.py", "국장"),
    ("collect_us.py", "미장"),
    ("collect_macro.py", "매크로"),
    ("collect_coin.py", "코인"),
]


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
    print(f"\n자산 인사이트 — {now:%Y-%m-%d %H:%M}\n")

    ok = 0
    if "--skip-collect" not in args:
        print("[1/2] 데이터 수집")
        for script, label in COLLECTORS:
            ok += run_one(script, label)
        print()
    else:
        print("[1/2] 수집 건너뜀 (--skip-collect)\n")
        ok = len(COLLECTORS)

    print("[2/2] 대시보드 생성")
    import dashboard
    path, size = dashboard.build()

    # 날짜별 사본도 남긴다 — 어제 것과 비교할 수 있게
    stamped = DATA / f"dashboard_{now:%Y%m%d_%H%M}.html"
    shutil.copy2(path, stamped)

    kb = stamped.stat().st_size / 1024
    print(f"  {stamped.name}  ({kb:,.0f}KB, {size:,}자)")
    print(f"  {path.name}      (항상 최신)")

    print(f"\n총 {time.time() - t0:.0f}초, 수집 {ok}/{len(COLLECTORS)}개 성공")
    print(f"\n  파일: {path}")
    print("  이 파일을 카톡 '나에게 보내기'나 메일로 폰에 보내면 됩니다.")
    print("  외부 요청이 없어서 오프라인에서도 열립니다.\n")

    if "--no-open" not in args and sys.platform == "win32":
        # 탐색기에서 파일을 선택한 상태로 연다 — 바로 드래그해서 전송
        subprocess.run(["explorer", "/select,", str(path)])


if __name__ == "__main__":
    main()
