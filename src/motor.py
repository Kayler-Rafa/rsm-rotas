# -*- coding: utf-8 -*-
"""Motor de consulta do RSM: junta grafo + algoritmos e serializa para a API web."""
from __future__ import annotations

import time
from typing import Dict, List, Optional, Sequence, Tuple

import algoritmos as alg
import clima as clima_mod
import geometria
import seguranca
from rede_rsm import (
    CLIMAS, CUSTO_ESTACIONAMENTO, FATOR_CARRO_G_KM, MODOS, MODO_RECARREGAVEL,
    OPCOES_PADRAO, PERFIS, PONTOS, PONTO_POR_ID, RECARGAS, SEGURANCAS,
    TARIFA_SEI, TRANSITOS, TRECHOS, Aresta, GrafoMultimodal, No, Opcoes,
    VetorCusto, cenario_de, construir_grafo, distancia_trecho, haversine_km,
    nos_do_ponto, propriedades,
)

Pesos = Tuple[float, float, float, float]


# ---------------------------------------------------------------- descricao
def _coords(ponto_id: str) -> List[float]:
    p = PONTO_POR_ID[ponto_id]
    return [p.lat, p.lon]


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
                "coord": _coords(u[0]),
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
            "acessivel": t.acessivel,
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
                      "lat": PONTO_POR_ID[r.ponto].lat,
                      "lon": PONTO_POR_ID[r.ponto].lon}
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


# =============================================================================
# Opcoes de viagem para o app do usuario (as "cards")
# =============================================================================
# O usuario nao escolhe clima nem transito: essas condicoes sao medidas ou
# estimadas em clima.py. O que ele escolhe e a OPCAO DE VIAGEM, entre as cinco
# que os perfis produzem sobre a mesma fronteira de Pareto.

MODOS_EXPOSTOS_APP = frozenset({"pe", "bike", "ebike", "patinete"})


def _resumo_modal(rota: Dict[str, object]) -> str:
    """Rotulo curto do card: os modais que carregam a viagem.

    A caminhada de acesso aparece em quase toda rota; inclui-la sempre deixaria
    todos os cards com o mesmo nome. So entra se for parte relevante do trajeto.
    """
    total = float(rota["dist_km"]) or 1.0
    km = {}
    for seg in rota["segmentos"]:                      # type: ignore[union-attr]
        if seg["tipo"] == "deslocamento":
            km[seg["modo"]] = km.get(seg["modo"], 0.0) + float(seg["dist_km"])
    relevantes = [m for m in rota["modos"]             # type: ignore[union-attr]
                  if m != "pe" or km.get(m, 0.0) / total >= 0.15]
    if not relevantes:
        relevantes = list(rota["modos"])               # type: ignore[arg-type]
    curto = {"carro": "Carro elétrico", "carro_app": "Carro de app",
             "metro": "Metrô", "onibus": "Ônibus", "bike": "Bicicleta",
             "ebike": "Bike elétrica", "patinete": "Patinete", "pe": "A pé"}
    return " + ".join(curto.get(m, MODOS[m].rotulo) for m in relevantes)


def _km_expostos(rota: Dict[str, object]) -> float:
    return sum(float(s["dist_km"]) for s in rota["segmentos"]   # type: ignore[union-attr]
               if s["tipo"] == "deslocamento" and s["modo"] in MODOS_EXPOSTOS_APP)


