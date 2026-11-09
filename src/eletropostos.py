# -*- coding: utf-8 -*-
"""Eletropostos REAIS do OpenStreetMap para a parada de recarga.

    python src/eletropostos.py          # rebaixa do Overpass e regrava o JSON

Antes eram 7 posicoes plausiveis inventadas (projeto.md, ressalvas). Agora:
  1. amenity=charging_station na caixa da RMR (Overpass) - 20 em nov/2026;
  2. cada um e associado ao ponto da rede mais proximo; so entra se estiver a
     ate RAIO_MAX_KM. Mais longe que isso, "parar no caminho" vira outra viagem;
  3. um eletroposto por ponto (o rapido, se houver; senao o mais proximo);
  4. o DESVIO ate o eletroposto e cobrado: ida e volta de carro, reta x 1,3,
     a 20 km/h urbanos, somado ao tempo da parada. A recarga continua modelada
     no ponto da rede (o grafo nao tem o eletroposto como vertice);
  5. potencia: o OSM do Recife nao traz o tipo de tomada (socket:*). Carregador
     de shopping no Brasil e quase sempre AC tipo 2 de 7-22 kW: vira
     "semirrapido" (22 kW, 50 min). O hub pago da Joy Energy (60 vagas) vira
     "rapido" (DC, 25 min). E estimativa, e o app nao diz o contrario;
  6. preco: fee=no no OSM -> energia gratuita (estacionamento nao incluido);
     sem a tag -> as tarifas estimadas de antes (R$ 22 / R$ 26).

O resultado fica em dados/eletropostos_osm.json, lido por rede_rsm sem importar
este modulo (evita import circular).
"""
from __future__ import annotations

import json
import os
import time
import urllib.parse
import urllib.request

from rede_rsm import PONTOS, Ponto, haversine_km

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ARQUIVO = os.path.join(RAIZ, "dados", "eletropostos_osm.json")
ESPELHOS = ("https://overpass-api.de/api/interpreter",
            "https://overpass.kumi.systems/api/interpreter",
            "https://overpass.private.coffee/api/interpreter")
UA = {"User-Agent": "RSM-MVP/1.0 (projeto academico, Faculdade Nova Roma)"}
CAIXA = (-8.30, -35.10, -7.90, -34.80)       # sul, oeste, norte, leste

RAIO_MAX_KM = 0.6
VEL_DESVIO_KMH = 20.0
RODEIO = 1.3
TIPOS = {
    "rapido":      {"potencia_kw": 50.0, "tempo_min": 25.0, "custo": 26.00},
    "semirrapido": {"potencia_kw": 22.0, "tempo_min": 50.0, "custo": 22.00},
}


def _baixar():
    q = """[out:json][timeout:90];
(node["amenity"="charging_station"](%f,%f,%f,%f);
 way["amenity"="charging_station"](%f,%f,%f,%f););
out center tags;""" % (CAIXA * 2)
    for rodada in range(4):                    # o Overpass publico oscila muito
      for url in ESPELHOS:
        try:
            req = urllib.request.Request(url, data=urllib.parse.urlencode({"data": q}).encode(),
                                         headers=UA)
            with urllib.request.urlopen(req, timeout=120) as r:
                return json.load(r)["elements"], url
        except Exception as erro:                         # noqa: BLE001
            print("  %s falhou (%s)" % (url, erro))
            time.sleep(5 + 10 * rodada)
    raise RuntimeError("Overpass indisponivel em todos os espelhos")


def _tipo(tags):
    texto = json.dumps(tags).lower()
    dc = any(k in texto for k in ("ccs", "chademo", "type2_combo", "dc"))
    hub = tags.get("fee") == "yes" and int(tags.get("capacity", "0") or 0) >= 10
    return "rapido" if dc or hub else "semirrapido"


def construir() -> None:
    elementos, fonte = _baixar()
    print("%d eletropostos no OSM (%s)" % (len(elementos), fonte))
    por_ponto = {}
    for e in elementos:
        t = e.get("tags", {})
        lat = e.get("lat") or e.get("center", {}).get("lat")
        lon = e.get("lon") or e.get("center", {}).get("lon")
        if lat is None or lon is None:
            continue
        aqui = Ponto("_", "", "", lat, lon, "")
        p = min(PONTOS, key=lambda x: haversine_km(aqui, x))
        d = haversine_km(aqui, p)
        nome = t.get("name") or t.get("brand") or t.get("operator") or "Eletroposto"
        if d > RAIO_MAX_KM:
            print("  fora  %-28s %.2f km de %s" % (nome, d, p.nome))
            continue
        tipo = _tipo(t)
        cfg = TIPOS[tipo]
        desvio_min = 2 * d * RODEIO / VEL_DESVIO_KMH * 60.0
        item = {
            "id": "rec_osm_%s" % e["id"], "osm": "%s/%s" % (e["type"], e["id"]),
            "ponto": p.id, "nome": "Eletroposto %s" % nome, "tipo": tipo,
            "potencia_kw": cfg["potencia_kw"],
            "tempo_min": round(cfg["tempo_min"] + desvio_min, 1),
            "desvio_km": round(d, 2), "desvio_min": round(desvio_min, 1),
            "custo": 0.0 if t.get("fee") == "no" else cfg["custo"],
            "gratuito": t.get("fee") == "no",
            "lat": lat, "lon": lon, "vagas": t.get("capacity"),
        }
        atual = por_ponto.get(p.id)
        if (atual is None or (tipo == "rapido" and atual["tipo"] != "rapido")
                or (tipo == atual["tipo"] and d < atual["desvio_km"])):
            por_ponto[p.id] = item
        print("  ok    %-28s %.2f km de %-30s %s" % (nome, d, p.nome, tipo))
    saida = {"fonte": "OpenStreetMap (amenity=charging_station), via Overpass",
             "gerado_em": time.strftime("%Y-%m-%d"),
             "raio_max_km": RAIO_MAX_KM, "total_osm": len(elementos),
             "eletropostos": sorted(por_ponto.values(), key=lambda x: x["ponto"])}
    with open(ARQUIVO, "w", encoding="utf-8") as fh:
        json.dump(saida, fh, ensure_ascii=False, indent=1)
    print("%d eletropostos na rede -> %s" % (len(por_ponto), ARQUIVO))


if __name__ == "__main__":
    construir()
