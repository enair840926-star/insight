# -*- coding: utf-8 -*-
"""수집 결과 찾기 — 로컬(data/)과 클라우드(cloud/)를 함께 본다

GitHub Actions가 장 시간에 맞춰 수집한 결과를 cloud/에 커밋한다.
PC에서 `git pull` 하면 그게 내려오고, 인사이트는 그 데이터로 만든다.
PC를 안 켜도 폰에는 최신 숫자가 뜨고, 인사이트를 만들고 싶을 때만
PC를 켜면 된다 — 그때 다시 수집할 필요가 없다.

**mtime으로 정렬하면 안 된다.** git이 파일을 내려받으면 mtime이
받은 시각으로 찍히므로, 아침에 수집된 클라우드 파일이 저녁에 pull하면
방금 만든 것처럼 보인다. 파일명에 박힌 수집 시각으로 정렬한다.
"""
import glob
import os
import re
from pathlib import Path

ROOT = Path(__file__).parent.parent
DATA = ROOT / "data"
CLOUD = ROOT / "cloud"

# prompt_kr_20260805_0800.txt / kr_20260805_0800.json
_STAMP = re.compile(r"_(\d{8}_\d{4})\.[^.]+$")


def _stamp(path):
    m = _STAMP.search(os.path.basename(path))
    return m.group(1) if m else ""


def latest(pattern):
    """data/와 cloud/에서 패턴에 맞는 가장 최근 파일. 없으면 None.

    pattern 예: "kr_2*.json", "prompt_macro_2*.txt"
    """
    files = []
    for d in (DATA, CLOUD):
        if d.is_dir():
            files += glob.glob(str(d / pattern))
    if not files:
        return None
    # 수집 시각(파일명) 우선, 같으면 mtime으로 가른다
    files.sort(key=lambda p: (_stamp(p), os.path.getmtime(p)))
    return Path(files[-1])


def publish(markets, dest=CLOUD, keep=2):
    """각 자산군의 최신 결과를 cloud/로 복사한다. 워크플로에서 쓴다.

    keep: 자산군당 남길 세대 수. 히스토리는 git이 갖고 있으므로
    많이 쌓아 둘 이유가 없다.
    """
    import shutil
    dest = Path(dest)
    dest.mkdir(exist_ok=True)
    copied = []
    for m in markets:
        for pattern in (f"{m}_2*.json", f"prompt_{m}_2*.txt"):
            src = latest(pattern)
            if not src or src.parent == dest:
                continue
            shutil.copy2(src, dest / src.name)
            copied.append(src.name)
        # 오래된 세대 정리
        for pattern in (f"{m}_2*.json", f"prompt_{m}_2*.txt"):
            olds = sorted(glob.glob(str(dest / pattern)), key=_stamp)
            for p in olds[:-keep]:
                os.remove(p)
    return copied
