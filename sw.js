// Minimal service worker for PWA installability
self.addEventListener('fetch', function(event) {
    event.respondWith(fetch(event.request));
});
