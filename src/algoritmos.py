# -*- coding: utf-8 -*-
"""Algoritmos do RSM, implementados do zero (apenas biblioteca padrao).

  Dijkstra  - caminho minimo com custo escalarizado          O(E log V)
  A*        - mesma busca com heuristica de Haversine        O(E log V) no pior caso
  Martins   - fronteira de Pareto exata por poda de dominancia
  NSGA-II   - fronteira aproximada, populacao evolutiva      O(G*P^2*d)
  TOPSIS    - ordena a fronteira pela preferencia do usuario O(k*d)
"""
from __future__ import annotations

import heapq
import itertools
import random
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from rede_rsm import (
    ESCALAS, MODOS, PONTO_POR_ID, Aresta, GrafoMultimodal, No, VetorCusto,
    haversine_km,
)

INF = float("inf")
Pesos = Tuple[float, float, float, float]
Solucao = Tuple[VetorCusto, List[No]]
Busca = Tuple[Dict[No, float], Dict[No, Optional[No]], List[No]]


# ------------------------------------------------------------ escalarizacao
def escalarizar(v: VetorCusto, pesos: Pesos) -> float:
    """Soma ponderada normalizada.

    Cada componente e dividido por uma escala de referencia antes de receber o
    peso do perfil. Sem a normalizacao, a emissao (em gramas) dominaria
    numericamente o tempo (em minutos) e o custo (em reais).
    """
    return sum((v[i] / ESCALAS[i]) * pesos[i] for i in range(4))


# ---------------------------------------------------------------- Dijkstra
def dijkstra(grafo: GrafoMultimodal, origem: No,
             destinos: Sequence[No], pesos: Pesos) -> Busca:
    """Caminho minimo com custo escalarizado nao-negativo.

    Retorna (distancias, predecessores, lista de vertices expandidos).
    Cada vertice sai do heap uma unica vez  -> V operacoes O(log V).
    Cada aresta gera no maximo uma insercao -> E operacoes O(log V).
    """
    dist: Dict[No, float] = {origem: 0.0}
    pred: Dict[No, Optional[No]] = {origem: None}
    visitado: Dict[No, bool] = {}
    fila: List[Tuple[float, int, No]] = [(0.0, 0, origem)]
    contador = itertools.count(1)          # desempate estavel no heap
    expandidos: List[No] = []
    alvos = set(destinos)

    while fila:
        d_atual, _, u = heapq.heappop(fila)          # O(log V)
        if visitado.get(u):                          # descarta entradas obsoletas
            continue
        visitado[u] = True
        expandidos.append(u)
        if u in alvos:
            break            # o primeiro destino extraido do heap ja e o otimo
        for a in grafo.vizinhos(u):                  # laco interno: total O(E)
            nova = d_atual + escalarizar(a.vetor, pesos)
            if nova < dist.get(a.destino, INF):
                dist[a.destino] = nova
                pred[a.destino] = u
                heapq.heappush(fila, (nova, next(contador), a.destino))
    return dist, pred, expandidos


# ----------------------------------------------------------------------- A*
def velocidade_maxima_reta(grafo: GrafoMultimodal) -> float:
    """Maior velocidade EM LINHA RETA de qualquer aresta do grafo, em km/h.

    E o limite que torna a heuristica admissivel. Usar a maior velocidade
    NOMINAL de um modal (o metro, 32 km/h) deixou de ser seguro quando o carro
    passou a andar na velocidade real das vias: uma aresta de carro pela Via
    Mangue cobre mais linha reta por minuto que o metro, a heuristica passaria
    a superestimar e o A* poderia devolver rota errada. Medir no proprio grafo
    garante, por construcao, tempo(u,v) >= reta(u,v) / v_max para toda aresta.
    """
    v_max = 1.0
    for u, arestas in grafo.adj.items():
        pu = PONTO_POR_ID[u[0]]
        for a in arestas:
            if a.tipo != "deslocamento" or a.tempo <= 0:
                continue
            km = haversine_km(pu, PONTO_POR_ID[a.destino[0]])
            v_max = max(v_max, km / (a.tempo / 60.0))
    return v_max * 1.0001            # folga contra arredondamento


