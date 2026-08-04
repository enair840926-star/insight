# -*- coding: utf-8 -*-
"""HTTP 유틸 — 재시도, 소스별 헤더, 실패 격리

비공식 API에 의존하므로(네이버·나스닥·CNN) 한 소스가 죽어도
앱 전체가 죽으면 안 된다. 모든 호출은 예외 대신 None을 반환한다.
"""
import time
import requests

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")

# 소스별로 요구하는 헤더가 다르다. 실측으로 확인된 값들.
REFERERS = {
    "stock.naver.com":   "https://m.stock.naver.com/",
    "finance.naver.com": "https://finance.naver.com/",
    "nasdaq.com":        "https://www.nasdaq.com/",
    "cnn.io":            "https://edition.cnn.com/",
}

_session = requests.Session()
_session.headers.update({
    "User-Agent": UA,
    "Accept": "*/*",
    "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8",
})


def _referer_for(url: str):
    for host, ref in REFERERS.items():
        if host in url:
            return ref
    return None


def fetch(url, timeout=20, retry=3, encoding=None, headers=None):
    """실패해도 예외를 던지지 않는다. 본문(str) 또는 None."""
    h = {}
    ref = _referer_for(url)
    if ref:
        h["Referer"] = ref
    if headers:
        h.update(headers)

    last = None
    for attempt in range(retry):
        try:
            r = _session.get(url, timeout=timeout, headers=h)
            if r.status_code == 200:
                if encoding:
                    r.encoding = encoding
                elif r.encoding is None:
                    r.encoding = "utf-8"
                return r.text
            # 403/404는 재시도해도 안 된다. 즉시 포기.
            if r.status_code in (401, 403, 404, 410):
                return None
            last = f"HTTP {r.status_code}"
        except requests.RequestException as e:
            last = type(e).__name__
        time.sleep(0.5 * (attempt + 1))
    return None


def fetch_json(url, **kw):
    import json
    txt = fetch(url, **kw)
    if not txt:
        return None
    try:
        return json.loads(txt)
    except (ValueError, TypeError):
        return None


def fetch_bytes(url, timeout=20, retry=3, headers=None):
    """RSS 인코딩을 직접 다뤄야 할 때(머니투데이 EUC-KR)."""
    h = {}
    ref = _referer_for(url)
    if ref:
        h["Referer"] = ref
    if headers:
        h.update(headers)
    for attempt in range(retry):
        try:
            r = _session.get(url, timeout=timeout, headers=h)
            if r.status_code == 200:
                return r.content
            if r.status_code in (401, 403, 404, 410):
                return None
        except requests.RequestException:
            pass
        time.sleep(0.5 * (attempt + 1))
    return None
