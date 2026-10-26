/* RSM - Rotas Sustentaveis Multimodais - frontend do MVP */
(function () {
  "use strict";

  var rede = null;            // /api/rede
  var modosAtivos = {};       // id -> bool
  var perfilAtivo = "mais_rapida";
  var mapa = null;
  var camadaRede = null;      // trechos do grafo, ao fundo
  var camadaRecarga = null;   // eletropostos
  var camadaRota = null;      // rota em destaque

  var $ = function (id) { return document.getElementById(id); };

  function fmt(n, casas) {
    if (n === null || n === undefined) return "—";
    return Number(n).toLocaleString("pt-BR", {
      minimumFractionDigits: casas, maximumFractionDigits: casas
    });
  }

  function esc(s) {
    return String(s).replace(/[&<>"]/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c];
    });
  }

  function carregando(ligado) { $("carregando").hidden = !ligado; }

  function api(caminho) {
    return fetch(caminho).then(function (r) {
      if (!r.ok) return r.json().then(function (j) { throw new Error(j.erro || r.statusText); });
      return r.json();
    });
  }

  // Query string comum a todos os endpoints: e a foto do que o usuario escolheu.
  function query() {
    var modos = Object.keys(modosAtivos).filter(function (k) { return modosAtivos[k]; });
    return "origem=" + $("origem").value +
      "&destino=" + $("destino").value +
      "&perfil=" + perfilAtivo +
      "&modos=" + modos.join(",") +
      "&clima=" + $("clima").value +
      "&transito=" + $("transito").value +
      "&seguranca=" + $("seguranca").value +
      "&acessivel=" + ($("acessivel").checked ? 1 : 0) +
      "&recarga=" + ($("recarga").checked ? 1 : 0) +
      "&normalizacao=" + $("normalizacao").value;
  }

  // ------------------------------------------------------------------ mapa
  function iniciarMapa() {
    mapa = L.map("mapa", { scrollWheelZoom: true }).setView([-8.09, -34.89], 11);
    L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 18, attribution: "&copy; OpenStreetMap"
    }).addTo(mapa);
    camadaRede = L.layerGroup().addTo(mapa);
    camadaRecarga = L.layerGroup().addTo(mapa);
    camadaRota = L.layerGroup().addTo(mapa);
  }

  var ICONES = {
    origem_destino: { cor: "#0f766e", r: 8 },
    terminal: { cor: "#b45309", r: 7 },
    estacao: { cor: "#dc2626", r: 6 },
    ponto_micro: { cor: "#7c3aed", r: 5 },
    parada: { cor: "#d97706", r: 5 },
    via: { cor: "#94a3b8", r: 4 }
  };

  function iconeRecarga(rapido) {
    return L.divIcon({
      className: "marcador-recarga",
      html: '<span class="raio' + (rapido ? " rapido" : "") + '">⚡</span>',
      iconSize: [22, 22], iconAnchor: [11, 11]
    });
  }

  function desenharRede() {
    camadaRede.clearLayers();
    rede.trechos.forEach(function (t) {
      L.polyline(t.coords, {
        color: t.metro ? "#dc2626" : "#c7ccd4",
        weight: t.metro ? 3 : 2,
        opacity: t.metro ? 0.55 : 0.7,
        dashArray: t.acessivel ? null : "4 4"
      }).bindTooltip(esc(t.infra) + " · " + fmt(t.dist_km, 2) + " km · seg. " +
        fmt(t.seguranca, 2) + (t.acessivel ? "" : " · não acessível"))
        .addTo(camadaRede);
    });
    rede.pontos.forEach(function (p) {
      var ic = ICONES[p.tipo] || ICONES.via;
      L.circleMarker([p.lat, p.lon], {
        radius: ic.r, color: "#fff", weight: 1.5,
        fillColor: ic.cor, fillOpacity: 0.95
      }).bindTooltip("<b>" + esc(p.nome) + "</b><br>" + esc(p.municipio) +
        " · " + esc(p.tipo.replace("_", " "))).addTo(camadaRede);
    });

    camadaRecarga.clearLayers();
    rede.recargas.forEach(function (r) {
      L.marker([r.lat, r.lon], { icon: iconeRecarga(r.tipo === "rapido") })
        .bindTooltip("<b>" + esc(r.nome) + "</b><br>" + esc(r.tipo) + " · " +
          fmt(r.potencia_kw, 0) + " kW<br>parada de " + fmt(r.tempo_min, 0) +
          " min · R$ " + fmt(r.custo, 2))
        .addTo(camadaRecarga);
    });

    $("legenda-mapa").innerHTML =
      '<span><i class="bolinha" style="background:#0f766e"></i> origem / destino</span>' +
      '<span><i class="bolinha" style="background:#dc2626"></i> estação</span>' +
      '<span><i class="bolinha" style="background:#b45309"></i> terminal</span>' +
      '<span><i class="bolinha" style="background:#7c3aed"></i> micromobilidade</span>' +
      '<span><i class="bolinha" style="background:#d97706"></i> parada de ônibus</span>' +
      '<span class="raio rapido">⚡</span> eletroposto (' + rede.recargas.length + ")" +
      '<span style="border-top:2px dashed #94a3b8;width:22px;display:inline-block"></span> trecho não acessível';
  }

  function desenharRota(rota) {
    camadaRota.clearLayers();
    if (!rota || !rota.segmentos) return;
    var todos = [];
    rota.segmentos.forEach(function (s) {
      if (s.tipo === "deslocamento") {
        L.polyline(s.coords, {
          color: s.cor, weight: 6, opacity: 0.9, lineCap: "round"
        }).bindTooltip("<b>" + esc(s.modo_rotulo) + "</b> · " +
          fmt(s.dist_km, 2) + " km · " + fmt(s.tempo, 1) + " min")
          .addTo(camadaRota);
        s.coords.forEach(function (c) { todos.push(c); });
      } else if (s.tipo === "recarga") {
        L.circleMarker(s.coord, {
          radius: 10, color: "#065f46", weight: 3,
          fillColor: "#a7f3d0", fillOpacity: 1
        }).bindTooltip("<b>Recarga</b><br>" + esc(s.local) + "<br>+" +
          fmt(s.tempo, 0) + " min · R$ " + fmt(s.custo, 2)).addTo(camadaRota);
      } else {
        L.circleMarker(s.coord, {
          radius: 6, color: "#1c2230", weight: 2,
          fillColor: "#fff", fillOpacity: 1
        }).bindTooltip("Transferência " + esc(s.de_rotulo) + " → " +
          esc(s.para_rotulo) + "<br>" + esc(s.ponto_nome) +
          " · +" + fmt(s.tempo, 1) + " min").addTo(camadaRota);
      }
    });
    if (todos.length) mapa.fitBounds(L.latLngBounds(todos).pad(0.12));
  }

  // -------------------------------------------------------------- controles
  function preencherControles() {
    var op = function (v, t) {
      var o = document.createElement("option");
      o.value = v; o.textContent = t; return o;
    };
    rede.pontos.forEach(function (p) {
      $("origem").appendChild(op(p.id, p.nome + " (" + p.municipio + ")"));
      $("destino").appendChild(op(p.id, p.nome + " (" + p.municipio + ")"));
    });
    $("origem").value = rede.origem_padrao;
    $("destino").value = rede.destino_padrao;

    // ---- chips de modal ("como voce quer ir") ----------------------------
    var html = "";
    Object.keys(rede.modos).forEach(function (k) {
      var m = rede.modos[k];
      modosAtivos[k] = true;
      var fixo = k === "pe";
      html += '<button type="button" class="chip ativo' + (fixo ? " fixo" : "") +
        '" data-modo="' + k + '"' + (fixo ? " disabled" : "") +
        ' title="' + esc(m.viabilidade) + '">' +
        '<i class="bolinha" style="background:' + m.cor + '"></i>' +
        esc(m.rotulo) + (m.eletrico ? ' <span class="eletrico">⚡</span>' : "") +
        "</button>";
    });
    $("chips-modos").innerHTML = html;
    Array.prototype.forEach.call($("chips-modos").querySelectorAll(".chip"), function (b) {
      b.addEventListener("click", function () {
        var k = b.getAttribute("data-modo");
        modosAtivos[k] = !modosAtivos[k];
        b.classList.toggle("ativo", modosAtivos[k]);
        sincronizarRecarga();
      });
    });

    // ---- chips de perfil --------------------------------------------------
    html = "";
    rede.perfis.forEach(function (p) {
      html += '<button type="button" class="chip' +
        (p.id === perfilAtivo ? " ativo" : "") + '" data-perfil="' + p.id + '">' +
        esc(p.rotulo) + "</button>";
    });
    $("chips-perfil").innerHTML = html;
    Array.prototype.forEach.call($("chips-perfil").querySelectorAll(".chip"), function (b) {
      b.addEventListener("click", function () {
        perfilAtivo = b.getAttribute("data-perfil");
        Array.prototype.forEach.call($("chips-perfil").querySelectorAll(".chip"),
          function (o) { o.classList.remove("ativo"); });
        b.classList.add("ativo");
        descreverPerfil();
      });
    });

    // ---- condicoes --------------------------------------------------------
    rede.climas.forEach(function (c) { $("clima").appendChild(op(c.id, c.rotulo)); });
    rede.transitos.forEach(function (c) { $("transito").appendChild(op(c.id, c.rotulo)); });
    rede.segurancas.forEach(function (c) { $("seguranca").appendChild(op(c.id, c.rotulo)); });
    // o select assume a primeira opcao; os padroes do backend nao sao a primeira
    $("clima").value = "bom";
    $("transito").value = "normal";
    $("seguranca").value = "indiferente";

    ["clima", "transito", "seguranca"].forEach(function (dim) {
      $(dim).addEventListener("change", function () { descrever(dim); });
      descrever(dim);
    });

    // ---- presets ----------------------------------------------------------
    Array.prototype.forEach.call(document.querySelectorAll(".atalhos button"), function (b) {
      b.addEventListener("click", function () { aplicarPreset(b.getAttribute("data-preset")); });
    });

    descreverPerfil();
    sincronizarRecarga();
  }

  var PRESETS = {
    todos: null,
    publico: ["pe", "metro", "onibus"],
    ativo: ["pe", "bike", "ebike", "patinete"],
    carro: ["pe", "carro", "carro_app"]
  };

  function aplicarPreset(nome) {
    var lista = PRESETS[nome];
    Object.keys(modosAtivos).forEach(function (k) {
      modosAtivos[k] = lista === null ? true : lista.indexOf(k) >= 0;
    });
    modosAtivos["pe"] = true;
    Array.prototype.forEach.call($("chips-modos").querySelectorAll(".chip"), function (b) {
      b.classList.toggle("ativo", modosAtivos[b.getAttribute("data-modo")]);
    });
    sincronizarRecarga();
    calcular();
  }

  // A parada de recarga so faz sentido com o carro proprio marcado: desabilitar
  // e mais honesto do que aceitar a opcao e devolver "sem rota".
  function sincronizarRecarga() {
    var temCarro = !!modosAtivos[rede.modo_recarregavel];
    $("recarga").disabled = !temCarro;
    $("switch-recarga").classList.toggle("desabilitado", !temCarro);
    if (!temCarro) $("recarga").checked = false;
    $("recarga-desc").textContent = temCarro
      ? "Obriga a rota a passar por um dos " + rede.recargas.length +
        " eletropostos. Só o carro próprio recarrega — no carro de aplicativo quem cuida da carga é o motorista."
      : "Marque o carro elétrico próprio para habilitar esta opção.";
  }

  function descrever(dim) {
    var lista = rede[dim === "clima" ? "climas" : dim === "transito" ? "transitos" : "segurancas"];
    var v = lista.filter(function (x) { return x.id === $(dim).value; })[0];
    $(dim + "-desc").textContent = v ? v.descricao : "";
  }

  function descreverPerfil() {
    var p = rede.perfis.filter(function (x) { return x.id === perfilAtivo; })[0];
    if (!p) return;
    var nomes = ["tempo", "custo", "CO₂", "desconforto"];
    $("perfil-pesos").textContent = "Pesos: " + p.pesos.map(function (w, i) {
      return nomes[i] + " " + fmt(w, 2);
    }).join(" · ");
  }

  // ----------------------------------------------------------------- render
  function metrica(k, v, u, destaque) {
    return '<div class="metrica' + (destaque ? " destaque" : "") + '">' +
      '<div class="k">' + k + "</div>" +
      '<div class="v">' + v + ' <span class="u">' + u + "</span></div></div>";
  }

  function renderResumo(r) {
    var rec = r.pareto && r.pareto.rotas.length
      ? r.pareto.rotas[r.pareto.recomendada] : r.dijkstra.rota;

    $("resumo-bloco").hidden = false;
    $("metricas").innerHTML =
      metrica("Tempo", fmt(rec.tempo, 1), "min") +
      metrica("Custo", "R$ " + fmt(rec.custo, 2), "") +
      metrica("Emissão", fmt(rec.co2, 0), "g CO₂eq") +
      metrica("Evitada vs. carro a combustão", fmt(rec.co2_evitado, 0), "g CO₂eq", true) +
      metrica("Distância", fmt(rec.dist_km, 2), "km") +
      metrica("Transferências", rec.transferencias, "");

    // A recomendada vem do TOPSIS sobre a fronteira; a otima do Dijkstra vem da
    // soma ponderada com escalas fixas. Criterios distintos, podem divergir.
    var alt = document.getElementById("alternativa");
    if (alt) alt.remove();
    var d = r.dijkstra.rota;
    if (Math.abs(d.tempo - rec.tempo) > 0.05 || d.modos.join() !== rec.modos.join()) {
      var bloco = document.createElement("p");
      bloco.id = "alternativa";
      bloco.className = "hint";
      bloco.style.marginTop = "10px";
      bloco.innerHTML =
        "A <b>ótima escalarizada</b> (Dijkstra/A*, soma ponderada com escalas fixas) " +
        "é outra rota: <b>" + fmt(d.tempo, 1) + " min</b>, R$ " + fmt(d.custo, 2) +
        ", " + fmt(d.co2, 0) + " g CO₂ — " + esc(d.modos_rotulo.join(" + ")) +
        ". A recomendação acima vem do TOPSIS sobre a fronteira de Pareto, que " +
        "compara as alternativas entre si em vez de usar escalas fixas.";
      $("metricas").insertAdjacentElement("afterend", bloco);
    }

    var html = "";
    rec.segmentos.forEach(function (s) {
      if (s.tipo === "deslocamento") {
        html += '<li class="passo"><span class="faixa" style="background:' + s.cor +
          '"></span><div><b>' + esc(s.modo_rotulo) + "</b> · " + fmt(s.dist_km, 2) +
          " km · " + fmt(s.tempo, 1) + " min" +
          '<div class="det">' + esc(s.infra.join(" → ")) + "</div></div></li>";
      } else if (s.tipo === "recarga") {
        html += '<li class="passo recarga"><span class="faixa" style="background:#065f46"></span>' +
          "<div><b>⚡ Recarga</b> · " + esc(s.local) +
          '<div class="det">+' + fmt(s.tempo, 0) + " min · R$ " + fmt(s.custo, 2) +
          " · " + esc(s.rotulo) + "</div></div></li>";
      } else {
        html += '<li class="passo transfer"><span class="faixa" style="background:#cbd2dc"></span>' +
          "<div>" + esc(s.de_rotulo) + " → " + esc(s.para_rotulo) +
          " em " + esc(s.ponto_nome) +
          '<div class="det">+' + fmt(s.tempo, 1) + " min" +
          (s.custo > 0 ? " · R$ " + fmt(s.custo, 2) : "") + "</div></div></li>";
      }
    });
    $("passos").innerHTML = html;
    desenharRota(rec);
  }

  // --------------------------------------------------------------- Pareto
  function renderPareto(r) {
    var alvo = $("tabela-pareto");
    var antigo = document.getElementById("por-perfil");
    if (antigo) antigo.remove();
    if (!r.pareto || !r.pareto.rotas.length) {
      alvo.innerHTML = "";
      $("pareto-grafico").innerHTML = '<p class="hint">Fronteira vazia.</p>';
      return;
    }
    var rotas = r.pareto.rotas;

    var cab = "<thead><tr><th>#</th><th>Tempo (min)</th><th>Custo (R$)</th>" +
      "<th>CO₂ (g)</th><th>Desconf.</th><th>Dist. (km)</th>" +
      "<th>TOPSIS</th><th class='esq'>Composição</th></tr></thead>";
    var corpo = "<tbody>";
    rotas.forEach(function (x, i) {
      corpo += '<tr data-i="' + i + '"' +
        (i === r.pareto.recomendada ? ' class="recomendada selecionada"' : "") + ">" +
        "<td>" + (i + 1) + "</td><td>" + fmt(x.tempo, 1) + "</td><td>" + fmt(x.custo, 2) +
        "</td><td>" + fmt(x.co2, 1) + "</td><td>" + fmt(x.desconforto, 2) +
        "</td><td>" + fmt(x.dist_km, 2) + "</td><td>" + fmt(x.topsis, 3) +
        "</td><td class='esq'>" + esc(x.modos_rotulo.join(" + ")) +
        (x.recargas ? ' <span class="tag">⚡ recarga</span>' : "") +
        (x.transferencias ? ' <span class="tag cinza">' + x.transferencias + " transf.</span>" : "") +
        (i === r.pareto.recomendada ? ' <span class="tag">recomendada</span>' : "") +
        "</td></tr>";
    });
    alvo.innerHTML = cab + corpo + "</tbody>";

    Array.prototype.forEach.call(alvo.querySelectorAll("tbody tr"), function (tr) {
      tr.addEventListener("click", function () {
        var i = Number(tr.getAttribute("data-i"));
        Array.prototype.forEach.call(alvo.querySelectorAll("tr"), function (o) {
          o.classList.remove("selecionada");
        });
        tr.classList.add("selecionada");
        desenharRota(rotas[i]);
        desenharDispersao(rotas, i);
      });
    });

    desenharDispersao(rotas, r.pareto.recomendada);
    renderPorPerfil(r);
  }

  function desenharDispersao(rotas, destaque) {
    var W = 720, H = 260, ml = 56, mr = 16, mt = 14, mb = 38;
    var xs = rotas.map(function (r) { return r.tempo; });
    var ys = rotas.map(function (r) { return r.custo; });
    var cs = rotas.map(function (r) { return r.co2; });
    var x0 = Math.min.apply(null, xs), x1 = Math.max.apply(null, xs);
    var y0 = Math.min.apply(null, ys), y1 = Math.max.apply(null, ys);
    var c1 = Math.max.apply(null, cs) || 1;
    if (x1 === x0) x1 = x0 + 1;
    if (y1 === y0) y1 = y0 + 1;

    var px = function (v) { return ml + (v - x0) / (x1 - x0) * (W - ml - mr); };
    var py = function (v) { return H - mb - (v - y0) / (y1 - y0) * (H - mt - mb); };

    var s = '<svg viewBox="0 0 ' + W + " " + H + '" role="img" ' +
      'aria-label="Fronteira de Pareto: tempo versus custo, cor indica emissao">';
    s += '<line x1="' + ml + '" y1="' + (H - mb) + '" x2="' + (W - mr) +
      '" y2="' + (H - mb) + '" stroke="#c7ccd4"/>';
    s += '<line x1="' + ml + '" y1="' + mt + '" x2="' + ml + '" y2="' +
      (H - mb) + '" stroke="#c7ccd4"/>';
    [0, 0.5, 1].forEach(function (f) {
      var vx = x0 + f * (x1 - x0), vy = y0 + f * (y1 - y0);
      s += '<text x="' + px(vx) + '" y="' + (H - mb + 15) +
        '" font-size="11" fill="#626b7d" text-anchor="middle">' + fmt(vx, 0) + "</text>";
      s += '<text x="' + (ml - 8) + '" y="' + (py(vy) + 4) +
        '" font-size="11" fill="#626b7d" text-anchor="end">' + fmt(vy, 2) + "</text>";
    });
    s += '<text x="' + ((W + ml) / 2) + '" y="' + (H - 6) +
      '" font-size="11.5" fill="#626b7d" text-anchor="middle">tempo (min)</text>';
    s += '<text x="14" y="' + (H / 2) + '" font-size="11.5" fill="#626b7d" ' +
      'text-anchor="middle" transform="rotate(-90 14 ' + (H / 2) + ')">custo (R$)</text>';

    rotas.forEach(function (r, i) {
      var t = Math.sqrt(r.co2 / c1);
      var cor = "rgb(" + Math.round(22 + t * 200) + "," +
        Math.round(163 - t * 120) + "," + Math.round(74 - t * 40) + ")";
      var destq = i === destaque;
      s += '<circle cx="' + px(r.tempo) + '" cy="' + py(r.custo) + '" r="' +
        (destq ? 9 : 6) + '" fill="' + cor + '" stroke="' +
        (destq ? "#1c2230" : "#fff") + '" stroke-width="' + (destq ? 2.5 : 1.5) +
        '"><title>#' + (i + 1) + " · " + fmt(r.tempo, 1) + " min · R$ " +
        fmt(r.custo, 2) + " · " + fmt(r.co2, 1) + " g CO2 · " +
        r.modos_rotulo.join(" + ") + "</title></circle>";
    });
    s += "</svg>";

    $("pareto-grafico").innerHTML = s + '<div class="legenda">' +
      '<span><i class="bolinha" style="background:rgb(22,163,74)"></i> emissão zero</span>' +
      '<span><i class="bolinha" style="background:rgb(222,43,34)"></i> emissão máxima da fronteira (' +
      fmt(c1, 0) + " g)</span>" +
      '<span><i class="bolinha" style="background:#1c2230"></i> rota em destaque no mapa</span></div>';
  }

  function renderPorPerfil(r) {
    var pp = r.pareto.por_perfil;
    var linhas = "";
    rede.perfis.forEach(function (p) {
      var v = pp[p.id];
      if (!v) return;
      linhas += "<tr><td class='esq'>" + esc(v.rotulo) +
        (p.id === r.perfil.id ? ' <span class="tag">ativo</span>' : "") + "</td>" +
        "<td>#" + (v.indice + 1) + "</td><td class='esq'>" +
        esc(v.modos_rotulo.join(" + ")) + "</td><td>" + fmt(v.tempo, 1) +
        "</td><td>" + fmt(v.custo, 2) + "</td><td>" + fmt(v.co2, 1) +
        "</td><td>" + fmt(v.co2_evitado, 0) + "</td><td>" + fmt(v.escore, 3) +
        "</td></tr>";
    });

    var nota = r.normalizacao === "vetorial"
      ? "Normalização <b>vetorial</b> (clássica). Atenção: o peso efetivo de cada " +
        "critério depende da dispersão da coluna na fronteira — como a emissão varia " +
        "muito mais que o tempo, ela domina a decisão mesmo com peso 0,10, e perfis " +
        "diferentes tendem a colapsar na mesma rota."
      : "Normalização <b>min-max</b>: cada critério é reescalado para [0,1] entre o " +
        "melhor e o pior valor da fronteira, de modo que os pesos do perfil significam " +
        "o que dizem. Troque para a vetorial no painel para ver o efeito da dispersão.";

    var el = document.createElement("div");
    el.id = "por-perfil";
    el.innerHTML = "<h3>Recomendação por perfil (TOPSIS sobre a mesma fronteira)</h3>" +
      '<div class="tabela-rolavel"><table><thead><tr>' +
      "<th class='esq'>Perfil</th><th>Solução</th><th class='esq'>Modais</th>" +
      "<th>Tempo (min)</th><th>Custo (R$)</th><th>CO₂ (g)</th>" +
      "<th>CO₂ evitado (g)</th><th>Escore</th></tr></thead><tbody>" +
      linhas + "</tbody></table></div><p class=\"hint\">" + nota + "</p>";
    $("aba-pareto").appendChild(el);
  }

  // ------------------------------------------------------- Dijkstra x A*
  function renderBusca(r) {
    var d = r.dijkstra, a = r.astar, c = r.comparacao;
    $("busca-cards").innerHTML = '<div class="cards">' +
      '<div class="card"><div class="t">Dijkstra — vértices expandidos</div><div class="n">' +
      d.expandidos + '</div><div class="d">' + fmt(d.ms, 2) + " ms · rota de " +
      fmt(d.rota.tempo, 1) + " min</div></div>" +
      '<div class="card"><div class="t">A* — vértices expandidos</div><div class="n">' +
      a.expandidos + '</div><div class="d">' + fmt(a.ms, 2) + " ms · rota de " +
      fmt(a.rota.tempo, 1) + " min</div></div>" +
      '<div class="card"><div class="t">Redução do espaço de busca</div><div class="n">' +
      fmt(c.reducao_busca_pct, 1) + '%</div><div class="d">grafo com ' + r.grafo.V +
      " vértices e " + r.grafo.E + " arestas</div></div>" +
      '<div class="card"><div class="t">Mesma rota ótima?</div><div class="n">' +
      (c.mesma_rota ? "sim" : "não") +
      '</div><div class="d">exigência da heurística admissível</div></div></div>';

    $("busca-nota").innerHTML =
      "A heurística divide a distância em linha reta pela <b>maior</b> velocidade da rede " +
      "(metrô, 32 km/h) para permanecer admissível. Como a maior parte do deslocamento " +
      "deste corredor ocorre em modais lentos, a estimativa fica conservadora e o poder de " +
      "poda cai — exatamente o comportamento previsto na Etapa 2 (§ 6.3), amplificado " +
      "pelos ~24 km do trajeto. Perfis com peso de tempo baixo enfraquecem ainda mais a " +
      "heurística, porque ela só estima o componente de tempo.";
  }

  // ------------------------------------------------- eixo metroferroviario
  function renderMetro(r) {
    var m = r.metro_obrigatorio;
    if (!m) {
      $("metro-conteudo").innerHTML =
        '<p class="hint">Nenhuma rota usando o metrô existe com estas opções.</p>';
      return;
    }
    var d = r.dijkstra.rota;
    var delta = m.penalidade_pct;
    var veredito = m.usa_metro_na_otima
      ? "A rota ótima escalarizada <b>já usa</b> o eixo metroferroviário."
      : (delta !== null && delta < 0
        ? "Forçar o metrô produz uma rota <b>" + fmt(-delta, 1) +
          "% mais rápida</b> que a ótima escalarizada, mas que perde no critério " +
          "agregado do perfil ativo — troca tempo por emissão e tarifa. O metrô é, " +
          "portanto, competitivo neste corredor: quando não aparece, é por causa dos " +
          "<em>outros</em> objetivos, não por desvio geográfico."
        : "Forçar o metrô custa <b>+" + fmt(delta, 1) +
          "%</b> no tempo em relação à melhor rota livre.");

    var rec = r.pareto && r.pareto.rotas.length
      ? r.pareto.rotas[r.pareto.recomendada] : d;
    if (rec.modos.indexOf("metro") >= 0) {
      veredito += " Neste caso a rota <b>recomendada</b> ao perfil ativo (TOPSIS sobre " +
        "a fronteira) de fato usa o metrô — a comparação acima é contra a ótima " +
        "escalarizada do Dijkstra, que é outro critério.";
    }

    var passos = "";
    m.segmentos.forEach(function (s) {
      passos += s.tipo === "deslocamento"
        ? "<li>" + esc(s.modo_rotulo) + " · " + fmt(s.dist_km, 2) + " km · " +
          fmt(s.tempo, 1) + " min</li>"
        : s.tipo === "recarga"
          ? "<li><em>⚡ recarga em " + esc(s.local) + " (+" + fmt(s.tempo, 0) +
            " min, R$ " + fmt(s.custo, 2) + ")</em></li>"
          : "<li><em>transferência " + esc(s.de_rotulo) + " → " +
            esc(s.para_rotulo) + " em " + esc(s.ponto_nome) + " (+" +
            fmt(s.tempo, 1) + " min)</em></li>";
    });

    $("metro-conteudo").innerHTML =
      "<h3>Contraprova: a melhor rota obrigada a passar pelo metrô</h3>" +
      '<div class="cards"><div class="card"><div class="t">Melhor rota livre</div><div class="n">' +
      fmt(d.tempo, 1) + ' <span style="font-size:13px">min</span></div><div class="d">' +
      esc(d.modos_rotulo.join(" + ")) + " · R$ " + fmt(d.custo, 2) + " · " +
      fmt(d.co2, 0) + " g CO₂</div></div>" +
      '<div class="card"><div class="t">Obrigada a usar o metrô</div><div class="n">' +
      fmt(m.tempo, 1) + ' <span style="font-size:13px">min</span></div><div class="d">' +
      esc(m.modos_rotulo.join(" + ")) + " · R$ " + fmt(m.custo, 2) + " · " +
      fmt(m.co2, 0) + " g CO₂</div></div>" +
      '<div class="card"><div class="t">Diferença de tempo</div><div class="n">' +
      (delta > 0 ? "+" : "") + fmt(delta, 1) + '%</div><div class="d">' +
      fmt(m.dist_km, 2) + " km contra " + fmt(d.dist_km, 2) + " km</div></div></div>" +
      '<p class="hint" style="margin-top:12px;font-size:13px">' + veredito + "</p>" +
      "<h3>Composição da rota via metrô</h3><ul>" + passos + "</ul>" +
      '<p class="hint">Resolvido exatamente sobre o grafo-produto G × {0,1}, em que o bit ' +
      "registra se o modal obrigatório já foi usado — dobra |V| e preserva O(E log V).</p>";
  }

  // --------------------------------------------------- viabilidade dos modais
  var SELO = {
    viavel: { texto: "viável", fundo: "#ecfdf5", cor: "#047857" },
    limitrofe: { texto: "limítrofe", fundo: "#fff8e6", cor: "#8a6206" },
    inviavel: { texto: "inviável", fundo: "#fdf1f1", cor: "#8c2020" },
    sem_rota: { texto: "sem rota", fundo: "#eef0f3", cor: "#626b7d" },
    desligado: { texto: "desligado", fundo: "#eef0f3", cor: "#626b7d" }
  };

  function rodarViabilidade() {
    carregando(true);
    api("/api/viabilidade?" + query()).then(function (r) {
      var lim = r.limiares;
      var linhas = "";
      r.modos.forEach(function (m) {
        var s = SELO[m.veredito] || SELO.sem_rota;
        var selo = '<span class="tag" style="background:' + s.fundo + ";color:" +
          s.cor + '">' + s.texto + "</span>";
        var preco = m.custo_min > 0 ? "R$ " + fmt(m.custo_min, 2) + "/min"
          : (m.custo_km > 0 ? "R$ " + fmt(m.custo_km, 2) + "/km" : "—");
        if (m.custo_fixo > 0) preco += " + R$ " + fmt(m.custo_fixo, 2) + " fixo";
        linhas += "<tr><td class='esq'><span class='bolinha' style='background:" +
          m.cor + "'></span> <b>" + esc(m.rotulo) + "</b>" +
          (m.eletrico ? ' <span class="eletrico">⚡</span>' : "") + selo +
          "<div class='det-modo'>" + esc(m.nota) + "</div></td>" +
          "<td>" + fmt(m.velocidade, 1) + "</td><td class='esq'>" + preco + "</td>" +
          "<td>" + (m.tempo === undefined ? "—" : fmt(m.tempo, 1)) + "</td>" +
          "<td>" + (m.custo === undefined ? "—" : fmt(m.custo, 2)) + "</td>" +
          "<td>" + (m.co2 === undefined ? "—" : fmt(m.co2, 0)) + "</td>" +
          "<td>" + (m.participacao_pct === undefined ? "—" : fmt(m.participacao_pct, 0) + "%") + "</td>" +
          "<td class='esq'>" + esc(m.motivo) + "</td></tr>";
      });

      $("viabilidade-conteudo").innerHTML =
        '<div class="tabela-rolavel"><table><thead><tr>' +
        "<th class='esq'>Modal</th><th>km/h</th><th class='esq'>Preço</th>" +
        "<th>Tempo (min)</th><th>Custo (R$)</th><th>CO₂ (g)</th>" +
        "<th>% no modal</th><th class='esq'>Por quê</th></tr></thead><tbody>" +
        linhas + "</tbody></table></div>" +
        '<p class="hint" style="margin-top:12px">Limiares do veredito (juízo de produto, ' +
        "não resultado de algoritmo): <b>inviável</b> acima de " +
        fmt(lim.tempo_inviavel, 0) + " min ou R$ " + fmt(lim.custo_inviavel, 2) +
        "; <b>limítrofe</b> acima de " + fmt(lim.tempo_limitrofe, 0) + " min ou R$ " +
        fmt(lim.custo_limitrofe, 2) + ". A coluna <b>% no modal</b> mostra quanto da " +
        "distância foi realmente percorrida nele: valores baixos significam que o resto " +
        "foi caminhada, porque o modal não cobre o corredor inteiro.</p>";
    }).catch(function (e) {
      $("viabilidade-conteudo").innerHTML = '<p class="erro">' + esc(e.message) + "</p>";
    }).finally(function () { carregando(false); });
  }

  // ------------------------------------------------------ efeito das condicoes
  var DIM_ROTULO = { clima: "Clima", transito: "Trânsito", seguranca: "Segurança" };

  function rodarCondicoes() {
    carregando(true);
    api("/api/condicoes?" + query()).then(function (r) {
      var linhas = "";
      var ultimaDim = null;
      r.linhas.forEach(function (c) {
        if (c.dimensao !== ultimaDim) {
          linhas += "<tr class='grupo'><td colspan='9' class='esq'>" +
            DIM_ROTULO[c.dimensao] + "</td></tr>";
          ultimaDim = c.dimensao;
        }
        if (c.erro) {
          linhas += "<tr><td class='esq'>" + esc(c.rotulo) +
            (c.atual ? ' <span class="tag">atual</span>' : "") +
            "</td><td colspan='8' class='esq'>" + esc(c.erro) + "</td></tr>";
          return;
        }
        linhas += "<tr" + (c.atual ? ' class="selecionada"' : "") + ">" +
          "<td class='esq'>" + esc(c.rotulo) +
          (c.atual ? ' <span class="tag">atual</span>' : "") + "</td>" +
          "<td>" + c.grafo.V + "</td><td>" + c.grafo.E + "</td>" +
          "<td class='esq'>" + esc(c.modos_rotulo.join(" + ")) + "</td>" +
          "<td>" + fmt(c.tempo, 1) + "</td><td>" + fmt(c.custo, 2) + "</td>" +
          "<td>" + fmt(c.co2, 0) + "</td><td>" + fmt(c.desconforto, 2) + "</td>" +
          "<td>" + fmt(c.reducao_pct, 1) + "%</td></tr>";
      });
      $("condicoes-conteudo").innerHTML =
        '<div class="tabela-rolavel"><table><thead><tr>' +
        "<th class='esq'>Condição</th><th>|V|</th><th>|E|</th>" +
        "<th class='esq'>Modais da rota ótima</th><th>Tempo (min)</th>" +
        "<th>Custo (R$)</th><th>CO₂ (g)</th><th>Desconf.</th>" +
        "<th>Poda A*</th></tr></thead><tbody>" + linhas + "</tbody></table></div>" +
        '<p class="hint" style="margin-top:12px">Cada linha varia <b>uma</b> dimensão e ' +
        "mantém o resto como você deixou. Sem fronteira de Pareto: aqui interessa a rota " +
        "ótima, e o Martins custaria centenas de milissegundos por linha.</p>";
    }).catch(function (e) {
      $("condicoes-conteudo").innerHTML = '<p class="erro">' + esc(e.message) + "</p>";
    }).finally(function () { carregando(false); });
  }

  // -------------------------------------------------------------- NSGA-II
  function rodarNsga() {
    carregando(true);
    api("/api/nsga2?" + query()).then(function (r) {
      if (r.erro) { $("nsga-conteudo").innerHTML = '<p class="erro">' + esc(r.erro) + "</p>"; return; }
      $("nsga-conteudo").innerHTML = '<div class="cards">' +
        '<div class="card"><div class="t">Martins (exato)</div><div class="n">' +
        r.exato.solucoes + '</div><div class="d">soluções · ' + fmt(r.exato.ms, 1) +
        " ms</div></div>" +
        '<div class="card"><div class="t">NSGA-II (aproximado)</div><div class="n">' +
        r.nsga2.solucoes + '</div><div class="d">soluções · ' + fmt(r.nsga2.ms, 0) +
        " ms · " + r.nsga2.avaliacoes + " avaliações</div></div>" +
        '<div class="card"><div class="t">Cobertura da fronteira</div><div class="n">' +
        fmt(r.cobertura_pct, 1) + '%</div><div class="d">' + r.recuperadas + " de " +
        r.exato.solucoes + " soluções exatas recuperadas</div></div></div>" +
        '<p class="hint" style="margin-top:12px">Nesta escala o método exato é ordens de ' +
        "grandeza mais rápido e retorna a fronteira completa. Isso não desautoriza a " +
        "metaheurística: ela é a escolha da literatura para instâncias em que o número de " +
        "rótulos não dominados explode. A escolha do algoritmo deve seguir o tamanho da " +
        "instância.</p>";
    }).catch(function (e) {
      $("nsga-conteudo").innerHTML = '<p class="erro">' + esc(e.message) + "</p>";
    }).finally(function () { carregando(false); });
  }

  // --------------------------------------------------------------- consulta
  function calcular() {
    carregando(true);
    // As abas sob demanda guardam o resultado da consulta ANTERIOR; deixa-las
    // na tela depois de trocar as opcoes e apresentar dado errado.
    $("nsga-conteudo").innerHTML = "";
    $("condicoes-conteudo").innerHTML = "";
    $("viabilidade-conteudo").innerHTML = "";

    api("/api/rota?" + query()).then(function (r) {
      if (r.erro) {
        $("resumo-bloco").hidden = false;
        $("metricas").innerHTML = '<p class="erro" style="grid-column:1/-1">' +
          esc(r.erro) + "</p>";
        $("passos").innerHTML = "";
        $("tabela-pareto").innerHTML = "";
        $("pareto-grafico").innerHTML = "";
        var pp = document.getElementById("por-perfil");
        if (pp) pp.remove();
        camadaRota.clearLayers();
        return;
      }
      $("grafo-chip").textContent =
        "|V| " + r.grafo.V + " · |E| " + r.grafo.E +
        " · densidade " + fmt(r.grafo.densidade, 2) +
        " · linha reta " + fmt(r.linha_reta_km, 2) + " km";
      renderResumo(r);
      renderPareto(r);
      renderBusca(r);
      renderMetro(r);
    }).catch(function (e) {
      $("resumo-bloco").hidden = false;
      $("metricas").innerHTML = '<p class="erro" style="grid-column:1/-1">' +
        esc(e.message) + "</p>";
    }).finally(function () { carregando(false); });
  }

  // ------------------------------------------------------------------ abas
  var ABAS = ["pareto", "viabilidade", "condicoes", "busca", "metro", "nsga"];

  function ligarAbas() {
    Array.prototype.forEach.call(document.querySelectorAll(".aba"), function (b) {
      b.addEventListener("click", function () {
        Array.prototype.forEach.call(document.querySelectorAll(".aba"), function (o) {
          o.classList.remove("ativa");
        });
        b.classList.add("ativa");
        ABAS.forEach(function (nome) {
          $("aba-" + nome).hidden = nome !== b.getAttribute("data-aba");
        });
      });
    });
  }

  // ------------------------------------------------------------------ init
  function init() {
    iniciarMapa();
    ligarAbas();
    $("calcular").addEventListener("click", calcular);
    $("rodar-nsga").addEventListener("click", rodarNsga);
    $("rodar-viabilidade").addEventListener("click", rodarViabilidade);
    $("rodar-condicoes").addEventListener("click", rodarCondicoes);
    $("inverter").addEventListener("click", function () {
      var o = $("origem").value;
      $("origem").value = $("destino").value;
      $("destino").value = o;
      calcular();
    });
    $("recarga").addEventListener("change", calcular);
    $("acessivel").addEventListener("change", calcular);

    carregando(true);
    api("/api/rede").then(function (r) {
      rede = r;
      preencherControles();
      desenharRede();
      calcular();
    }).catch(function (e) {
      document.body.insertAdjacentHTML("afterbegin",
        '<p class="erro" style="margin:16px 20px">Não foi possível carregar a rede: ' +
        esc(e.message) + "</p>");
      carregando(false);
    });
  }

  document.addEventListener("DOMContentLoaded", init);
})();
