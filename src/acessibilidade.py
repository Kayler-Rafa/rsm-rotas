# -*- coding: utf-8 -*-
"""Acessibilidade de cada trecho medida no OpenStreetMap, nao atribuida a mao.

    python src/acessibilidade.py            # usa dados/_barreiras_brutas.json
    python src/acessibilidade.py --baixar   # rebaixa as barreiras do Overpass

Antes, Trecho.acessivel era um proxy: so a Ladeira da Se era False. Agora:

  1. barreiras = vias do OSM com highway=steps (escada) ou com piso que
     cadeira de rodas e andador nao vencem: surface = sett, cobblestone,
     unhewn_cobblestone, unpaved, ground, dirt, sand, gravel, grass;
  2. para cada trecho, a ROTA A PE REAL (geometria.json, u|v|foot) e
     amostrada a cada ~5 m; cada amostra a ate RAIO_M de uma barreira fica
     marcada com aquela via;
  3. so conta o que corre AO LONGO da barreira: sequencias continuas de
     amostras na mesma via com pelo menos MIN_TRECHO_M. Uma rua de
     paralelepipedo que so CRUZA a rota da ~2 x RAIO_M de sequencia e fica de
     fora - sem isso, toda rota do centro cruzaria alguma e seria inacessivel;
  4. veredito: qualquer escada ao longo (>= MIN_TRECHO_M) -> nao acessivel;
     piso irregular somando > MAX_PISO_M -> nao acessivel.

Resultado em dados/acessibilidade_osm.json, lido por rede_rsm (um trecho so
fica MAIS restrito: o que ja era False continua False).

Limite honesto: o OSM do Recife nao marca largura de calcada, rampa nem meio-
fio rebaixado na maior parte das ruas. Ausencia de barreira no mapa nao prova
calcada boa; prova so que nao ha escada nem paralelepipedo mapeados.
"""
from __future__ import annotations

import json
import math
import os
import sys
import time
import urllib.parse
import urllib.request
from typing import Dict, List, Tuple

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BRUTO = os.path.join(RAIZ, "dados", "_barreiras_brutas.json")
ARQUIVO = os.path.join(RAIZ, "dados", "acessibilidade_osm.json")
GEOMETRIA = os.path.join(RAIZ, "dados", "geometria.json")

PISOS_IRREGULARES = ("sett", "cobblestone", "unhewn_cobblestone", "unpaved", "ground",
                     "dirt", "sand", "gravel", "grass")
RAIO_M = 4.0           # a rota do roteador fica EM CIMA da via que usa; paralela fica a 8-10 m
PASSO_M = 5.0          # amostragem da rota
MIN_TRECHO_M = 30.0    # sequencia minima ao longo da mesma via (cruzamento < isso)
MAX_PISO_M = 100.0     # piso irregular tolerado num trecho
CAIXA = (-8.20, -34.96, -7.99, -34.83)
# Vias por onde um carro passa. Na rota de carro, uma barreira fora destas
# classes (escada, trilha, calcada mapeada a parte) esta ao lado, nao no caminho.
VIAS_DE_CARRO = ("motorway", "trunk", "primary", "secondary", "tertiary", "unclassified",
                 "residential", "service", "living_street", "road")
ESPELHOS = ("https://overpass-api.de/api/interpreter",
            "https://overpass.kumi.systems/api/interpreter",
            "https://overpass.private.coffee/api/interpreter")
UA = {"User-Agent": "RSM-MVP/1.0 (projeto academico, Faculdade Nova Roma)"}