def _avisos(rota: Dict[str, object], cond: Dict[str, object]) -> List[Dict[str, str]]:
    """Alertas honestos sobre a rota, dadas as condicoes do momento."""
    avisos: List[Dict[str, str]] = []
    c = cond["clima"]                                   # type: ignore[index]
    t = cond["transito"]                                # type: ignore[index]
    expostos = _km_expostos(rota)
    modos = rota["modos"]                               # type: ignore[assignment]

    if expostos >= 1.0:
        if c["clima"] == "chuva_forte":                 # type: ignore[index]
            avisos.append({"nivel": "alerta", "texto":
                           "Chuva forte agora: %.0f km expostos. Não é a melhor "
                           "hora para pedalar ou caminhar esse trecho."
                           % expostos})
        elif c["clima"] == "chuva_leve":                # type: ignore[index]
            avisos.append({"nivel": "aviso", "texto":
                           "Chuva fraca: %.0f km expostos, leve capa."
                           % expostos})
        elif c.get("calor"):                            # type: ignore[union-attr]
            avisos.append({"nivel": "aviso", "texto":
                           "%.0f °C agora: %.0f km ao sol."
                           % (c["temperatura"], expostos)})   # type: ignore[index]

    if t["transito"] == "congestionado" and (           # type: ignore[index]
            set(modos) & {"onibus", "carro", "carro_app"}):
        avisos.append({"nivel": "aviso", "texto":
                       "Hora de pico: o tempo acima já considera o trânsito."})

    if "onibus" in modos:
        avisos.append({"nivel": "info", "texto":
                       "Sem horários em tempo real na RMR: a espera é uma "
                       "estimativa de 7 min, não a espera real."})

    if "ebike" in modos or "patinete" in modos:
        avisos.append({"nivel": "info", "texto":
                       "Cobrança por minuto; a disponibilidade da frota não é "
                       "consultada em tempo real."})
    return avisos


USUARIO_ROTULO = {"pedestre": ("a pé", "quem anda"), "ciclista": ("de bicicleta", "quem pedala")}


def _seguranca_da_rota(rota: Dict[str, object]) -> Dict[str, object]:
    """Nivel de seguranca viaria de cada trecho a pe ou de duas rodas da rota."""
    trechos: List[Dict[str, object]] = []
    for seg in rota["segmentos"]:                         # type: ignore[union-attr]
        if seg["tipo"] != "deslocamento":
            continue
        modo = seg["modo"]
        usuario = seguranca.USUARIO_DO_MODO.get(modo)
        if not usuario:
            continue
        for a, b in zip(seg["pontos"], seg["pontos"][1:]):
            nivel = seguranca.nivel(a, b, modo)
            risco = seguranca.risco_trecho(a, b, modo)
            # a rua citada e a que mais pesa no veredito, nao a de maior
            # densidade: 50 m de uma rua perigosa nao explicam um trecho de 2 km.
            # Rua com poucos sinistros nao bloqueia sozinha, entao vem depois.
            vias = sorted(risco.get("vias") or [],        # type: ignore[arg-type]
                          key=lambda x: (int(x[usuario]) < seguranca.MIN_SINISTROS_PARA_BLOQUEAR,
                                         -float(x["peso_%s" % usuario])))
            trechos.append({
                "de": a, "para": b, "modo": modo, "usuario": usuario, "nivel": nivel,
                "densidade": risco.get("%s_km_ano" % usuario),
                "via": vias[0]["nome"] if vias else None,
                "sinistros_usuario": vias[0][usuario] if vias else None,
                "fatais": vias[0]["fatais"] if vias else None,
                "cobertura": risco.get("cobertura"),
            })
    return {
        "trechos": trechos,
        "inseguros": [t for t in trechos if t["nivel"] == "inseguro"],
        "atencao": [t for t in trechos if t["nivel"] == "atencao"],
        "sem_dado": sum(1 for t in trechos if t["nivel"] == "sem_dado"),
    }


def _card(perfil_id: str, rota: Dict[str, object],
          cond: Dict[str, object]) -> Dict[str, object]:
    return {
        "perfil": perfil_id,
        "rotulo": PERFIS[perfil_id]["rotulo"],
        "resumo": _resumo_modal(rota),
        "tempo": rota["tempo"],
        "custo": rota["custo"],
        "co2": rota["co2"],
        "co2_evitado": rota["co2_evitado"],
        "dist_km": rota["dist_km"],
        "transferencias": rota["transferencias"],
        "recargas": rota.get("recargas", 0),
        "modos": rota["modos"],
        "modos_rotulo": rota["modos_rotulo"],
        "km_expostos": round(_km_expostos(rota), 1),
        "usa_carro": "carro" in rota["modos"],          # type: ignore[operator]
        "avisos": _avisos(rota, cond),
        "segmentos": rota["segmentos"],
        "seguranca": _seguranca_da_rota(rota),
    }


