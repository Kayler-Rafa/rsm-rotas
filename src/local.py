# -*- coding: utf-8 -*-
"""Onde a pessoa esta: localizacao (GPS) e busca de endereco.

A rede tem 30 pontos com coordenada conferida no OpenStreetMap (projeto.md,
"nao coloque coordenada de memoria"). Uma posicao qualquer - do GPS ou de um
endereco - NAO vira um vertice novo: o grafo, a matriz de carro do OSRM, os
tracados e a seguranca viaria estao todos pre-calculados por ponto. Em vez
disso a posicao e ligada ao ponto mais proximo por uma caminhada estimada, que
o app mostra a parte ("a pe ate Estacao Recife: 350 m, 5 min").

Busca: Nominatim (OpenStreetMap), limitado a caixa da Regiao Metropolitana do
Recife. Politica de uso do Nominatim: no maximo 1 requisicao por segundo,
User-Agent identificando o app, sem autocompletar - a busca so dispara quando a
pessoa confirma. Por isso ha cache e um intervalo minimo entre consultas.
"""
from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Dict, List, Optional

from rede_rsm import MODOS, PONTOS, SINUOSIDADE_A_PE, VEL_PE_ACESSIVEL, Ponto, haversine_km

NOMINATIM = "https://nominatim.openstreetmap.org/search"
UA = {"User-Agent": "RSM-MVP/1.0 (projeto academico, Faculdade Nova Roma)",
      "Accept-Language": "pt-BR"}
# Caixa da RMR (Olinda ao norte, Jaboatao ao sul): lon_min, lat_max, lon_max, lat_min
CAIXA_RMR = (-35.10, -7.90, -34.80, -8.30)

# Caminhar na cidade nao e linha reta: o mesmo fator de rodeio usado no resto
# do modelo para pe sem rota real.
RODEIO_A_PE = SINUOSIDADE_A_PE
# Acima disto o ponto mais proximo nao e mais "ali do lado": o app avisa que a
# posicao esta fora da area coberta pela rede.
LONGE_KM = 2.5

_cache: Dict[str, List[Dict[str, object]]] = {}
_trava = threading.Lock()
_ultima = [0.0]


def _vel_pe_kmh(acessivel: bool) -> float:
    return VEL_PE_ACESSIVEL if acessivel else MODOS["pe"].velocidade


def caminhada(lat: float, lon: float, p: Ponto, acessivel: bool = False) -> Dict[str, float]:
    alvo = Ponto("_", "", "", lat, lon, "")
    km = haversine_km(alvo, p) * RODEIO_A_PE
    return {"km": round(km, 2), "min": round(km / _vel_pe_kmh(acessivel) * 60.0, 1)}


def proximos(lat: float, lon: float, n: int = 3,
             acessivel: bool = False) -> Dict[str, object]:
    """Os n pontos da rede mais proximos, com a caminhada ate cada um."""
    aqui = Ponto("_", "", "", lat, lon, "")
    ordem = sorted(PONTOS, key=lambda p: haversine_km(aqui, p))[:n]
    itens = []
    for p in ordem:
        c = caminhada(lat, lon, p, acessivel)
        itens.append({"id": p.id, "nome": p.nome, "lat": p.lat, "lon": p.lon,
                      "km": c["km"], "min": c["min"]})
    itens.sort(key=lambda x: x["km"])
    return {"lat": lat, "lon": lon, "pontos": itens,
            "longe": bool(itens) and float(itens[0]["km"]) > LONGE_KM}  # type: ignore[arg-type]


def buscar(q: str, timeout: int = 10) -> List[Dict[str, object]]:
    """Ate 5 enderecos na RMR para o texto, cada um com o ponto mais proximo."""
    q = " ".join((q or "").split())[:120]
    if len(q) < 3:
        return []
    chave = q.lower()
    if chave in _cache:
        return _cache[chave]
    params = {"q": q, "format": "jsonv2", "limit": "5", "countrycodes": "br",
              "viewbox": "%.2f,%.2f,%.2f,%.2f" % CAIXA_RMR, "bounded": "1",
              "addressdetails": "0"}
    url = NOMINATIM + "?" + urllib.parse.urlencode(params)
    with _trava:                                  # 1 requisicao por segundo
        espera = 1.05 - (time.time() - _ultima[0])
        if espera > 0:
            time.sleep(espera)
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA),
                                        timeout=timeout) as r:
                brutos = json.load(r)
        except (urllib.error.URLError, OSError, ValueError):
            _ultima[0] = time.time()
            raise RuntimeError("Busca de endereço indisponível agora. Tente de novo "
                               "ou use a lista de lugares.")
        _ultima[0] = time.time()
    saida: List[Dict[str, object]] = []
    for b in brutos:
        try:
            lat, lon = float(b["lat"]), float(b["lon"])
        except (KeyError, TypeError, ValueError):
            continue
        nome = str(b.get("display_name") or "")
        partes = [x.strip() for x in nome.split(",")]
        curto = ", ".join(partes[:3]) if partes else q
        perto = proximos(lat, lon, 1)
        saida.append({"nome": curto, "completo": nome, "lat": lat, "lon": lon,
                      "ponto": perto["pontos"][0] if perto["pontos"] else None,  # type: ignore[index]
                      "longe": perto["longe"]})
    _cache[chave] = saida
    return saida
