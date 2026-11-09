# -*- coding: utf-8 -*-
"""Motor de consulta do RSM: junta grafo + algoritmos e serializa para a API web."""
from __future__ import annotations

import time
from typing import Dict, List, Optional, Sequence, Tuple

import algoritmos as alg
import geometria
from rede_rsm import (
    CLIMAS, CUSTO_ESTACIONAMENTO, FATOR_CARRO_G_KM, MODOS, MODO_RECARREGAVEL,
    OPCOES_PADRAO, PERFIS, PONTOS, PONTO_POR_ID, RECARGAS, RECARGA_POR_PONTO, SEGURANCAS,
    TARIFA_SEI, TRANSITOS, TRECHOS, Aresta, GrafoMultimodal, No, Opcoes,
    VetorCusto, cenario_de, construir_grafo, distancia_trecho, haversine_km,
    nos_do_ponto, propriedades, trecho_acessivel,
)

Pesos = Tuple[float, float, float, float]


# ---------------------------------------------------------------- descricao
def _coords(ponto_id: str) -> List[float]:
    p = PONTO_POR_ID[ponto_id]
    return [p.lat, p.lon]


def _coord_recarga(ponto_id: str) -> List[float]:
    """Onde desenhar a parada: no eletroposto real, se houver; senao no ponto."""
    r = RECARGA_POR_PONTO.get(ponto_id)
    if r is not None and r.lat is not None and r.lon is not None:
        return [r.lat, r.lon]
    return _coords(ponto_id)


def descrever_rota(g: GrafoMultimodal, caminho: List[No]) -> Dict[str, object]:
    """Agrupa arestas consecutivas do mesmo modo em segmentos legiveis."""
    segmentos: List[Dict[str, object]] = []
    total = [0.0, 0.0, 0.0, 0.0]
    dist_total = 0.0
    transferencias = 0
    recargas = 0

    atual: Optional[Dict[str, object]] = None
    for u, v in zip(caminho, caminho[1:]):
        a = g.aresta_entre(u, v)
        if a is None:
            continue
        for i, x in enumerate(a.vetor):
            total[i] += x

        if a.tipo == "recarga":
            if atual is not None:
                segmentos.append(atual)
                atual = None
            recargas += 1
            segmentos.append({
                "tipo": "recarga",
                "ponto": u[0],
                "ponto_nome": PONTO_POR_ID[u[0]].nome,
                "local": a.infra,
                "rotulo": a.rotulo,
                "tempo": round(a.tempo, 2),
                "custo": round(a.custo, 2),
                "coord": _coord_recarga(u[0]),
            })
            continue

        if a.tipo == "transferencia":
            if atual is not None:
                segmentos.append(atual)
                atual = None
            transferencias += 1
            segmentos.append({
                "tipo": "transferencia",
                "de": u[1],
                "para": v[1],
                "de_rotulo": MODOS[u[1]].rotulo,
                "para_rotulo": MODOS[v[1]].rotulo,
                "ponto": u[0],
                "ponto_nome": PONTO_POR_ID[u[0]].nome,
                "tempo": round(a.tempo, 2),
                "custo": round(a.custo, 2),
                "coord": _coords(u[0]),
            })
            continue

        dist_total += a.dist_km
        modo = u[1]
        if atual is not None and atual["modo"] == modo:
            atual["dist_km"] = round(float(atual["dist_km"]) + a.dist_km, 2)
            atual["tempo"] = round(float(atual["tempo"]) + a.tempo, 2)
            atual["custo"] = round(float(atual["custo"]) + a.custo, 2)
            atual["co2"] = round(float(atual["co2"]) + a.co2, 2)
            atual["pontos"].append(v[0])            # type: ignore[union-attr]
            atual["coords"].append(_coords(v[0]))   # type: ignore[union-attr]
            atual["tracado"].extend(                # type: ignore[union-attr]
                geometria.polilinha(u[0], v[0],
                                    [_coords(u[0]), _coords(v[0])], modo))
            infras = atual["infra"]                 # type: ignore[assignment]
            if a.infra and a.infra not in infras:   # type: ignore[operator]
                infras.append(a.infra)              # type: ignore[union-attr]
        else:
            if atual is not None:
                segmentos.append(atual)
            atual = {
                "tipo": "deslocamento",
                "modo": modo,
                "modo_rotulo": MODOS[modo].rotulo,
                "cor": MODOS[modo].cor,
                "dist_km": round(a.dist_km, 2),
                "tempo": round(a.tempo, 2),
                "custo": round(a.custo, 2),
                "co2": round(a.co2, 2),
                "pontos": [u[0], v[0]],
                "coords": [_coords(u[0]), _coords(v[0])],
                # tracado real da via, para o mapa nao desenhar uma reta por
                # cima de quarteirao e mar; cai na reta se nao houver cache
                "tracado": geometria.polilinha(
                    u[0], v[0], [_coords(u[0]), _coords(v[0])], modo),
                "infra": [a.infra] if a.infra else [],
            }
    if atual is not None:
        segmentos.append(atual)

    modos_usados: List[str] = []
    for s in segmentos:
        if s["tipo"] == "deslocamento" and s["modo"] not in modos_usados:
            modos_usados.append(str(s["modo"]))

    co2_carro = dist_total * FATOR_CARRO_G_KM
    return {
        "tempo": round(total[0], 1),
        "custo": round(total[1], 2),
        "co2": round(total[2], 1),
        "desconforto": round(total[3], 2),
        "dist_km": round(dist_total, 2),
        "transferencias": transferencias,
        "recargas": recargas,
        "modos": modos_usados,
        "modos_rotulo": [MODOS[m].rotulo for m in modos_usados],
        "co2_evitado": round(max(0.0, co2_carro - total[2]), 1),
        "segmentos": segmentos,
        "vertices": len(caminho),
    }