def baixar() -> None:
    q = """[out:json][timeout:150];
(way["highway"="steps"](%f,%f,%f,%f);
 way["highway"]["surface"~"^(%s)$"](%f,%f,%f,%f););
out tags geom;""" % (CAIXA + ("|".join(PISOS_IRREGULARES),) + CAIXA)
    for rodada in range(5):
        for url in ESPELHOS:
            try:
                req = urllib.request.Request(url, data=urllib.parse.urlencode({"data": q}).encode(),
                                             headers=UA)
                with urllib.request.urlopen(req, timeout=170) as r:
                    els = json.load(r)["elements"]
                with open(BRUTO, "w", encoding="utf-8") as fh:
                    json.dump(els, fh, ensure_ascii=False)
                print("%d barreiras baixadas (%s)" % (len(els), url))
                return
            except Exception as erro:                     # noqa: BLE001
                print("  %s falhou (%s)" % (url, erro))
                time.sleep(5 + 10 * rodada)
    raise RuntimeError("Overpass indisponivel")


# ------------------------------------------------- geometria plana local (m)
_LAT0 = -8.08
_KX = 111320.0 * math.cos(math.radians(_LAT0))
_KY = 110574.0


def _xy(lat: float, lon: float) -> Tuple[float, float]:
    return lon * _KX, lat * _KY


def _dist_seg(p, a, b) -> float:
    (px, py), (ax, ay), (bx, by) = p, a, b
    dx, dy = bx - ax, by - ay
    n = dx * dx + dy * dy
    t = 0.0 if n == 0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / n))
    return math.hypot(px - ax - t * dx, py - ay - t * dy)


def _classe(tags: Dict[str, str]) -> str:
    return "escada" if tags.get("highway") == "steps" else "piso"


