# -*- coding: utf-8 -*-
"""Seguranca viaria por rua, a partir de dado aberto oficial.

Fonte: CTTU - Autarquia de Transito e Transporte Urbano do Recife, conjunto
"Chamados de Sinistros (Acidentes) de Transito com e sem vitimas 2015 a 2024",
Portal de Dados Abertos do Recife (dados.recife.pe.gov.br). Consultado pela API
do portal (datastore_search); so os AGREGADOS por rua ficam gravados em
dados/seguranca_cttu.json - nenhum registro individual.

O que este dado mede, e o que NAO mede:
  - mede SEGURANCA VIARIA: sinistros com pedestre, com ciclista, com vitima,
    com vitima fatal, por endereco;
  - NAO mede seguranca publica (assalto, roubo). O conjunto de ocorrencias da
    Guarda Municipal existe no catalogo do portal, mas esta publicado sem nenhum
    arquivo; nao ha dado aberto de criminalidade por rua na RMR;
  - cobre SO o Recife. Trechos de Olinda e Jaboatao ficam "sem dado" - o que
    NAO significa "seguro";
  - nao traz coordenada, so o nome da rua: o casamento com os trechos do modelo
    e por nome (ver rede_rsm.Trecho.vias).

Comprimento das ruas (para densidade por km): OpenStreetMap via Overpass,
somando as vias com o mesmo nome dentro do Recife.
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from typing import Dict, List, Optional

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ARQUIVO = os.path.join(RAIZ, "dados", "seguranca_cttu.json")

PORTAL = "https://dados.recife.pe.gov.br/api/3/action/datastore_search"
# recursos do datastore, um por ano (ids do portal)
RECURSOS = {
    2022: "c2281788-2e8c-472c-8812-67c4f85e9272",
    2023: "dbb9165a-7539-4fdd-943a-acffe12df3e0",
    2024: "87ac4237-f5f9-44d2-bcf1-927aaa0a2d31",
}
CAMPOS = "endereco,bairro,tipo,pedestre,ciclista,vitimas,vitimasfatais,hora"
UA = {"User-Agent": "RSM-MVP/1.0 (projeto academico, Faculdade Nova Roma)"}

OVERPASS = "https://overpass-api.de/api/interpreter"
# Classes viarias usadas como referencia para o limiar da cidade: sao as vias
# comparaveis as do corredor (arteriais e coletoras).
CLASSES_REFERENCIA = ("trunk", "primary", "secondary", "tertiary")


# ------------------------------------------------------------ nomes de via
_PREFIXOS = [
    (r"^AVENIDA\b", "AV"), (r"^AV\.", "AV"), (r"^R\.", "RUA"), (r"^RUA\b", "RUA"),
    (r"^TRAVESSA\b", "TV"), (r"^ESTRADA\b", "EST"), (r"^PRACA\b", "PC"),
    (r"^PCA\b", "PC"), (r"^PONTE\b", "PTE"), (r"^VIADUTO\b", "VD"),
]


def normalizar(nome: str) -> str:
    """Nome de via em forma comparavel: maiusculo, sem acento, prefixo curto.

    A CTTU escreve "AV GOVERNADOR AGAMENON MAGALHAES"; o OpenStreetMap,
    "Avenida Governador Agamenon Magalhaes". Os dois viram a mesma chave.
    """
    s = unicodedata.normalize("NFKD", nome or "")
    s = "".join(c for c in s if not unicodedata.combining(c)).upper()
    s = re.sub(r"[^A-Z0-9 .]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    for padrao, troca in _PREFIXOS:
        s = re.sub(padrao, troca, s)
    return re.sub(r"\s+", " ", s.replace(".", " ")).strip()


_TIPOS = ("AV", "RUA", "TV", "EST", "PC", "PRC", "PTE", "VD", "ROD", "AL", "LG")


def nucleo(nome: str) -> str:
    """Nome sem o tipo de via: a CTTU e o OSM nem sempre concordam no tipo.

    A Visconde de Jequitinhonha e "RUA" na CTTU e "Avenida" no OpenStreetMap;
    pelo nome exato, a via mais longa do trecho sul ficava "sem dado".
    """
    partes = normalizar(nome).split(" ", 1)
    if len(partes) == 2 and partes[0] in _TIPOS:
        return partes[1]
    return normalizar(nome)


def _num(v) -> float:
    try:
        return float(str(v).replace(",", "."))
    except (TypeError, ValueError):
        return 0.0


# --------------------------------------------------------------- construcao
def _registros(recurso: str) -> List[Dict[str, object]]:
    saida: List[Dict[str, object]] = []
    offset, lote = 0, 5000
    while True:
        url = "%s?resource_id=%s&fields=%s&limit=%d&offset=%d" % (
            PORTAL, recurso, CAMPOS, lote, offset)
        with urllib.request.urlopen(urllib.request.Request(url, headers=UA),
                                    timeout=90) as r:
            dados = json.load(r)["result"]
        # O portal devolve no maximo 500 registros por pagina, seja qual for o
        # "limit" pedido. Avancar pelo que VEIO, nao pelo que foi pedido - a
        # primeira versao avancava de 5000 em 5000 e pulava 90% dos sinistros.
        saida += dados["records"]
        offset += len(dados["records"])
        if not dados["records"] or offset >= dados["total"]:
            if len(saida) != dados["total"]:
                raise RuntimeError("paginacao incompleta: %d de %d"
                                   % (len(saida), dados["total"]))
            return saida


def _agregar():
    por_via: Dict[str, Dict[str, float]] = {}
    por_nucleo: Dict[str, Dict[str, float]] = {}
    for ano, recurso in RECURSOS.items():
        regs = _registros(recurso)
        print("  CTTU %d: %d sinistros" % (ano, len(regs)))
        for r in regs:
            via = normalizar(str(r.get("endereco") or ""))
            if not via:
                continue
            for tabela, chave in ((por_via, via), (por_nucleo, nucleo(via))):
                a = tabela.setdefault(chave, {"sinistros": 0, "com_vitima": 0,
                                              "pedestre": 0, "ciclista": 0, "fatais": 0})
                a["sinistros"] += 1
                if _num(r.get("vitimas")) > 0:
                    a["com_vitima"] += 1
                if _num(r.get("pedestre")) > 0:
                    a["pedestre"] += 1
                if _num(r.get("ciclista")) > 0:
                    a["ciclista"] += 1
                if _num(r.get("vitimasfatais")) > 0:
                    a["fatais"] += 1
        time.sleep(0.5)
    return por_via, por_nucleo


def _comprimentos_osm():
    """Comprimento (km) e classe de cada via nomeada do Recife, do OSM."""
    q = """[out:json][timeout:180];
