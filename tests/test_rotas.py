# -*- coding: utf-8 -*-
"""Testes de corretude das rotas e dos algoritmos.

    python -m unittest discover -s tests -v

Cada teste verifica uma propriedade que TEM de valer se o algoritmo estiver
certo - nao um numero esperado copiado da saida. Se um teste falhar, e o modelo
ou o algoritmo que esta errado, nao o teste.
"""
from __future__ import annotations

import itertools
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

import algoritmos as alg                      # noqa: E402
import geometria                              # noqa: E402
import motor                                  # noqa: E402
from rede_rsm import (                        # noqa: E402
    ESCALAS, FATOR_CONGESTIONAMENTO, PERFIS, PONTO_POR_ID, RECARGAS, TRANSITOS,
    VEICULOS_INDIVIDUAIS, Opcoes, construir_grafo, haversine_km,
)

# Pares origem-destino que cobrem o corredor inteiro e os dois sentidos.
PARES = [
    ("se_olinda", "igreja_piedade"),
    ("igreja_piedade", "se_olinda"),
    ("se_olinda", "praca_bv"),
    ("recife_antigo", "igreja_piedade"),
    ("praca_bv", "se_olinda"),
    ("est_recife", "cajueiro_seco"),
]
UNITARIOS = {
    "tempo": (1.0, 0.0, 0.0, 0.0),
    "custo": (0.0, 1.0, 0.0, 0.0),
    "co2": (0.0, 0.0, 1.0, 0.0),
    "desconforto": (0.0, 0.0, 0.0, 1.0),
}


def _grafo(o, d, **kw):
    op = Opcoes(**kw)
    g = construir_grafo(op, o, d)
    return g, (o, "pe", 0, 0), motor.nos_destino(g, d, op.recarga_efetiva)


def _custo_dijkstra(g, origem, destinos, pesos):
    dist, _pred, _exp = alg.dijkstra(g, origem, destinos, pesos)
    alvo = alg.melhor_destino(dist, destinos)
    return None if alvo is None else dist[alvo]


class TestBuscaOtima(unittest.TestCase):
    """Dijkstra, A* e Martins precisam concordar entre si."""

    def test_a_estrela_iguala_dijkstra(self):
        # A* com heuristica admissivel devolve o MESMO custo otimo do Dijkstra.
        # Roda em todas as condicoes de transito: com transito livre o carro
        # anda a ~39 km/h em linha reta, acima da velocidade nominal do metro,
        # e uma heuristica baseada nela deixaria de ser admissivel.
        for (o, d), transito, (pid, cfg) in itertools.product(
                PARES, TRANSITOS, PERFIS.items()):
            with self.subTest(o=o, d=d, transito=transito, perfil=pid):
                g, origem, destinos = _grafo(o, d, transito=transito)
                pesos = cfg["pesos"]
                esperado = _custo_dijkstra(g, origem, destinos, pesos)
                h = alg.heuristica_geografica(d, pesos, alg.velocidade_maxima_reta(g))
                dist, _pred, _exp = alg.a_estrela(g, origem, destinos, pesos, h)
                alvo = alg.melhor_destino(dist, destinos)
                self.assertAlmostEqual(dist[alvo], esperado, places=9)

    def test_heuristica_nunca_superestima(self):
        # Admissibilidade verificada diretamente: h(n) <= custo real ate o destino,
        # para todo vertice alcancavel. Custo real = Dijkstra reverso.
        for (o, d), transito in itertools.product(PARES[:3], TRANSITOS):
            with self.subTest(o=o, d=d, transito=transito):
                g, origem, destinos = _grafo(o, d, transito=transito)
                pesos = UNITARIOS["tempo"]
                h = alg.heuristica_geografica(d, pesos, alg.velocidade_maxima_reta(g))
                reverso = {}
                for u, arestas in g.adj.items():
                    for a in arestas:
                        reverso.setdefault(a.destino, []).append((u, a))
                import heapq
                custo = {n: 0.0 for n in destinos}
                fila = [(0.0, i, n) for i, n in enumerate(destinos)]
                heapq.heapify(fila)
                cont = len(fila)
                while fila:
                    c, _, v = heapq.heappop(fila)
                    if c > custo.get(v, float("inf")):
                        continue
                    for u, a in reverso.get(v, []):
                        nc = c + alg.escalarizar(a.vetor, pesos)
                        if nc < custo.get(u, float("inf")):
                            custo[u] = nc
                            cont += 1
                            heapq.heappush(fila, (nc, cont, u))
                for n, real in custo.items():
                    self.assertLessEqual(h(n), real + 1e-9, msg=str(n))

    def test_martins_contem_os_otimos_de_cada_objetivo(self):
        # A fronteira de Pareto exata precisa conter, para cada objetivo isolado,
        # uma rota com o mesmo valor otimo que o Dijkstra encontra otimizando so
        # aquele objetivo. Se nao contiver, o Martins esta podando errado.
        for o, d in PARES:
            with self.subTest(o=o, d=d):
                g, origem, destinos = _grafo(o, d)
                frente, _ = alg.martins(g, origem, destinos)
                self.assertTrue(frente)
                for i, (nome, pesos) in enumerate(UNITARIOS.items()):
                    otimo = _custo_dijkstra(g, origem, destinos, pesos)
                    melhor_na_frente = min(alg.escalarizar(v, pesos) for v, _ in frente)
                    self.assertAlmostEqual(melhor_na_frente, otimo, places=9,
                                           msg="objetivo %s" % nome)

    def test_fronteira_sem_rota_dominada(self):
        for o, d in PARES:
            with self.subTest(o=o, d=d):
                g, origem, destinos = _grafo(o, d)
                frente, _ = alg.martins(g, origem, destinos)
                for (a, _), (b, _) in itertools.permutations(frente, 2):
                    self.assertFalse(alg.domina(a, b))