def _vazio() -> Dict[str, object]:
    return {"tempo": None, "custo": None, "co2": None, "desconforto": None,
            "dist_km": None, "transferencias": 0, "recargas": 0,
            "modos": [], "modos_rotulo": [],
            "co2_evitado": None, "segmentos": [], "vertices": 0}


def nos_destino(g: GrafoMultimodal, destino_id: str,
                exigir_recarga: bool = False) -> List[No]:
    """Nos que encerram a viagem: sempre a pe.

    Uma viagem termina com a pessoa em pe no destino, nao sentada dentro do
    veiculo. Sem isso o Dijkstra pode encerrar no no do carro e a rota nunca
    paga o desembarque - nem o tempo de estacionar, nem a vaga.

    Com exigir_recarga, so valem os nos com o bit R=1: a parada no eletroposto
    deixa de ser uma sugestao e passa a ser condicao de chegada, resolvida pela
    propria busca em vez de por pos-processamento.
    """
    return [n for n in g.adj
            if n[0] == destino_id and n[1] == "pe"
            and (n[3] == 1 if exigir_recarga else True)]


# ------------------------------------------------------- expansoes por ponto
def _expansoes_por_ponto(expandidos: Sequence[No], g: GrafoMultimodal) -> Dict[str, Dict[str, int]]:
    total_por_ponto: Dict[str, int] = {}
    for n in g.adj:
        total_por_ponto[n[0]] = total_por_ponto.get(n[0], 0) + 1
    exp: Dict[str, int] = {}
    for n in expandidos:
        exp[n[0]] = exp.get(n[0], 0) + 1
    return {pid: {"expandidos": exp.get(pid, 0), "total": tot}
            for pid, tot in total_por_ponto.items()}