# Qual componente do vetor de custo cada card promete minimizar.
# tempo = 0, custo = 1, CO2 = 2, desconforto = 3.
OBJETIVO_DO_PERFIL = {
    "mais_rapida": 0,
    "menor_custo": 1,
    "menor_emissao": 2,
    "menos_esforco": 3,
}


def _cards_de(g: GrafoMultimodal, origem: No, destinos: List[No],
              cond: Dict[str, object], normalizacao: str
              ) -> Optional[Dict[str, Dict[str, object]]]:
    """Uma unica fronteira de Pareto; cada card a le de um jeito.

    Os quatro cards extremos pegam o MINIMO do seu objetivo na fronteira, nao o
    TOPSIS. O card diz "mais rapida" ao usuario: ele tem que ser literalmente a
    rota de menor tempo. O TOPSIS com peso 0,70 em tempo nao garante isso -
    ele equilibra, e ja devolveu uma rota 0,5 min mais lenta que o minimo com o
    rotulo de mais rapida. Empate e desfeito pelo custo escalarizado do perfil.

    So "equilibrada" usa TOPSIS, que e exatamente a pergunta que ele responde:
    qual alternativa esta mais proxima do ideal em todos os criterios ao mesmo
    tempo.
    """
    frente, _ = alg.martins(g, origem, destinos)
    if not frente:
        return None
    rotas = [descrever_rota(g, c) for _, c in frente]
    saida: Dict[str, Dict[str, object]] = {}

    for pid, cfg in PERFIS.items():
        obj = OBJETIVO_DO_PERFIL.get(pid)
        if obj is None:
            j, _esc = alg.topsis(frente, cfg["pesos"], normalizacao)  # type: ignore[arg-type]
        else:
            pesos = cfg["pesos"]                       # type: ignore[assignment]
            j = min(range(len(frente)),
                    key=lambda k: (frente[k][0][obj],
                                   alg.escalarizar(frente[k][0], pesos)))
        if j < 0:
            continue
        saida[pid] = _card(pid, rotas[j], cond)
    return saida


# Quantos tracados ausentes uma consulta pode buscar ao vivo. O OSRM publico
# leva de 1 a 8 s por consulta; sem limite, uma origem nunca usada travaria a
# resposta. O que ficar de fora e desenhado em reta e buscado na proxima vez.
MAX_TRACADOS_AO_VIVO = 6


def _completar_tracado(rota: Dict[str, object], orcamento: List[int]) -> None:
    """Troca a reta pelo tracado real nos segmentos de uma rota que vai para a tela.

    So e chamado para os cards - nunca para a fronteira de Pareto inteira, que
    pode ter dezenas de rotas e custaria minutos de consulta ao OSRM.
    """
    for seg in rota["segmentos"]:                       # type: ignore[union-attr]
        if seg["tipo"] != "deslocamento" or seg["modo"] == "metro":
            continue
        pontos = seg["pontos"]
        faltou = False
        for a, b in zip(pontos, pontos[1:]):
            if geometria.distancia_real(a, b, "carro") is None:
                if orcamento[0] <= 0:
                    faltou = True
                    continue
                orcamento[0] -= 1
                if not geometria.garantir(a, b):
                    faltou = True
        if not faltou:
            tracado: List[List[float]] = []
            for a, b in zip(pontos, pontos[1:]):
                tracado.extend(geometria.polilinha(a, b, [_coords(a), _coords(b)],
                                                   seg["modo"]))
            seg["tracado"] = tracado