class TestRotasFisicamenteValidas(unittest.TestCase):

    def test_no_maximo_um_veiculo_individual(self):
        for o, d in PARES:
            with self.subTest(o=o, d=d):
                g, origem, destinos = _grafo(o, d)
                frente, _ = alg.martins(g, origem, destinos)
                for _v, caminho in frente:
                    usados = {n[1] for n in caminho if n[1] in VEICULOS_INDIVIDUAIS}
                    self.assertLessEqual(len(usados), 1, msg=str(usados))

    def test_toda_rota_termina_a_pe(self):
        for o, d in PARES:
            with self.subTest(o=o, d=d):
                g, origem, destinos = _grafo(o, d)
                frente, _ = alg.martins(g, origem, destinos)
                for _v, caminho in frente:
                    self.assertEqual(caminho[-1][:2], (d, "pe"))

    def test_carro_proprio_so_embarca_na_origem(self):
        for o, d in PARES:
            with self.subTest(o=o, d=d):
                g, origem, destinos = _grafo(o, d)
                frente, _ = alg.martins(g, origem, destinos)
                for _v, caminho in frente:
                    for a, b in zip(caminho, caminho[1:]):
                        if b[1] == "carro" and a[1] != "carro":
                            self.assertEqual(a[0], o)

    def test_recarga_obrigatoria_passa_por_eletroposto(self):
        eletro = {r.ponto for r in RECARGAS}
        for o, d in PARES[:2]:
            with self.subTest(o=o, d=d):
                g, origem, destinos = _grafo(o, d, recarga=True)
                frente, _ = alg.martins(g, origem, destinos)
                self.assertTrue(frente)
                for _v, caminho in frente:
                    parou = any(a[0] == b[0] and a[3] == 0 and b[3] == 1 and a[0] in eletro
                                for a, b in zip(caminho, caminho[1:]))
                    self.assertTrue(parou)


    def test_mobilidade_reduzida_nao_caminha_longe(self):
        # A primeira versao mandava estacionar no centro e andar 13 km.
        from rede_rsm import LIMITE_PE_ACESSIVEL_KM
        for o, d in PARES:
            with self.subTest(o=o, d=d):
                r = motor.opcoes_de_viagem(o, d, acessivel=True)
                for card in r.get("cards", []):
                    for seg in card["segmentos"]:
                        if seg["tipo"] == "deslocamento" and seg["modo"] == "pe":
                            # um segmento pode encadear trechos curtos; a maior
                            # cadeia possivel na rede e bem menor que 2 km
                            self.assertLess(seg["dist_km"], 2.0, msg=card["resumo"])
                    for m in ("bike", "ebike", "patinete"):
                        self.assertNotIn(m, card["modos"])


