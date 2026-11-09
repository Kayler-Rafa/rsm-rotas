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


class TestTransportePublico(unittest.TestCase):
    """O card de transporte publico e o onibus nos dois sentidos."""

    def test_card_transporte_publico_so_usa_coletivo_e_e_o_mais_rapido(self):
        for o, d in PARES:
            r = motor.opcoes_de_viagem(o, d)
            cards = [c for c in r["cards"] if "transporte_publico" in c["perfis_id"]]
            self.assertEqual(len(cards), 1, "%s->%s sem card de transporte publico" % (o, d))
            c = cards[0]
            self.assertTrue(set(c["modos"]) <= {"pe", "onibus", "metro"}, c["modos"])
            self.assertTrue(set(c["modos"]) & {"onibus", "metro"}, c["modos"])
            # e a mais rapida entre todas as rotas so de coletivo (Dijkstra exato)
            ref = motor.consultar(o, d, Opcoes(modos=frozenset({"pe", "onibus", "metro"}),
                                               clima=r["condicoes"]["clima"]["clima"],
                                               transito=r["condicoes"]["transito"]["transito"]),
                                  "mais_rapida", com_pareto=False)
            self.assertIn("dijkstra", ref)
            self.assertLessEqual(float(c["tempo"]),
                                 float(ref["dijkstra"]["rota"]["tempo"]) + 0.11)

    def test_onibus_leva_o_mesmo_tempo_nos_dois_sentidos(self):
        """Os pontos de rua estao na pista sentido sul; a volta nao pode pagar
        um retorno em cada ponto (era 119 min contra 62 na ida)."""
        op = Opcoes(modos=frozenset({"pe", "onibus"}))
        ida = motor.consultar("se_olinda", "igreja_piedade", op, "mais_rapida", com_pareto=False)
        volta = motor.consultar("igreja_piedade", "se_olinda", op, "mais_rapida", com_pareto=False)
        ti = float(ida["dijkstra"]["rota"]["tempo"])
        tv = float(volta["dijkstra"]["rota"]["tempo"])
        self.assertLess(abs(ti - tv) / min(ti, tv), 0.10, "ida %.1f x volta %.1f" % (ti, tv))


class TestRiscoNoturno(unittest.TestCase):
    """Risco viario por turno: a noite so pode restringir mais, nunca liberar."""

    ORDEM = {"ok": 0, "atencao": 1, "inseguro": 2}

    def setUp(self):
        import seguranca
        self.seg = seguranca

    def test_turno_da_hora(self):
        self.assertEqual(self.seg.turno_da_hora(17), "dia")
        self.assertEqual(self.seg.turno_da_hora(18), "noite")
        self.assertEqual(self.seg.turno_da_hora(5), "noite")
        self.assertEqual(self.seg.turno_da_hora(6), "dia")

    def test_noite_nunca_libera_trecho(self):
        from rede_rsm import TRECHOS
        for t in TRECHOS:
            for modo in ("pe", "bike"):
                for a, b in ((t.u, t.v), (t.v, t.u)):
                    dia = self.seg.nivel(a, b, modo, "dia")
                    noite = self.seg.nivel(a, b, modo, "noite")
                    if dia in self.ORDEM:
                        self.assertGreaterEqual(self.ORDEM[noite], self.ORDEM[dia],
                                                (a, b, modo, dia, noite))
                    else:
                        self.assertEqual(dia, noite)

    def test_amostra_pequena_fica_na_media(self):
        """Encolhimento: rua com 1 sinistro, noturno, nao vira 3x mais perigosa."""
        a = {"pedestre": 1, "pedestre_noite": 1, "sinistros": 1, "sem_hora": 0}
        self.assertLess(self.seg.fator_noite(a, "pedestre"), 1.25)
        # e rua sem nenhum caso noturno nunca fica abaixo de 1 (dia = total)
        b = {"pedestre": 30, "pedestre_noite": 0, "sinistros": 30, "sem_hora": 0}
        self.assertEqual(self.seg.fator_noite(b, "pedestre"), 1.0)

    def test_caso_real_domingos_ferreira_de_bicicleta(self):
        self.assertEqual(self.seg.nivel("df_norte", "df_centro", "bike", "dia"), "ok")
        self.assertEqual(self.seg.nivel("df_norte", "df_centro", "bike", "noite"), "atencao")

    def test_ninguem_anda_ou_pedala_em_via_insegura_a_noite(self):
        for o, d in PARES:
            g = construir_grafo(Opcoes(turno="noite"), o, d)
            for u, arestas in g.adj.items():
                for ar in arestas:
                    if ar.tipo == "deslocamento" and u[1] in ("pe", "bike", "ebike", "patinete"):
                        self.assertFalse(self.seg.inseguro_para(u[0], ar.destino[0], u[1], "noite"),
                                         (u, ar.destino))


