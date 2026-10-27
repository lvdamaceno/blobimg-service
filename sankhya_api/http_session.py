"""Sessão HTTP compartilhada (keep-alive) e timeouts padrão para a API Sankhya."""

import requests
from requests.adapters import HTTPAdapter

# (conexão, leitura) em segundos
DEFAULT_TIMEOUT = (5, 15)

session = requests.Session()
session.mount("https://", HTTPAdapter(pool_connections=4, pool_maxsize=20))