def heuristica_geografica(destino_id: str, pesos: Pesos,
                          v_max: Optional[float] = None) -> Callable[[No], float]:
    """h(n) = limite inferior do custo restante.

    Admissibilidade: distancia em linha reta ate o destino dividida por v_max,
    a maior velocidade em linha reta de qualquer aresta (velocidade_maxima_reta).
    Pela desigualdade triangular, nenhum caminho cobre essa distancia em menos
    tempo. Os demais objetivos tem minimo zero e sao estimados como zero.
    Consistencia: h(u) - h(v) <= reta(u,v)/v_max <= tempo(u,v) para toda aresta.
    """
    if v_max is None:
        v_max = max(m.velocidade for m in MODOS.values())
    p_destino = PONTO_POR_ID[destino_id]
    cache: Dict[str, float] = {}

    def h(n: No) -> float:
        # memoizacao: a trigonometria do haversine domina o custo por expansao
        val = cache.get(n[0])
        if val is None:
            km = haversine_km(PONTO_POR_ID[n[0]], p_destino)
            val = escalarizar(((km / v_max) * 60.0, 0.0, 0.0, 0.0), pesos)
            cache[n[0]] = val
        return val

    return h


def a_estrela(grafo: GrafoMultimodal, origem: No, destinos: Sequence[No],
              pesos: Pesos, h: Callable[[No], float]) -> Busca:
    """A*: ordena a fila por f(n) = g(n) + h(n). Com h admissivel, e otimo."""
    g_score: Dict[No, float] = {origem: 0.0}
    pred: Dict[No, Optional[No]] = {origem: None}
    fechado: Dict[No, bool] = {}
    contador = itertools.count(1)
    fila: List[Tuple[float, int, No]] = [(h(origem), 0, origem)]
    expandidos: List[No] = []
    alvos = set(destinos)

    while fila:
        _, _, u = heapq.heappop(fila)
        if fechado.get(u):
            continue
        fechado[u] = True
        expandidos.append(u)
        if u in alvos:
            break            # com h admissivel, o primeiro destino fechado e otimo
        for a in grafo.vizinhos(u):
            tentativa = g_score[u] + escalarizar(a.vetor, pesos)
            if tentativa < g_score.get(a.destino, INF):
                g_score[a.destino] = tentativa
                pred[a.destino] = u
                heapq.heappush(fila, (tentativa + h(a.destino), next(contador), a.destino))
    return g_score, pred, expandidos


def reconstruir(pred: Dict[No, Optional[No]], alvo: No) -> List[No]:
    caminho: List[No] = []
    atual: Optional[No] = alvo
    while atual is not None:
        caminho.append(atual)
        atual = pred.get(atual)
    return list(reversed(caminho))


def melhor_destino(dist: Dict[No, float], destinos: Sequence[No]) -> Optional[No]:
    candidatos = [d for d in destinos if d in dist]
    if not candidatos:
        return None
    return min(candidatos, key=lambda d: dist[d])


# ------------------------------------------------------------ dominancia
def domina(a: VetorCusto, b: VetorCusto) -> bool:
    """a domina b: nao e pior em nenhum componente e e melhor em ao menos um."""
    melhor_em_algum = False
    for x, y in zip(a, b):
        if x > y + 1e-12:
            return False
        if x < y - 1e-12:
            melhor_em_algum = True
    return melhor_em_algum


def filtrar_pareto(solucoes: List[Solucao]) -> List[Solucao]:
    """Remove solucoes dominadas e duplicatas; ordena por tempo."""
    unicas: List[Solucao] = []
    vistos = set()
    for v, c in solucoes:
        chave = tuple(round(x, 6) for x in v)
        if chave in vistos:
            continue
        vistos.add(chave)
        unicas.append((v, c))
    frente = [(v, c) for v, c in unicas
              if not any(domina(o, v) for o, _ in unicas if o is not v)]
    frente.sort(key=lambda s: s[0])
    return frente