class TestRuasSemSinistro(unittest.TestCase):
    """Rua do Recife sem registro na CTTU conta como zero, nao como 'sem dado'."""

    def test_rua_do_recife_sem_sinistro_conta_como_zero(self):
        import seguranca
        r = seguranca.risco_trecho("df_centro", "shopping", "pe")
        self.assertTrue(r["tem_dado"])
        self.assertEqual(r["cobertura"], 1.0)
        self.assertTrue(any(v["sem_registro"] for v in r["vias"]))
        for v in r["vias"]:
            if v["sem_registro"]:
                self.assertEqual(v["sinistros"], 0)

    def test_zero_so_vale_no_recife(self):
        import seguranca
        # trecho de Olinda: mesmo que um nome exista no Recife, nada vira zero
        r = seguranca.risco_trecho("se_olinda", "carmo", "pe")
        self.assertFalse(any(v.get("sem_registro") for v in r["vias"]))
        self.assertEqual(seguranca.nivel("se_olinda", "carmo", "pe"), "sem_dado")


class TestAcessibilidadeMedida(unittest.TestCase):
    """Acessibilidade medida no OSM: escada e piso irregular ao longo do caminho."""

    def test_ladeira_da_se_e_inacessivel_pelo_dado(self):
        from rede_rsm import TRECHOS, _medida, trecho_acessivel
        t = next(t for t in TRECHOS if (t.u, t.v) == ("se_olinda", "carmo"))
        m = _medida(t)
        self.assertIsNotNone(m)
        self.assertFalse(m["acessivel"])
        self.assertGreater(m["piso_m"], 100)             # paralelepipedo de Olinda
        self.assertFalse(trecho_acessivel(t))

    def test_medicao_so_restringe(self):
        from rede_rsm import TRECHOS, trecho_acessivel
        for t in TRECHOS:
            if not t.acessivel:
                self.assertFalse(trecho_acessivel(t), (t.u, t.v))

    def test_caminho_acessivel_nunca_e_mais_curto(self):
        from rede_rsm import TRECHOS, distancia_pe_acessivel, distancia_trecho
        for t in TRECHOS:
            if "pe" in t.modos:
                self.assertGreaterEqual(distancia_pe_acessivel(t), distancia_trecho(t, "pe"))

    def test_cruzar_rua_de_paralelepipedo_nao_conta(self):
        """Uma via de barreira PERPENDICULAR a rota da < MIN_TRECHO_M de sequencia."""
        import acessibilidade as A
        barreira = [{"type": "way", "id": 1, "tags": {"highway": "residential", "surface": "sett"},
                     "geometry": [{"lat": -8.0900, "lon": -34.9000},
                                  {"lat": -8.0900, "lon": -34.8990}]}]
        grade = A._indice(barreira)
        cruza = [[-8.0910, -34.8995], [-8.0890, -34.8995]]      # norte-sul, cruza
        ao_longo = [[-8.0900, -34.9000], [-8.0900, -34.8990]]  # em cima da via, 110 m
        self.assertEqual(A.medir(cruza, grade)["piso_m"], 0)
        self.assertGreater(A.medir(ao_longo, grade)["piso_m"], 90)


