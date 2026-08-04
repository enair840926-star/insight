const CACHE = 'insight-v2';
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