# ------------------------------------------------------------------ Martins
@dataclass(order=True)
class Rotulo:
    chave: VetorCusto
    seq: int
    no: No = field(compare=False)
    vetor: VetorCusto = field(compare=False)
    pai: Optional["Rotulo"] = field(compare=False, default=None)


def martins(grafo: GrafoMultimodal, origem: No, destinos: Sequence[No],
            max_rotulos: int = 400_000) -> Tuple[List[Solucao], int]:
    """Generalizacao multiobjetivo do Dijkstra (Martins, 1984).

    Mantem, para cada vertice, um conjunto de rotulos nao-dominados.
    Complexidade: O(N log N + N * d * k), onde N e o numero de rotulos
    nao-dominados gerados - no pior caso exponencial (problema NP-dificil),
    mas tratavel em redes urbanas com objetivos correlacionados.
    """
    contador = itertools.count()
    zero: VetorCusto = (0.0, 0.0, 0.0, 0.0)
    inicial = Rotulo(chave=zero, seq=next(contador), no=origem, vetor=zero, pai=None)
    fila: List[Rotulo] = [inicial]
    permanentes: Dict[No, List[VetorCusto]] = {}
    gerados = 0
    alvos = set(destinos)
    solucoes: List[Solucao] = []

    while fila and gerados < max_rotulos:
        atual = heapq.heappop(fila)
        perm = permanentes.setdefault(atual.no, [])
        if any(domina(v, atual.vetor) or v == atual.vetor for v in perm):
            continue                                   # rotulo ja dominado
        perm[:] = [v for v in perm if not domina(atual.vetor, v)]
        perm.append(atual.vetor)

        if atual.no in alvos:
            caminho: List[No] = []
            r: Optional[Rotulo] = atual
            while r is not None:
                caminho.append(r.no)
                r = r.pai
            solucoes.append((atual.vetor, list(reversed(caminho))))
            continue

        for a in grafo.vizinhos(atual.no):
            novo = tuple(x + y for x, y in zip(atual.vetor, a.vetor))
            alvo_perm = permanentes.get(a.destino, [])
            if any(domina(v, novo) or v == novo for v in alvo_perm):
                continue
            gerados += 1
            heapq.heappush(fila, Rotulo(chave=novo, seq=next(contador),  # type: ignore[arg-type]
                                        no=a.destino, vetor=novo, pai=atual))
    return filtrar_pareto(solucoes), gerados


# ------------------------------------------------------------------ NSGA-II
def avaliar_caminho(grafo: GrafoMultimodal, caminho: List[No]) -> Optional[VetorCusto]:
    total = [0.0, 0.0, 0.0, 0.0]
    for u, v in zip(caminho, caminho[1:]):
        a = grafo.aresta_entre(u, v)
        if a is None:
            return None
        for i, x in enumerate(a.vetor):
            total[i] += x
    return (total[0], total[1], total[2], total[3])


def caminho_aleatorio(grafo: GrafoMultimodal, origem: No, destino_id: str,
                      rng: random.Random, max_passos: int = 260,
                      modo_destino: str = "pe") -> Optional[List[No]]:
    def chegou(n: No) -> bool:
        return n[0] == destino_id and n[1] == modo_destino

    caminho = [origem]
    atual = origem
    visitados = {origem}
    for _ in range(max_passos):
        if chegou(atual):
            return caminho
        opcoes = [a for a in grafo.vizinhos(atual) if a.destino not in visitados]
        if not opcoes:
            return None
        chegada = [a for a in opcoes if chegou(a.destino)]
        escolha = rng.choice(chegada) if chegada else rng.choice(opcoes)
        atual = escolha.destino
        visitados.add(atual)
        caminho.append(atual)
    return None


def fast_non_dominated_sort(vetores: List[VetorCusto]) -> List[List[int]]:
    n = len(vetores)
    dominados: List[List[int]] = [[] for _ in range(n)]
    contagem = [0] * n
    frentes: List[List[int]] = [[]]
    for p in range(n):
        for q in range(n):
            if p == q:
                continue
            if domina(vetores[p], vetores[q]):
                dominados[p].append(q)
            elif domina(vetores[q], vetores[p]):
                contagem[p] += 1
        if contagem[p] == 0:
            frentes[0].append(p)
    i = 0
    while i < len(frentes) and frentes[i]:
        proxima: List[int] = []
        for p in frentes[i]:
            for q in dominados[p]:
                contagem[q] -= 1
                if contagem[q] == 0:
                    proxima.append(q)
        i += 1
        frentes.append(proxima)
    return [f for f in frentes if f]


