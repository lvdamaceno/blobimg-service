"""
Módulo responsável por autenticar na API da Sankhya.

Contém a classe SankhyaAuth, que realiza login e obtém o token de autenticação
utilizando credenciais armazenadas em variáveis de ambiente.
"""

import os
from datetime import datetime
import requests
from dotenv import load_dotenv
from sankhya_api.exceptions import AuthError

load_dotenv()


def log_tempo(msg=""):
    """Loga uma mensagem com timestamp atual para medir performance."""
    print(f"{datetime.now()} - {msg}")


class SankhyaAuth:  # pylint: disable=too-few-public-methods
    """Classe responsável por autenticar na API da Sankhya e obter o token de acesso."""

    def __init__(self):
        """Inicializa a URL de autenticação e o token como None."""
        self.url_auth = "https://api.sankhya.com.br/login"
        self.token = None

    def authenticate(self):
        """
        Realiza a autenticação na API da Sankhya usando variáveis de ambiente.

        Retorna:
           str: Token de autenticação Bearer.

        Levanta:
           AuthError: Se ocorrer um erro de autenticação ou conexão.
        """

        # log_tempo("Início da autenticação")

        headers = {
            "token": os.getenv("SANKHYA_TOKEN"),
            "appkey": os.getenv("SANKHYA_APPKEY"),
            "username": os.getenv("SANKHYA_USERNAME"),
            "password": os.getenv("SANKHYA_PASSWORD")
        }

        # log_tempo("Headers de autenticação preparados")
        # log_tempo("Antes de fazer POST na URL de autenticação")

        try:
            response = requests.post(self.url_auth, headers=headers, timeout=60)
            # log_tempo("Resposta recebida da API Sankhya")

            if response.status_code == 200:
                self.token = response.json().get("bearerToken")
                if not self.token:
                    # log_tempo("Token ausente no corpo da resposta")
                    raise AuthError("Token não encontrado no corpo da resposta.")
                # log_tempo("Token obtido com sucesso")
                return self.token

            # log_tempo(f"Erro HTTP na autenticação: {response.status_code}")
            raise AuthError(f"Erro na autenticação: {response.status_code} - {response.text}")

        except requests.RequestException as e:
            # log_tempo(f"Erro de conexão capturado: {e}")
            raise AuthError(f"Erro de conexão: {e}") from e
