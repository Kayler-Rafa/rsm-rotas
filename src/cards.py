# -*- coding: utf-8 -*-
"""Opcoes de viagem do app do usuario (as "cards").

Separado de motor.py, que fica com o nucleo (descricao de rota, consultas da
tela tecnica, viabilidade, NSGA-II). Aqui: uma fronteira de Pareto lida por
perfil, card de transporte publico, variante de recarga, recomendacao pelas
condicoes, seguranca viaria por trecho, aviso de contramao e o que o filtro de
seguranca evitou. motor.opcoes_de_viagem continua existindo (reexportado).
"""
from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Optional

import algoritmos as alg
import clima as clima_mod
import geometria
import seguranca
from motor import _coords, _motivo_sem_rota, descrever_rota, nos_destino
from rede_rsm import (
    MODOS, PERFIS, PONTO_POR_ID, GrafoMultimodal, No, Opcoes, construir_grafo,
    haversine_km, propriedades,
)

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

    contra = [c for s in rota["segmentos"]              # type: ignore[union-attr]
              for c in (s.get("contramao") or [])]
    if contra:
        c = contra[0]
        avisos.append({"nivel": "aviso", "texto":
                       "Entre %s e %s a rota ignora a mão única (%s km contra %s km "
                       "respeitando). Pedalar na contramão é infração (CTB art. 58) "
                       "onde não há sinalização: desça e empurre nesse trecho."
                       % (c["de_nome"], c["para_nome"],
                          ("%.2f" % c["km"]).replace(".", ","),
                          ("%.2f" % c["km_legal"]).replace(".", ","))})

    if "ebike" in modos or "patinete" in modos:
        avisos.append({"nivel": "info", "texto":
                       "Cobrança por minuto; a disponibilidade da frota não é "
                       "consultada em tempo real."})
    return avisos


USUARIO_ROTULO = {"pedestre": ("a pé", "quem anda"), "ciclista": ("de bicicleta", "quem pedala")}


def _seguranca_da_rota(rota: Dict[str, object], turno: str = "dia") -> Dict[str, object]:
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
            nivel = seguranca.nivel(a, b, modo, turno)
            risco = seguranca.risco_trecho(a, b, modo, turno)
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
                "sinistros_noite": vias[0].get("%s_noite" % usuario) if vias else None,
                "fator_noite": vias[0].get("fator_noite_%s" % usuario) if vias else None,
                "fatais": vias[0]["fatais"] if vias else None,
                "cobertura": risco.get("cobertura"),
            })
    return {
        "turno": turno,
        "trechos": trechos,
        "inseguros": [t for t in trechos if t["nivel"] == "inseguro"],
        "atencao": [t for t in trechos if t["nivel"] == "atencao"],
        "sem_dado": sum(1 for t in trechos if t["nivel"] == "sem_dado"),
    }


# Card fora dos perfis de TOPSIS: a melhor viagem SO de transporte publico.
PERFIL_TRANSPORTE_PUBLICO = "transporte_publico"
ROTULO_TRANSPORTE_PUBLICO = "Transporte público"
MODOS_TRANSPORTE_PUBLICO = frozenset({"pe", "onibus", "metro"})


def _rotulo_perfil(perfil_id: str) -> str:
    if perfil_id == PERFIL_TRANSPORTE_PUBLICO:
        return ROTULO_TRANSPORTE_PUBLICO
    return str(PERFIS[perfil_id]["rotulo"])


MODOS_CONTRAMAO = frozenset({"bike", "ebike", "patinete"})


def _marcar_contramao(rota: Dict[str, object]) -> None:
    """Anota em cada perna de duas rodas os trechos de provavel contramao
    (criterio em geometria.contramao_bike)."""
    for seg in rota["segmentos"]:                       # type: ignore[union-attr]
        if seg["tipo"] != "deslocamento" or seg["modo"] not in MODOS_CONTRAMAO:
            continue
        marcas = []
        for a, b in zip(seg["pontos"], seg["pontos"][1:]):
            c = geometria.contramao_bike(a, b)
            if c:
                marcas.append(dict(c, de=a, para=b, de_nome=PONTO_POR_ID[a].nome,
                                   para_nome=PONTO_POR_ID[b].nome))
        seg["contramao"] = marcas


def _card(perfil_id: str, rota: Dict[str, object],
          cond: Dict[str, object]) -> Dict[str, object]:
    _marcar_contramao(rota)
    return {
        "perfil": perfil_id,
        "rotulo": _rotulo_perfil(perfil_id),
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
        "seguranca": _seguranca_da_rota(
            rota, str((cond.get("transito") or {}).get("turno", "dia"))),   # type: ignore[union-attr]
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
                    transito=op.transito, acessivel=op.acessivel, recarga=True,
                    turno=op.turno)
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


def _transporte_publico(origem_id: str, destino_id: str, op: Opcoes,
                        cond: Dict[str, object]) -> Optional[Dict[str, object]]:
    """A viagem mais rapida usando so onibus, metro e caminhada.

    Com todos os modais, o transporte publico nunca e o extremo de nenhum
    objetivo: o carro ganha tempo e esforco, a bicicleta ganha custo e emissao,
    e a bicicleta + metro ocupa o lugar dele na fronteira. Mas e a opcao que
    quem nao tem carro nem quer pedalar 20 km de fato usa, e o app de rotas
    SUSTENTAVEIS nao pode escondê-la. Por isso ela e calculada a parte, num
    grafo so com esses modais, por Dijkstra lexicografico (tempo, depois custo,
    emissao, esforco) - exato, nao heuristico.

    Devolve None se nao existir rota, ou se a melhor for so a pe (nesse caso
    nao e "transporte publico", e a caminhada ja aparece em outro card).
    """
    op_tp = Opcoes(modos=MODOS_TRANSPORTE_PUBLICO, clima=op.clima,
                   transito=op.transito, acessivel=op.acessivel,
                   evitar_inseguros=op.evitar_inseguros, turno=op.turno)
    g = construir_grafo(op_tp, origem_id, destino_id)
    origem: No = (origem_id, "pe", 0, 0)
    destinos = nos_destino(g, destino_id)
    if origem not in g.adj or not destinos:
        return None
    dist, pred, _ = alg.dijkstra(g, origem, destinos, PESOS_TEMPO_LEXICOGRAFICO)
    alvo = alg.melhor_destino(dist, destinos)
    if alvo is None:
        return None
    rota = descrever_rota(g, alg.reconstruir(pred, alvo))
    if not set(rota["modos"]) & {"onibus", "metro"}:   # type: ignore[arg-type]
        return None
    return _card(PERFIL_TRANSPORTE_PUBLICO, rota, cond)


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
        turno=str(cond["transito"].get("turno", "dia")),   # type: ignore[union-attr]
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
                          acessivel=op.acessivel, evitar_inseguros=False,
                          turno=op.turno)
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
    tp = _transporte_publico(origem_id, destino_id, op, cond)
    if tp is not None:
        por_perfil[PERFIL_TRANSPORTE_PUBLICO] = tp

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
             "equilibrada", PERFIL_TRANSPORTE_PUBLICO]
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
            existente["perfis"].append(_rotulo_perfil(pid))     # type: ignore[union-attr]
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
        "gerado_em": datetime.now(clima_mod.FUSO_RECIFE).strftime("%H:%M:%S"),
        "turno": op.turno,
    }
