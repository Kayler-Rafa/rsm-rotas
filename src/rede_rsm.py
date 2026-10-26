# -*- coding: utf-8 -*-
"""RSM - Rotas Sustentaveis Multimodais.

Modelagem da rede da Regiao Metropolitana do Recife como grafo multimodal em
camadas, no formato G = (V, E) com V subconjunto de P x M x F.

Corredor de referencia deste MVP:
    Igreja da Se (Alto da Se, Olinda)  <->  Igreja de N. Sra. da Piedade (Jaboatao)

O vertice carrega dois bits de estado alem do par (ponto, modo):

  F = {0,1}  ja embarcou em um veiculo individual? Impede rotas fisicamente
             absurdas do tipo "pedala a bicicleta propria, abandona no meio do
             caminho e aluga uma eletrica".
  R = {0,1}  ja passou por um ponto de recarga? So existe quando o usuario pede
             parada para recarga; caso contrario o grafo nao cresce.

Ver construir_grafo().
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, FrozenSet, List, Optional, Tuple

No = Tuple[str, str, int, int]   # (ponto_id, modo, usou_veiculo, recarregou)
VetorCusto = Tuple[float, float, float, float]    # tempo(min), custo(R$), co2(g), desconforto
INF = float("inf")

# Fator de emissao de referencia: automovel flex compacto, ciclo de vida,
# Brasil (ICCT, 2023). Usado para calcular a emissao EVITADA.
FATOR_CARRO_G_KM = 155.0

# Matriz eletrica brasileira: 83 g CO2eq/kWh (ICCT, 2023, herdado da Etapa 1).
# Um automovel eletrico compacto consome ~0,15 kWh/km -> ~12,5 g CO2eq/km.
# ATENCAO: isso e emissao OPERACIONAL. O baseline de 155 g/km acima e de CICLO
# DE VIDA (inclui fabricacao). A comparacao favorece levemente o eletrico.
G_POR_KWH = 83.0
KWH_POR_KM_CARRO = 0.15

# Tarifa do Sistema Estrutural Integrado, anel A, herdada da Etapa 1.
# Valor a reverificar junto ao Grande Recife antes de qualquer uso real.
TARIFA_SEI = 4.10

# Estacionamento do carro proprio, cobrado ao deixar o veiculo. Sem isso a
# comparacao e enviesada: o carro aparece custando so a energia (~R$ 6) contra
# a tarifa cheia do transporte publico. Media grosseira de vaga paga em Boa
# Viagem / centro; nao diferencia park-and-ride de estacionamento comercial.
CUSTO_ESTACIONAMENTO = 8.00


# --------------------------------------------------------------------- modos
@dataclass(frozen=True)
class Modo:
    nome: str
    velocidade: float       # km/h - velocidade comercial
    custo_km: float         # R$/km
    custo_min: float        # R$/min (micromobilidade compartilhada cobra por tempo)
    custo_fixo: float       # R$ - tarifa, desbloqueio ou bandeirada, na transferencia
    co2_km: float           # g CO2eq/km
    desconforto_km: float   # adimensional, por km
    eletrico: bool
    individual: bool        # veiculo individual: no maximo um por viagem
    pessoal: bool           # veiculo proprio: embarca na origem, desembarca no destino
    rotulo: str
    cor: str
    viabilidade: str        # nota qualitativa herdada da analise de requisitos


MODOS: Dict[str, Modo] = {
    "pe": Modo(
        "pe", 4.8, 0.00, 0.00, 0.00, 0.00, 1.00,
        True, False, False, "a pé", "#64748b",
        "Viavel no MVP como acesso e egresso. Como modo unico em um corredor de "
        "~24 km significa cerca de 5 horas de caminhada - existe no grafo, mas "
        "nao e uma opcao de viagem real."),

    "bike": Modo(
        "bike", 14.0, 0.00, 0.00, 0.00, 0.00, 0.55,
        True, True, True, "bicicleta", "#16a34a",
        "Viavel no MVP. Veiculo proprio: embarca na origem e so desembarca no "
        "destino ou em ponto com bicicletario (estacao ou terminal). Sem "
        "restricao municipal, ao contrario da frota compartilhada."),

    "ebike": Modo(
        "ebike", 18.0, 0.00, 0.55, 1.00, 0.83, 0.25,
        True, True, False, "bicicleta elétrica compartilhada", "#0891b2",
        "Viavel com integracao. Cobranca por MINUTO, nao por km - o que torna a "
        "travessia completa do corredor cara. Regulamentacao restrita ao Recife: "
        "nao ha oferta em Olinda nem em Jaboatao."),

    "patinete": Modo(
        "patinete", 16.0, 0.00, 0.65, 1.00, 1.25, 0.35,
        True, True, False, "patinete compartilhado", "#7c3aed",
        "Viavel com integracao, porem projetado para primeira e ultima milha "
        "(2-3 km). Cobranca por minuto e regulamentacao restrita ao Recife."),

    "metro": Modo(
        "metro", 32.0, 0.00, 0.00, TARIFA_SEI, 3.70, 0.20,
        True, False, False, "metrô", "#dc2626",
        "Viavel com validacao local. Tracao eletrica documentada (CBTU). E o "
        "modo de maior velocidade comercial da rede e o par natural da "
        "caminhada neste corredor."),

    "onibus": Modo(
        "onibus", 18.0, 0.00, 0.00, TARIFA_SEI, 68.00, 0.30,
        False, False, False, "ônibus", "#d97706",
        "Viavel no MVP. NAO ha frota eletrica em operacao na RMR: o modo e "
        "modelado como diesel, com 68 g CO2eq/km, e e a unica fonte relevante "
        "de emissao entre os modos disponiveis."),

    "carro": Modo(
        "carro", 24.0, 0.25, 0.00, 0.00,
        G_POR_KWH * KWH_POR_KM_CARRO, 0.10,
        True, True, True, "carro elétrico próprio", "#0f766e",
        "Viavel com validacao local. Veiculo proprio: embarca na origem e "
        "desembarca no destino ou em estacao/terminal (park-and-ride). Custo = "
        "energia + desgaste (R$ 0,25/km) + R$ 8,00 de estacionamento ao deixar "
        "o veiculo; nao inclui depreciacao, seguro nem IPVA."),

    "carro_app": Modo(
        "carro_app", 24.0, 1.90, 0.00, 6.00,
        G_POR_KWH * KWH_POR_KM_CARRO, 0.08,
        True, True, False, "carro elétrico de aplicativo", "#065f46",
        "Viavel com integracao. A frota eletrica dos aplicativos na RMR ainda e "
        "pequena, entao a disponibilidade e otimista. Tarifa = bandeirada + "
        "preco por km; nao modela tarifa dinamica nem deslocamento em vazio."),
}

# Modos expostos ao tempo: sofrem o efeito do cenario de chuva.
MODOS_EXPOSTOS: FrozenSet[str] = frozenset({"pe", "bike", "ebike", "patinete"})

# Veiculo individual: no maximo um por viagem (regra do bit F do vertice).
VEICULOS_INDIVIDUAIS: FrozenSet[str] = frozenset(
    k for k, m in MODOS.items() if m.individual)

# Veiculo proprio: embarca na origem, desembarca no destino ou em estacionamento.
MODOS_PESSOAIS: FrozenSet[str] = frozenset(
    k for k, m in MODOS.items() if m.pessoal)

# Micromobilidade compartilhada: a regulamentacao municipal levantada na Etapa 1
# existe apenas no Recife. Olinda e Jaboatao nao tem oferta.
MODOS_COMPARTILHADOS: FrozenSet[str] = frozenset({"ebike", "patinete"})
MUNICIPIOS_COM_MICROMOBILIDADE: FrozenSet[str] = frozenset({"Recife"})

# Onde um veiculo proprio pode ser deixado no meio da viagem (park-and-ride,
# bicicletario). E o que sustenta as combinacoes bicicleta+metro e carro+metro.
TIPOS_COM_ESTACIONAMENTO: FrozenSet[str] = frozenset({"estacao", "terminal"})


# -------------------------------------------------------------------- pontos
@dataclass(frozen=True)
class Ponto:
    id: str
    nome: str
    tipo: str          # origem_destino | estacao | terminal | parada | ponto_micro | via
    lat: float
    lon: float
    municipio: str


# Coordenadas VERIFICADAS, nao de memoria. A primeira versao desta lista foi
# montada de cabeca e estava errada em quase tudo: a Igreja da Se a ~790 m do
# lugar, a Estacao Tancredo Neves a 3,3 km, uma estacao que nao existe ("Largo da
# Paz") e duas que faltavam (Porta Larga, Monte dos Guararapes). Rota errada
# comecava ali.
#
# Fontes:
#   estacoes e igrejas   -> nos do OpenStreetMap via Overpass (dados/estacoes_osm.json)
#   pontos de rua        -> pontos de manobra da rota real do OSRM entre as duas
#                           igrejas (dados/rota_referencia_steps.json), ou o ponto
#                           de via mais proximo devolvido pelo servico "nearest"
#                           do OSRM, conferido pelo NOME da via (dados/nearest.json)
PONTOS: List[Ponto] = [
    # --- Olinda -------------------------------------------------------------
    Ponto("se_olinda",        "Igreja da Sé (Alto da Sé)",           "origem_destino", -8.01383, -34.84910, "Olinda"),
    Ponto("carmo",            "Praça do Carmo",                      "parada",         -8.01703, -34.84836, "Olinda"),
    Ponto("olinda_agamenon",  "Av. Agamenon Magalhães (Olinda)",     "parada",         -8.01903, -34.86113, "Olinda"),
    # --- Recife: centro -----------------------------------------------------
    Ponto("cruz_cabuga",      "Av. Cruz Cabugá (Santo Amaro)",       "parada",         -8.03809, -34.87029, "Recife"),
    Ponto("boa_vista",        "Boa Vista (R. Gervásio Pires)",       "parada",         -8.05449, -34.88329, "Recife"),
    Ponto("recife_antigo",    "Marco Zero",                          "ponto_micro",    -8.06339, -34.87148, "Recife"),
    Ponto("sto_antonio",      "Av. Dantas Barreto (Santo Antônio)",  "parada",         -8.06697, -34.87951, "Recife"),
    Ponto("est_recife",       "Estação Recife",          "terminal",       -8.06917, -34.88537, "Recife"),
    Ponto("sao_jose",         "São José (R. Imperial)",              "parada",         -8.07460, -34.89018, "Recife"),
    Ponto("joana_bezerra",    "Estação Joana Bezerra",               "estacao",        -8.07321, -34.89539, "Recife"),
    Ponto("ponte_pg",         "Ponte Paulo Guerra",                  "via",            -8.08275, -34.89084, "Recife"),
    Ponto("pina",             "Pina (Av. Herculano Bandeira)",       "ponto_micro",    -8.08451, -34.88927, "Recife"),
    # --- Recife: Boa Viagem -------------------------------------------------
    Ponto("df_norte",         "Av. Domingos Ferreira (norte)",       "parada",         -8.09290, -34.88530, "Recife"),
    Ponto("df_centro",        "Av. Domingos Ferreira (centro)",      "parada",         -8.11500, -34.89500, "Recife"),
    Ponto("jequitinhonha",    "Av. Visconde de Jequitinhonha",       "parada",         -8.13039, -34.90255, "Recife"),
    Ponto("bv_norte",         "Orla de Boa Viagem (norte)",          "ponto_micro",    -8.10048, -34.88462, "Recife"),
    Ponto("praca_bv",         "Praça de Boa Viagem",                 "ponto_micro",    -8.13170, -34.90138, "Recife"),
    Ponto("setubal",          "Orla de Boa Viagem (sul)",            "ponto_micro",    -8.13892, -34.90241, "Recife"),
    # --- Linha Sul do metro (CBTU), na ordem real das estacoes --------------
    Ponto("imbiribeira",      "Estação Imbiribeira",                 "estacao",        -8.09020, -34.90751, "Recife"),
    Ponto("antonio_falcao",   "Estação Antônio Falcão",              "estacao",        -8.10989, -34.90908, "Recife"),
    Ponto("shopping",         "Estação Shopping",                    "estacao",        -8.11620, -34.91055, "Recife"),
    Ponto("tancredo_neves",   "Estação Tancredo Neves",              "estacao",        -8.12227, -34.91182, "Recife"),
    Ponto("aeroporto",        "Estação Aeroporto",                   "estacao",        -8.13417, -34.91467, "Recife"),
    Ponto("porta_larga",      "Estação Porta Larga",                 "estacao",        -8.14706, -34.91762, "Recife"),
    Ponto("monte_guararapes", "Estação Monte dos Guararapes",        "estacao",        -8.15446, -34.92019, "Jaboatao"),
    Ponto("prazeres",         "Estação Prazeres",                    "estacao",        -8.16110, -34.92677, "Jaboatao"),
    Ponto("cajueiro_seco",    "TI Cajueiro Seco",                    "terminal",       -8.16840, -34.93408, "Jaboatao"),
    # --- Jaboatao dos Guararapes -------------------------------------------
    Ponto("ayrton_senna",     "Av. Ayrton Senna (Piedade)",          "parada",         -8.15880, -34.91322, "Jaboatao"),
    Ponto("piedade_orla",     "Orla de Piedade",                     "via",            -8.16328, -34.91265, "Jaboatao"),
    Ponto("igreja_piedade",   "Igreja de N. Sra. da Piedade",        "origem_destino", -8.16850, -34.91541, "Jaboatao"),
]

PONTO_POR_ID: Dict[str, Ponto] = {p.id: p for p in PONTOS}


# ------------------------------------------------------------ pontos de recarga
@dataclass(frozen=True)
class Recarga:
    id: str
    ponto: str          # ponto da rede ao qual o eletroposto esta associado
    nome: str
    tipo: str           # "rapido" | "semirrapido"
    potencia_kw: float
    tempo_min: float    # parada tipica para uma recarga parcial util
    custo: float        # R$ da parada


# Eletropostos plausiveis ao longo do corredor. NAO sao dados oficiais: sao
# posicoes aproximadas em pontos ja modelados da rede, para permitir testar a
# funcionalidade de parada para recarga. Em producao devem vir de uma base de
# eletropostos (PlugShare, MobiE, concessionarias) com disponibilidade real.
RECARGAS: List[Recarga] = [
    Recarga("rec_cruz_cabuga",   "cruz_cabuga",   "Eletroposto Av. Cruz Cabugá",
            "semirrapido", 22.0, 50.0, 22.00),
    Recarga("rec_recife_antigo", "recife_antigo", "Eletroposto Bairro do Recife",
            "rapido", 50.0, 25.0, 26.00),
    Recarga("rec_est_recife",    "est_recife",    "Eletroposto Estação Recife",
            "semirrapido", 22.0, 50.0, 22.00),
    Recarga("rec_df_centro",     "df_centro",     "Eletroposto Av. Domingos Ferreira",
            "rapido", 50.0, 25.0, 26.00),
    Recarga("rec_praca_bv",      "praca_bv",      "Eletroposto Praça de Boa Viagem",
            "semirrapido", 22.0, 50.0, 22.00),
    Recarga("rec_jequitinhonha", "jequitinhonha", "Eletroposto Av. Visconde de Jequitinhonha",
            "rapido", 50.0, 25.0, 26.00),
    Recarga("rec_cajueiro_seco", "cajueiro_seco", "Eletroposto TI Cajueiro Seco",
            "rapido", 50.0, 25.0, 26.00),
]

# Modo que o usuario recarrega por conta propria. O carro de aplicativo nao
# entra: quem cuida da carga e o motorista, nao o passageiro.
MODO_RECARREGAVEL = "carro"


# -------------------------------------------------------------------- trechos
@dataclass(frozen=True)
class Trecho:
    u: str
    v: str
    modos: Tuple[str, ...]
    seguranca: float          # indice proxy em [0,1] - quanto maior, mais seguro
    acessivel: bool
    infra: str
    dist_km: float = 0.0      # 0.0 => calculada por haversine x sinuosidade
    sinuosidade: float = 1.15
    classe: str = "arterial"  # expressa | arterial | coletora | local | ciclovia | trilho


# ------------------------------------------------ velocidade dos motorizados
# Uma versao anterior dava a cada trecho uma "classe viaria" escolhida a mao
# (expressa, arterial, local...) e multiplicava a velocidade por ela. Foi o que
# fez a rota de carro sair pela Av. Sul e pela Imbiribeira, passando pelo
# aeroporto: eu tinha classificado esses trechos como expressos. Classificacao
# a mao e palpite, e palpite produz rota errada.
#
# Agora o tempo dos modos motorizados vem do roteador real (OSRM sobre o
# OpenStreetMap), que usa o tipo e o limite de velocidade de cada via. O OSRM da
# o tempo em FLUXO LIVRE; o Recife nao anda em fluxo livre. O indice TomTom de
# congestionamento do Recife (64,7%, Etapa 1) e definido exatamente como o tempo
# extra de viagem sobre o fluxo livre - logo, tempo tipico = fluxo livre x 1,647.
FATOR_CONGESTIONAMENTO = 1.647
# Onibus para em ponto: embarque, desembarque e aceleracao. Sem GTFS nao ha
# como medir linha a linha; 35% sobre o tempo do carro e ordem de grandeza.
FATOR_PARADAS_ONIBUS = 1.35
# Para quem anda ou pedala, mao unica nao existe. A distancia vem da rota real a
# pe / de bicicleta (geometria.construir_ativos). So sem esse cache vale o
# fallback: se a distancia de carro passa de 1,6x a linha reta, ela embute um
# contorno que o pedestre nao faz e vale a estimativa 1,3x reta.
LIMITE_CONTORNO = 1.6
SINUOSIDADE_A_PE = 1.3

MODOS_MOTORIZADOS: FrozenSet[str] = frozenset({"onibus", "carro", "carro_app"})
MODOS_ATALHO: FrozenSet[str] = frozenset({"carro", "carro_app"})
MODOS_DUAS_RODAS: FrozenSet[str] = frozenset({"bike", "ebike", "patinete"})

# Mobilidade reduzida. A primeira versao do cenario acessivel so removia
# bicicletas e trechos sem acessibilidade - e deixava a pessoa caminhar a
# vontade: a opcao "menor custo" virou estacionar no centro e andar 13 km
# (2 h 44) ate Piedade, porque andar e gratis e nao emite. Para quem usa cadeira
# de rodas ou apoio, caminhada e so acesso curto. Dois parametros, explicitos:
VEL_PE_ACESSIVEL = 3.0          # km/h
LIMITE_PE_ACESSIVEL_KM = 0.8    # por trecho; os trechos curtos nao encadeiam longe

# Ciclovia segregada: sem semaforo nem disputa com carro. Unico efeito de classe
# que sobrou, e so sobre as duas rodas.
BONUS_CICLOVIA = 1.10


# Conjuntos de modos admitidos por tipo de infraestrutura. Carro e carro de app
# NAO aparecem aqui: eles nao percorrem estes trechos, e sim arestas-atalho
# calculadas pelo roteador real (ver construir_grafo).
ATIVO = ("pe", "bike", "ebike", "patinete")
ATIVO_ONIBUS = ATIVO + ("onibus",)
METRO = ("metro",)

TRECHOS: List[Trecho] = [
    # ---- corredor principal: o mesmo caminho que a rota real de carro faz ---
    Trecho("se_olinda", "carmo",               ATIVO, 0.70, False, "Ladeira da Se (paralelepipedo)", classe="local"),
    Trecho("carmo", "olinda_agamenon",         ATIVO_ONIBUS, 0.65, True, "Av. Sigismundo Goncalves / Pres. Kennedy"),
    Trecho("olinda_agamenon", "cruz_cabuga",   ATIVO_ONIBUS, 0.55, True, "Av. Agamenon Magalhaes"),
    Trecho("cruz_cabuga", "boa_vista",         ATIVO_ONIBUS, 0.60, True, "Av. Cruz Cabuga"),
    Trecho("boa_vista", "est_recife",          ATIVO_ONIBUS, 0.60, True, "R. Gervasio Pires / R. da Santa Cruz"),
    Trecho("est_recife", "sao_jose",           ATIVO_ONIBUS, 0.60, True, "Viaduto Joaquim Cardoso / R. Imperial"),
    Trecho("sao_jose", "ponte_pg",             ATIVO_ONIBUS, 0.55, True, "R. Imperial / Cabanga"),
    Trecho("ponte_pg", "pina",                 ATIVO_ONIBUS, 0.65, True, "Ponte Paulo Guerra"),
    Trecho("pina", "df_norte",                 ATIVO_ONIBUS, 0.70, True, "Av. Herculano Bandeira / Domingos Ferreira"),
    Trecho("df_norte", "df_centro",            ATIVO_ONIBUS, 0.70, True, "Av. Domingos Ferreira"),
    Trecho("df_centro", "jequitinhonha",       ATIVO_ONIBUS, 0.70, True, "Av. Domingos Ferreira"),
    Trecho("jequitinhonha", "ayrton_senna",    ATIVO_ONIBUS, 0.60, True, "Av. Visconde de Jequitinhonha"),
    Trecho("ayrton_senna", "igreja_piedade",   ATIVO_ONIBUS, 0.65, True, "Av. Ayrton Senna"),

    # ---- centro do Recife --------------------------------------------------
    Trecho("boa_vista", "recife_antigo",       ATIVO, 0.70, True, "Ponte da Boa Vista / Bairro do Recife"),
    Trecho("recife_antigo", "sto_antonio",     ATIVO, 0.70, True, "Ponte Mauricio de Nassau"),
    Trecho("sto_antonio", "est_recife",        ATIVO_ONIBUS, 0.70, True, "Av. Dantas Barreto"),
    Trecho("sao_jose", "joana_bezerra",        ATIVO_ONIBUS, 0.55, True, "acesso a Estacao Joana Bezerra"),

    # ---- orla: calcadao e ciclovia de Boa Viagem ---------------------------
    Trecho("pina", "bv_norte",                 ATIVO, 0.85, True, "Orla do Pina", classe="ciclovia"),
    Trecho("bv_norte", "praca_bv",             ATIVO, 0.90, True, "Calcadao de Boa Viagem (ciclovia)", classe="ciclovia"),
    Trecho("praca_bv", "setubal",              ATIVO, 0.90, True, "Calcadao de Boa Viagem (ciclovia)", classe="ciclovia"),
    Trecho("setubal", "piedade_orla",          ATIVO, 0.80, True, "Orla de Setubal / Piedade", classe="ciclovia"),
    Trecho("piedade_orla", "igreja_piedade",   ATIVO, 0.70, True, "Piedade"),
    # travessias entre a orla e a Av. Domingos Ferreira
    Trecho("bv_norte", "df_norte",             ATIVO, 0.75, True, "travessia orla - Domingos Ferreira"),
    Trecho("praca_bv", "jequitinhonha",        ATIVO, 0.80, True, "Praça de Boa Viagem"),
    Trecho("piedade_orla", "ayrton_senna",     ATIVO, 0.70, True, "travessia orla - Ayrton Senna"),

    # ---- acessos as estacoes da Linha Sul, que fica ~2 km para o interior ---
    Trecho("imbiribeira", "df_norte",          ATIVO_ONIBUS, 0.55, True, "transversal Imbiribeira - Boa Viagem"),
    Trecho("antonio_falcao", "df_centro",      ATIVO_ONIBUS, 0.55, True, "R. Antonio Falcao"),
    Trecho("shopping", "df_centro",            ATIVO, 0.60, True, "acesso a Estacao Shopping"),
    Trecho("tancredo_neves", "jequitinhonha",  ATIVO_ONIBUS, 0.55, True, "transversal Tancredo Neves"),
    Trecho("aeroporto", "jequitinhonha",       ATIVO, 0.55, True, "acesso a Estacao Aeroporto"),
    Trecho("porta_larga", "ayrton_senna",      ATIVO, 0.55, True, "acesso a Estacao Porta Larga"),
    Trecho("monte_guararapes", "ayrton_senna", ATIVO, 0.55, True, "acesso a Estacao Monte dos Guararapes"),
    Trecho("prazeres", "ayrton_senna",         ATIVO_ONIBUS, 0.55, True, "transversal Prazeres - Piedade"),
    Trecho("cajueiro_seco", "igreja_piedade",  ATIVO_ONIBUS, 0.60, True, "Av. Bernardo Vieira de Melo"),

    # ---- Linha Sul do metro (CBTU), na ordem real --------------------------
    Trecho("est_recife", "joana_bezerra",      METRO, 0.95, True, "Metro Linha Sul", sinuosidade=1.05, classe="trilho"),
    Trecho("joana_bezerra", "imbiribeira",     METRO, 0.95, True, "Metro Linha Sul", sinuosidade=1.05, classe="trilho"),
    Trecho("imbiribeira", "antonio_falcao",    METRO, 0.95, True, "Metro Linha Sul", sinuosidade=1.05, classe="trilho"),
    Trecho("antonio_falcao", "shopping",       METRO, 0.95, True, "Metro Linha Sul", sinuosidade=1.05, classe="trilho"),
    Trecho("shopping", "tancredo_neves",       METRO, 0.95, True, "Metro Linha Sul", sinuosidade=1.05, classe="trilho"),
    Trecho("tancredo_neves", "aeroporto",      METRO, 0.95, True, "Metro Linha Sul", sinuosidade=1.05, classe="trilho"),
    Trecho("aeroporto", "porta_larga",         METRO, 0.95, True, "Metro Linha Sul", sinuosidade=1.05, classe="trilho"),
    Trecho("porta_larga", "monte_guararapes",  METRO, 0.95, True, "Metro Linha Sul", sinuosidade=1.05, classe="trilho"),
    Trecho("monte_guararapes", "prazeres",     METRO, 0.95, True, "Metro Linha Sul", sinuosidade=1.05, classe="trilho"),
    Trecho("prazeres", "cajueiro_seco",        METRO, 0.95, True, "Metro Linha Sul", sinuosidade=1.05, classe="trilho"),
]

# ------------------------------------------------------------ transferencias
# Quais modos admitem troca em cada tipo de ponto. O carro de aplicativo embarca
# e desembarca em qualquer ponto sobre via; o carro proprio precisa de vaga.
TRANSFERENCIA_PERMITIDA: Dict[str, Tuple[str, ...]] = {
    "origem_destino": ("pe", "bike", "ebike", "patinete", "onibus", "carro", "carro_app"),
    "estacao":        ("pe", "metro", "onibus", "bike", "carro", "carro_app"),
    "terminal":       ("pe", "metro", "onibus", "bike", "carro", "carro_app"),
    "parada":         ("pe", "onibus", "carro_app"),
    "ponto_micro":    ("pe", "bike", "ebike", "patinete", "carro_app"),
    "via":            ("pe", "bike", "ebike", "patinete", "carro_app"),
}

# (modo_de, modo_para) -> (tempo_min, custo_extra_R$, desconforto_extra)
# Valores fixos: a Etapa 1 nao identificou GTFS aberto nem API de tempo real,
# entao estes numeros representam a espera TIPICA, nao a espera efetiva.
TRANSFERENCIAS: Dict[Tuple[str, str], Tuple[float, float, float]] = {
    ("pe", "onibus"):      (7.0, 0.0, 0.60),
    ("onibus", "pe"):      (1.0, 0.0, 0.10),
    ("pe", "metro"):       (5.0, 0.0, 0.40),
    ("metro", "pe"):       (2.0, 0.0, 0.10),
    ("pe", "bike"):        (1.0, 0.0, 0.10),
    ("bike", "pe"):        (1.5, 0.0, 0.10),   # prender no bicicletario
    ("pe", "ebike"):       (2.5, 0.0, 0.15),
    ("ebike", "pe"):       (1.0, 0.0, 0.10),
    ("pe", "patinete"):    (2.0, 0.0, 0.15),
    ("patinete", "pe"):    (1.0, 0.0, 0.10),
    ("pe", "carro"):       (2.0, 0.0, 0.05),   # chegar ao carro e destravar
    ("carro", "pe"):       (5.0, CUSTO_ESTACIONAMENTO, 0.20),  # vaga + estacionar
    ("pe", "carro_app"):   (6.0, 0.0, 0.10),   # espera media do motorista
    ("carro_app", "pe"):   (0.5, 0.0, 0.05),
    ("onibus", "metro"):   (4.0, 0.0, 0.30),
    ("metro", "onibus"):   (4.0, 0.0, 0.30),
}

MODOS_TARIFADOS: FrozenSet[str] = frozenset(
    k for k, m in MODOS.items() if m.custo_fixo > 0)
MODOS_INTEGRADOS: FrozenSet[str] = frozenset({"onibus", "metro"})   # integracao VEM (2 h)


# ------------------------------------------- condicoes escolhidas pelo usuario
# Em vez de cenarios fechados, o usuario monta a consulta: quais modais aceita,
# como esta o clima, como esta o transito, quanta seguranca exige. Cada uma
# dessas escolhas vira um fator sobre os pesos das arestas ou uma restricao de
# admissibilidade, aplicados ANTES da busca.

CLIMAS: Dict[str, Dict[str, object]] = {
    "bom": {"rotulo": "Tempo bom", "desconforto": 1.0, "velocidade": 1.00,
            "motorizado": 1.00,
            "descricao": "Condicoes nominais."},
    "chuva_leve": {"rotulo": "Chuva leve", "desconforto": 1.6, "velocidade": 0.90,
                   "motorizado": 1.10,
                   "descricao": "Desconforto dos modos expostos x1,6; "
                                "velocidade a 90%; motorizados +10%."},
    "chuva_forte": {"rotulo": "Chuva forte", "desconforto": 2.6, "velocidade": 0.75,
                    "motorizado": 1.20,
                    "descricao": "Desconforto dos modos expostos x2,6; "
                                 "velocidade a 75%; motorizados +20%."},
}

TRANSITOS: Dict[str, Dict[str, object]] = {
    "livre": {"rotulo": "Livre", "fator": 0.75,
              "descricao": "Fora de pico. Onibus, carro e carro de app 25% mais rapidos."},
    "normal": {"rotulo": "Normal", "fator": 1.00,
               "descricao": "Velocidade comercial media do modelo."},
    "congestionado": {"rotulo": "Congestionado", "fator": 1.45,
                      "descricao": "Pico da manha. O Recife e a capital brasileira mais "
                                   "congestionada (indice TomTom 64,7%); modos motorizados "
                                   "45% mais lentos."},
}

SEGURANCAS: Dict[str, Dict[str, object]] = {
    "indiferente": {"rotulo": "Indiferente", "minimo": 0.0,
                    "descricao": "Usa toda a rede; a seguranca entra apenas no desconforto."},
    "evitar_ruins": {"rotulo": "Evitar trechos ruins", "minimo": 0.55,
                     "descricao": "Remove do grafo os trechos com indice de seguranca "
                                  "abaixo de 0,55."},
    "so_seguros": {"rotulo": "So trechos seguros", "minimo": 0.70,
                   "descricao": "Remove os trechos com indice abaixo de 0,70. Pode nao "
                                "existir rota: o indice e um proxy por tipo de via."},
}


@dataclass(frozen=True)
class Opcoes:
    """O que o usuario escolheu na interface."""
    modos: FrozenSet[str] = frozenset(MODOS)
    clima: str = "bom"
    transito: str = "normal"
    seguranca: str = "indiferente"
    acessivel: bool = False
    recarga: bool = False          # obrigar parada em eletroposto (carro proprio)
    # Nao mandar ninguem a pe ou de duas rodas por via entre as 10% mais
    # perigosas do Recife para aquele tipo de usuario (dado da CTTU, seguranca.py).
    evitar_inseguros: bool = True

    @property
    def recarga_efetiva(self) -> bool:
        # so faz sentido se o carro proprio estiver entre os modais aceitos
        return self.recarga and MODO_RECARREGAVEL in self.modos


@dataclass(frozen=True)
class Cenario:
    """Fatores derivados das opcoes, aplicados as arestas."""
    modos_bloqueados: FrozenSet[str] = frozenset()
    exigir_acessivel: bool = False
    fator_desconforto: float = 1.0       # alpha, sobre modos expostos
    fator_velocidade: float = 1.0        # sobre modos expostos
    fator_tempo_motorizado: float = 1.0  # onibus, carro, carro de app
    seguranca_min: float = 0.0           # corta trechos abaixo deste indice
    evitar_inseguros: bool = True        # corta trecho inseguro para modo exposto


def cenario_de(op: Opcoes) -> Cenario:
    clima = CLIMAS.get(op.clima, CLIMAS["bom"])
    transito = TRANSITOS.get(op.transito, TRANSITOS["normal"])
    seg = SEGURANCAS.get(op.seguranca, SEGURANCAS["indiferente"])
    # o congestionamento multiplica o efeito do clima sobre os motorizados
    motorizado = float(clima["motorizado"]) * float(transito["fator"])
    # a pe nunca e removido: e o modo de acesso e egresso de toda viagem
    bloqueados = frozenset(k for k in MODOS if k not in op.modos and k != "pe")
    # Mobilidade reduzida exclui as duas rodas. Isto se perdeu uma vez, quando os
    # cenarios fixos viraram opcoes: o cenario so removia trechos inacessiveis e
    # continuava oferecendo bicicleta a quem pediu rota acessivel.
    if op.acessivel:
        bloqueados |= MODOS_DUAS_RODAS
    return Cenario(
        modos_bloqueados=bloqueados,
        exigir_acessivel=op.acessivel,
        fator_desconforto=float(clima["desconforto"]),
        fator_velocidade=float(clima["velocidade"]),
        fator_tempo_motorizado=motorizado,
        seguranca_min=float(seg["minimo"]),
        evitar_inseguros=op.evitar_inseguros,
    )


OPCOES_PADRAO = Opcoes()
CENARIO_BASE = cenario_de(OPCOES_PADRAO)


# -------------------------------------------------------------------- perfis
PERFIS: Dict[str, Dict[str, object]] = {
    "mais_rapida":   {"rotulo": "Mais rápida",   "pesos": (0.70, 0.10, 0.10, 0.10)},
    "menor_custo":   {"rotulo": "Menor custo",   "pesos": (0.10, 0.70, 0.10, 0.10)},
    "menor_emissao": {"rotulo": "Menor emissão", "pesos": (0.10, 0.10, 0.70, 0.10)},
    "menos_esforco": {"rotulo": "Menos esforço", "pesos": (0.10, 0.10, 0.10, 0.70)},
    "equilibrada":   {"rotulo": "Equilibrada",   "pesos": (0.25, 0.25, 0.25, 0.25)},
}

# Escalas de normalizacao do custo escalarizado. Sem elas a emissao dominaria
# numericamente os demais criterios. Ajustadas ao corredor de ~24 km, agora com
# modos que podem custar dezenas de reais.
ESCALAS: VetorCusto = (90.0, 40.0, 2000.0, 25.0)


# ------------------------------------------------------------------ geometria
def haversine_km(a: Ponto, b: Ponto) -> float:
    """Distancia em linha reta entre dois pontos geograficos."""
    r = 6371.0
    dlat = math.radians(b.lat - a.lat)
    dlon = math.radians(b.lon - a.lon)
    lat1 = math.radians(a.lat)
    lat2 = math.radians(b.lat)
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h))


def distancia_trecho(t: Trecho, modo: Optional[str] = None) -> float:
    """Extensao do trecho para aquele modal.

    metro        -> linha reta x 1,05 (trilho quase reto; o OSRM nao roteia trilho)
    onibus       -> distancia de CARRO do roteador real, mao unica incluida
    a pe / 2 rodas -> distancia de carro, a menos que ela embuta contorno de mao
                    unica (> 1,6x a reta); ai 1,3x a reta. Usa o menor dos dois
                    sentidos, porque pedestre nao respeita mao unica.
    Sem a matriz do OSRM, tudo cai na estimativa por linha reta.
    """
    if t.dist_km > 0:
        return t.dist_km
    reta = haversine_km(PONTO_POR_ID[t.u], PONTO_POR_ID[t.v])
    if "metro" in t.modos:
        return reta * t.sinuosidade

    import geometria                       # tardio: quebra o ciclo de import
    if modo is not None and modo != "onibus":
        # a pe e duas rodas: rota real sem mao unica (FOSSGIS), ja com o caminho
        # do carro como alternativa onde ele e mais curto (geometria.construir_ativos)
        item = geometria.item_ativo(t.u, t.v, modo)
        if item:
            return float(item["dist_km"])  # type: ignore[arg-type]
    ida = geometria.carro(t.u, t.v)
    volta = geometria.carro(t.v, t.u)
    if modo == "onibus" and ida:
        return ida[0]
    candidatos = [x[0] for x in (ida, volta) if x]
    if candidatos:
        menor = min(candidatos)
        if menor <= reta * LIMITE_CONTORNO:
            return menor
    return reta * SINUOSIDADE_A_PE


# ----------------------------------------------------------------- estruturas
@dataclass
class Aresta:
    destino: No
    tempo: float          # minutos
    custo: float          # R$
    co2: float            # g CO2eq
    desconforto: float    # adimensional
    dist_km: float
    tipo: str             # "deslocamento" | "transferencia"
    rotulo: str = ""
    infra: str = ""

    @property
    def vetor(self) -> VetorCusto:
        return (self.tempo, self.custo, self.co2, self.desconforto)


@dataclass
class GrafoMultimodal:
    adj: Dict[No, List[Aresta]] = field(default_factory=dict)

    def add_no(self, n: No) -> None:
        self.adj.setdefault(n, [])

    def add_aresta(self, u: No, a: Aresta) -> None:
        self.add_no(u)
        self.add_no(a.destino)
        self.adj[u].append(a)

    @property
    def V(self) -> int:
        return len(self.adj)

    @property
    def E(self) -> int:
        return sum(len(v) for v in self.adj.values())

    def vizinhos(self, u: No) -> List[Aresta]:
        return self.adj.get(u, [])

    def aresta_entre(self, u: No, v: No) -> Optional[Aresta]:
        melhor: Optional[Aresta] = None
        for a in self.adj.get(u, []):
            if a.destino == v and (melhor is None or a.tempo < melhor.tempo):
                melhor = a
        return melhor


# ----------------------------------------------------------- custos de aresta
def custo_deslocamento(t: Trecho, modo: str, cen: Cenario,
                       flag: int, rec: int) -> Aresta:
    """Vetor de custo de um trecho percorrido em um modo, sob um cenario."""
    m = MODOS[modo]
    dist = distancia_trecho(t, modo)
    exposto = modo in MODOS_EXPOSTOS

    tempo = None
    if modo == "onibus":
        import geometria
        osrm = geometria.carro(t.u, t.v)
        if osrm:
            tempo = (osrm[1] * FATOR_CONGESTIONAMENTO * FATOR_PARADAS_ONIBUS
                     * cen.fator_tempo_motorizado)
    if tempo is None:
        vel = m.velocidade
        if modo == "pe" and cen.exigir_acessivel:
            vel = VEL_PE_ACESSIVEL
        if modo in MODOS_DUAS_RODAS and t.classe == "ciclovia":
            vel *= BONUS_CICLOVIA
        if exposto:
            vel *= cen.fator_velocidade
        tempo = (dist / vel) * 60.0
        if modo in MODOS_MOTORIZADOS:
            tempo *= cen.fator_tempo_motorizado

    # A micromobilidade compartilhada cobra por minuto, nao por quilometro:
    # sob chuva a viagem fica mais lenta e, por consequencia, mais cara.
    custo = dist * m.custo_km + tempo * m.custo_min
    co2 = dist * m.co2_km

    alpha = cen.fator_desconforto if exposto else 1.0
    desconforto = dist * m.desconforto_km * (2.0 - t.seguranca) * alpha
    if not t.acessivel:
        desconforto *= 1.30

    return Aresta(
        destino=(t.v, modo, flag, rec), tempo=tempo, custo=custo, co2=co2,
        desconforto=desconforto, dist_km=dist, tipo="deslocamento",
        rotulo="%s %.2f km" % (m.rotulo, dist), infra=t.infra,
    )


# Seguranca atribuida a uma viagem de carro pelo roteador: o trajeto real nao e
# um trecho do modelo, entao nao ha indice proprio. Valor medio da rede.
SEGURANCA_VIA_CARRO = 0.80


def custo_atalho(u: str, v: str, modo: str, cen: Cenario,
                 flag: int, rec: int) -> Aresta:
    """Aresta-atalho de carro ou carro de app entre dois pontos quaisquer.

    O carro nao e obrigado a passar pelos pontos do modelo: vai de u a v pelo
    caminho que o roteador real escolheria. E a mesma ideia dos "transfer
    graphs" da literatura revisada na Etapa 1 (Potthoff e Sauer, 2022): a rede
    de transporte publico fica explicita, e o trecho por via e pre-calculado
    sobre a malha viaria completa.
    """
    import geometria
    m = MODOS[modo]
    osrm = geometria.carro(u, v)
    if osrm:
        dist, t_livre = osrm
        tempo = t_livre * FATOR_CONGESTIONAMENTO * cen.fator_tempo_motorizado
    else:
        # sem a matriz: estimativa grosseira, so para o app nao quebrar
        dist = haversine_km(PONTO_POR_ID[u], PONTO_POR_ID[v]) * 1.35
        tempo = dist / m.velocidade * 60.0 * cen.fator_tempo_motorizado
    return Aresta(
        destino=(v, modo, flag, rec), tempo=tempo,
        custo=dist * m.custo_km + tempo * m.custo_min,
        co2=dist * m.co2_km,
        desconforto=dist * m.desconforto_km * (2.0 - SEGURANCA_VIA_CARRO),
        dist_km=dist, tipo="deslocamento",
        rotulo="%s %.2f km" % (m.rotulo, dist),
        infra="rota por via (OpenStreetMap)",
    )


def _inverter(t: Trecho) -> Trecho:
    return Trecho(t.v, t.u, t.modos, t.seguranca, t.acessivel, t.infra,
                  t.dist_km, t.sinuosidade, t.classe)


def oferta_no_ponto(p: Ponto, modo: str) -> bool:
    """Assimetria regulatoria levantada na Etapa 1.

    A micromobilidade compartilhada so esta regulamentada no Recife; nem Olinda
    (origem) nem Jaboatao (destino) tem oferta. Bicicleta propria e automovel
    nao sao afetados.
    """
    if modo not in MODOS_COMPARTILHADOS:
        return True
    return p.municipio in MUNICIPIOS_COM_MICROMOBILIDADE


def pode_embarcar(p: Ponto, modo: str, origem_id: str) -> bool:
    """Onde a viagem pode PEGAR um veiculo individual."""
    if modo in MODOS_PESSOAIS:
        return p.id == origem_id          # o veiculo proprio esta na origem
    return oferta_no_ponto(p, modo)


def pode_desembarcar(p: Ponto, modo: str, destino_id: str) -> bool:
    """Onde a viagem pode LARGAR um veiculo individual."""
    if modo in MODOS_PESSOAIS:
        return p.id == destino_id or p.tipo in TIPOS_COM_ESTACIONAMENTO
    return oferta_no_ponto(p, modo)


# ------------------------------------------------------- construcao do grafo
RECARGA_POR_PONTO: Dict[str, Recarga] = {r.ponto: r for r in RECARGAS}


def construir_grafo(opcoes: Optional[Opcoes] = None,
                    origem_id: str = "se_olinda",
                    destino_id: str = "igreja_piedade") -> GrafoMultimodal:
    """Expande cada ponto fisico em um no por (modo, estado) e liga as camadas.

    Estados do vertice:
      F  ja embarcou em veiculo individual. Camadas de veiculo individual so
         existem com F=1 e so se entra nelas a partir de F=0, de modo que uma
         viagem usa no maximo UM veiculo individual. As camadas coletivas
         (a pe, onibus, metro) existem nos dois estados, o que preserva a pe +
         metro, bicicleta + metro (bicicletario) e carro + metro (park-and-ride).
      R  ja passou por eletroposto. So e desdobrado quando o usuario pede parada
         para recarga; caso contrario todo o grafo fica em R=0 e nao cresce.

    Custo de construcao: O(|T| * |M| + |P| * |M|^2), linear no tamanho da rede.
    """
    op = opcoes or OPCOES_PADRAO
    cen = cenario_de(op)
    g = GrafoMultimodal()
    recs = (0, 1) if op.recarga_efetiva else (0,)

    def modo_ok(modo: str) -> bool:
        return modo not in cen.modos_bloqueados

    # 1) Arestas de deslocamento (bidirecionais dentro de cada camada modal)
    for t in TRECHOS:
        if cen.exigir_acessivel and not t.acessivel:
            continue
        if t.seguranca < cen.seguranca_min:
            continue
        pu, pv = PONTO_POR_ID[t.u], PONTO_POR_ID[t.v]
        for modo in t.modos:
            if not modo_ok(modo):
                continue
            if (cen.exigir_acessivel and modo == "pe"
                    and distancia_trecho(t, "pe") > LIMITE_PE_ACESSIVEL_KM):
                continue
            # Seguranca viaria medida: quem anda ou pedala nao e mandado por via
            # entre as 10% mais perigosas do Recife para o seu tipo de usuario.
            # Onibus e carro nao sao cortados - quem esta dentro do veiculo nao
            # e o usuario exposto que esses sinistros medem.
            if cen.evitar_inseguros and modo in MODOS_EXPOSTOS:
                import seguranca
                if seguranca.inseguro_para(t.u, t.v, modo):
                    continue
            # o trecho so existe na camada se o modo tem oferta nos dois extremos
            if not (oferta_no_ponto(pu, modo) and oferta_no_ponto(pv, modo)):
                continue
            # veiculo individual so e percorrido com o bit ja marcado
            estados = (1,) if modo in VEICULOS_INDIVIDUAIS else (0, 1)
            for f in estados:
                for r in recs:
                    g.add_aresta((t.u, modo, f, r),
                                 custo_deslocamento(t, modo, cen, f, r))
                    g.add_aresta((t.v, modo, f, r),
                                 custo_deslocamento(_inverter(t), modo, cen, f, r))

    # 1b) Arestas-atalho de carro e carro de app, calculadas sobre a malha viaria
    #     real. So entre os pontos onde uma perna de carro pode comecar ou
    #     terminar - o resto do caminho e problema do roteador, nao do grafo.
    estacoes = [p.id for p in PONTOS if p.tipo in TIPOS_COM_ESTACIONAMENTO]
    eletropostos = [r.ponto for r in RECARGAS] if op.recarga_efetiva else []
    pares: Dict[str, set] = {"carro": set(), "carro_app": set()}
    if modo_ok("carro"):
        alvos = set(estacoes) | {destino_id} | set(eletropostos)
        pares["carro"] |= {(origem_id, x) for x in alvos}
        for e in eletropostos:                       # origem -> eletroposto -> alvo
            pares["carro"] |= {(e, x) for x in set(estacoes) | {destino_id}}
    if modo_ok("carro_app"):
        pontas = set(estacoes) | {origem_id, destino_id}
        pares["carro_app"] |= {(origem_id, x) for x in pontas}
        pares["carro_app"] |= {(x, destino_id) for x in pontas}
    for modo, conj in pares.items():
        for u, v in conj:
            if u == v:
                continue
            for r in recs:
                g.add_aresta((u, modo, 1, r), custo_atalho(u, v, modo, cen, 1, r))

    # 2) Arestas de transferencia (troca de camada modal no mesmo ponto)
    for p in PONTOS:
        modos_ok = TRANSFERENCIA_PERMITIDA[p.tipo]
        # Na origem e no destino da consulta sempre se pode pegar ou deixar o
        # proprio carro, a propria bicicleta ou um carro de app, seja qual for o
        # tipo do ponto: e dali que a pessoa sai e e ali que ela chega. Sem isso,
        # quem saia do Marco Zero nao conseguia usar o proprio carro, e quem ia
        # de carro ate a Praca de Boa Viagem era obrigado a estacionar numa
        # estacao de metro e terminar a pe.
        if p.id in (origem_id, destino_id):
            modos_ok = tuple(set(modos_ok) | {"carro", "carro_app", "bike"})
        for (m_de, m_para), (dt, dc, dd) in TRANSFERENCIAS.items():
            if m_de not in modos_ok or m_para not in modos_ok:
                continue
            if not modo_ok(m_de) or not modo_ok(m_para):
                continue

            # Tarifa cobrada ao embarcar, e nao no deslocamento. A integracao
            # temporal VEM (2 h) isenta a troca direta onibus <-> metro.
            integrado = m_de in MODOS_INTEGRADOS and m_para in MODOS_INTEGRADOS
            cobra = m_para in MODOS_TARIFADOS and not integrado
            tarifa = MODOS[m_para].custo_fixo if cobra else 0.0

            # quais pares de estado F esta transferencia liga
            if m_para in VEICULOS_INDIVIDUAIS:            # embarque no veiculo
                if not pode_embarcar(p, m_para, origem_id):
                    continue
                pares_f = [(0, 1)]
            elif m_de in VEICULOS_INDIVIDUAIS:            # desembarque do veiculo
                if not pode_desembarcar(p, m_de, destino_id):
                    continue
                pares_f = [(1, 1)]
            else:                                         # troca entre coletivos
                pares_f = [(0, 0), (1, 1)]

            for f_de, f_para in pares_f:
                for r in recs:                            # a troca preserva R
                    u, v = (p.id, m_de, f_de, r), (p.id, m_para, f_para, r)
                    if u not in g.adj and v not in g.adj:
                        continue
                    # entrar num veiculo que nao anda dali, ou sair de um que
                    # nunca chega ali, cria no morto: so incha o grafo
                    if m_para in VEICULOS_INDIVIDUAIS and not g.vizinhos(v):
                        continue
                    if m_de in VEICULOS_INDIVIDUAIS and u not in g.adj:
                        continue
                    g.add_aresta(u, Aresta(
                        destino=v, tempo=dt, custo=dc + tarifa, co2=0.0,
                        desconforto=dd, dist_km=0.0, tipo="transferencia",
                        rotulo="transferencia %s -> %s" % (MODOS[m_de].rotulo,
                                                           MODOS[m_para].rotulo),
                        infra=p.nome,
                    ))

    # 3) Paradas para recarga: unica aresta que vira o bit R de 0 para 1.
    #    Como o destino so e aceito com R=1 (ver motor.nos_destino), obrigar a
    #    recarga vira uma restricao estrutural, resolvida pela mesma busca.
    if op.recarga_efetiva:
        for rec in RECARGAS:
            u = (rec.ponto, MODO_RECARREGAVEL, 1, 0)
            if u not in g.adj:
                continue                  # o eletroposto nao esta sobre a rede viaria
            g.add_aresta(u, Aresta(
                destino=(rec.ponto, MODO_RECARREGAVEL, 1, 1),
                tempo=rec.tempo_min, custo=rec.custo, co2=0.0,
                desconforto=0.15, dist_km=0.0, tipo="recarga",
                rotulo="recarga %s (%.0f kW)" % ("rápida" if rec.tipo == "rapido" else "semirrápida", rec.potencia_kw),
                infra=rec.nome,
            ))
    return g


def nos_do_ponto(g: GrafoMultimodal, ponto_id: str) -> List[No]:
    return [n for n in g.adj if n[0] == ponto_id]


def propriedades(g: GrafoMultimodal) -> Dict[str, object]:
    return {
        "V": g.V,
        "E": g.E,
        "densidade": round(g.E / g.V, 2) if g.V else 0.0,
        "pontos": len(PONTOS),
        "trechos": len(TRECHOS),
        "modos": len(MODOS),
    }


if __name__ == "__main__":
    combos = [
        ("todos os modais", Opcoes()),
        ("chuva forte", Opcoes(clima="chuva_forte")),
        ("congestionado", Opcoes(transito="congestionado")),
        ("so trechos seguros", Opcoes(seguranca="so_seguros")),
        ("mobilidade reduzida", Opcoes(
            modos=frozenset({"pe", "metro", "onibus", "carro", "carro_app"}),
            acessivel=True)),
        ("sem automovel", Opcoes(
            modos=frozenset({"pe", "bike", "ebike", "patinete", "metro", "onibus"}))),
        ("com parada de recarga", Opcoes(recarga=True)),
    ]
    for rotulo, op in combos:
        g = construir_grafo(op)
        pr = propriedades(g)
        print("%-24s |V|=%4d  |E|=%4d  densidade=%.2f"
              % (rotulo, pr["V"], pr["E"], pr["densidade"]))

    a, b = PONTO_POR_ID["se_olinda"], PONTO_POR_ID["igreja_piedade"]
    print("")
    print("Distancia em linha reta Se de Olinda -> Igreja de Piedade: %.2f km"
          % haversine_km(a, b))
    print("Eletropostos modelados: %d" % len(RECARGAS))

    d = 24.0
    print("")
    print("Custo de percorrer ~%.0f km em cada modal (sem transferencias):" % d)
    print("  %-34s %6s %8s %10s %10s" % ("modal", "km/h", "min", "R$", "g CO2eq"))
    for k, m in MODOS.items():
        t = d / m.velocidade * 60.0
        custo = d * m.custo_km + t * m.custo_min + m.custo_fixo
        print("  %-34s %6.1f %8.1f %10.2f %10.0f"
              % (m.rotulo, m.velocidade, t, custo, d * m.co2_km))
