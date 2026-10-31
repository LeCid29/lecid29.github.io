// 2 Odds — service worker : démarrage rapide et affichage hors connexion
const SHELL = "2odds-shell-d28b478b0d", DATA = "2odds-data", FONTS = "2odds-fonts";
const FILES = ["./", "index.html", "manifest.webmanifest", "icons/icon-96.png", "icons/icon-192.png", "icons/icon-512.png", "icons/icon-512-maskable.png"];
self.addEventListener("install", (e) => {
  const dataUrl = new URL("data/app.json", self.registration.scope).href;
  e.waitUntil(Promise.all([
    caches.open(SHELL).then((c) => c.addAll(FILES)),
    caches.open(DATA).then((c) => fetch(dataUrl, { cache: "no-store" }).then((r) => r.ok ? c.put(new Request(dataUrl), r) : null).catch(() => null)),
  ]).then(() => self.skipWaiting()));
});
self.addEventListener("activate", (e) => {
  e.waitUntil(caches.keys().then((ks) => Promise.all(ks.filter((k) => k.startsWith("2odds-shell-") && k !== SHELL).map((k) => caches.delete(k)))).then(() => self.clients.claim()));
});
self.addEventListener("fetch", (e) => {
  const req = e.request;
  if (req.method !== "GET") return;
  const url = new URL(req.url);
  // données : toujours la version la plus récente, la dernière reçue si pas de réseau
  if (url.origin === location.origin && url.pathname.endsWith("/data/app.json")) {
    const key = new Request(url.origin + url.pathname);
    e.respondWith(fetch(req).then((r) => {
      if (r.ok) { const cp = r.clone(); caches.open(DATA).then((c) => c.put(key, cp)); }
      return r;
    }).catch(() => caches.match(key).then((r) => {
      if (!r) return Response.error();
      const h = new Headers(r.headers); h.set("x-2odds-offline", "1");
      return r.blob().then((b) => new Response(b, { status: 200, headers: h }));
    })));
    return;
  }
  // page : réseau d'abord (mises à jour immédiates), sinon la copie enregistrée
  if (req.mode === "navigate") {
    e.respondWith(fetch(req).then((r) => {
      if (r.ok) { const cp = r.clone(); caches.open(SHELL).then((c) => c.put("index.html", cp)); }
      return r;
    }).catch(() => caches.match("index.html", { ignoreSearch: true }).then((r) => r || caches.match("./"))));
    return;
  }
  // polices Google : copie enregistrée, rafraîchie en arrière-plan
  if (url.hostname === "fonts.googleapis.com" || url.hostname === "fonts.gstatic.com") {
    e.respondWith(caches.open(FONTS).then((c) => c.match(req).then((hit) => {
      const net = fetch(req).then((r) => { if (r.ok || r.type === "opaque") c.put(req, r.clone()); return r; }).catch(() => hit);
      return hit || net;
    })));
    return;
  }
  // fichiers fixes (icônes, manifeste) : copie enregistrée d'abord
  if (url.origin === location.origin) {
    e.respondWith(caches.match(req, { ignoreSearch: true }).then((hit) => hit || fetch(req)));
  }
});