# ---------------------------------------------- rota obrigada a usar um modo
def rota_obrigando_modo(g: GrafoMultimodal, origem: No, destino_id: str,
                        pesos: Pesos, modo: str,
                        exigir_recarga: bool = False) -> Optional[List[No]]:
    """Melhor rota que usa ao menos uma aresta de deslocamento no modo dado.

    Resolvido exatamente sobre o grafo-produto G x {0,1}, onde o bit registra
    se o modo obrigatorio ja foi utilizado. Dobra |V| e preserva O(E log V).
    """
    import heapq
    import itertools

    inicio = (origem, 0)
    dist: Dict[Tuple[No, int], float] = {inicio: 0.0}
    pred: Dict[Tuple[No, int], Optional[Tuple[No, int]]] = {inicio: None}
    visto: Dict[Tuple[No, int], bool] = {}
    cont = itertools.count(1)
    fila = [(0.0, 0, inicio)]

    while fila:
        d, _, estado = heapq.heappop(fila)
        if visto.get(estado):
            continue
        visto[estado] = True
        no_atual, flag = estado[0], estado[1]
        if (no_atual[0] == destino_id and no_atual[1] == "pe" and flag == 1
                and (no_atual[3] == 1 if exigir_recarga else True)):
            caminho: List[No] = []
            atual: Optional[Tuple[No, int]] = estado
            while atual is not None:
                caminho.append(atual[0])
                atual = pred.get(atual)
            return list(reversed(caminho))
        for a in g.vizinhos(estado[0]):
            novo_flag = flag
            if a.tipo == "deslocamento" and estado[0][1] == modo:
                novo_flag = 1
            prox = (a.destino, novo_flag)
            nova = d + alg.escalarizar(a.vetor, pesos)
            if nova < dist.get(prox, alg.INF):
                dist[prox] = nova
                pred[prox] = estado
                heapq.heappush(fila, (nova, next(cont), prox))
    return None


def _motivo_sem_rota(op: Opcoes) -> str:
    """Mensagem util no lugar de "nao ha rota".

    O usuario escolheu as restricoes; a interface deve dizer QUAL delas fechou
    o grafo, para que ele saiba o que afrouxar.
    """
    causas: List[str] = []
    if op.seguranca != "indiferente":
        causas.append("a exigencia de seguranca (%s) removeu trechos necessarios"
                      % SEGURANCAS[op.seguranca]["rotulo"])
    if op.acessivel:
        causas.append("a exigencia de acessibilidade removeu trechos necessarios")
    if op.recarga_efetiva:
        causas.append("a parada obrigatoria em eletroposto nao e alcancavel de carro "
                      "ao longo desta rota")
    # So culpa os modais desligados quando nenhuma restricao explicita explica o
    # corte - senao o diagnostico vira chute e confunde mais do que ajuda.
    faltando = {"metro", "onibus", "carro", "carro_app", "bike"} - set(op.modos)
    if faltando and not causas:
        causas.append("os modais desligados (%s) eram os unicos que cobriam algum "
                      "trecho do percurso" % ", ".join(sorted(faltando)))
    if not causas:
        return "Nao existe caminho entre origem e destino com estas opcoes."
    return ("Nao existe rota com estas opcoes. Causa provavel: "
            + "; ".join(causas) + ".")


# ----------------------------------------------------------- consulta principal
def _resumo_opcoes(op: Opcoes) -> Dict[str, object]:
    return {
        "modos": sorted(op.modos),
        "clima": op.clima,
        "clima_rotulo": CLIMAS[op.clima]["rotulo"],
        "transito": op.transito,
        "transito_rotulo": TRANSITOS[op.transito]["rotulo"],
        "seguranca": op.seguranca,
        "seguranca_rotulo": SEGURANCAS[op.seguranca]["rotulo"],
        "acessivel": op.acessivel,
        "recarga": op.recarga,
        "recarga_efetiva": op.recarga_efetiva,
    }


