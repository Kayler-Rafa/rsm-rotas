# -*- coding: utf-8 -*-
"""Servidor HTTP do MVP web do RSM - apenas biblioteca padrao do Python.

    python server.py [porta]

Depois abra http://localhost:8000 no navegador.
"""
from __future__ import annotations

import json
import mimetypes
import os
import sys
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import clima
import motor
from rede_rsm import CLIMAS, MODOS, PERFIS, PONTO_POR_ID, SEGURANCAS, TRANSITOS, Opcoes

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEB = os.path.join(RAIZ, "web")

_cache_rede = None


def _valida(params, chave, universo, padrao):
    v = (params.get(chave) or [padrao])[0]
    return v if v in universo else padrao


def _bool(params, chave, padrao=False):
    v = (params.get(chave) or [None])[0]
    if v is None:
        return padrao
    return v.lower() in ("1", "true", "sim", "on", "yes")


def _opcoes(params) -> Opcoes:
    """Monta as opcoes do usuario a partir da query string.

    Modais desconhecidos sao ignorados em silencio; se a lista vier vazia,
    volta para todos, porque uma consulta sem nenhum modal nao tem resposta
    util - so uma tela de erro.
    """
    bruto = (params.get("modos") or [""])[0]
    escolhidos = frozenset(m for m in bruto.split(",") if m in MODOS)
    if not escolhidos:
        escolhidos = frozenset(MODOS)
    escolhidos = escolhidos | {"pe"}        # a pe e sempre o acesso e o egresso
    return Opcoes(
        modos=escolhidos,
        clima=_valida(params, "clima", CLIMAS, "bom"),
        transito=_valida(params, "transito", TRANSITOS, "normal"),
        seguranca=_valida(params, "seguranca", SEGURANCAS, "indiferente"),
        acessivel=_bool(params, "acessivel"),
        recarga=_bool(params, "recarga"),
        evitar_inseguros=_bool(params, "evitar_inseguros", True),
    )


class Handler(BaseHTTPRequestHandler):
    server_version = "RSM/2.0"

    # ------------------------------------------------------------ utilidades
    def _json(self, obj, status=200):
        corpo = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(corpo)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(corpo)

    def _arquivo(self, caminho_rel):
        caminho = os.path.normpath(os.path.join(WEB, caminho_rel.lstrip("/")))
        if not caminho.startswith(WEB) or not os.path.isfile(caminho):
            self.send_error(404, "Nao encontrado")
            return
        tipo, _ = mimetypes.guess_type(caminho)
        with open(caminho, "rb") as fh:
            corpo = fh.read()
        self.send_response(200)
        self.send_header("Content-Type", (tipo or "application/octet-stream")
                         + ("; charset=utf-8" if (tipo or "").startswith("text/")
                            or (tipo or "").endswith("javascript") else ""))
        self.send_header("Content-Length", str(len(corpo)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(corpo)

    # ----------------------------------------------------------------- rotas
    def do_GET(self):
        global _cache_rede
        url = urlparse(self.path)
        rota = url.path
        params = parse_qs(url.query)

        try:
            if rota in ("/", "/index.html"):
                return self._arquivo("index.html")

            if rota in ("/admin", "/admin/", "/admin.html"):
                return self._arquivo("admin.html")

            if rota == "/api/condicoes-atuais":
                return self._json(clima.condicoes_atuais(
                    forcar=_bool(params, "forcar")))

            if rota == "/api/rede":
                if _cache_rede is None:
                    _cache_rede = motor.rede_serializada()
                return self._json(_cache_rede)

            origem = _valida(params, "origem", PONTO_POR_ID, "se_olinda")
            destino = _valida(params, "destino", PONTO_POR_ID, "igreja_piedade")
            perfil = _valida(params, "perfil", PERFIS, "mais_rapida")
            norm = _valida(params, "normalizacao", {"minmax", "vetorial"}, "minmax")

            if rota == "/api/opcoes":
                if origem == destino:
                    return self._json({"erro": "Origem e destino sao o mesmo ponto."}, 400)
                return self._json(motor.opcoes_de_viagem(
                    origem, destino, acessivel=_bool(params, "acessivel"),
                    normalizacao=norm,
                    evitar_inseguros=_bool(params, "evitar_inseguros", True)))

            if rota == "/api/rota":
                if origem == destino:
                    return self._json({"erro": "Origem e destino sao o mesmo ponto."}, 400)
                return self._json(motor.consultar(
                    origem, destino, _opcoes(params), perfil,
                    com_pareto=_bool(params, "pareto", True), normalizacao=norm))

            if rota == "/api/condicoes":
                # Varia UMA dimensao por vez a partir das opcoes atuais, para
                # mostrar o efeito isolado de clima, transito e seguranca.
                # Sem fronteira de Pareto: aqui interessa a rota otima, e o
                # Martins custaria centenas de ms por linha.
                import dataclasses
                base = _opcoes(params)
                linhas = []
                variacoes = (
                    [("clima", k, CLIMAS[k]["rotulo"]) for k in CLIMAS]
                    + [("transito", k, TRANSITOS[k]["rotulo"]) for k in TRANSITOS]
                    + [("seguranca", k, SEGURANCAS[k]["rotulo"]) for k in SEGURANCAS]
                )
                for dim, valor, rotulo in variacoes:
                    op = dataclasses.replace(base, **{dim: valor})
                    r = motor.consultar(origem, destino, op, perfil,
                                        com_pareto=False, normalizacao=norm)
                    linha = {"dimensao": dim, "valor": valor, "rotulo": rotulo,
                             "atual": getattr(base, dim) == valor,
                             "grafo": r.get("grafo")}
                    if "erro" in r:
                        linha["erro"] = r["erro"]
                    else:
                        d = r["dijkstra"]["rota"]
                        linha.update({
                            "tempo": d["tempo"], "custo": d["custo"], "co2": d["co2"],
                            "desconforto": d["desconforto"], "dist_km": d["dist_km"],
                            "modos_rotulo": d["modos_rotulo"],
                            "expandidos_dijkstra": r["dijkstra"]["expandidos"],
                            "expandidos_astar": r["astar"]["expandidos"],
                            "reducao_pct": r["comparacao"]["reducao_busca_pct"],
                            "mesma_rota": r["comparacao"]["mesma_rota"],
                        })
                    linhas.append(linha)
                return self._json({"linhas": linhas, "opcoes": motor._resumo_opcoes(base)})

            if rota == "/api/viabilidade":
                return self._json(motor.viabilidade_modos(
                    origem, destino, _opcoes(params), perfil))

            if rota == "/api/nsga2":
                return self._json(motor.nsga2_resultado(
                    origem, destino, _opcoes(params), perfil))

            return self._arquivo(rota)

        except BrokenPipeError:
            return
        except Exception as exc:                       # noqa: BLE001
            traceback.print_exc()
            return self._json({"erro": "%s: %s" % (type(exc).__name__, exc)}, 500)

    def log_message(self, fmt, *args):                 # silencia o log padrao
        if "/api/" in (args[0] if args else ""):
            sys.stderr.write("  %s\n" % (fmt % args))


def main():
    porta = int(sys.argv[1]) if len(sys.argv) > 1 else 8000
    srv = ThreadingHTTPServer(("127.0.0.1", porta), Handler)
    print("RSM - Rotas Sustentaveis Multimodais")
    print("Servidor em http://localhost:%d  (Ctrl+C para parar)" % porta)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nencerrado.")
        srv.server_close()


if __name__ == "__main__":
    main()