def _recomendar(cards: List[Dict[str, object]],
                cond: Dict[str, object]) -> Dict[str, str]:
    """Qual card o app sugere, e por que - em uma frase.

    A recomendacao responde as CONDICOES; a escolha continua sendo do usuario.
    """
    if not cards:
        return {"perfil": "", "motivo": ""}
    c = cond["clima"]                                   # type: ignore[index]
    t = cond["transito"]                                # type: ignore[index]
    por_perfil = {str(x["perfil"]): x for x in cards}

    if c["clima"] == "chuva_forte":                     # type: ignore[index]
        melhor = min(cards, key=lambda x: (x["km_expostos"], x["tempo"]))
        return {"perfil": str(melhor["perfil"]),
                "motivo": "Chuva forte agora. Escolhi a opção com menos "
                          "exposição: %.0f km ao relento."
                          % float(melhor["km_expostos"])}

    if c["clima"] == "chuva_leve":                      # type: ignore[index]
        secos = [x for x in cards if float(x["km_expostos"]) <= 2.0]
        if secos:
            melhor = min(secos, key=lambda x: x["tempo"])
            return {"perfil": str(melhor["perfil"]),
                    "motivo": "Está chovendo fraco. Esta opção te deixa quase "
                              "todo o trajeto abrigado."}

    if c.get("calor"):                                  # type: ignore[union-attr]
        frescas = [x for x in cards if float(x["km_expostos"]) <= 2.0]
        if frescas:
            melhor = min(frescas, key=lambda x: x["tempo"])
            return {"perfil": str(melhor["perfil"]),
                    "motivo": "%.0f °C agora. Esta opção evita o sol."
                              % float(c["temperatura"])}      # type: ignore[index]

    if t["transito"] == "congestionado":                # type: ignore[index]
        fora = [x for x in cards
                if not (set(x["modos"]) & {"carro", "carro_app", "onibus"})]
        if fora:
            melhor = min(fora, key=lambda x: x["tempo"])
            return {"perfil": str(melhor["perfil"]),
                    "motivo": "Hora de pico. Esta opção não depende do trânsito."}

    padrao = por_perfil.get("equilibrada") or cards[0]
    return {"perfil": str(padrao["perfil"]),
            "motivo": "Condições normais. Esta equilibra tempo, custo e emissão."}


def _evitados(sem_filtro: Dict[str, Dict[str, object]],
              com_filtro: Dict[str, Dict[str, object]]) -> List[Dict[str, object]]:
    """O que o filtro de seguranca tirou do usuario, e quanto isso custou.

    Para cada perfil, compara a escolha feita SEM o filtro com a escolha feita
    COM ele. So vira aviso se a rota sem filtro de fato passava por via
    insegura para quem anda ou pedala - nao se ela so mudou por outro motivo.
    """
    lim = seguranca.fonte()
    anos = lim.get("anos") or []
    periodo = "%d–%d" % (anos[0], anos[-1]) if anos else ""
    saida: List[Dict[str, object]] = []
    vistos = set()
    for pid, bruto in sem_filtro.items():
        inseguros = bruto["seguranca"]["inseguros"]        # type: ignore[index]
        if not inseguros:
            continue
        seguro = com_filtro.get(pid)
        for t in inseguros:
            chave = (t["modo"], t["via"])
            if chave in vistos:
                continue
            vistos.add(chave)
            como, quem = USUARIO_ROTULO[t["usuario"]]
            if seguro is None:
                consequencia = "Sem essa via, essa opção deixou de existir."
                delta = None
            else:
                # A troca tem de ser dita no criterio do card, nao so no tempo:
                # na prioridade "menor custo" a rota insegura era andar de graca
                # e a segura e de onibus - mais RAPIDA, porem paga. Dizer so
                # "17 min a menos" deixava sem sentido por que ela nao veio antes.
                delta = round(float(seguro["tempo"]) - float(bruto["tempo"]), 1)
                d_custo = float(seguro["custo"]) - float(bruto["custo"])
                d_co2 = float(seguro["co2"]) - float(bruto["co2"])
                partes = []
                if abs(d_custo) >= 0.05:
                    partes.append(("custa +R$ %.2f" % d_custo if d_custo > 0 else
                                   "custa R$ %.2f a menos" % -d_custo).replace(".", ","))
                if pid == "menor_emissao" and abs(d_co2) >= 1:
                    partes.append("emite %+d g de CO₂" % round(d_co2))
                partes.append("leva o mesmo tempo" if abs(delta) < 0.5 else
                              "leva +%d min" % round(delta) if delta > 0 else
                              "leva %d min a menos" % round(-delta))
                consequencia = "A alternativa segura (%s) %s." % (
                    seguro["resumo"], " e ".join(partes))
            texto = ("Não te mandamos %s pela %s: %d sinistros com %s em %s (CTTU), "
                     "entre as 10%% vias mais perigosas do Recife para %s. %s"
                     % (como, t["via"] or "via", t["sinistros_usuario"] or 0,
                        "pedestre" if t["usuario"] == "pedestre" else "ciclista",
                        periodo, quem, consequencia))
            saida.append({
                "perfil": pid, "perfil_rotulo": PERFIS[pid]["rotulo"],
                "modo": t["modo"], "via": t["via"], "usuario": t["usuario"],
                "sinistros_usuario": t["sinistros_usuario"], "fatais": t["fatais"],
                "densidade": t["densidade"],
                "limiar": (lim.get("limiar") or {}).get(t["usuario"]),  # type: ignore[union-attr]
                "delta_tempo": delta, "texto": texto,
            })
    return saida


