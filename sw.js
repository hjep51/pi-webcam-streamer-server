// Service worker for PWA — caches the app shell for offline support
const CACHE_NAME = 'pi-webcam-v1';
const SHELL_URLS = ['/'];

self.addEventListener('install', function(event) {
    self.skipWaiting();
});

self.addEventListener('activate', function(event) {
    event.waitUntil(clients.claim());
});

self.addEventListener('fetch', function(event) {
    event.respondWith(
        fetch(event.request)
            .then(function(response) {
                // Cache successful GET responses for offline fallback
                if (event.request.method === 'GET' && response.ok) {
                    var clone = response.clone();
                    caches.open(CACHE_NAME).then(function(cache) {
                        cache.put(event.request, clone);
                    });
                }
                return response;
            })
            .catch(function() {
                return caches.match(event.request);
            })
    );
});
