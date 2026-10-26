# -*- coding: utf-8 -*-
"""Condicoes de viagem obtidas automaticamente - nao perguntadas ao usuario.

Clima: Open-Meteo (https://open-meteo.com), gratuito e sem chave de API.
Transito: heuristica de horario, porque nao ha fonte aberta de transito em
tempo real para a RMR. Esta explicitamente rotulado como estimativa.

Nada aqui e obrigatorio: se a rede falhar, o modulo devolve "tempo bom" com
origem "indisponivel" e a interface diz que nao conseguiu medir. Uma previsao
errada silenciosa seria pior do que assumir a ausencia de dado.
"""
from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import Dict, Optional

# Centro geografico aproximado do corredor modelado (Recife / Olinda / Jaboatao).
LAT, LON = -8.09, -34.89

URL = ("https://api.open-meteo.com/v1/forecast"
       "?latitude=%.4f&longitude=%.4f"
       "&current=temperature_2m,relative_humidity_2m,precipitation,"
       "weather_code,wind_speed_10m&timezone=America%%2FRecife") % (LAT, LON)

TIMEOUT_S = 6
# O app reconsulta a cada minuto. O Open-Meteo so atualiza o dado "current" a
# cada 15 min, entao buscar mais que isso e desperdicio; 5 min faz a mudanca de
# tempo chegar ao usuario em no maximo ~20 min sem martelar o servico.
TTL_S = 300
FUSO_RECIFE = timezone(timedelta(hours=-3))   # sem horario de verao

_cache: Dict[str, object] = {}
_cache_ts = 0.0
_lock = threading.Lock()


# --------------------------------------------------------------- codigos WMO
# Tabela reduzida do padrao WMO usado pelo Open-Meteo.
_DESCRICAO = {
    0: "céu limpo", 1: "predominantemente limpo", 2: "parcialmente nublado",
    3: "nublado", 45: "nevoeiro", 48: "nevoeiro com geada",
    51: "garoa fraca", 53: "garoa moderada", 55: "garoa forte",
    61: "chuva fraca", 63: "chuva moderada", 65: "chuva forte",
    66: "chuva congelante fraca", 67: "chuva congelante forte",
    80: "pancadas fracas", 81: "pancadas moderadas", 82: "pancadas fortes",
    95: "trovoada", 96: "trovoada com granizo", 99: "trovoada com granizo",
}

_CODIGO_FORTE = frozenset({65, 82, 95, 96, 99})
_CODIGO_LEVE = frozenset({51, 53, 55, 56, 57, 61, 63, 66, 67, 80, 81})


def _clima_do_codigo(codigo: int, precipitacao: float) -> str:
    """Classifica em bom / chuva_leve / chuva_forte.

    Usa o codigo WMO e a precipitacao medida, ficando com a pior das duas
    leituras - o codigo descreve a condicao dominante e pode subestimar uma
    pancada localizada.
    """
    por_codigo = ("chuva_forte" if codigo in _CODIGO_FORTE
                  else "chuva_leve" if codigo in _CODIGO_LEVE else "bom")
    por_chuva = ("chuva_forte" if precipitacao >= 4.0
                 else "chuva_leve" if precipitacao >= 0.3 else "bom")
    ordem = {"bom": 0, "chuva_leve": 1, "chuva_forte": 2}
    return por_codigo if ordem[por_codigo] >= ordem[por_chuva] else por_chuva


def _buscar() -> Dict[str, object]:
    with urllib.request.urlopen(URL, timeout=TIMEOUT_S) as resposta:
        dados = json.load(resposta)
    atual = dados.get("current") or {}
    codigo = int(atual.get("weather_code", 0))
    precipitacao = float(atual.get("precipitation") or 0.0)
    temperatura = float(atual.get("temperature_2m") or 0.0)
    umidade = float(atual.get("relative_humidity_2m") or 0.0)
    vento = float(atual.get("wind_speed_10m") or 0.0)
    return {
        "clima": _clima_do_codigo(codigo, precipitacao),
        "descricao": _DESCRICAO.get(codigo, "condicao %d" % codigo),
        "temperatura": round(temperatura, 1),
        "umidade": round(umidade),
        "precipitacao": round(precipitacao, 1),
        "vento": round(vento, 1),
        "fonte": "Open-Meteo",
        "medido_em": atual.get("time"),
        "disponivel": True,
    }


def clima_atual(forcar: bool = False) -> Dict[str, object]:
    """Clima corrente, com cache de 10 min e degradacao silenciosa."""
    global _cache_ts
    with _lock:
        if not forcar and _cache and (time.time() - _cache_ts) < TTL_S:
            return dict(_cache)
    try:
        dados = _buscar()
    except (urllib.error.URLError, OSError, ValueError, KeyError) as erro:
        # Sem rede ou resposta inesperada: assume tempo bom e AVISA que assumiu.
        dados = {
            "clima": "bom",
            "descricao": "nao foi possivel medir",
            "temperatura": None, "umidade": None,
            "precipitacao": None, "vento": None,
            "fonte": "indisponivel",
            "erro": "%s: %s" % (type(erro).__name__, erro),
            "medido_em": None,
            "disponivel": False,
        }
    with _lock:
        _cache.clear()
        _cache.update(dados)
        _cache_ts = time.time()
    return dict(dados)


# ------------------------------------------------------------------ transito
def transito_atual(agora: Optional[datetime] = None) -> Dict[str, object]:
    """Estimativa de transito pelo horario.

    NAO e medicao. A Etapa 1 nao identificou fonte aberta de transito em tempo
    real para a RMR; o que existe e o indice TomTom agregado (Recife e a capital
    brasileira mais congestionada, indice 64,7%, 18 km/h no pico da manha).
    A faixa de pico abaixo vem dai, nao de um sensor.
    """
    agora = agora or datetime.now(FUSO_RECIFE)
    dia = agora.weekday()            # 0 = segunda
    minutos = agora.hour * 60 + agora.minute

    def faixa(ini_h, ini_m, fim_h, fim_m):
        return ini_h * 60 + ini_m <= minutos < fim_h * 60 + fim_m

    if dia <= 4:                                     # dia util
        if faixa(6, 30, 9, 0) or faixa(16, 30, 19, 30):
            nivel, motivo = "congestionado", "hora de pico em dia util"
        elif faixa(9, 0, 16, 30) or faixa(19, 30, 21, 0):
            nivel, motivo = "normal", "dia util fora do pico"
        else:
            nivel, motivo = "livre", "madrugada"
    elif dia == 5:                                   # sabado
        nivel, motivo = ("normal", "sabado durante o dia") \
            if faixa(9, 0, 14, 0) else ("livre", "sabado fora do movimento")
    else:                                            # domingo
        nivel, motivo = "livre", "domingo"

    return {
        "transito": nivel,
        "motivo": motivo,
        "hora_local": agora.strftime("%H:%M"),
        "fonte": "estimativa por horario",
        "disponivel": True,
        "medido": False,
    }


def condicoes_atuais(forcar: bool = False) -> Dict[str, object]:
    c = clima_atual(forcar)
    t = transito_atual()
    # Calor tambem e uma condicao de conforto, e no Recife pesa mais que a chuva
    # na maior parte do ano.
    temp = c.get("temperatura")
    c["calor"] = bool(temp is not None and temp >= 31.0)
    return {"clima": c, "transito": t}


if __name__ == "__main__":
    print(json.dumps(condicoes_atuais(True), indent=2, ensure_ascii=False))