def crowding_distance(vetores: List[VetorCusto], frente: List[int]) -> Dict[int, float]:
    d = {i: 0.0 for i in frente}
    if len(frente) <= 2:
        return {i: INF for i in frente}
    for obj in range(4):
        ordenada = sorted(frente, key=lambda i: vetores[i][obj])
        d[ordenada[0]] = INF
        d[ordenada[-1]] = INF
        lo, hi = vetores[ordenada[0]][obj], vetores[ordenada[-1]][obj]
        span = hi - lo
        if span <= 0:
            continue
        for k in range(1, len(ordenada) - 1):
            i = ordenada[k]
            if d[i] == INF:
                continue
            d[i] += (vetores[ordenada[k + 1]][obj] - vetores[ordenada[k - 1]][obj]) / span
    return d


def nsga2(grafo: GrafoMultimodal, origem: No, destino_id: str,
          tamanho_pop: int = 80, geracoes: int = 60,
          semente: int = 42, modo_destino: str = "pe") -> Tuple[List[Solucao], int]:
    """NSGA-II com representacao por caminho: cruzamento em no comum e
    mutacao por re-roteamento do sufixo."""
    rng = random.Random(semente)
    avaliacoes = 0

    def gerar() -> Optional[List[No]]:
        for _ in range(60):
            c = caminho_aleatorio(grafo, origem, destino_id, rng,
                                  modo_destino=modo_destino)
            if c:
                return c
        return None

    populacao: List[List[No]] = []
    tentativas = 0
    while len(populacao) < tamanho_pop and tentativas < tamanho_pop * 30:
        tentativas += 1
        c = gerar()
        if c:
            populacao.append(c)
    if not populacao:
        return [], 0

    def avaliar(pop: List[List[No]]) -> List[VetorCusto]:
        nonlocal avaliacoes
        avaliacoes += len(pop)
        out: List[VetorCusto] = []
        for c in pop:
            v = avaliar_caminho(grafo, c)
            out.append(v if v else (INF, INF, INF, INF))
        return out

    def cruzar(p1: List[No], p2: List[No]) -> List[No]:
        comuns = [n for n in p1[1:-1] if n in p2[1:-1]]
        if not comuns:
            return p1[:]
        pivo = rng.choice(comuns)
        i, j = p1.index(pivo), p2.index(pivo)
        filho = p1[:i] + p2[j:]
        vistos: set = set()
        limpo: List[No] = []
        for n in filho:                      # remove ciclos gerados pelo cruzamento
            if n in vistos:
                # A truncagem descarta nos que ja estavam em `limpo`; sem tirar
                # esses nos de `vistos`, um deles reaparece mais adiante, cai
                # neste ramo e o index() falha. Manter vistos == set(limpo).
                k = limpo.index(n)
                for descartado in limpo[k + 1:]:
                    vistos.discard(descartado)
                limpo = limpo[:k + 1]
                continue
            vistos.add(n)
            limpo.append(n)
        return limpo

    def mutar(c: List[No]) -> List[No]:
        if len(c) < 3:
            return c
        k = rng.randrange(1, len(c) - 1)
        sufixo = caminho_aleatorio(grafo, c[k], destino_id, rng,
                                   modo_destino=modo_destino)
        return c[:k] + sufixo[1:] if sufixo else c

    for _ in range(geracoes):
        vetores = avaliar(populacao)
        frentes = fast_non_dominated_sort(vetores)
        rank = {i: r for r, f in enumerate(frentes) for i in f}
        cd: Dict[int, float] = {}
        for f in frentes:
            cd.update(crowding_distance(vetores, f))

        filhos: List[List[No]] = []
        guarda = 0
        while len(filhos) < tamanho_pop and guarda < tamanho_pop * 20:
            guarda += 1
            a, b = rng.randrange(len(populacao)), rng.randrange(len(populacao))
            pai1 = populacao[a] if (rank[a], -cd[a]) <= (rank[b], -cd[b]) else populacao[b]
            a, b = rng.randrange(len(populacao)), rng.randrange(len(populacao))
            pai2 = populacao[a] if (rank[a], -cd[a]) <= (rank[b], -cd[b]) else populacao[b]
            filho = cruzar(pai1, pai2) if rng.random() < 0.9 else pai1[:]
            if rng.random() < 0.25:
                filho = mutar(filho)
            if (filho and filho[0] == origem and filho[-1][0] == destino_id
                    and filho[-1][1] == modo_destino):
                filhos.append(filho)
        if not filhos:
            break

        combinada = populacao + filhos
        vet_comb = avaliar(combinada)
        frentes = fast_non_dominated_sort(vet_comb)
        nova: List[List[No]] = []
        for f in frentes:
            if len(nova) + len(f) <= tamanho_pop:
                nova.extend(combinada[i] for i in f)
            else:
                cdf = crowding_distance(vet_comb, f)
                restantes = sorted(f, key=lambda i: -cdf[i])[:tamanho_pop - len(nova)]
                nova.extend(combinada[i] for i in restantes)
                break
        populacao = nova

    vetores = avaliar(populacao)
    solucoes = [(v, c) for v, c in zip(vetores, populacao) if v[0] < INF]
    return filtrar_pareto(solucoes), avaliacoes