# Tempo primeiro; custo, emissao e esforco com peso infimo so para desempatar.
PESOS_TEMPO_LEXICOGRAFICO = (1.0, 1e-6, 1e-6, 1e-6)


def _variante_recarga(origem_id: str, destino_id: str, op: Opcoes,
                      cond: Dict[str, object]) -> Optional[Dict[str, object]]:
    """A mesma viagem de carro proprio, com a parada de recarga que menos atrasa."""
    op_rec = Opcoes(modos=frozenset({"pe", "carro"}), clima=op.clima,
                    transito=op.transito, acessivel=op.acessivel, recarga=True)
    g = construir_grafo(op_rec, origem_id, destino_id)
    origem: No = (origem_id, "pe", 0, 0)
    destinos = nos_destino(g, destino_id, True)
    if origem not in g.adj or not destinos:
        return None
    dist, pred, _ = alg.dijkstra(g, origem, destinos, PESOS_TEMPO_LEXICOGRAFICO)
    alvo = alg.melhor_destino(dist, destinos)
    if alvo is None:
        return None
    rota = descrever_rota(g, alg.reconstruir(pred, alvo))
    if "carro" not in rota["modos"] or not rota["recargas"]:   # type: ignore[operator]
        return None
    return _card("mais_rapida", rota, cond)


