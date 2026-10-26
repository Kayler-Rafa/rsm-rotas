/* RSM - app do usuario. Design do artifact 6GbHjBDz9TsGkrBF8vaR98, ligado a
   API real (/api/rede e /api/opcoes). A analise do modelo fica em /admin. */
(function () {
"use strict";

/* =========================================================
   1. Modais, glifos e formatacao
   ========================================================= */
const MODAIS = {
  pe:        { rotulo:"a pé",                             cor:"#64748b", glifo:"ape"  },
  bike:      { rotulo:"bicicleta",                        cor:"#16a34a", glifo:"bike" },
  ebike:     { rotulo:"bicicleta elétrica compartilhada", cor:"#0891b2", glifo:"bike" },
  patinete:  { rotulo:"patinete compartilhado",           cor:"#7c3aed", glifo:"pat"  },
  metro:     { rotulo:"metrô",                            cor:"#dc2626", glifo:"trem" },
  onibus:    { rotulo:"ônibus",                           cor:"#d97706", glifo:"bus"  },
  carro:     { rotulo:"carro elétrico próprio",           cor:"#0f766e", glifo:"carro"},
  carro_app: { rotulo:"carro elétrico de aplicativo",     cor:"#065f46", glifo:"carro"}
};
const corDe = m => (MODAIS[m] || {}).cor || "#64748b";

const G = m => `<svg viewBox="0 0 32 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">${m}</svg>`;
const GLIFOS = {
  carro: G(`<path d="M3.5 16.5v-3.2l2.7-4.7A2.2 2.2 0 0 1 8.1 7.5h11.3c.8 0 1.5.4 1.9 1.1l2.6 4.4 2.5.8c.9.3 1.5 1.1 1.5 2v.7"/>
            <path d="M3.5 16.5h2M26.5 16.5h1.9M6.8 12.6h17.4"/>
            <circle cx="9.3" cy="17" r="2.5"/><circle cx="22.7" cy="17" r="2.5"/><path d="M11.8 17h8.4"/>`),
  bike:  G(`<circle cx="7" cy="16" r="5"/><circle cx="25" cy="16" r="5"/>
            <path d="M7 16l5.5-8h5.5M12.5 8H10M17.5 8l-5 8h12.5M20 8h3.5l1.5 8"/>`),
  trem:  G(`<rect x="8.5" y="2.5" width="15" height="15" rx="4.5"/>
            <path d="M11.5 7.5h9M11.5 13.5h2.2M18.3 13.5h2.2"/>
            <path d="M12 17.5l-2.5 4M20 17.5l2.5 4"/>`),
  bus:   G(`<rect x="4.5" y="2.5" width="23" height="14.5" rx="3.5"/>
            <path d="M4.5 10h23M12 2.5v7.5M20 2.5v7.5"/>
            <circle cx="8.8" cy="13.8" r="1.2"/><circle cx="23.2" cy="13.8" r="1.2"/>
            <path d="M8 17v3.5M24 17v3.5"/>`),
  ape:   G(`<circle cx="17" cy="4" r="2.4"/>
            <path d="M17 8v6.5M17 14.5l-3.5 7M17 14.5l4 6.5M17 9.5l-4.5 2.5M17 9.5l5 3"/>`),
  pat:   G(`<circle cx="6.5" cy="17.5" r="3.2"/><circle cx="25" cy="17.5" r="3.2"/>
            <path d="M21.8 17.5H8.5L18.5 4h-3.2M18.5 4h3.5l2.2 13.5"/>`)
};

const esc = s => String(s).replace(/[&<>"]/g, c => ({ "&":"&amp;", "<":"&lt;", ">":"&gt;", '"':"&quot;" }[c]));
const minutosTxt = m => {
  const t = Math.round(m);
  return t < 60 ? `${t} min` : `${Math.floor(t/60)} h ${String(t%60).padStart(2,"0")}`;
};
const brl = v => "R$ " + Number(v).toFixed(2).replace(".", ",");
const km  = v => Number(v).toFixed(1).replace(".", ",") + " km";
const kg  = g => (g/1000).toFixed(1).replace(".", ",") + " kg";
const cap = s => s ? s.charAt(0).toUpperCase() + s.slice(1) : s;
function chegada(horaLocal, minutos){
  const [h,m] = horaLocal.split(":").map(Number);
  const t = new Date(2026,0,1,h,m + Math.round(minutos));
  return String(t.getHours()).padStart(2,"0") + ":" + String(t.getMinutes()).padStart(2,"0");
}

/* =========================================================
   2. Estado e API
   ========================================================= */
const estado = { rede:null, dados:null, selecionada:0, recarga:{}, acessivel:false };
const $ = id => document.getElementById(id);

function carregando(l){ $("carregando").hidden = !l; }
function api(caminho){
  return fetch(caminho).then(r => r.json().then(j => {
    if (!r.ok) throw new Error(j.erro || r.statusText);
    return j;
  }));
}

/* =========================================================
   3. Tema
   ========================================================= */
const SOL = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/></svg>';
const LUA = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M20 14.5A8.5 8.5 0 019.5 4a8.5 8.5 0 1010.5 10.5z"/></svg>';
function aplicarTema(t){
  document.documentElement.setAttribute("data-tema", t);
  $("btnTema").innerHTML = t === "claro" ? LUA : SOL;
  const meta = document.querySelector('meta[name="theme-color"]');
  if (meta) meta.setAttribute("content", t === "claro" ? "#ffffff" : "#000000");
  try { localStorage.setItem("rsm-tema", t); } catch(e){}
}
(function(){ let t = "escuro"; try { t = localStorage.getItem("rsm-tema") || "escuro"; } catch(e){} aplicarTema(t); })();
$("btnTema").addEventListener("click", () =>
  aplicarTema(document.documentElement.getAttribute("data-tema") === "claro" ? "escuro" : "claro"));

/* =========================================================
   4. Condicoes - o que e medido e o que e estimado
   ========================================================= */
const TXT_CLIMA = { bom:"Tempo bom", chuva_leve:"Chuva leve", chuva_forte:"Chuva forte" };
const TXT_TRAN  = { livre:"trânsito livre", normal:"trânsito normal", congestionado:"trânsito congestionado" };

function renderCondicoes(){
  const { clima, transito } = estado.dados.condicoes;
  let c;
  if (clima.disponivel){
    const hora = (clima.medido_em || "").slice(11);
    c = `<span class="c" title="${esc(clima.descricao)} · ${esc(clima.fonte)} · medido às ${esc(hora)}">
           <i class="pt pt-m"></i>${TXT_CLIMA[clima.clima]}, ${Math.round(clima.temperatura)}° <b>medido</b></span>`;
  } else {
    c = `<span class="c" title="A fonte meteorológica não respondeu; o app seguiu assumindo tempo bom.">
           <i class="pt pt-e"></i>Tempo não medido <b>assumindo bom</b></span>`;
  }
  $("condicoes").innerHTML = c +
    `<span class="c" title="${esc(transito.fonte)} · ${esc(transito.motivo)} · ${esc(transito.hora_local)}">
       <i class="pt pt-e"></i>${cap(TXT_TRAN[transito.transito])} <b>estimado</b></span>` +
    `<span class="c atualizado" title="As opções são recalculadas a cada minuto">atualizado às ${esc((estado.dados.gerado_em || "").slice(0, 5))}</span>`;
}

/* =========================================================
   5. Linhas de opcao
   ========================================================= */
const idCard = r => r.resumo + "|" + r.modos.join(",");
function variante(rota){
  return (rota.variante_recarga && estado.recarga[idCard(rota)]) ? rota.variante_recarga : rota;
}
function composicao(segs){
  const ordem = [], soma = {};
  segs.filter(s => s.tipo === "deslocamento").forEach(s => {
    if (!(s.modo in soma)) { soma[s.modo] = 0; ordem.push(s.modo); }
    soma[s.modo] += s.dist_km;
  });
  const total = ordem.reduce((a,m) => a + soma[m], 0) || 1;
  return ordem.map(m => ({ modo:m, pct:(soma[m]/total)*100, km:soma[m] }));
}
function modoPrincipal(segs){
  const c = composicao(segs);
  return c.length ? c.reduce((a,b) => b.km > a.km ? b : a).modo : "pe";
}
const impactoTxt = r => r.co2 < 1 ? "sem emissão" : "evita " + kg(r.co2_evitado);

const SVG_AL = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round"><path d="M12 9v5M12 17.4v.01"/><path d="M10.3 3.9L2.6 17.2A2 2 0 004.3 20h15.4a2 2 0 001.7-2.8L13.7 3.9a2 2 0 00-3.4 0z"/></svg>';

const SVG_ESCUDO = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3l7 3v5.5c0 4.3-2.9 8.1-7 9.5-4.1-1.4-7-5.2-7-9.5V6z"/><path d="M9 12l2 2 4-4"/></svg>';

function renderOpcoes(){
  const ul = $("opcoes");
  const hora = estado.dados.condicoes.transito.hora_local;
  ul.innerHTML = "";

  estado.dados.cards.forEach((r, i) => {
    const v = variante(r);
    const sel = estado.selecionada === i;
    const li = document.createElement("li");
    li.className = "opcao"; li.dataset.sel = sel ? "1" : "0"; li.dataset.i = i;

    const marcas = []
      .concat(r.recomendado ? ['<span class="marca marca-rec">Recomendado</span>'] : [])
      .concat(r.perfis.map(p => `<span class="marca">${esc(p)}</span>`)).join("");

    const barra = composicao(v.segmentos)
      .map(c => `<i style="--m:${corDe(c.modo)};flex:${c.pct.toFixed(2)}" title="${esc(MODAIS[c.modo].rotulo)} · ${km(c.km)}"></i>`).join("");

    const alerta = (r.avisos || []).find(a => a.nivel === "alerta");
    const trocas = v.transferencias;

    let html = `
      <button class="opcao-linha" type="button" aria-pressed="${sel}">
        <span class="glifo">${GLIFOS[MODAIS[modoPrincipal(v.segmentos)].glifo]}</span>
        <span class="meio">
          <span class="l1"><span class="nome">${esc(r.resumo)}</span><span class="preco">${brl(v.custo)}</span></span>
          <span class="l2">
            <span class="dur">${minutosTxt(v.tempo)}</span>
            <span class="chega">chega às ${chegada(hora, v.tempo)} · ${trocas} ${trocas === 1 ? "troca" : "trocas"}</span>
            <span class="impacto">${impactoTxt(v)}</span>
          </span>
          <span class="barra">${barra}</span>
          ${marcas ? `<span class="marcas">${marcas}</span>` : ""}
        </span>
      </button>`;

    if (alerta) html += `<div class="alerta">${SVG_AL}<span>${esc(alerta.texto)}</span></div>`;
    // o filtro de seguranca tirou esta opcao de uma via perigosa: dizer qual e por que
    (r.evitou || []).forEach(e => {
      html += `<div class="seguro">${SVG_ESCUDO}<span>${esc(e.texto)}</span></div>`;
    });

    if (r.usa_carro && r.variante_recarga) {
      const dT = r.variante_recarga.tempo - r.tempo, dC = r.variante_recarga.custo - r.custo;
      html += `<button class="recarga" type="button" aria-pressed="${!!estado.recarga[idCard(r)]}" data-recarga="${i}">
          <span class="rot">Parar para recarregar</span>
          <span class="delta">+${Math.round(dT)} min · +${brl(dC)}</span>
          <span class="chave"></span>
        </button>`;
    }
    if (sel) html += passosHTML(r, v);

    li.innerHTML = html;
    ul.appendChild(li);
  });

  const r = estado.dados.cards[estado.selecionada];
  if (r) {
    const v = variante(r);
    $("ctaNome").textContent = "Escolher " + r.resumo;
    $("ctaPreco").textContent = brl(v.custo);
  }
}

// Seguranca viaria de uma perna a pe ou de duas rodas, com o dado da CTTU.
// Tres respostas possiveis, e "sem dado" nunca e apresentado como seguro.
function segurancaDoPasso(v, s){
  const seg = v.seguranca;
  if (!seg || !seg.trechos) return "";
  const meus = seg.trechos.filter(t => t.modo === s.modo &&
    s.pontos.some((p, k) => p === t.de && s.pontos[k + 1] === t.para));
  if (!meus.length) return "";
  const quem = meus[0].usuario === "pedestre" ? "pedestre" : "ciclista";
  const atencao = meus.filter(t => t.nivel === "atencao");
  if (atencao.length) {
    const t = atencao[0];
    return `<span class="pt-seg atencao">Atenção: ${esc(t.via || "via")} tem ${t.sinistros_usuario} sinistros com ${quem} em 3 anos</span>`;
  }
  const semDado = meus.filter(t => t.nivel === "sem_dado").length;
  if (semDado === meus.length) return `<span class="pt-seg">Sem dado de segurança viária neste trecho</span>`;
  if (semDado) return `<span class="pt-seg">Parte do trecho sem dado de segurança viária</span>`;
  return `<span class="pt-seg ok">Sem histórico alto de sinistros com ${quem}</span>`;
}

function passosHTML(rota, v){
  const segs = v.segmentos;
  const itens = segs.map((s, idx) => {
    const ultimo = idx === segs.length - 1;
    if (s.tipo === "deslocamento") {
      const c = s.cor || corDe(s.modo);
      return `<li class="passo">
        <span class="tr"><span class="ln${s.modo === "metro" ? " tracejado" : ""}" style="--m:${c}"></span></span>
        <span class="pt-txt"><span class="pt-t">${esc(cap(MODAIS[s.modo].rotulo))}</span>
        <span class="pt-s">${km(s.dist_km)} · ${minutosTxt(s.tempo)}</span>${segurancaDoPasso(v, s)}</span></li>`;
    }
    if (s.tipo === "recarga") {
      return `<li class="passo">
        <span class="tr"><span class="no rec" style="--m:${corDe("carro")}"></span>${ultimo ? "" : `<span class="ln" style="--m:${corDe("carro")}"></span>`}</span>
        <span class="pt-txt"><span class="pt-t">${esc(cap(s.rotulo))}</span>
        <span class="pt-s">${esc(s.local)} · ${minutosTxt(s.tempo)} · ${brl(s.custo)}</span></span></li>`;
    }
    const para = MODAIS[s.para] ? MODAIS[s.para].rotulo : s.para_rotulo;
    const titulo = idx === 0 ? `Começar de ${para}` : (s.para === "pe" ? `Descer e seguir a pé` : `Trocar para ${para}`);
    const extra = s.custo > 0 ? ` · ${brl(s.custo)}` : "";
    return `<li class="passo">
      <span class="tr"><span class="no"></span>${ultimo ? "" : '<span class="ln" style="--m:var(--div)"></span>'}</span>
      <span class="pt-txt"><span class="pt-t">${esc(titulo)}</span>
      <span class="pt-s">${esc(s.ponto_nome)} · ${minutosTxt(s.tempo)}${extra}</span></span></li>`;
  }).join("");

  const infos = (rota.avisos || []).filter(a => a.nivel !== "alerta")
    .map(a => `<p class="info">${esc(a.texto)}</p>`).join("");
  return `<ol class="passos">${itens}</ol>${infos ? `<div class="infos">${infos}</div>` : ""}`;
}

$("opcoes").addEventListener("click", ev => {
  const alavanca = ev.target.closest("[data-recarga]");
  if (alavanca) {
    ev.stopPropagation();
    const i = Number(alavanca.dataset.recarga);
    const id = idCard(estado.dados.cards[i]);
    estado.recarga[id] = !estado.recarga[id];
    renderOpcoes();
    if (estado.selecionada === i) desenhar(false);
    return;
  }
  const linha = ev.target.closest(".opcao-linha");
  if (!linha) return;
  estado.selecionada = Number(linha.closest(".opcao").dataset.i);
  renderOpcoes();
  desenhar(true);
});

/* =========================================================
   6. Mapa
   ========================================================= */
const mapa = L.map("mapa", { zoomControl:false, attributionControl:true }).setView([-8.096,-34.888], 12);
const tiles = L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png",
  { maxZoom:19, attribution:"© OpenStreetMap" }).addTo(mapa);
let falhasTile = 0;
tiles.on("tileerror", () => { if (++falhasTile === 6) { mapa.removeLayer(tiles); document.body.classList.add("sem-tiles"); } });
const camada = L.layerGroup().addTo(mapa);

const RAIO = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M13.2 2.5 5 13.4h5.6l-1.2 8.1 8.6-11.3h-5.7z"/></svg>';

const pin = (ll, c) => L.marker(ll, { icon: L.divIcon({ className:"pin "+c, html:"<i></i>", iconSize:[18,18], iconAnchor:[9,9] }) });

function padding(){
  const desktop = window.matchMedia("(min-width:860px)").matches;
  return desktop ? { paddingTopLeft:[440,60], paddingBottomRight:[60,60] }
                 : { paddingTopLeft:[40,80],  paddingBottomRight:[40, Math.round(innerHeight*0.42)] };
}

function desenhar(ajustar){
  camada.clearLayers();
  if (!estado.dados || !estado.dados.cards) return;
  const r = estado.dados.cards[estado.selecionada];
  if (!r) return;
  const v = variante(r);
  const pontos = [];

  v.segmentos.forEach(s => {
    if (s.tipo === "deslocamento") {
      const geo = s.tracado || s.coords;
      const c = s.cor || corDe(s.modo);
      L.polyline(geo, {
        color:c, weight:6, opacity:.96, lineCap:"round", lineJoin:"round",
        // o metro nao tem tracado de via: fica pontilhado, convencao de trilho
        dashArray: s.modo === "metro" ? "1 12" : null
      }).addTo(camada);
      geo.forEach(p => pontos.push(p));
      L.circleMarker(geo[geo.length - 1], { radius:5, color:c, weight:2.5, fillOpacity:0 }).addTo(camada);
    }
    if (s.tipo === "recarga" && s.coord) {
      // parada efetiva de recarga: raio, acima da linha da rota
      L.marker(s.coord, {
        icon: L.divIcon({ className:"pin-raio", html:RAIO, iconSize:[30,30], iconAnchor:[15,15] }),
        zIndexOffset: 1000, keyboard: false
      }).addTo(camada)
        .bindTooltip(`${cap(s.rotulo)} — ${s.local} · ${minutosTxt(s.tempo)} · ${brl(s.custo)}`);
      pontos.push(s.coord);
    }
  });

  // eletropostos so no card do carro proprio: sao uma escolha, nao uma parada
  if (r.usa_carro) estado.rede.recargas.forEach(e =>
    L.circleMarker([e.lat, e.lon], { radius:6, color:corDe("carro"), weight:1.5, opacity:.55, dashArray:"2 3", fillOpacity:0 })
      .addTo(camada).bindTooltip(e.nome));

  if (pontos.length) {
    pin(pontos[0], "pin-o").addTo(camada);
    pin(pontos[pontos.length - 1], "pin-d").addTo(camada);
    if (ajustar !== false) mapa.fitBounds(L.latLngBounds(pontos), padding());
  }
}
$("btnCentro").addEventListener("click", () => desenhar(true));

/* =========================================================
   7. Folha arrastavel (so no celular)
   ========================================================= */
const folha = $("folha"), rolagem = $("rolagem");
const ALTO = 0, MEIO = 34;   // em dvh
let snap = MEIO, arrastando = false, y0 = 0, base = 0;

function setY(v){ folha.style.setProperty("--y", v + "dvh"); }
setY(MEIO);
function movel(){ return !window.matchMedia("(min-width:860px)").matches; }

function comecar(ev){
  if (!movel()) return;
  if (ev.target.closest("select, button") && !ev.target.closest(".pega")) return;
  if (ev.target.closest(".folha-rolagem") && snap === ALTO && rolagem.scrollTop > 0) return;
  arrastando = true; y0 = ev.clientY; base = snap;
  folha.classList.add("arrastando");
  if (folha.setPointerCapture) folha.setPointerCapture(ev.pointerId);
}
function mover(ev){
  if (!arrastando) return;
  let v = base + (ev.clientY - y0) / innerHeight * 100;
  if (v < ALTO) v = ALTO - Math.pow(ALTO - v, .7);
  if (v > 80) v = 80;
  setY(v);
  if (rolagem.scrollTop === 0 || v > base) ev.preventDefault();
}
function terminar(){
  if (!arrastando) return;
  arrastando = false;
  folha.classList.remove("arrastando");
  const atual = parseFloat(getComputedStyle(folha).getPropertyValue("--y"));
  snap = Math.abs(atual - ALTO) < Math.abs(atual - MEIO) ? ALTO : MEIO;
  if (atual > MEIO + 14) snap = MEIO;
  setY(snap);
  setTimeout(() => desenhar(false), 360);
}
folha.addEventListener("pointerdown", comecar);
folha.addEventListener("pointermove", mover, { passive:false });
folha.addEventListener("pointerup", terminar);
folha.addEventListener("pointercancel", terminar);
$("pega").addEventListener("click", () => {
  if (!movel()) return;
  snap = snap === MEIO ? ALTO : MEIO; setY(snap);
});

/* =========================================================
   8. Consulta
   ========================================================= */
// silencioso = atualizacao automatica: sem spinner, sem mexer no mapa nem na
// escolha do usuario, a menos que a opcao escolhida tenha deixado de existir.
function buscar(silencioso){
  const o = $("selOrigem").value, d = $("selDestino").value;
  if (o === d) {
    $("opcoes").innerHTML = '<li class="erro">Origem e destino são o mesmo lugar.</li>';
    $("sugestao").textContent = ""; camada.clearLayers(); return;
  }
  if (silencioso && estado.buscando) return;
  estado.buscando = true;
  if (!silencioso) carregando(true);
  const anterior = estado.dados && estado.dados.cards ? estado.dados : null;
  const idSelecionado = anterior && anterior.cards[estado.selecionada]
    ? idCard(anterior.cards[estado.selecionada]) : null;
  const idRecomendadoAntes = anterior ? idCard(anterior.cards.find(c => c.recomendado) || anterior.cards[0]) : null;

  api(`/api/opcoes?origem=${o}&destino=${d}&acessivel=${estado.acessivel ? 1 : 0}`)
    .then(r => {
      if (silencioso && ($("selOrigem").value !== o || $("selDestino").value !== d)) return;
      estado.dados = r;
      estado.ultimaBusca = Date.now();
      if (r.condicoes) renderCondicoes();
      if (r.erro) {
        $("opcoes").innerHTML = `<li class="erro">${esc(r.erro)}</li>`;
        $("sugestao").textContent = ""; $("ctaNome").textContent = ""; $("ctaPreco").textContent = "";
        camada.clearLayers();
        return;
      }
      let ajustar = true;
      if (silencioso && idSelecionado) {
        const k = r.cards.findIndex(c => idCard(c) === idSelecionado);
        if (k >= 0) { estado.selecionada = k; ajustar = false; }
        else estado.selecionada = 0;           // a opcao escolhida sumiu: volta para a sugerida
      } else {
        estado.selecionada = 0; estado.recarga = {};
      }
      const rec = r.cards.find(c => c.recomendado) || r.cards[0];
      const mudou = silencioso && idRecomendadoAntes && idCard(rec) !== idRecomendadoAntes;
      $("sugestao").innerHTML = (mudou ? "<b>A sugestão mudou.</b> " : "") + esc(r.motivo_recomendacao || "");
      renderOpcoes();
      desenhar(ajustar);
    })
    .catch(e => { if (!silencioso) $("opcoes").innerHTML = `<li class="erro">${esc(e.message)}</li>`; })
    .finally(() => { estado.buscando = false; if (!silencioso) carregando(false); });
}

// Atualizacao periodica: a cada minuto, so com a aba visivel. Clima (Open-Meteo,
// atualizado a cada 15 min na fonte) e transito (por horario) mudam sozinhos;
// a melhor rota muda com eles.
const INTERVALO_MS = 60000;
setInterval(() => { if (!document.hidden && estado.dados) buscar(true); }, INTERVALO_MS);
document.addEventListener("visibilitychange", () => {
  if (!document.hidden && estado.dados && Date.now() - (estado.ultimaBusca || 0) > INTERVALO_MS)
    buscar(true);
});

$("btnTrocar").addEventListener("click", () => {
  const o = $("selOrigem"), d = $("selDestino");
  const t = o.value; o.value = d.value; d.value = t;
  buscar();
});
$("btnAcessivel").addEventListener("click", e => {
  estado.acessivel = !estado.acessivel;
  e.currentTarget.setAttribute("aria-pressed", String(estado.acessivel));
  buscar();                 // a acessibilidade muda o grafo: recalcula no servidor
});
$("cta").addEventListener("click", () => {
  if (movel()) { snap = MEIO; setY(MEIO); }
  desenhar(true);
});
window.addEventListener("resize", () => { mapa.invalidateSize(); if (!movel()) setY(0); else setY(snap); });

carregando(true);
api("/api/rede").then(rede => {
  estado.rede = rede;
  const o = $("selOrigem"), d = $("selDestino");
  rede.pontos.forEach(p => { o.add(new Option(p.nome, p.id)); d.add(new Option(p.nome, p.id)); });
  o.value = rede.origem_padrao; d.value = rede.destino_padrao;
  o.addEventListener("change", () => buscar(false));
  d.addEventListener("change", () => buscar(false));
  buscar(false);
}).catch(e => {
  $("opcoes").innerHTML = `<li class="erro">Não foi possível carregar a rede: ${esc(e.message)}</li>`;
  carregando(false);
});
})();