def consultar(origem_id: str, destino_id: str, opcoes: Optional[Opcoes] = None,
              perfil_id: str = "mais_rapida", com_pareto: bool = True,
              normalizacao: str = "minmax") -> Dict[str, object]:
    op = opcoes or OPCOES_PADRAO
    pesos: Pesos = PERFIS[perfil_id]["pesos"]          # type: ignore[assignment]
    g = construir_grafo(op, origem_id, destino_id)

    origem: No = (origem_id, "pe", 0, 0)
    destinos = nos_destino(g, destino_id, op.recarga_efetiva)
    props = propriedades(g)

    resposta: Dict[str, object] = {
        "origem": origem_id,
        "destino": destino_id,
        "origem_nome": PONTO_POR_ID[origem_id].nome,
        "destino_nome": PONTO_POR_ID[destino_id].nome,
        "opcoes": _resumo_opcoes(op),
        "perfil": {"id": perfil_id, "rotulo": PERFIS[perfil_id]["rotulo"], "pesos": list(pesos)},
        "normalizacao": normalizacao,
        "grafo": props,
        "linha_reta_km": round(haversine_km(PONTO_POR_ID[origem_id],
                                            PONTO_POR_ID[destino_id]), 2),
    }

    if origem not in g.adj or not destinos:
        resposta["erro"] = _motivo_sem_rota(op)
        return resposta

    # --- Dijkstra -----------------------------------------------------------
    t0 = time.perf_counter()
    dist_d, pred_d, exp_d = alg.dijkstra(g, origem, destinos, pesos)
    ms_d = (time.perf_counter() - t0) * 1000
    alvo_d = alg.melhor_destino(dist_d, destinos)

    # --- A* -----------------------------------------------------------------
    h = alg.heuristica_geografica(destino_id, pesos,
                                  alg.velocidade_maxima_reta(g))
    t0 = time.perf_counter()
    dist_a, pred_a, exp_a = alg.a_estrela(g, origem, destinos, pesos, h)
    ms_a = (time.perf_counter() - t0) * 1000
    alvo_a = alg.melhor_destino(dist_a, destinos)

    if alvo_d is None:
        resposta["erro"] = _motivo_sem_rota(op)
        return resposta

    cam_d = alg.reconstruir(pred_d, alvo_d)
    rota_d = descrever_rota(g, cam_d)
    if alvo_a is not None:
        cam_a = alg.reconstruir(pred_a, alvo_a)
        rota_a = descrever_rota(g, cam_a)
    else:
        cam_a, rota_a = [], _vazio()

    reducao = (1 - len(exp_a) / len(exp_d)) * 100 if exp_d else 0.0
    mesma = bool(cam_a) and abs(float(rota_d["tempo"]) - float(rota_a["tempo"])) < 1e-6 \
        and rota_d["modos"] == rota_a["modos"]

    resposta["dijkstra"] = {
        "rota": rota_d, "expandidos": len(exp_d), "ms": round(ms_d, 2),
        "custo_escalarizado": round(dist_d[alvo_d], 6),
    }
    resposta["astar"] = {
        "rota": rota_a, "expandidos": len(exp_a), "ms": round(ms_a, 2),
        "custo_escalarizado": round(dist_a[alvo_a], 6) if alvo_a else None,
    }
    resposta["comparacao"] = {
        "reducao_busca_pct": round(reducao, 1),
        "mesma_rota": mesma,
    }
    resposta["expansoes"] = {
        "dijkstra": _expansoes_por_ponto(exp_d, g),
        "astar": _expansoes_por_ponto(exp_a, g),
    }

    # --- Martins + TOPSIS ---------------------------------------------------
    if com_pareto:
        t0 = time.perf_counter()
        frente, gerados = alg.martins(g, origem, destinos)
        ms_m = (time.perf_counter() - t0) * 1000

        rotas = [descrever_rota(g, c) for _, c in frente]
        idx, escores = alg.topsis(frente, pesos, normalizacao)
        for i, r in enumerate(rotas):
            r["topsis"] = round(escores[i], 4) if i < len(escores) else None
            r["recomendada"] = (i == idx)

        # ranking TOPSIS para todos os perfis, sobre a MESMA fronteira
        por_perfil: Dict[str, object] = {}
        for pid, cfg in PERFIS.items():
            j, esc = alg.topsis(frente, cfg["pesos"], normalizacao)  # type: ignore[arg-type]
            por_perfil[pid] = {
                "rotulo": cfg["rotulo"],
                "indice": j,
                "escore": round(esc[j], 4) if j >= 0 else None,
                "tempo": rotas[j]["tempo"] if j >= 0 else None,
                "custo": rotas[j]["custo"] if j >= 0 else None,
                "co2": rotas[j]["co2"] if j >= 0 else None,
                "co2_evitado": rotas[j]["co2_evitado"] if j >= 0 else None,
                "modos_rotulo": rotas[j]["modos_rotulo"] if j >= 0 else [],
            }

        resposta["pareto"] = {
            "rotas": rotas,
            "rotulos_gerados": gerados,
            "ms": round(ms_m, 2),
            "recomendada": idx,
            "por_perfil": por_perfil,
        }

    # --- contraprova: rota obrigada a usar o metro --------------------------
    cam_metro = rota_obrigando_modo(g, origem, destino_id, pesos, "metro",
                                    op.recarga_efetiva)
    if cam_metro:
        rota_metro = descrever_rota(g, cam_metro)
        t_livre = float(rota_d["tempo"])
        rota_metro["penalidade_pct"] = round(
            (float(rota_metro["tempo"]) / t_livre - 1) * 100, 1) if t_livre else None
        rota_metro["usa_metro_na_otima"] = "metro" in rota_d["modos"]
        resposta["metro_obrigatorio"] = rota_metro

    return resposta


