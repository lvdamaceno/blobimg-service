"""
Módulo responsável por consultar a API Sankhya com autenticação e retentativas automáticas.

Contém a classe SankhyaClient, que realiza autenticação via token Bearer e executa consultas SQL
através da API REST da Sankhya. Inclui mecanismos de revalidação do token em caso de expiração e
tratamento de erros de conexão com múltiplas tentativas controladas.

Dependências:
    - requests
    - os
    - time
    - logging
    - dotenv
    - SankhyaAuth (auth.py)
    - RequestError (exceção personalizada)
"""

import logging
import time
from datetime import datetime
from requests.exceptions import ReadTimeout, ConnectionError as RequestsConnectionError
import requests
from .auth import SankhyaAuth
from .exceptions import RequestError, SankhyaHTTPError


def log_tempo(msg=""):
    """Loga uma mensagem com timestamp atual para medir performance."""
    print(f"{datetime.now()} - {msg}")


class SankhyaClient:  # pylint: disable=too-few-public-methods
    """
    Cliente para interação com a API Sankhya usando autenticação Bearer.

    Esta classe realiza requisições à API Sankhya para execução de comandos SQL,
    gerenciando automaticamente autenticação e tentativas de reconexão em caso de falhas.
    """

    def __init__(self, servicename, endpoint, retries, timeout=30):
        # log_tempo("Início da execução do SankhyaClient")
        self.auth = SankhyaAuth()

        self._token = None  # token será obtido apenas quando necessário
        self.endpoint = endpoint
        self.timeout = timeout
        self.retries = retries
        self.servicename = servicename

    @property
    def token(self):
        """Token autenticado, obtido sob demanda."""
        if not self._token:
            # log_tempo("Token ainda não foi obtido. Autenticando...")
            self._token = self.auth.authenticate()
            # log_tempo("Token obtido com sucesso")
        return self._token

    def _renew_token(self):
        """Renova e atualiza o token."""
        # log_tempo("Renovando token de autenticação")
        self._token = self.auth.authenticate()

    def execute_query(self, sql: str):
        """
        Executa uma consulta SQL no serviço Sankhya utilizando o endpoint REST autenticado.
        """
        payload = {
            "serviceName": self.servicename,
            "requestBody": {"sql": sql}
        }

        headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json"
        }

        # log_tempo("Antes de enviar para endpoint CS")

        for attempt in range(self.retries):
            try:
                response = requests.get(
                    self.endpoint,
                    headers=headers,
                    json=payload,
                    timeout=self.timeout
                )

                # log_tempo(f"Resposta recebida do endpoint (tentativa {attempt + 1})")

                if response.status_code == 200:
                    return response.json()
                if response.status_code in (401, 403):
                    # log_tempo("Token expirado ou inválido, tentando renovar")
                    self._renew_token()
                    headers["Authorization"] = f"Bearer {self.token}"
                    continue
                raise SankhyaHTTPError(f"Erro HTTP {response.status_code}: {response.text}")
            except (ReadTimeout, RequestsConnectionError) as e:
                logging.warning("[%d/%d] Timeout ou erro de conexão: %s", attempt + 1, self.retries, e)
                time.sleep(5)
            except Exception as e:
                raise RequestError(f"Erro de conexão geral: {e}") from e

        raise RequestError("Falha após múltiplas tentativas de conexão.")