class TestRotasBatemComAMalhaReal(unittest.TestCase):
    """O carro tem de andar pelo caminho que um roteador real escolheria."""

    @unittest.skipUnless(geometria.carro("se_olinda", "igreja_piedade"),
                         "sem dados/matriz_carro.json - rode src/geometria.py")
    def test_carro_segue_o_roteador_real(self):
        for o, d in PARES:
            with self.subTest(o=o, d=d):
                g, origem, destinos = _grafo(o, d, modos=frozenset({"pe", "carro"}))
                dist, pred, _ = alg.dijkstra(g, origem, destinos, UNITARIOS["tempo"])
                rota = motor.descrever_rota(g, alg.reconstruir(pred, alg.melhor_destino(dist, destinos)))
                carro = [s for s in rota["segmentos"]
                         if s["tipo"] == "deslocamento" and s["modo"] == "carro"]
                self.assertEqual(len(carro), 1)
                km, livre = geometria.carro(o, d)
                self.assertAlmostEqual(carro[0]["dist_km"], km, places=1)
                self.assertAlmostEqual(carro[0]["tempo"], livre * FATOR_CONGESTIONAMENTO, places=0)

    def test_nenhum_ponto_longe_da_via(self):
        # O erro que originou tudo isto: pontos posicionados de memoria, a ate
        # 3,3 km do lugar real. Estacoes e igrejas foram conferidas no OSM.
        verificados = {
            "se_olinda": (-8.01383, -34.84910), "igreja_piedade": (-8.16850, -34.91541),
            "est_recife": (-8.06917, -34.88537), "tancredo_neves": (-8.12227, -34.91182),
            "aeroporto": (-8.13417, -34.91467), "imbiribeira": (-8.09020, -34.90751),
        }
        from rede_rsm import Ponto
        for pid, (lat, lon) in verificados.items():
            with self.subTest(ponto=pid):
                ref = Ponto("x", "", "", lat, lon, "")
                self.assertLess(haversine_km(PONTO_POR_ID[pid], ref), 0.05)

    @unittest.skipUnless(geometria.item_ativo("pina", "ponte_pg", "bike"),
                         "sem rotas a pe/bike - rode src/geometria.py --so-ativos")
    def test_bike_e_pedestre_nao_contornam_mao_unica(self):
        # Quem pedala ou anda nao da volta no quarteirao por mao unica. De Pina a
        # Ponte Paulo Guerra o carro faz 3,48 km; a pe ou de bicicleta, 0,26 km.
        from rede_rsm import TRECHOS, distancia_trecho
        for modo in ("pe", "bike"):
            self.assertLess(distancia_trecho(
                next(t for t in TRECHOS if {t.u, t.v} == {"pina", "ponte_pg"}), modo), 0.5)
        # e nunca mais longo que o carro no melhor dos dois sentidos
        for t in TRECHOS:
            if "metro" in t.modos or "bike" not in t.modos:
                continue
            carro = [x[0] for x in (geometria.carro(t.u, t.v), geometria.carro(t.v, t.u)) if x]
            if not carro or not geometria.item_ativo(t.u, t.v, "bike"):
                continue
            with self.subTest(trecho=(t.u, t.v)):
                self.assertLessEqual(distancia_trecho(t, "bike"), min(carro) + 0.05)