# ----------------------------------------------------------- rede para o mapa
def rede_serializada() -> Dict[str, object]:
    trechos = []
    for t in TRECHOS:
        trechos.append({
            "u": t.u, "v": t.v,
            "modos": list(t.modos),
            "seguranca": t.seguranca,
            "acessivel": trecho_acessivel(t),
            "infra": t.infra,
            "dist_km": round(distancia_trecho(t), 2),
            "coords": [_coords(t.u), _coords(t.v)],
            "tracado": geometria.polilinha(
                t.u, t.v, [_coords(t.u), _coords(t.v)],
                "carro" if "carro" in t.modos else
                ("bike" if "bike" in t.modos else None)),
            "metro": "metro" in t.modos,
        })
    return {
        "pontos": [{"id": p.id, "nome": p.nome, "tipo": p.tipo,
                    "lat": p.lat, "lon": p.lon, "municipio": p.municipio}
                   for p in PONTOS],
        "trechos": trechos,
        "modos": {k: {"rotulo": m.rotulo, "cor": m.cor, "velocidade": m.velocidade,
                      "custo_km": m.custo_km, "custo_min": m.custo_min,
                      "custo_fixo": m.custo_fixo, "co2_km": m.co2_km,
                      "desconforto_km": m.desconforto_km, "eletrico": m.eletrico,
                      "individual": m.individual, "pessoal": m.pessoal,
                      "viabilidade": m.viabilidade}
                  for k, m in MODOS.items()},
        "recargas": [{"id": r.id, "ponto": r.ponto, "nome": r.nome,
                      "tipo": r.tipo, "potencia_kw": r.potencia_kw,
                      "tempo_min": r.tempo_min, "custo": r.custo,
                      "lat": r.lat if r.lat is not None else PONTO_POR_ID[r.ponto].lat,
                      "lon": r.lon if r.lon is not None else PONTO_POR_ID[r.ponto].lon,
                      "desvio_km": r.desvio_km, "gratuito": r.gratuito,
                      "real": r.lat is not None}
                     for r in RECARGAS],
        "climas": [{"id": k, "rotulo": v["rotulo"], "descricao": v["descricao"]}
                   for k, v in CLIMAS.items()],
        "transitos": [{"id": k, "rotulo": v["rotulo"], "descricao": v["descricao"]}
                      for k, v in TRANSITOS.items()],
        "segurancas": [{"id": k, "rotulo": v["rotulo"], "descricao": v["descricao"],
                        "minimo": v["minimo"]}
                       for k, v in SEGURANCAS.items()],
        "perfis": [{"id": k, "rotulo": v["rotulo"], "pesos": list(v["pesos"])}  # type: ignore[arg-type]
                   for k, v in PERFIS.items()],
        "origem_padrao": "se_olinda",
        "destino_padrao": "igreja_piedade",
        "fator_carro_g_km": FATOR_CARRO_G_KM,
        "tarifa_sei": TARIFA_SEI,
        "custo_estacionamento": CUSTO_ESTACIONAMENTO,
        "modo_recarregavel": MODO_RECARREGAVEL,
    }