class TestEletropostosReais(unittest.TestCase):
    """Eletropostos vem do OSM, perto do ponto, e o desvio entra no tempo."""

    def test_eletropostos_sao_do_osm_e_perto_do_ponto(self):
        import eletropostos
        self.assertTrue(RECARGAS)
        for r in RECARGAS:
            self.assertIsNotNone(r.lat, r.id)               # posicao real, nao estimada
            self.assertTrue(r.id.startswith("rec_osm_"), r.id)
            p = PONTO_POR_ID[r.ponto]
            from rede_rsm import Ponto
            d = haversine_km(Ponto("_", "", "", r.lat, r.lon, ""), p)
            self.assertLessEqual(d, eletropostos.RAIO_MAX_KM + 1e-6, r.nome)
            base = eletropostos.TIPOS[r.tipo]["tempo_min"]
            self.assertGreater(r.tempo_min, base, "desvio nao somado: %s" % r.nome)
        self.assertEqual(len({r.ponto for r in RECARGAS}), len(RECARGAS))  # um por ponto


class TestLocalizacao(unittest.TestCase):
    """GPS / endereco: liga a posicao ao ponto da rede mais proximo."""

    def test_ponto_mais_proximo_e_caminhada(self):
        import local
        r = local.proximos(-8.0631, -34.8711)          # ao lado do Marco Zero
        self.assertEqual(r["pontos"][0]["id"], "recife_antigo")
        self.assertLess(r["pontos"][0]["km"], 0.2)
        self.assertFalse(r["longe"])
        kms = [p["km"] for p in r["pontos"]]
        self.assertEqual(kms, sorted(kms))
        # caminhada = reta x rodeio, na velocidade a pe (mais lenta se acessivel)
        acess = local.proximos(-8.0631, -34.8711, acessivel=True)["pontos"][0]["min"]
        self.assertGreater(acess, r["pontos"][0]["min"])

    def test_longe_da_rede_e_avisado(self):
        import local
        self.assertTrue(local.proximos(-8.20, -35.05)["longe"])   # interior de Jaboatao


class TestContramao(unittest.TestCase):
    """Aviso de bicicleta na contramao: so onde a rota de fato pula um contorno."""

    def test_contramao_so_onde_a_rota_legal_e_bem_maior(self):
        from rede_rsm import MODOS_DUAS_RODAS, TRECHOS
        dados = geometria.carregar()
        marcados = 0
        for t in TRECHOS:
            if not set(t.modos) & MODOS_DUAS_RODAS:
                continue
            item = dados.get("%s|%s|cycling" % (t.u, t.v))
            for a, b in ((t.u, t.v), (t.v, t.u)):
                c = geometria.contramao_bike(a, b)
                if not c:
                    continue
                marcados += 1
                # traçado de avenida de pista dupla (vindo do carro) nunca é contramão
                self.assertFalse(str(item["fonte"]).startswith("OSRM carro"), (a, b))
                self.assertLessEqual(c["km"], geometria.FRACAO_CONTRAMAO * c["km_legal"] + 1e-9)
                self.assertGreaterEqual(c["km_legal"] - c["km"],
                                        geometria.ECONOMIA_MIN_KM_CONTRAMAO - 1e-9)
        # se o critério marcar quase tudo, virou ruído e ninguém lê o aviso
        self.assertLess(marcados, 10)

    def test_caso_real_sao_jose_ponte_paulo_guerra(self):
        r = motor.opcoes_de_viagem("se_olinda", "igreja_piedade")
        bike = [c for c in r["cards"] if c["modos"] and "bike" in c["modos"]]
        self.assertTrue(bike)
        marcas = [(x["de"], x["para"]) for s in bike[0]["segmentos"]
                  for x in (s.get("contramao") or [])]
        self.assertIn(("sao_jose", "ponte_pg"), marcas)
        self.assertTrue(any("mão única" in a["texto"] for a in bike[0]["avisos"]))
        # e nenhum card sem duas rodas recebe a marca
        for c in r["cards"]:
            if not set(c["modos"]) & {"bike", "ebike", "patinete"}:
                self.assertFalse(any(s.get("contramao") for s in c["segmentos"]))


if __name__ == "__main__":
    unittest.main()
