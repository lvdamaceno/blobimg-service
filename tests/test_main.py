"""Testes do serviço de imagens, com o Sankhya simulado (nenhuma chamada real)."""

import io
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient
from PIL import Image

import main


def _imagem(formato: str, tamanho=(1000, 800), modo="RGB", cor=(0, 0, 255)) -> bytes:
    saida = io.BytesIO()
    Image.new(modo, tamanho, cor).save(saida, formato)
    return saida.getvalue()


def _abrir(conteudo: bytes) -> Image.Image:
    return Image.open(io.BytesIO(conteudo))


class SankhyaFalso:
    """Substitui consulta_sankhya. `imagens` mapeia codprod -> bytes, None (sem imagem) ou Exception."""

    def __init__(self):
        self.imagens = {}
        self.consultas = []
        self.atraso = 0
        self._lock = threading.Lock()

    def __call__(self, query, service):
        if "SELECT CODPROD" in query:
            ultimo = int(re.search(r"CODPROD > (\d+)", query).group(1))
            com_imagem = sorted(c for c, v in self.imagens.items() if isinstance(v, bytes))
            return [c for c in com_imagem if c > ultimo][:5]  # simula o limite de linhas do DbExplorer

        codprod = int(query.rsplit("=", 1)[1])
        with self._lock:
            self.consultas.append(codprod)
        time.sleep(self.atraso)
        valor = self.imagens.get(codprod)
        if isinstance(valor, Exception):
            raise valor
        return [valor.hex()] if valor else [None]

    def total(self, codprod):
        return self.consultas.count(codprod)


@pytest.fixture
def sankhya(monkeypatch, tmp_path):
    falso = SankhyaFalso()
    monkeypatch.setattr(main, "consulta_sankhya", falso)
    monkeypatch.setattr(main, "IMAGES_DIR", tmp_path)
    monkeypatch.setattr(main, "AQUECIMENTO_PAUSA", 0)
    main._sem_imagem.clear()
    main._locks.clear()
    return falso


@pytest.fixture
def client(sankhya):
    return TestClient(main.app)


def _esperar(condicao, timeout=5):
    limite = time.monotonic() + timeout
    while time.monotonic() < limite:
        if condicao():
            return True
        time.sleep(0.02)
    return False


def _envelhecer(path, segundos):
    antigo = time.time() - segundos
    os.utime(path, (antigo, antigo))


# --- Formato da resposta -------------------------------------------------------

@pytest.mark.parametrize("url", ["/1", "/1.jpg"])
def test_rotas_servem_jpeg(client, sankhya, url):
    sankhya.imagens[1] = _imagem("JPEG")
    r = client.get(url)
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/jpeg"
    assert r.content == sankhya.imagens[1]  # JPEG original não é recodificado


def test_png_transparente_vira_jpeg_com_fundo_branco(client, sankhya, tmp_path):
    sankhya.imagens[1] = _imagem("PNG", modo="RGBA", cor=(255, 0, 0, 0))
    r = client.get("/1.jpg")
    assert r.headers["content-type"] == "image/jpeg"
    img = _abrir(r.content)
    assert img.format == "JPEG"
    assert img.getpixel((0, 0)) == (255, 255, 255)
    assert _abrir((tmp_path / "1.jpg").read_bytes()).format == "JPEG"


def test_png_antigo_no_cache_e_convertido_ao_servir(client, sankhya, tmp_path):
    (tmp_path / "1.jpg").write_bytes(_imagem("PNG"))
    r = client.get("/1.jpg")
    assert r.headers["content-type"] == "image/jpeg"
    assert _abrir(r.content).format == "JPEG"
    assert sankhya.total(1) == 0


def test_etag_e_304(client, sankhya):
    sankhya.imagens[1] = _imagem("JPEG")
    r = client.get("/1.jpg")
    assert r.headers["cache-control"] == main.CACHE_CONTROL
    r2 = client.get("/1.jpg", headers={"If-None-Match": r.headers["etag"]})
    assert r2.status_code == 304
    assert r2.content == b""


# --- Erros ---------------------------------------------------------------------

def test_sem_imagem_404_com_cache_negativo(client, sankhya):
    assert client.get("/2").status_code == 404
    assert client.get("/2").status_code == 404
    assert sankhya.total(2) == 1


def test_falha_do_sankhya_502_sem_cache_negativo(client, sankhya):
    sankhya.imagens[3] = RuntimeError("Sankhya fora")
    assert client.get("/3").status_code == 502
    sankhya.imagens[3] = _imagem("JPEG")
    assert client.get("/3").status_code == 200


def test_codprod_invalido(client):
    assert client.get("/abc.jpg").status_code == 422


# --- Cache ---------------------------------------------------------------------

def test_segunda_requisicao_vem_do_disco(client, sankhya):
    sankhya.imagens[1] = _imagem("JPEG")
    client.get("/1")
    client.get("/1")
    assert sankhya.total(1) == 1


def test_requisicoes_simultaneas_fazem_uma_consulta(sankhya):
    sankhya.imagens[1] = _imagem("JPEG")
    sankhya.atraso = 0.3
    with ThreadPoolExecutor(8) as pool:
        resultados = list(pool.map(lambda _: main._obter_imagem(1), range(8)))
    assert all(r == sankhya.imagens[1] for r in resultados)
    assert sankhya.total(1) == 1


