"""Define exceções personalizadas utilizadas no projeto para tratamento de erros específicos."""


class AuthError(Exception):
    """Exceção personalizada para erros de autenticação com a API Sankhya."""


class SankhyaConnectionError(Exception):
    """Erro ao conectar com os serviços Sankhya."""


class CSIntegrationError(Exception):
    """Erro ao enviar ou processar dados na integração com o CS."""


class RequestError(Exception):
    """Exceção para erros gerais de requisições."""


class SankhyaHTTPError(Exception):
    """Erro ao processar resposta HTTP da API Sankhya."""