# ------------------------------------------------------------------- TOPSIS
def topsis(frente: List[Solucao], pesos: Pesos,
           normalizacao: str = "minmax") -> Tuple[int, List[float]]:
    """Ordena a fronteira pela proximidade relativa a solucao ideal.

    Todos os criterios sao de custo (quanto menor, melhor): o ideal e o minimo
    de cada coluna normalizada e o anti-ideal e o maximo.

    Duas normalizacoes, porque a escolha muda a recomendacao:

    "vetorial" - divide cada coluna pela norma euclidiana. E a formulacao
        classica do TOPSIS e a usada na Etapa 2. Tem um efeito colateral
        conhecido: o peso efetivo de um criterio depende da DISPERSAO daquela
        coluna na fronteira. Neste corredor a emissao varia de 0 a ~1.070 g
        enquanto o tempo varia menos de 20% em torno da media, de modo que a
        emissao domina a decisao mesmo com peso 0,10 - e o perfil "mais rapida"
        deixa de escolher a rota mais rapida.

    "minmax" - reescala cada coluna para [0,1] entre o melhor e o pior valor da
        fronteira. Os pesos passam a significar o que dizem, independentemente
        da dispersao. E o padrao aqui pela coerencia com os perfis.
    """
    if not frente:
        return -1, []
    m = [list(v) for v, _ in frente]
    n_obj = len(m[0])
    if normalizacao == "vetorial":
        normas = [max(1e-12, sum(linha[j] ** 2 for linha in m) ** 0.5) for j in range(n_obj)]
        norm = [[linha[j] / normas[j] * pesos[j] for j in range(n_obj)] for linha in m]
    else:
        lo = [min(linha[j] for linha in m) for j in range(n_obj)]
        hi = [max(linha[j] for linha in m) for j in range(n_obj)]
        span = [max(1e-12, hi[j] - lo[j]) for j in range(n_obj)]
        norm = [[((linha[j] - lo[j]) / span[j]) * pesos[j] for j in range(n_obj)]
                for linha in m]
    ideal = [min(linha[j] for linha in norm) for j in range(n_obj)]
    anti = [max(linha[j] for linha in norm) for j in range(n_obj)]
    escores: List[float] = []
    for linha in norm:
        d_mais = sum((linha[j] - ideal[j]) ** 2 for j in range(n_obj)) ** 0.5
        d_menos = sum((linha[j] - anti[j]) ** 2 for j in range(n_obj)) ** 0.5
        escores.append(d_menos / (d_mais + d_menos) if (d_mais + d_menos) > 0 else 0.0)
    melhor = max(range(len(escores)), key=lambda i: escores[i])
    return melhor, escores