def nsga2_resultado(origem_id: str, destino_id: str,
                    opcoes: Optional[Opcoes] = None,
                    perfil_id: str = "mais_rapida") -> Dict[str, object]:
    op = opcoes or OPCOES_PADRAO
    pesos: Pesos = PERFIS[perfil_id]["pesos"]          # type: ignore[assignment]
    g = construir_grafo(op, origem_id, destino_id)
    origem: No = (origem_id, "pe", 0, 0)
    destinos = nos_destino(g, destino_id, op.recarga_efetiva)
    if origem not in g.adj or not destinos:
        return {"erro": _motivo_sem_rota(op)}

    t0 = time.perf_counter()
    exata, _ = alg.martins(g, origem, destinos)
    ms_exato = (time.perf_counter() - t0) * 1000

    t0 = time.perf_counter()
    aprox, avaliacoes = alg.nsga2(g, origem, destino_id, modo_destino="pe")
    ms_nsga = (time.perf_counter() - t0) * 1000

    chaves_exatas = {tuple(round(x, 4) for x in v) for v, _ in exata}
    recuperadas = sum(1 for v, _ in aprox
                      if tuple(round(x, 4) for x in v) in chaves_exatas)
    cobertura = (recuperadas / len(exata) * 100) if exata else 0.0

    return {
        "exato": {"solucoes": len(exata), "ms": round(ms_exato, 2),
                  "pontos": [[round(x, 3) for x in v] for v, _ in exata]},
        "nsga2": {"solucoes": len(aprox), "ms": round(ms_nsga, 2),
                  "avaliacoes": avaliacoes,
                  "pontos": [[round(x, 3) for x in v] for v, _ in aprox]},
        "recuperadas": recuperadas,
        "cobertura_pct": round(cobertura, 1),
    }


# ------------------------------------------------------ viabilidade por modal
# Limiares de uma viagem urbana cotidiana neste corredor. Sao juizo de produto,
# nao resultado de algoritmo - por isso ficam explicitos aqui e aparecem na
# interface junto com o veredito.
LIMITE_TEMPO_INVIAVEL = 120.0    # min
LIMITE_TEMPO_LIMITE = 75.0
LIMITE_CUSTO_INVIAVEL = 25.00    # R$
LIMITE_CUSTO_LIMITE = 12.00


def _veredito(tempo: float, custo: float) -> Tuple[str, str]:
    if tempo > LIMITE_TEMPO_INVIAVEL and custo > LIMITE_CUSTO_INVIAVEL:
        return "inviavel", "leva %.0f min e custa R$ %.2f" % (tempo, custo)
    if tempo > LIMITE_TEMPO_INVIAVEL:
        return "inviavel", "leva %.0f min (acima de %.0f min)" % (tempo, LIMITE_TEMPO_INVIAVEL)
    if custo > LIMITE_CUSTO_INVIAVEL:
        return "inviavel", "custa R$ %.2f (acima de R$ %.2f)" % (custo, LIMITE_CUSTO_INVIAVEL)
    if tempo > LIMITE_TEMPO_LIMITE or custo > LIMITE_CUSTO_LIMITE:
        return "limitrofe", "%.0f min e R$ %.2f" % (tempo, custo)
    return "viavel", "%.0f min e R$ %.2f" % (tempo, custo)


