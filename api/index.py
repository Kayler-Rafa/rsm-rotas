# -*- coding: utf-8 -*-
"""Entrada da Vercel: reaproveita o Handler do servidor (so biblioteca padrao).

A Vercel roda cada requisicao numa funcao Python que procura uma classe
`handler` derivada de BaseHTTPRequestHandler. O vercel.json manda todas as
rotas (app, /admin, /api/*, arquivos de web/) para ca.
"""
import os
import sys

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(RAIZ, "src"))

from server import Handler  # noqa: E402


class handler(Handler):  # noqa: N801  (nome exigido pela Vercel)
    pass
