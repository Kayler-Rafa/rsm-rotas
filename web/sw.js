/* Service worker do RSM.
   - Casca do app (HTML, CSS, JS, ícones, Leaflet): rede primeiro, cache como
     reserva. Assim uma versão nova chega na hora e o app ainda abre sem rede.
   - /api/*: sempre rede. Rota com clima e trânsito velhos é rota errada; sem
     rede, devolve um erro em JSON que o app já sabe mostrar.
   - Tiles do mapa: não passam por aqui (são milhares; o navegador cuida). */
const VERSAO = "rsm-v1";
const CASCA = [
  "/",
  "/app.css",
  "/app.js",
  "/manifest.webmanifest",
  "/icones/icone-192.png",
  "/icones/icone-512.png",
  "https://unpkg.com/leaflet@1.9.4/dist/leaflet.css",
  "https://unpkg.com/leaflet@1.9.4/dist/leaflet.js",
];

self.addEventListener("install", (ev) => {
  ev.waitUntil(
    caches.open(VERSAO)
      .then((c) => Promise.allSettled(CASCA.map((u) => c.add(u))))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", (ev) => {
  ev.waitUntil(
    caches.keys()
      .then((ks) => Promise.all(ks.filter((k) => k !== VERSAO).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

function semRede() {
  return new Response(
    JSON.stringify({ erro: "Sem conexão. As rotas precisam de internet para usar clima e trânsito atuais." }),
    { status: 503, headers: { "Content-Type": "application/json; charset=utf-8" } }
  );
}

self.addEventListener("fetch", (ev) => {
  const req = ev.request;
  if (req.method !== "GET") return;
  const url = new URL(req.url);

  if (url.origin === self.location.origin && url.pathname.startsWith("/api/")) {
    ev.respondWith(fetch(req).catch(semRede));
    return;
  }

  const ehCasca = url.origin === self.location.origin || url.hostname === "unpkg.com";
  if (!ehCasca) return;

  ev.respondWith(
    fetch(req)
      .then((resp) => {
        if (resp.ok) {
          const copia = resp.clone();
          caches.open(VERSAO).then((c) => c.put(req, copia));
        }
        return resp;
      })
      .catch(() =>
        caches.match(req).then((r) => r || (req.mode === "navigate" ? caches.match("/") : undefined))
          .then((r) => r || Response.error())
      )
  );
});
