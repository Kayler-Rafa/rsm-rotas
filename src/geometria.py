# -*- coding: utf-8 -*-
"""Geometria e distancia reais dos trechos, do OpenStreetMap via OSRM.

Duas coisas dependem disto:

1. O mapa. Sem geometria, o desenho e uma reta entre dois pontos do modelo, e a
   reta atravessa quarteirao, rio e mar.
2. A distancia. A estimativa anterior era haversine x fator de sinuosidade, o
   que erra feio onde a malha e torta.

A geometria e POR MODAL, nao por trecho. No Alto da Se, descer de carro ate a
Praca do Carmo da 3,5 km por ruas historicas de mao unica; a pe sao 0,9 km pela
ladeira. Guardar um numero so para os dois seria errado nos dois casos.

  carro / carro de app / onibus -> perfil "driving"
  bicicleta / bike eletrica / patinete -> perfil "cycling"
  a pe -> perfil "foot"
  metro -> nenhum: OSRM roteia por via, nao por trilho, e um tracado
           ferroviario falso seria pior que a reta

O servidor publico do OSRM e lento e instavel, entao nada disto acontece durante
uma consulta: o cache e montado uma vez por `python geometria.py` e gravado em
dados/geometria.json. Sem o arquivo, tudo cai de volta na reta e na estimativa -
o app funciona, so fica mais feio e menos preciso.
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from typing import Dict, List, Optional, Tuple

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ARQUIVO = os.path.join(RAIZ, "dados", "geometria.json")
ARQUIVO_MATRIZ = os.path.join(RAIZ, "dados", "matriz_carro.json")

OSRM_TABELA = ("https://router.project-osrm.org/table/v1/driving/%s"
               "?annotations=duration,distance")

OSRM = ("https://router.project-osrm.org/route/v1/%s/"
        "%.6f,%.6f;%.6f,%.6f?overview=full&geometries=geojson")

PERFIL_POR_MODO: Dict[str, str] = {
    "carro": "driving", "carro_app": "driving", "onibus": "driving",
    "bike": "cycling", "ebike": "cycling", "patinete": "cycling",
    "pe": "foot",
}

# Se o perfil pedido nao estiver no cache, vale mais usar o parente proximo do
# que cair na reta: calcada e ciclovia seguem as mesmas vias.
SUBSTITUTO = {"foot": ("cycling", "driving"),
              "cycling": ("foot", "driving"),
              "driving": ("cycling", "foot")}

_cache: Dict[str, Dict[str, object]] = {}
_carregado = False


def perfil_de(modo: Optional[str]) -> Optional[str]:
    if modo is None:
        return "driving"
    return PERFIL_POR_MODO.get(modo)


def _chave(u: str, v: str, perfil: str) -> str:
    return "%s|%s|%s" % (u, v, perfil)


def carregar() -> Dict[str, Dict[str, object]]:
    global _carregado
    if _carregado:
        return _cache
    _carregado = True
    try:
        with open(ARQUIVO, encoding="utf-8") as fh:
            _cache.update(json.load(fh))
    except (OSError, ValueError):
        pass                      # sem cache: o chamador usa a reta
    return _cache


def _buscar_cache(u: str, v: str, perfil: str
                  ) -> Tuple[Optional[Dict[str, object]], bool]:
    """Devolve (item, invertido). Tenta o perfil pedido e depois os substitutos."""
    dados = carregar()
    for p in (perfil,) + SUBSTITUTO.get(perfil, ()):
        item = dados.get(_chave(u, v, p))
        if item:
            return item, False
        item = dados.get(_chave(v, u, p))     # o trecho e bidirecional
        if item:
            return item, True
    return None, False


def polilinha(u: str, v: str, fallback: List[List[float]],
              modo: Optional[str] = None) -> List[List[float]]:
    """Tracado [[lat,lon], ...] do trecho u->v no modal dado, ou a reta."""
    perfil = perfil_de(modo)
    if perfil is None:                        # metro: trilho, sem via
        return fallback
    item, invertido = _buscar_cache(u, v, perfil)
    if not item:
        return list(fallback)
    coords = item["coords"]                   # type: ignore[assignment]
    # COPIA, sempre. Devolver a lista do cache deixava o chamador mutar o cache:
    # descrever_rota faz tracado.extend(...) e a lista crescia a cada consulta,
    # ate uma rota acumular 200 mil pontos.
    return list(reversed(coords)) if invertido else list(coords)  # type: ignore[arg-type]


def distancia_real(u: str, v: str, modo: Optional[str] = None) -> Optional[float]:
    """Extensao medida sobre a via para aquele modal, em km, ou None."""
    perfil = perfil_de(modo)
    if perfil is None:
        return None
    item, _ = _buscar_cache(u, v, perfil)
    return float(item["dist_km"]) if item else None   # type: ignore[arg-type]


def item_ativo(u: str, v: str, modo: str) -> Optional[Dict[str, object]]:
    """Rota a pe ou de duas rodas do trecho, SEM cair no perfil de carro.

    Para distancia e para as ruas do trecho, o substituto "driving" seria pior
    que nada: e justamente o contorno de mao unica que se quer evitar.
    """
    perfil = perfil_de(modo)
    if perfil not in ("foot", "cycling"):
        return None
    dados = carregar()
    return dados.get(_chave(u, v, perfil)) or dados.get(_chave(v, u, perfil))


# ------------------------------------------------------ matriz do roteador real
# Distancia e tempo de carro entre TODOS os pares de pontos, numa unica consulta
# ao servico "table" do OSRM. E daqui que saem o tempo das arestas-atalho de
# carro e o tempo do onibus. O tempo e de FLUXO LIVRE; o congestionamento e
# aplicado em rede_rsm (FATOR_CONGESTIONAMENTO).
_matriz: Optional[Dict[str, object]] = None


def _carregar_matriz() -> Dict[str, object]:
    global _matriz
    if _matriz is not None:
        return _matriz
    try:
        with open(ARQUIVO_MATRIZ, encoding="utf-8") as fh:
            dados = json.load(fh)
        dados["idx"] = {pid: i for i, pid in enumerate(dados["ids"])}
        _matriz = dados
    except (OSError, ValueError, KeyError):
        _matriz = {}
    return _matriz


def carro(u: str, v: str) -> Optional[Tuple[float, float]]:
    """(distancia_km, tempo_min em fluxo livre) de carro de u a v, ou None."""
    m = _carregar_matriz()
    if not m:
        return None
    i, j = m["idx"].get(u), m["idx"].get(v)          # type: ignore[union-attr]
    if i is None or j is None:
        return None
    d = m["dist_m"][i][j]                             # type: ignore[index]
    t = m["dur_s"][i][j]                              # type: ignore[index]
    if d is None or t is None:
        return None
    return d / 1000.0, t / 60.0


def construir_matriz() -> None:
    from rede_rsm import PONTOS
    coords = ";".join("%.6f,%.6f" % (p.lon, p.lat) for p in PONTOS)
    with urllib.request.urlopen(OSRM_TABELA % coords, timeout=60) as resposta:
        dados = json.load(resposta)
    if dados.get("code") != "Ok":
        raise RuntimeError("OSRM table: %s" % dados.get("code"))
    os.makedirs(os.path.dirname(ARQUIVO_MATRIZ), exist_ok=True)
    with open(ARQUIVO_MATRIZ, "w", encoding="utf-8") as fh:
        json.dump({"ids": [p.id for p in PONTOS],
                   "dur_s": dados["durations"], "dist_m": dados["distances"],
                   "fonte": "OSRM table, perfil driving, fluxo livre",
                   "gerado_em": time.strftime("%Y-%m-%d %H:%M")}, fh)
    global _matriz
    _matriz = None
    print("matriz %dx%d gravada em %s" % (len(PONTOS), len(PONTOS), ARQUIVO_MATRIZ))


def garantir(u: str, v: str, timeout: int = 12) -> bool:
    """Garante o tracado de carro u->v no cache, buscando ao vivo se faltar.

    Usado so para as rotas que de fato vao para a tela (os cards), nunca para
    toda a fronteira de Pareto. Grava no arquivo para a proxima vez.
    """
    dados = carregar()
    if _chave(u, v, "driving") in dados:
        return True
    from rede_rsm import PONTO_POR_ID
    pu, pv = PONTO_POR_ID[u], PONTO_POR_ID[v]
    item = _consultar("driving", (pu.lat, pu.lon), (pv.lat, pv.lon), tentativas=1,
                      timeout=timeout)
    if not item:
        return False
    dados[_chave(u, v, "driving")] = item
    try:
        with open(ARQUIVO, "w", encoding="utf-8") as fh:
            json.dump(dados, fh, ensure_ascii=False)
    except OSError:
        pass
    return True


# --------------------------------------------------------------- construcao
def _consultar(perfil: str, a: Tuple[float, float], b: Tuple[float, float],
               tentativas: int = 4, timeout: int = 30) -> Optional[Dict[str, object]]:
    url = OSRM % (perfil, a[1], a[0], b[1], b[0])
    for n in range(tentativas):
        try:
            with urllib.request.urlopen(url, timeout=timeout) as resposta:
                dados = json.load(resposta)
            rota = (dados.get("routes") or [None])[0]
            if not rota:
                return None
            return {"dist_km": round(rota["distance"] / 1000.0, 3),
                    "coords": [[c[1], c[0]] for c in rota["geometry"]["coordinates"]],
                    "perfil": perfil}
        except (urllib.error.URLError, OSError, ValueError, KeyError) as erro:
            if n == tentativas - 1:
                print("        falhou (%s)" % type(erro).__name__)
                return None
            time.sleep(2.5 * (n + 1))
    return None


def construir_cache(forcar: bool = False) -> None:
    """Baixa o tracado de carro dos trechos e dos atalhos mais usados.

    O servidor publico do OSRM so hospeda o perfil de carro (medido: /foot/ e
    /cycling/ devolvem roteamento de automovel), entao so "driving" e baixado.

    Roda uma vez, fora do caminho do usuario. Grava a cada item e pula o que ja
    tem. NAO rode duas builds ao mesmo tempo: cada processo regrava o arquivo
    inteiro, e o ultimo a gravar vence.
    """
    from rede_rsm import PONTOS, RECARGAS, TIPOS_COM_ESTACIONAMENTO, TRECHOS

    os.makedirs(os.path.dirname(ARQUIVO), exist_ok=True)
    dados = dict(carregar())

    pares = []
    for t in TRECHOS:
        if "metro" not in t.modos:
            pares.append((t.u, t.v))
    estacoes = [p.id for p in PONTOS if p.tipo in TIPOS_COM_ESTACIONAMENTO]
    eletro = [r.ponto for r in RECARGAS]
    for o, d in (("se_olinda", "igreja_piedade"), ("igreja_piedade", "se_olinda")):
        pares.append((o, d))
        for x in set(estacoes) | set(eletro):
            pares += [(o, x), (x, d)]
    tarefas = []
    for u, v in pares:
        if (u != v and (forcar or _chave(u, v, "driving") not in dados)
                and (u, v) not in tarefas):
            tarefas.append((u, v))

    from rede_rsm import PONTO_POR_ID
    print("%d tracados a baixar (%d ja no cache)" % (len(tarefas), len(dados)))
    for i, (u, v) in enumerate(tarefas, 1):
        pu, pv = PONTO_POR_ID[u], PONTO_POR_ID[v]
        print("[%3d/%3d] %-16s -> %-16s" % (i, len(tarefas), u, v), flush=True)
        item = _consultar("driving", (pu.lat, pu.lon), (pv.lat, pv.lon))
        if item:
            dados[_chave(u, v, "driving")] = item
            with open(ARQUIVO, "w", encoding="utf-8") as fh:
                json.dump(dados, fh, ensure_ascii=False)
        time.sleep(0.5)
    print("%d entradas no cache" % len(dados))


# --------------------------------------------------- a pe e de bicicleta, reais
# O OSRM publico so tem carro, mas o FOSSGIS (mantenedores alemaes do OSM) roda
# OSRM com os perfis de pedestre e de bicicleta sobre o mesmo mapa.
#
# Por que isso importa: a malha de carro embute contorno de mao unica. De Pina a
# Ponte Paulo Guerra sao 3,48 km de carro e 0,26 km a pe ou de bicicleta.
#
# Bicicleta: o perfil "bike" do OSRM ja aceita a contramao, mas como "empurrando"
# (6 km/h), entao muitas vezes prefere pedalar um contorno. Na pratica quem pedala
# no Recife nao contorna quarteirao por mao unica. A bicicleta fica com o MENOR
# caminho entre: perfil bike na ida, perfil bike na volta (invertido) e perfil a
# pe (que ignora mao unica). O tempo continua vindo da velocidade do modal.
FOSSGIS = ("https://routing.openstreetmap.de/routed-%s/route/v1/driving/"
           "%.6f,%.6f;%.6f,%.6f?overview=full&geometries=geojson&steps=true")
UA = {"User-Agent": "RSM-MVP/0.1 (rotas sustentaveis multimodais, uso academico)"}


def _consultar_fossgis(servico: str, a: Tuple[float, float], b: Tuple[float, float],
                       tentativas: int = 4) -> Optional[Dict[str, object]]:
    url = FOSSGIS % (servico, a[1], a[0], b[1], b[0])
    for n in range(tentativas):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=30) as resposta:
                dados = json.load(resposta)
            rota = (dados.get("routes") or [None])[0]
            if not rota:
                return None
            km: Dict[str, float] = {}
            for passo in rota["legs"][0]["steps"]:
                nome = (passo.get("name") or "").strip()
                if nome and passo["distance"] > 0:
                    km[nome] = km.get(nome, 0.0) + passo["distance"] / 1000.0
            return {"dist_km": round(rota["distance"] / 1000.0, 3),
                    "coords": [[c[1], c[0]] for c in rota["geometry"]["coordinates"]],
                    "vias": [[n, round(k, 3)] for n, k in
                             sorted(km.items(), key=lambda x: -x[1])]}
        except (urllib.error.URLError, OSError, ValueError, KeyError, IndexError) as erro:
            if n == tentativas - 1:
                print("        falhou (%s)" % type(erro).__name__)
                return None
            time.sleep(2.5 * (n + 1))
    return None


def _invertido(item: Dict[str, object]) -> Dict[str, object]:
    novo = dict(item)
    novo["coords"] = list(reversed(item["coords"]))   # type: ignore[arg-type]
    return novo


def construir_ativos(forcar: bool = False) -> None:
    """Baixa rota a pe e de bicicleta de cada trecho (FOSSGIS) para o cache."""
    from rede_rsm import MODOS_DUAS_RODAS, PONTO_POR_ID, TRECHOS

    dados = dict(carregar())
    trechos = [t for t in TRECHOS if "metro" not in t.modos
               and ("pe" in t.modos or set(t.modos) & MODOS_DUAS_RODAS)]
    print("%d trechos a pe/de bicicleta" % len(trechos))
    for i, t in enumerate(trechos, 1):
        if not forcar and _chave(t.u, t.v, "foot") in dados \
                and _chave(t.u, t.v, "cycling") in dados:
            continue
        pu, pv = PONTO_POR_ID[t.u], PONTO_POR_ID[t.v]
        a, b = (pu.lat, pu.lon), (pv.lat, pv.lon)
        pe = _consultar_fossgis("foot", a, b)
        time.sleep(0.4)
        ida = _consultar_fossgis("bike", a, b)
        time.sleep(0.4)
        volta = _consultar_fossgis("bike", b, a)
        time.sleep(0.4)
        # Os perfis a pe e de bicicleta do OSRM excluem highway=trunk (via
        # expressa). No Recife essa classe inclui avenidas urbanas com calcada e
        # ciclovia - Agamenon, Av. Sul, Mascarenhas de Moraes - e o perfil a pe
        # dava 5,4 km de Olinda a Cruz Cabuga contra 2,4 km pela Agamenon. Se o
        # caminho do carro, em qualquer sentido, for mais curto, ele vale. As ruas
        # desse caminho ficam em vias=None: a seguranca usa as do carro.
        pelo_carro = []
        if dados.get(_chave(t.u, t.v, "driving")):
            pelo_carro.append(dict(dados[_chave(t.u, t.v, "driving")], vias=None,
                                   fonte="OSRM carro (via expressa com calcada)"))
        if dados.get(_chave(t.v, t.u, "driving")):
            pelo_carro.append(dict(_invertido(dados[_chave(t.v, t.u, "driving")]), vias=None,
                                   fonte="OSRM carro, sentido oposto (via expressa com calcada)"))
        opcoes_pe = ([dict(pe, fonte="FOSSGIS routed-foot")] if pe else []) + pelo_carro
        if opcoes_pe:
            dados[_chave(t.u, t.v, "foot")] = dict(
                min(opcoes_pe, key=lambda c: float(c["dist_km"])), perfil="foot")
        candidatos = list(pelo_carro)
        if ida:
            candidatos.append(dict(ida, fonte="FOSSGIS routed-bike"))
        if volta:
            candidatos.append(dict(_invertido(volta),
                                   fonte="FOSSGIS routed-bike, sentido oposto"))
        if pe:
            candidatos.append(dict(pe, fonte="FOSSGIS routed-foot (sem mao unica)"))
        if candidatos:
            melhor = min(candidatos, key=lambda c: float(c["dist_km"]))
            dados[_chave(t.u, t.v, "cycling")] = dict(melhor, perfil="cycling")
        carro_km = (carro(t.u, t.v) or (None,))[0]
        print("[%2d/%2d] %-16s - %-16s carro %s  a pe %s  bike %s (%s)" % (
            i, len(trechos), t.u, t.v,
            "%.2f" % carro_km if carro_km else "-",
            dados.get(_chave(t.u, t.v, "foot"), {}).get("dist_km", "-"),
            dados.get(_chave(t.u, t.v, "cycling"), {}).get("dist_km", "-"),
            dados.get(_chave(t.u, t.v, "cycling"), {}).get("fonte", "")), flush=True)
        with open(ARQUIVO, "w", encoding="utf-8") as fh:
            json.dump(dados, fh, ensure_ascii=False)
    _cache.clear()
    _cache.update(dados)


if __name__ == "__main__":
    if "--so-ativos" not in sys.argv:
        construir_matriz()
        construir_cache(forcar="--forcar" in sys.argv)
    construir_ativos(forcar="--forcar" in sys.argv)
