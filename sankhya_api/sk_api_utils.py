import os
import threading
from sankhya_api.request import SankhyaClient

_sankhya_clients = {}
_clients_lock = threading.Lock()


def load_query(nome, **params):
    caminho = os.path.join("queries", f"{nome}.sql")
    with open(caminho, "r", encoding="utf-8") as file:
        return file.read().format(**params)


def get_sankhya_client(service):
    with _clients_lock:
        if service not in _sankhya_clients:
            base_url = 'https://api.sankhya.com.br/gateway/v1/mge/service.sbr?serviceName='
            endpoint = f"{base_url}{service}&outputType=json"
            _sankhya_clients[service] = SankhyaClient(service, endpoint, 3)
        return _sankhya_clients[service]


def consulta_sankhya(query, service):
    client = get_sankhya_client(service)

    result = client.execute_query(query)
    rows = result.get("responseBody", {}).get("rows", []) if result else []
    return [item[0] for item in rows]