def _indice(barreiras) -> Dict[Tuple[int, int], List[tuple]]:
    """Grade de 50 m -> segmentos de barreira (para nao testar 3 mil vias por amostra)."""
    grade: Dict[Tuple[int, int], List[tuple]] = {}
    for e in barreiras:
        if e.get("tags", {}).get("area") == "yes":
            continue          # praca: o contorno do poligono nao e caminho
        geo = e.get("geometry") or []
        pts = [_xy(g["lat"], g["lon"]) for g in geo if g]
        info = (e["id"], _classe(e.get("tags", {})), e.get("tags", {}).get("name"),
                e.get("tags", {}).get("surface") or e.get("tags", {}).get("highway"),
                e.get("tags", {}).get("highway") in VIAS_DE_CARRO)
        for a, b in zip(pts, pts[1:]):
            x0, x1 = sorted((a[0], b[0]))
            y0, y1 = sorted((a[1], b[1]))
            for gx in range(int((x0 - RAIO_M) // 50), int((x1 + RAIO_M) // 50) + 1):
                for gy in range(int((y0 - RAIO_M) // 50), int((y1 + RAIO_M) // 50) + 1):
                    grade.setdefault((gx, gy), []).append((a, b, info))
    return grade


def _amostras(coords: List[List[float]]) -> List[Tuple[float, float]]:
    pts = [_xy(c[0], c[1]) for c in coords]
    saida = []
    for a, b in zip(pts, pts[1:]):
        d = math.hypot(b[0] - a[0], b[1] - a[1])
        n = max(1, int(d // PASSO_M))
        for k in range(n):
            t = k / n
            saida.append((a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1])))
    if pts:
        saida.append(pts[-1])
    return saida


def medir(coords: List[List[float]], grade, so_vias_de_carro: bool = False) -> Dict[str, object]:
    """Metros de escada e de piso irregular AO LONGO da rota.

    so_vias_de_carro: a rota e de carro, entao so barreiras em vias de carro
    estao de fato no caminho."""
    marcas = []
    for p in _amostras(coords):
        melhor = None
        for a, b, info in grade.get((int(p[0] // 50), int(p[1] // 50)), ()):
            if so_vias_de_carro and not info[4]:
                continue
            d = _dist_seg(p, a, b)
            if d <= RAIO_M and (melhor is None or d < melhor[0]):
                melhor = (d, info)
        marcas.append(melhor[1] if melhor else None)
    # sequencias continuas na mesma via
    total = {"escada": 0.0, "piso": 0.0}
    vias: Dict[str, float] = {}
    i = 0
    while i < len(marcas):
        if marcas[i] is None:
            i += 1
            continue
        j = i
        while j + 1 < len(marcas) and marcas[j + 1] is not None and marcas[j + 1][0] == marcas[i][0]:
            j += 1
        comp = (j - i) * PASSO_M
        if comp >= MIN_TRECHO_M:
            _id, classe, nome, tipo, _carro = marcas[i]
            total[classe] += comp
            chave = "%s (%s)" % (nome or "sem nome", tipo)
            vias[chave] = vias.get(chave, 0.0) + comp
        i = j + 1
    acessivel = total["escada"] == 0.0 and total["piso"] <= MAX_PISO_M
    return {"acessivel": acessivel, "escada_m": round(total["escada"]),
            "piso_m": round(total["piso"]),
            "vias": sorted(([k, round(v)] for k, v in vias.items()), key=lambda x: -x[1])}


def construir() -> None:
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from rede_rsm import TRECHOS
    with open(BRUTO, encoding="utf-8") as fh:
        barreiras = json.load(fh)
    with open(GEOMETRIA, encoding="utf-8") as fh:
        geo = json.load(fh)
    grade = _indice(barreiras)
    saida: Dict[str, object] = {}
    for t in TRECHOS:
        if "pe" not in t.modos:
            continue
        # "Esta rota tem escada" nao e "nao existe caminho acessivel": o
        # roteador a pe as vezes corta por um caminho de grama no canteiro ou
        # pela escada de uma passarela, com a calcada da avenida ao lado. O
        # trecho e acessivel se ALGUM caminho entre as pontas nao tem barreira
        # mapeada: a rota a pe, ou a rota de carro nos dois sentidos (avenida
        # tem calcada). A Ladeira da Se continua inacessivel: ali todo caminho
        # e paralelepipedo.
        candidatos = []
        for chave, rotulo in (("%s|%s|foot" % (t.u, t.v), "a pe"),
                              ("%s|%s|foot" % (t.v, t.u), "a pe"),
                              ("%s|%s|driving" % (t.u, t.v), "pela via (ida)"),
                              ("%s|%s|driving" % (t.v, t.u), "pela via (volta)")):
            item = geo.get(chave)
            if item and item.get("coords"):
                r = medir(item["coords"], grade, so_vias_de_carro=chave.endswith("|driving"))
                r["caminho"] = rotulo
                r["km"] = item.get("dist_km")
                candidatos.append(r)
        if not candidatos:
            continue
        livres = [c for c in candidatos if c["acessivel"]]
        r = dict(min(livres, key=lambda c: float(c["km"] or 0)) if livres
                 else min(candidatos, key=lambda c: c["escada_m"] * 10 + c["piso_m"]))
        r["acessivel"] = bool(livres)
        r["barreira_na_rota_a_pe"] = not candidatos[0]["acessivel"]
        saida["%s|%s" % (t.u, t.v)] = r
        print("%-16s %-16s %-5s %-16s escada %4d m  piso %4d m  %s" % (
            t.u, t.v, "ok" if r["acessivel"] else "NAO", r["caminho"], r["escada_m"],
            r["piso_m"], "; ".join("%s %d m" % (n, m) for n, m in r["vias"][:2])))
    with open(ARQUIVO, "w", encoding="utf-8") as fh:
        json.dump({"fonte": "OpenStreetMap (highway=steps, surface irregular), via Overpass",
                   "criterio": {"raio_m": RAIO_M, "min_trecho_m": MIN_TRECHO_M,
                                "max_piso_m": MAX_PISO_M, "pisos": PISOS_IRREGULARES},
                   "gerado_em": time.strftime("%Y-%m-%d"), "trechos": saida},
                  fh, ensure_ascii=False, indent=1)
    print("gravado em %s" % ARQUIVO)


if __name__ == "__main__":
    if "--baixar" in sys.argv:
        baixar()
    construir()
