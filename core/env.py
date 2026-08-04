# -*- coding: utf-8 -*-
"""API 키 로딩

키는 .env 파일이나 환경변수에서만 읽는다. 코드에 절대 넣지 않는다.
.env는 .gitignore에 있으므로 커밋되지 않는다.
"""
import os
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_ENV_FILE = _ROOT / ".env"
_loaded = False


def _load():
    global _loaded
    if _loaded:
        return
    _loaded = True
    if not _ENV_FILE.exists():
        return
    for line in _ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k, v = k.strip(), v.strip().strip('"').strip("'")
        # 환경변수가 이미 있으면 그쪽을 우선한다
        if k and v and k not in os.environ:
            os.environ[k] = v


def get(name, required=False):
    _load()
    v = os.environ.get(name)
    if required and not v:
        raise RuntimeError(
            f"{name}이(가) 설정되지 않았습니다.\n"
            f"  {_ENV_FILE} 파일에 다음 줄을 추가하세요:\n"
            f"  {name}=발급받은_키"
        )
    return v


def has(name):
    return bool(get(name))