def test_vencida_serve_antiga_e_atualiza_em_segundo_plano(client, sankhya, tmp_path):
    antiga, nova = _imagem("JPEG", cor=(0, 0, 255)), _imagem("JPEG", cor=(0, 255, 0))
    sankhya.imagens[1] = antiga
    client.get("/1")
    _envelhecer(tmp_path / "1.jpg", main.IMAGEM_TTL + 10)
    sankhya.imagens[1] = nova
    sankhya.atraso = 0.2

    r = client.get("/1")
    assert r.content == antiga  # não espera o Sankhya
    assert _esperar(lambda: (tmp_path / "1.jpg").read_bytes() == nova)
    assert client.get("/1").content == nova


def test_vencida_removida_no_erp_passa_a_404(client, sankhya, tmp_path):
    sankhya.imagens[1] = _imagem("JPEG")
    client.get("/1")
    client.get("/1?w=100")
    _envelhecer(tmp_path / "1.jpg", main.IMAGEM_TTL + 10)
    sankhya.imagens[1] = None

    assert client.get("/1").status_code == 200
    assert _esperar(lambda: not (tmp_path / "1.jpg").exists())
    assert not (tmp_path / "1_w100.jpg").exists()
    assert client.get("/1").status_code == 404


def test_vencida_com_sankhya_fora_mantem_antiga(client, sankhya, tmp_path):
    sankhya.imagens[1] = _imagem("JPEG")
    client.get("/1")
    _envelhecer(tmp_path / "1.jpg", main.IMAGEM_TTL + 10)
    sankhya.imagens[1] = RuntimeError("Sankhya fora")

    assert client.get("/1").status_code == 200
    assert _esperar(lambda: sankhya.total(1) == 2)
    assert _esperar(lambda: not main._lock_do_produto(1).locked())
    assert client.get("/1").status_code == 200


# --- Redimensionamento ---------------------------------------------------------

@pytest.mark.parametrize("w", main.LARGURAS)
def test_larguras_aceitas(client, sankhya, w):
    sankhya.imagens[1] = _imagem("JPEG", tamanho=(1000, 800))
    r = client.get(f"/1.jpg?w={w}")
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/jpeg"
    assert _abrir(r.content).size == (w, w * 800 // 1000)


@pytest.mark.parametrize("w", [0, 50, 150, 5000, -1])
def test_larguras_nao_aceitas(client, sankhya, w):
    sankhya.imagens[1] = _imagem("JPEG")
    assert client.get(f"/1.jpg?w={w}").status_code == 422
    assert sankhya.total(1) == 0


def test_nunca_amplia(client, sankhya):
    sankhya.imagens[1] = _imagem("JPEG", tamanho=(300, 200))
    assert _abrir(client.get("/1?w=800").content).size == (300, 200)


def test_redimensionada_fica_em_disco(client, sankhya, tmp_path, monkeypatch):
    sankhya.imagens[1] = _imagem("JPEG")
    primeira = client.get("/1?w=200").content
    assert (tmp_path / "1_w200.jpg").read_bytes() == primeira

    chamadas = []
    original = main._redimensionar
    monkeypatch.setattr(main, "_redimensionar", lambda *a: chamadas.append(a) or original(*a))
    assert client.get("/1?w=200").content == primeira
    assert chamadas == []


def test_redimensionada_refeita_quando_original_muda(client, sankhya, tmp_path):
    sankhya.imagens[1] = _imagem("JPEG", cor=(0, 0, 255))
    azul = client.get("/1?w=200").content
    _envelhecer(tmp_path / "1_w200.jpg", 100)

    sankhya.imagens[1] = _imagem("JPEG", cor=(0, 255, 0))
    main.consultar_e_salvar_imagem(1)
    verde = client.get("/1?w=200").content
    assert verde != azul
    r, g, b = _abrir(verde).getpixel((10, 10))
    assert g > 200 and b < 50


# --- Health e aquecimento ------------------------------------------------------

def test_health_conta_so_originais(client, sankhya):
    sankhya.imagens[1] = _imagem("JPEG")
    sankhya.imagens[2] = _imagem("JPEG")
    client.get("/1")
    client.get("/2?w=100")
    assert client.get("/health").json() == {"status": "ok", "imagens_em_cache": 2}


def test_aquecimento_baixa_so_o_que_falta(sankhya, tmp_path):
    for codprod in range(1, 13):
        sankhya.imagens[codprod] = _imagem("JPEG", tamanho=(10, 10))
    (tmp_path / "3.jpg").write_bytes(sankhya.imagens[3])

    assert main._listar_produtos_com_imagem() == list(range(1, 13))  # paginada
    assert main._aquecer_uma_vez() is True
    assert sorted(int(p.stem) for p in tmp_path.glob("*.jpg")) == list(range(1, 13))
    assert sankhya.total(3) == 0
    assert len(sankhya.consultas) == 11


def test_aquecimento_para_apos_falhas_seguidas(sankhya, monkeypatch):
    for codprod in range(1, 31):
        sankhya.imagens[codprod] = _imagem("JPEG", tamanho=(10, 10))

    def falhar(codprod):
        sankhya.consultas.append(codprod)
        raise RuntimeError("Sankhya fora")

    monkeypatch.setattr(main, "consultar_e_salvar_imagem", falhar)

    assert main._aquecer_uma_vez() is False
    assert len(sankhya.consultas) == main.AQUECIMENTO_MAX_FALHAS


def test_aquecimento_desligado_por_padrao_fora_do_render():
    assert os.getenv("RENDER") or not main.AQUECER_CACHE