class TestCards(unittest.TestCase):

    def test_card_extremo_e_o_minimo_da_fronteira(self):
        # "Mais rapida" tem de ser literalmente a de menor tempo, etc.
        campo = {"mais_rapida": "tempo", "menor_custo": "custo",
                 "menor_emissao": "co2"}
        for o, d in PARES[:2]:
            with self.subTest(o=o, d=d):
                r = motor.opcoes_de_viagem(o, d)
                g, origem, destinos = _grafo(o, d, clima=r["condicoes"]["clima"]["clima"],
                                             transito=r["condicoes"]["transito"]["transito"])
                indice = {"tempo": 0, "custo": 1, "co2": 2}
                for perfil, chave in campo.items():
                    card = next(c for c in r["cards"] if perfil in c["perfis_id"])
                    # o Dijkstra devolve o custo ESCALARIZADO (valor / escala);
                    # multiplicar pela escala recupera minutos, reais ou gramas
                    otimo = (_custo_dijkstra(g, origem, destinos, UNITARIOS[chave])
                             * ESCALAS[indice[chave]])
                    self.assertAlmostEqual(card[chave], otimo, delta=0.11, msg=perfil)


    def test_variante_recarga_e_a_mesma_viagem_de_carro(self):
        # "Parar para recarregar" no card do carro nao pode virar outra viagem.
        # Ja devolveu: carregar 50 min, largar o carro e seguir de metro (+83 min).
        tempo_carga_mais_rapida = min(r.tempo_min for r in RECARGAS)
        for o, d in PARES:
            with self.subTest(o=o, d=d):
                r = motor.opcoes_de_viagem(o, d)
                for card in r["cards"]:
                    v = card.get("variante_recarga")
                    if not v:
                        continue
                    self.assertTrue(card["usa_carro"])
                    self.assertTrue(set(v["modos"]) <= {"carro", "pe"}, v["modos"])
                    self.assertEqual(v["recargas"], 1)
                    extra = v["tempo"] - card["tempo"]
                    self.assertGreaterEqual(extra, tempo_carga_mais_rapida - 0.1)


class TestSeguranca(unittest.TestCase):
    """Rotas seguras: o filtro da CTTU tem de valer sempre, e o aviso tem de ser verdadeiro."""

    @classmethod
    def setUpClass(cls):
        import seguranca
        cls.seg = seguranca
        if not seguranca.carregar():
            raise unittest.SkipTest("sem dados/seguranca_cttu.json - rode src/seguranca.py")

    def test_ninguem_anda_ou_pedala_em_via_insegura(self):
        # Em QUALQUER par, nenhuma rota da fronteira pode ter perna a pe ou de
        # duas rodas num trecho marcado como inseguro para aquele usuario.
        from rede_rsm import PONTOS
        ids = [p.id for p in PONTOS]
        for o, d in itertools.permutations(ids, 2):
            g, origem, destinos = _grafo(o, d)
            frente, _ = alg.martins(g, origem, destinos)
            for _v, caminho in frente:
                for a, b in zip(caminho, caminho[1:]):
                    if a[1] == b[1] and a[0] != b[0]:          # aresta de deslocamento
                        self.assertFalse(self.seg.inseguro_para(a[0], b[0], a[1]),
                                         msg="%s -> %s de %s (%s->%s)" % (a[0], b[0], a[1], o, d))

    def test_aviso_so_quando_a_rota_evitada_era_mesmo_insegura(self):
        for o, d in [("praca_bv", "sto_antonio"), ("imbiribeira", "recife_antigo"),
                     ("se_olinda", "igreja_piedade")]:
            with self.subTest(o=o, d=d):
                r = motor.opcoes_de_viagem(o, d)
                for e in r["evitados"]:
                    usuario = "pedestre" if e["modo"] == "pe" else "ciclista"
                    self.assertEqual(e["usuario"], usuario)
                    self.assertGreaterEqual(e["densidade"], e["limiar"])
                    self.assertIn(e["via"], e["texto"])
                for card in r["cards"]:
                    self.assertFalse(card["seguranca"]["inseguros"], card["resumo"])

    def test_caso_real_dantas_barreto(self):
        # Da Imbiribeira ao Recife Antigo, o caminho a pe mais barato passaria
        # pela Av. Dantas Barreto (10 sinistros com pedestre, 2022-2024).
        # (Era Praca de BV -> Santo Antonio ate a bicicleta deixar de contornar
        # mao unica na Ponte Paulo Guerra: ai a bicicleta passou a vencer.)
        r = motor.opcoes_de_viagem("imbiribeira", "recife_antigo")
        vias = {e["via"] for e in r["evitados"]}
        self.assertTrue(any("Dantas Barreto" in (v or "") for v in vias), vias)

    def test_sem_dado_nao_e_seguro(self):
        # Trecho em Olinda: a CTTU nao cobre. Nao pode aparecer como "ok".
        self.assertEqual(self.seg.nivel("se_olinda", "carmo", "pe"), "sem_dado")
        self.assertFalse(self.seg.inseguro_para("se_olinda", "carmo", "pe"))


if __name__ == "__main__":
    unittest.main()
