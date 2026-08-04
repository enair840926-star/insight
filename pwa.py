# -*- coding: utf-8 -*-
"""PWA 자산 생성 — 매니페스트 / 서비스워커 / 아이콘

아이콘 PNG를 표준 라이브러리만으로 만든다. Pillow를 설치하면 편하지만
이 프로젝트는 의존성 0을 유지한다 (Node.js도 FastAPI도 안 쓴 것과 같은 이유).
PNG는 압축된 스캔라인 + CRC 청크 몇 개라 직접 쓰는 게 어렵지 않다.
"""
import struct
import zlib
from pathlib import Path

# 대시보드와 같은 팔레트
GROUND = (0x0b, 0x0f, 0x14)
TEAL = (0x22, 0xd3, 0xee)
TEAL_DIM = (0x0e, 0x88, 0x9c)
MUTED = (0x33, 0x42, 0x4e)


def _chunk(typ, data):
    return (struct.pack(">I", len(data)) + typ + data
            + struct.pack(">I", zlib.crc32(typ + data) & 0xFFFFFFFF))


def write_png(path, size, pixels):
    """pixels: size*size 길이의 (r,g,b) 리스트"""
    rows = []
    for y in range(size):
        row = bytearray()
        row.append(0)                       # 필터 타입 0 (None)
        for x in range(size):
            row.extend(pixels[y * size + x])
        rows.append(bytes(row))
    raw = b"".join(rows)
    png = (b"\x89PNG\r\n\x1a\n"
           + _chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0))
           + _chunk(b"IDAT", zlib.compress(raw, 9))
           + _chunk(b"IEND", b""))
    Path(path).write_bytes(png)
    return len(png)


def make_icon(size):
    """오름차순 막대 4개. 안드로이드 maskable 대응으로 중앙 80% 안에 넣는다
    (바깥 20%는 런처가 둥글게 잘라낸다)."""
    px = [GROUND] * (size * size)

    def rect(x0, y0, x1, y1, color):
        x0, y0 = max(0, int(x0)), max(0, int(y0))
        x1, y1 = min(size, int(x1)), min(size, int(y1))
        for y in range(y0, y1):
            base = y * size
            for x in range(x0, x1):
                px[base + x] = color

    s = size / 512.0                        # 512 기준으로 그리고 비례 축소
    bar_w, gap = 70 * s, 30 * s
    total = bar_w * 4 + gap * 3
    x = (size - total) / 2
    bottom = size - 96 * s
    heights = [120, 190, 265, 340]
    colors = [MUTED, MUTED, TEAL_DIM, TEAL]

    for h, c in zip(heights, colors):
        top = bottom - h * s
        rect(x, top, x + bar_w, bottom, c)
        x += bar_w + gap

    # 바닥 기준선 — 막대가 떠 보이지 않게
    rect((size - total) / 2, bottom, (size + total) / 2, bottom + 8 * s, MUTED)
    return px


MANIFEST = """{
  "name": "자산 인사이트",
  "short_name": "인사이트",
  "description": "국장·미장·매크로·코인 수급 대시보드",
  "start_url": "./",
  "scope": "./",
  "display": "standalone",
  "orientation": "portrait",
  "background_color": "#0b0f14",
  "theme_color": "#0b0f14",
  "lang": "ko",
  "icons": [
    {"src": "icon-192.png", "sizes": "192x192", "type": "image/png", "purpose": "any"},
    {"src": "icon-512.png", "sizes": "512x512", "type": "image/png", "purpose": "any"},
    {"src": "icon-512.png", "sizes": "512x512", "type": "image/png", "purpose": "maskable"}
  ]
}"""

# 네트워크 우선 — 온라인이면 항상 최신을 받고, 끊기면 마지막 캐시를 쓴다.
# 캐시 우선으로 하면 PC에서 push한 새 데이터가 폰에 안 내려온다.
SERVICE_WORKER = """const CACHE = 'insight-v2';
const SHELL = ['./', './index.html', './manifest.json',
               './icon-192.png', './icon-512.png'];

self.addEventListener('install', e => {
  e.waitUntil(caches.open(CACHE).then(c => c.addAll(SHELL)).catch(() => {}));
  self.skipWaiting();
});

self.addEventListener('activate', e => {
  e.waitUntil(caches.keys().then(keys =>
    Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k)))
  ).then(() => self.clients.claim()));
});

self.addEventListener('fetch', e => {
  if (e.request.method !== 'GET') return;

  // GitHub Pages는 HTML에 Cache-Control: max-age=600 을 붙인다.
  // 그냥 fetch하면 브라우저 HTTP 캐시가 먼저 응답해서, 갱신을 해도
  // 폰에서 최대 10분간 어제 데이터가 보인다. 페이지 요청만 캐시를
  // 무시하고 서버에서 직접 받는다 (아이콘·매니페스트는 그대로 캐시).
  const isPage = e.request.mode === 'navigate' ||
                 e.request.url.endsWith('/') ||
                 e.request.url.endsWith('index.html');
  const req = isPage ? new Request(e.request.url, {cache: 'reload'}) : e.request;

  e.respondWith(
    fetch(req).then(res => {
      const copy = res.clone();
      caches.open(CACHE).then(c => c.put(e.request, copy)).catch(() => {});
      return res;
    }).catch(() => caches.match(e.request).then(r => r || caches.match('./index.html')))
  );
});
"""


def write_assets(docs_dir):
    """docs/ 에 PWA 부속 파일을 쓴다. index.html은 dashboard가 만든다."""
    docs = Path(docs_dir)
    docs.mkdir(parents=True, exist_ok=True)
    made = []

    (docs / "manifest.json").write_text(MANIFEST, encoding="utf-8")
    made.append(("manifest.json", len(MANIFEST)))

    (docs / "sw.js").write_text(SERVICE_WORKER, encoding="utf-8")
    made.append(("sw.js", len(SERVICE_WORKER)))

    for s in (192, 512):
        n = write_png(docs / f"icon-{s}.png", s, make_icon(s))
        made.append((f"icon-{s}.png", n))

    # GitHub Pages는 기본으로 Jekyll을 돌린다. 밑줄로 시작하는 파일을
    # 무시하는 등 예상 못 한 처리가 붙으므로 꺼둔다.
    (docs / ".nojekyll").write_text("", encoding="utf-8")
    made.append((".nojekyll", 0))
    return made


HEAD_EXTRA = """<link rel="manifest" href="manifest.json">
<meta name="theme-color" content="#0b0f14">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-title" content="인사이트">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<link rel="apple-touch-icon" href="icon-192.png">
<link rel="icon" href="icon-192.png">"""

REGISTER_SW = """
if ('serviceWorker' in navigator) {
  window.addEventListener('load', () => {
    navigator.serviceWorker.register('sw.js').catch(() => {});
  });
}
"""


if __name__ == "__main__":
    import sys
    out = sys.argv[1] if len(sys.argv) > 1 else "docs"
    for name, size in write_assets(out):
        print(f"  {name:16s} {size:>8,} bytes")