def viabilidade_modos(origem_id: str, destino_id: str,
                      opcoes: Optional[Opcoes] = None,
                      perfil_id: str = "mais_rapida") -> Dict[str, object]:
    """Para cada modal, a melhor viagem possivel usando SOMENTE ele mais a pe.

    E o teste que responde "este modal da conta deste par origem-destino?".
    Isolar o modo evita que ele apareca como uma perna de 500 m dentro de uma
    rota mista e pareca viavel por tabela.

    As demais opcoes do usuario (clima, transito, seguranca, acessibilidade)
    sao mantidas: a viabilidade de um modal depende das condicoes.
    """
    base = opcoes or OPCOES_PADRAO
    pesos: Pesos = PERFIS[perfil_id]["pesos"]          # type: ignore[assignment]
    linhas: List[Dict[str, object]] = []

    for mid, modo in MODOS.items():
        item: Dict[str, object] = {
            "id": mid,
            "rotulo": modo.rotulo,
            "cor": modo.cor,
            "eletrico": modo.eletrico,
            "individual": modo.individual,
            "pessoal": modo.pessoal,
            "nota": modo.viabilidade,
            "velocidade": modo.velocidade,
            "custo_km": modo.custo_km,
            "custo_min": modo.custo_min,
            "custo_fixo": modo.custo_fixo,
            "co2_km": modo.co2_km,
            "selecionado": mid in base.modos,
        }

        if mid not in base.modos:
            item.update({"veredito": "desligado",
                         "motivo": "voce nao marcou este modal"})
            linhas.append(item)
            continue

        # so este modal + a pe, mantendo clima, transito, seguranca e acesso
        op = Opcoes(
            modos=frozenset({"pe", mid}),
            clima=base.clima, transito=base.transito,
            seguranca=base.seguranca, acessivel=base.acessivel,
            recarga=False,
        )
        g = construir_grafo(op, origem_id, destino_id)
        origem: No = (origem_id, "pe", 0, 0)
        destinos = nos_destino(g, destino_id)
        if origem not in g.adj or not destinos:
            item.update({"veredito": "sem_rota",
                         "motivo": "origem ou destino fora da camada deste modal"})
            linhas.append(item)
            continue

        dist, pred, _ = alg.dijkstra(g, origem, destinos, pesos)
        alvo = alg.melhor_destino(dist, destinos)
        if alvo is None:
            item.update({"veredito": "sem_rota",
                         "motivo": "nao ha caminho continuo apenas com a pe + este modal"})
            linhas.append(item)
            continue

        rota = descrever_rota(g, alg.reconstruir(pred, alvo))
        km_modo = sum(float(x["dist_km"]) for x in rota["segmentos"]       # type: ignore[index]
                      if x["tipo"] == "deslocamento" and x["modo"] == mid)
        total = float(rota["dist_km"]) or 1.0
        vered, motivo = _veredito(float(rota["tempo"]), float(rota["custo"]))

        item.update({
            "veredito": vered,
            "motivo": motivo,
            "tempo": rota["tempo"],
            "custo": rota["custo"],
            "co2": rota["co2"],
            "co2_evitado": rota["co2_evitado"],
            "dist_km": rota["dist_km"],
            "km_no_modo": round(km_modo, 2),
            "participacao_pct": round(km_modo / total * 100, 1),
            "transferencias": rota["transferencias"],
        })
        linhas.append(item)

    ordem = {"viavel": 0, "limitrofe": 1, "inviavel": 2, "sem_rota": 3, "desligado": 4}
    linhas.sort(key=lambda x: (ordem.get(str(x["veredito"]), 9),
                               x.get("tempo") or 1e9))
    return {
        "opcoes": _resumo_opcoes(base),
        "perfil": perfil_id,
        "modos": linhas,
        "limiares": {
            "tempo_inviavel": LIMITE_TEMPO_INVIAVEL,
            "tempo_limitrofe": LIMITE_TEMPO_LIMITE,
            "custo_inviavel": LIMITE_CUSTO_INVIAVEL,
            "custo_limitrofe": LIMITE_CUSTO_LIMITE,
        },
    }


# As opcoes do app moram em cards.py; reexportadas aqui para quem ja usava
# motor.opcoes_de_viagem (server.py, testes). Import no fim: cards importa motor.
from cards import opcoes_de_viagem  # noqa: E402,F401