area["name"="Recife"]["admin_level"="8"]->.r;
way(area.r)["highway"]["name"];
out tags geom;"""
    elementos = None
    for tentativa in range(4):                       # o Overpass publico da 504 as vezes
        try:
            req = urllib.request.Request(
                OVERPASS, data=urllib.parse.urlencode({"data": q}).encode(), headers=UA)
            with urllib.request.urlopen(req, timeout=240) as r:
                elementos = json.load(r)["elements"]
            break
        except (urllib.error.HTTPError, urllib.error.URLError, OSError) as erro:
            print("  Overpass falhou (%s), tentando de novo..." % erro)
            time.sleep(20 * (tentativa + 1))
    if elementos is None:
        raise RuntimeError("Overpass indisponivel")
    import math

    def dist(a, b):
        la1, lo1, la2, lo2 = map(math.radians, (a["lat"], a["lon"], b["lat"], b["lon"]))
        h = (math.sin((la2 - la1) / 2) ** 2
             + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2)
        return 2 * 6371.0 * math.asin(math.sqrt(h))

    # Cada via do OSM vira um segmento com comprimento, ponto medio, direcao e
    # se e mao unica - o que o calculo de pista dupla precisa.
    def segmento(e):
        geo = e.get("geometry") or []
        if len(geo) < 2:
            return None
        km = sum(dist(a, b) for a, b in zip(geo, geo[1:]))
        meio = geo[len(geo) // 2]
        dy = geo[-1]["lat"] - geo[0]["lat"]
        dx = (geo[-1]["lon"] - geo[0]["lon"]) * math.cos(math.radians(meio["lat"]))
        norma = math.hypot(dx, dy) or 1.0
        return {"km": km, "meio": meio, "dir": (dx / norma, dy / norma),
                "mao_unica": e["tags"].get("oneway") in ("yes", "1", "-1"),
                "classe": e["tags"]["highway"]}

    grupos: Dict[str, List[Dict[str, object]]] = {}
    grupos_nucleo: Dict[str, List[Dict[str, object]]] = {}
    for e in elementos:
        seg = segmento(e)
        if seg is None:
            continue
        via = normalizar(e["tags"]["name"])
        grupos.setdefault(via, []).append(seg)
        grupos_nucleo.setdefault(nucleo(via), []).append(seg)

    # Comprimento da via. Somar tudo conta DUAS vezes a avenida com canteiro
    # central (o OSM desenha uma via por sentido): a Agamenon dava 20 km e a
    # densidade de sinistros caia a metade. A tentativa seguinte - a maior
    # distancia entre dois pontos da via - encurta avenida curva: a Agamenon, que
    # e um arco, virava 5,5 km. O criterio agora e local: um segmento de mao
    # unica conta pela metade se ha, a menos de 80 m, outro segmento de mesmo
    # nome no sentido oposto - ou seja, e uma das duas pistas da mesma avenida.
    # Funciona em reta e em curva, e nao corta ao meio a rua de mao unica de
    # verdade (que nao tem par no sentido oposto).
    def comprimento(segs):
        total = 0.0
        for i, s in enumerate(segs):
            fator = 1.0
            if s["mao_unica"]:
                for j, o in enumerate(segs):
                    if i == j or not o["mao_unica"]:
                        continue
                    oposto = s["dir"][0] * o["dir"][0] + s["dir"][1] * o["dir"][1] < -0.5
                    if oposto and dist(s["meio"], o["meio"]) < 0.08:
                        fator = 0.5
                        break
            total += s["km"] * fator
        return total

    def resumo(grupos_):
        saida: Dict[str, Dict[str, object]] = {}
        for via, segs in grupos_.items():
            saida[via] = {"km": round(comprimento(segs), 3),
                          "soma_km": round(sum(s["km"] for s in segs), 3),
                          "classes": sorted({s["classe"] for s in segs})}
        return saida

    vias, nucleos = resumo(grupos), resumo(grupos_nucleo)
    print("  OSM: %d vias nomeadas no Recife" % len(vias))
    for nome in ("AV GOVERNADOR AGAMENON MAGALHAES", "AV ENGENHEIRO DOMINGOS FERREIRA",
                 "AV BOA VIAGEM", "AV CRUZ CABUGA"):
        if nome in vias:
            print("    %-36s %.2f km (soma das vias: %.2f)"
                  % (nome, vias[nome]["km"], vias[nome]["soma_km"]))
    return vias, nucleos


def _percentil(valores: List[float], p: float) -> float:
    if not valores:
        return 0.0
    v = sorted(valores)
    k = (len(v) - 1) * p
    i = int(k)
    j = min(i + 1, len(v) - 1)
    return v[i] + (v[j] - v[i]) * (k - i)


def _vias_dos_trechos() -> Dict[str, List[List[object]]]:
    """Por quais ruas cada trecho do modelo passa, com quantos km em cada.

    Nao e suposicao: e o caminho que o roteador (OSRM) faz entre os dois
    extremos do trecho, com o nome de cada via nas manobras.
    """
    from rede_rsm import PONTO_POR_ID, TRECHOS
    url = ("https://router.project-osrm.org/route/v1/driving/%.6f,%.6f;%.6f,%.6f"
           "?overview=false&steps=true")
    saida: Dict[str, List[List[object]]] = {}
    for t in TRECHOS:
        if "metro" in t.modos:
            continue
        a, b = PONTO_POR_ID[t.u], PONTO_POR_ID[t.v]
        for tentativa in range(3):
            try:
                with urllib.request.urlopen(
                        urllib.request.Request(url % (a.lon, a.lat, b.lon, b.lat), headers=UA),
                        timeout=30) as r:
                    passos = json.load(r)["routes"][0]["legs"][0]["steps"]
                break
            except Exception:                         # noqa: BLE001
                if tentativa == 2:
                    passos = []
                time.sleep(2.0 * (tentativa + 1))
        km: Dict[str, float] = {}
        original: Dict[str, str] = {}
        for p in passos:
            nome = normalizar(p.get("name") or "")
            if nome and p["distance"] > 0:
                km[nome] = km.get(nome, 0.0) + p["distance"] / 1000.0
                original.setdefault(nome, p["name"])       # com acento, para exibir
        saida["%s|%s" % (t.u, t.v)] = [[n, round(k, 3), original[n]] for n, k in
                                       sorted(km.items(), key=lambda x: -x[1])]
        print("  %-16s - %-16s %s" % (t.u, t.v, ", ".join(
            "%s %.1f" % (x[2][:28], x[1]) for x in saida["%s|%s" % (t.u, t.v)][:3])))
        time.sleep(0.4)
    return saida


def construir() -> None:
    """Agrega os sinistros da CTTU por via e grava dados/seguranca_cttu.json."""
    print("Buscando sinistros na API do Portal de Dados Abertos do Recife...")
    por_via, por_nucleo = _agregar()
    print("Buscando comprimento das vias no OpenStreetMap...")
    osm, osm_nucleo = _comprimentos_osm()
    anterior = carregar().get("trechos")
    if anterior and "--refazer-trechos" not in sys.argv:
        print("Reaproveitando as ruas de cada trecho (--refazer-trechos para rebuscar)")
        trechos = anterior
    else:
        print("Buscando por quais ruas cada trecho passa (OSRM)...")
        trechos = _vias_dos_trechos()

    anos = len(RECURSOS)
    densidades = {"pedestre": [], "ciclista": []}
    for tabela, comprimentos, referencia in ((por_via, osm, True),
                                             (por_nucleo, osm_nucleo, False)):
        for via, a in tabela.items():
            info = comprimentos.get(via)
            if not info:
                continue
            a["km"] = info["km"]
            a["classes"] = info["classes"]
            km = float(info["km"])
            if km < 0.5:
                continue                 # via curta demais: densidade vira ruido
            for tipo in densidades:
                a["%s_km_ano" % tipo] = round(a[tipo] / km / anos, 3)
            # o limiar da cidade usa so nomes exatos, para nao contar duas vezes
            if referencia and km >= 1.0 and set(info["classes"]) & set(CLASSES_REFERENCIA):
                for tipo in densidades:
                    densidades[tipo].append(a[tipo] / km / anos)

    # O limiar e da CIDADE, nao do corredor: uma via e "insegura" para quem
    # anda ou pedala se estiver entre as 10% arteriais do Recife com mais
    # sinistros por km envolvendo aquele tipo de usuario.
    limiar = {t: round(_percentil(v, 0.90), 3) for t, v in densidades.items()}
    # "Atencao" (P75): perto do limiar, a incerteza da medida pesa. A Domingos
    # Ferreira fica a 2% do P90; tratar isso como certeza seria desonesto.
    atencao = {t: round(_percentil(v, 0.75), 3) for t, v in densidades.items()}
    saida = {
        "fonte": "CTTU - Chamados de Sinistros de Transito com e sem vitimas, "
                 "Portal de Dados Abertos do Recife",
        "anos": sorted(RECURSOS),
        "gerado_em": time.strftime("%Y-%m-%d %H:%M"),
        "comprimento": "OpenStreetMap (Overpass), soma das vias de mesmo nome no Recife",
        "limiar_p90_por_km_ano": limiar,
        "atencao_p75_por_km_ano": atencao,
        "vias_de_referencia": {t: len(v) for t, v in densidades.items()},
        "por_via": por_via,
        "por_nucleo": por_nucleo,
        "trechos": trechos,
    }
    os.makedirs(os.path.dirname(ARQUIVO), exist_ok=True)
    with open(ARQUIVO, "w", encoding="utf-8") as fh:
        json.dump(saida, fh, ensure_ascii=False)
    print("%d vias com sinistro; limiar P90 = %s; gravado em %s"
          % (len(por_via), limiar, ARQUIVO))


# -------------------------------------------------------------------- consulta
_dados: Optional[Dict[str, object]] = None


def carregar() -> Dict[str, object]:
    global _dados
    if _dados is None:
        try:
            with open(ARQUIVO, encoding="utf-8") as fh:
                _dados = json.load(fh)
        except (OSError, ValueError):
            _dados = {}
    return _dados


def via(nome: str) -> Optional[Dict[str, object]]:
    d = carregar()
    return (d.get("por_via") or {}).get(normalizar(nome))    # type: ignore[union-attr]


def limiar(tipo: str) -> Optional[float]:
    d = carregar()
    return (d.get("limiar_p90_por_km_ano") or {}).get(tipo)  # type: ignore[union-attr]


def limiar_atencao(tipo: str) -> Optional[float]:
    d = carregar()
    return (d.get("atencao_p75_por_km_ano") or {}).get(tipo)  # type: ignore[union-attr]


# Um trecho so e julgado se ao menos metade da sua extensao tem dado. Menos que
# isso (trecho em Olinda ou Jaboatao, rua sem sinistro registrado com nome
# casavel) e "sem dado" - que NAO quer dizer seguro.
COBERTURA_MINIMA = 0.5

# tipo de usuario do dado da CTTU para cada modo exposto
USUARIO_DO_MODO = {"pe": "pedestre", "bike": "ciclista", "ebike": "ciclista",
                   "patinete": "ciclista"}

# Trechos em que o caminho de quem anda ou pedala NAO e o do carro. O OSRM
# publico so roteia carro, e o carro nao anda no calcadao: para ir de uma ponta a
# outra da orla ele sai pela Av. Domingos Ferreira. Usar esse caminho atribuiria
# a orla os sinistros da Domingos Ferreira - justamente a via perigosa que a
# orla serve para evitar. Nestes trechos a via e declarada; o comprimento vem do
# proprio trecho.
VIAS_A_PE_DECLARADAS = {
    ("pina", "bv_norte"): ["Avenida Boa Viagem"],
    ("bv_norte", "praca_bv"): ["Avenida Boa Viagem"],
    ("praca_bv", "setubal"): ["Avenida Boa Viagem"],
    # metade em Jaboatao (Av. Bernardo Vieira de Melo), onde a CTTU nao cobre
    ("setubal", "piedade_orla"): ["Avenida Boa Viagem", "Avenida Bernardo Vieira de Melo"],
}

_risco_cache: Dict[str, Dict[str, object]] = {}

# Rua curta: a densidade usa ao menos 0,5 km de comprimento. Sem isso, 1 sinistro
# numa rua de 100 m viraria a rua mais perigosa da cidade. Antes, rua curta
# simplesmente nao tinha densidade - e a rota real do pedestre, que anda por rua
# pequena, caia em "sem dado" (a Rua Tobias Barreto, 3 atropelamentos em 0,5 km,
# sumia do calculo do trecho Santo Antonio - Estacao Recife).
KM_MINIMO_DENSIDADE = 0.5


# Poucos eventos nao bastam para bloquear. Com 2 ou 3 sinistros em 3 anos, um a
# mais ou a menos muda o veredito: a Ponte Paulo Guerra (3 com ciclista em 260 m)
# e a Rua Velha (2) cortavam a unica ligacao de bicicleta do centro com Boa
# Viagem. Rua com menos de 5 sinistros daquele tipo de usuario no periodo entra
# no calculo com a densidade limitada logo abaixo do P90: pode dar "atencao",
# nunca "inseguro" sozinha.
MIN_SINISTROS_PARA_BLOQUEAR = 5


def _densidade(a: Dict[str, object], tipo: str, anos: int) -> float:
    return float(a[tipo]) / max(float(a["km"]), KM_MINIMO_DENSIDADE) / anos  # type: ignore[arg-type]


def _densidade_para_veredito(a: Dict[str, object], tipo: str, anos: int) -> float:
    dens = _densidade(a, tipo, anos)
    lim = limiar(tipo)
    if lim and float(a[tipo]) < MIN_SINISTROS_PARA_BLOQUEAR:   # type: ignore[arg-type]
        return min(dens, lim * 0.999)
    return dens


def _vias_do_trecho(u: str, v: str, modo: Optional[str] = None) -> List[List[object]]:
    declaradas = VIAS_A_PE_DECLARADAS.get((u, v)) or VIAS_A_PE_DECLARADAS.get((v, u))
    if declaradas:
        from rede_rsm import PONTO_POR_ID, haversine_km
        km = haversine_km(PONTO_POR_ID[u], PONTO_POR_ID[v]) * 1.05 / len(declaradas)
        return [[normalizar(nome), round(km, 3), nome] for nome in declaradas]
    # As ruas por onde quem anda ou pedala de fato passa: a rota a pe / de
    # bicicleta sem mao unica. Sem ela (ou quando o caminho escolhido e o do
    # carro, vias=None), as ruas da rota de carro.
    if modo:
        import geometria
        item = geometria.item_ativo(u, v, modo)
        if item and item.get("vias"):
            return [[normalizar(str(n)), km, n] for n, km in item["vias"]]  # type: ignore[union-attr]
    trechos = carregar().get("trechos") or {}                 # type: ignore[union-attr]
    return trechos.get("%s|%s" % (u, v)) or trechos.get("%s|%s" % (v, u)) or []


def risco_trecho(u: str, v: str, modo: Optional[str] = None) -> Dict[str, object]:
    """Risco de um trecho do modelo para quem anda e para quem pedala.

    Densidade = media, ponderada pelos km, da densidade de sinistros (por km e
    por ano) de cada rua por onde o trecho passa - no caminho daquele modo.
    Inseguro = densidade no nivel das 10% arteriais mais perigosas do Recife.
    """
    chave = "%s|%s|%s" % (u, v, modo)
    if chave in _risco_cache:
        return _risco_cache[chave]
    d = carregar()
    vias = _vias_do_trecho(u, v, modo)
    por_via = d.get("por_via") or {}                          # type: ignore[union-attr]
    por_nucleo = d.get("por_nucleo") or {}                    # type: ignore[union-attr]
    total = sum(float(item[1]) for item in vias) or 0.0

    saida: Dict[str, object] = {"vias": [], "cobertura": 0.0, "tem_dado": False}
    com_dado = 0.0
    soma = {"pedestre": 0.0, "ciclista": 0.0}
    anos = len(d.get("anos") or []) or 3                      # type: ignore[arg-type]
    for item in vias:
        nome, km = item[0], item[1]
        exibicao = item[2] if len(item) > 2 else nome.title()
        a = por_via.get(nome)
        if not a or not a.get("km"):
            a = por_nucleo.get(nucleo(nome))          # tipo de via divergente
        if not a or not a.get("km"):
            continue                                  # rua fora do Recife ou sem nome casavel
        dens = {t: _densidade(a, t, anos) for t in soma}
        veredito = {t: _densidade_para_veredito(a, t, anos) for t in soma}
        com_dado += float(km)
        for t in soma:
            soma[t] += float(km) * veredito[t]
        saida["vias"].append({                                # type: ignore[union-attr]
            "nome": exibicao, "km_no_trecho": km, "sinistros": a["sinistros"],
            "pedestre": a["pedestre"], "ciclista": a["ciclista"],
            "fatais": a["fatais"], "pedestre_km_ano": round(dens["pedestre"], 3),
            "ciclista_km_ano": round(dens["ciclista"], 3),
            # quanto esta rua pesa no veredito do trecho (km x densidade usada)
            "peso_pedestre": round(float(km) * veredito["pedestre"], 4),
            "peso_ciclista": round(float(km) * veredito["ciclista"], 4),
        })
    if total > 0:
        saida["cobertura"] = round(com_dado / total, 2)
    if total > 0 and com_dado / total >= COBERTURA_MINIMA:
        saida["tem_dado"] = True
        for t in soma:
            dens = soma[t] / com_dado
            lim = limiar(t) or float("inf")
            saida["%s_km_ano" % t] = round(dens, 3)
            saida["inseguro_%s" % t] = dens >= lim
            saida["atencao_%s" % t] = dens >= (limiar_atencao(t) or float("inf"))
    _risco_cache[chave] = saida
    return saida


def inseguro_para(u: str, v: str, modo: str) -> bool:
    usuario = USUARIO_DO_MODO.get(modo)
    if not usuario:
        return False
    return bool(risco_trecho(u, v, modo).get("inseguro_%s" % usuario))


def nivel(u: str, v: str, modo: str) -> str:
    """'inseguro', 'atencao', 'ok' ou 'sem_dado' para um modo exposto num trecho."""
    usuario = USUARIO_DO_MODO.get(modo)
    if not usuario:
        return "nao_se_aplica"
    r = risco_trecho(u, v, modo)
    if not r.get("tem_dado"):
        return "sem_dado"
    if r.get("inseguro_%s" % usuario):
        return "inseguro"
    if r.get("atencao_%s" % usuario):
        return "atencao"
    return "ok"


def fonte() -> Dict[str, object]:
    d = carregar()
    return {"fonte": d.get("fonte"), "anos": d.get("anos"),
            "limiar": d.get("limiar_p90_por_km_ano"),
            "atencao": d.get("atencao_p75_por_km_ano"), "gerado_em": d.get("gerado_em")}


if __name__ == "__main__":
    construir()
    if "--vias" in sys.argv:
        d = carregar()
        for nome in sys.argv[sys.argv.index("--vias") + 1:]:
            print(nome, "->", via(nome))