def opcoes_de_viagem(origem_id: str, destino_id: str,
                     acessivel: bool = False,
                     normalizacao: str = "minmax",
                     evitar_inseguros: bool = True) -> Dict[str, object]:
    """Resposta do app do usuario: as cinco opcoes de viagem, mais o contexto.

    Para cards que usam o carro eletrico proprio, calcula tambem a variante
    COM parada em eletroposto e devolve as duas - quem decide se para e o
    usuario, e a troca no card nao dispara uma nova consulta.
    """
    cond = clima_mod.condicoes_atuais()
    op = Opcoes(
        modos=frozenset(MODOS),
        clima=str(cond["clima"]["clima"]),             # type: ignore[index]
        transito=str(cond["transito"]["transito"]),    # type: ignore[index]
        acessivel=acessivel,
        evitar_inseguros=evitar_inseguros,
    )

    g = construir_grafo(op, origem_id, destino_id)
    origem: No = (origem_id, "pe", 0, 0)
    destinos = nos_destino(g, destino_id)
    if origem not in g.adj or not destinos:
        return {"erro": _motivo_sem_rota(op), "condicoes": cond}

    por_perfil = _cards_de(g, origem, destinos, cond, normalizacao)
    if not por_perfil:
        return {"erro": _motivo_sem_rota(op), "condicoes": cond}

    # O mesmo calculo SEM o filtro de seguranca, so para saber o que ele evitou
    # e poder dizer isso ao usuario, com o dado e com o custo do desvio.
    evitados: List[Dict[str, object]] = []
    if evitar_inseguros:
        op_bruto = Opcoes(modos=op.modos, clima=op.clima, transito=op.transito,
                          acessivel=op.acessivel, evitar_inseguros=False)
        g_bruto = construir_grafo(op_bruto, origem_id, destino_id)
        destinos_bruto = nos_destino(g_bruto, destino_id)
        if origem in g_bruto.adj and destinos_bruto:
            bruto = _cards_de(g_bruto, origem, destinos_bruto, cond, normalizacao) or {}
            evitados = _evitados(bruto, por_perfil)

    # Variante com recarga, para os cards que usam o carro proprio.
    #
    # O interruptor promete "esta viagem de carro, com uma parada para carregar".
    # Uma versao anterior escolhia a variante pelo TOPSIS entre TODAS as rotas
    # com recarga - e o TOPSIS gostava de largar o carro na Estacao Recife depois
    # de carregar 50 min no eletroposto lento e seguir de metro e a pe: +83 min,
    # e outra viagem. Agora a variante e so carro (e a caminhada de desembarque),
    # e a parada escolhida e a que MENOS atrasa - empate desfeito pelo custo.
    if any(x["usa_carro"] for x in por_perfil.values()):
        variante = _variante_recarga(origem_id, destino_id, op, cond)
        if variante is not None:
            for card in por_perfil.values():
                if card["usa_carro"]:
                    card["_variante_recarga"] = variante

    # Perfis diferentes caem com frequencia na MESMA rota - com todos os modais
    # ligados, o carro costuma vencer tempo, custo e esforco ao mesmo tempo.
    # Mostrar tres cards identicos seria ruido; o card vira a rota, e as
    # prioridades que ela atende viram etiquetas dentro dele.
    ordem = ["mais_rapida", "menor_custo", "menor_emissao", "menos_esforco",
             "equilibrada"]
    cards: List[Dict[str, object]] = []
    indice: Dict[str, Dict[str, object]] = {}
    for pid in ordem:
        card = por_perfil.get(pid)
        if card is None:
            continue
        chave = "%s|%.2f|%.2f" % ("+".join(card["modos"]),      # type: ignore[arg-type]
                                  card["tempo"], card["custo"])
        existente = indice.get(chave)
        if existente is None:
            card["perfis"] = [card["rotulo"]]
            card["perfis_id"] = [pid]
            indice[chave] = card
            cards.append(card)
        else:
            existente["perfis"].append(PERFIS[pid]["rotulo"])   # type: ignore[union-attr]
            existente["perfis_id"].append(pid)                  # type: ignore[union-attr]

    # a variante com recarga segue o perfil primario do card mesclado
    for card in cards:
        alt = card.pop("_variante_recarga", None)
        if alt is not None:
            alt.pop("_variante_recarga", None)
            card["variante_recarga"] = alt

    orcamento = [MAX_TRACADOS_AO_VIVO]
    for card in cards:
        _completar_tracado(card, orcamento)
        if card.get("variante_recarga"):
            _completar_tracado(card["variante_recarga"], orcamento)  # type: ignore[arg-type]

    for card in cards:
        card["evitou"] = [e for e in evitados
                          if e["perfil"] in card["perfis_id"]]      # type: ignore[operator]

    rec = _recomendar(cards, cond)
    for card in cards:
        card["recomendado"] = rec["perfil"] in card["perfis_id"]   # type: ignore[operator]
    # o card sugerido vem primeiro; o resto por tempo, como num app de corrida
    cards.sort(key=lambda x: (not x["recomendado"], x["tempo"]))

    return {
        "origem": origem_id,
        "destino": destino_id,
        "origem_nome": PONTO_POR_ID[origem_id].nome,
        "destino_nome": PONTO_POR_ID[destino_id].nome,
        "condicoes": cond,
        "cards": cards,
        "recomendado": rec["perfil"],
        "motivo_recomendacao": rec["motivo"],
        "linha_reta_km": round(haversine_km(PONTO_POR_ID[origem_id],
                                            PONTO_POR_ID[destino_id]), 2),
        "grafo": propriedades(g),
        "evitados": evitados,
        "seguranca_fonte": seguranca.fonte(),
        "gerado_em": time.strftime("%H:%M:%S"),
    }
