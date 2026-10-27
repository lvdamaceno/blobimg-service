import hashlib
import io
import logging
import os
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Query, Request, Response
from PIL import Image, UnidentifiedImageError
from sankhya_api.sk_api_utils import consulta_sankhya

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("blobimg")


@asynccontextmanager
async def _lifespan(_app):
    if AQUECER_CACHE:
        threading.Thread(target=_aquecer_cache, daemon=True).start()
    yield


app = FastAPI(lifespan=_lifespan)
IMAGES_DIR = Path(os.getenv("IMAGES_DIR", "images"))  # aponte para o disco persistente, se houver
IMAGES_DIR.mkdir(parents=True, exist_ok=True)  # Garante que a pasta existe

IMAGEM_TTL = int(os.getenv("IMAGEM_TTL", "86400"))  # validade da imagem em disco (segundos)
SEM_IMAGEM_TTL = 3600  # segundos que um "produto sem imagem" fica em cache
CACHE_CONTROL = "public, max-age=86400"  # 1 dia no navegador/CDN
JPEG_QUALIDADE = 90
LARGURAS = (100, 200, 400, 800)  # tamanhos aceitos no ?w=, guardados em disco

# Aquecimento: baixa em segundo plano as imagens que ainda não estão no cache.
# Ligado por padrão só no Render (que define RENDER=true), para não baixar tudo em dev.
AQUECER_CACHE = os.getenv("AQUECER_CACHE", os.getenv("RENDER", "false")).lower() in ("1", "true")
AQUECIMENTO_INTERVALO = 86400  # repete diariamente, para pegar produtos novos
AQUECIMENTO_PAUSA = 0.2  # segundos entre consultas, para não sobrecarregar o Sankhya
AQUECIMENTO_MAX_FALHAS = 10  # falhas seguidas antes de desistir e tentar mais tarde

# O gateway do Sankhya devolve erro 500 para imagens grandes; acima disso, busca em partes
LIMITE_CONSULTA_INTEIRA = 2_000_000  # bytes
TAMANHO_PARTE = 2_000_000  # bytes por consulta ao buscar em partes

_sem_imagem: dict[int, float] = {}  # codprod -> expira em (timestamp)
_locks: dict[int, threading.Lock] = {}
_locks_guard = threading.Lock()
_aquecimento = {"estado": "desligado", "pendentes": 0, "processadas": 0, "baixadas": 0, "falhas": 0, "ultimo_erro": None}


class ImagemNaoEncontrada(Exception):
    """Produto não existe ou não tem imagem cadastrada."""


def _lock_do_produto(codprod: int) -> threading.Lock:
    with _locks_guard:
        return _locks.setdefault(codprod, threading.Lock())


def _caminho(codprod: int) -> Path:
    return IMAGES_DIR / f"{codprod}.jpg"


def _salvar_jpeg(img: Image.Image) -> bytes:
    # JPEG não tem transparência: compõe sobre fundo branco
    if img.mode in ("RGBA", "LA", "P"):
        img = img.convert("RGBA")
        fundo = Image.new("RGB", img.size, (255, 255, 255))
        fundo.paste(img, mask=img.getchannel("A"))
        img = fundo
    elif img.mode not in ("RGB", "L", "CMYK"):
        img = img.convert("RGB")
    saida = io.BytesIO()
    img.save(saida, format="JPEG", quality=JPEG_QUALIDADE, optimize=True)
    return saida.getvalue()


def _para_jpeg(conteudo: bytes) -> bytes:
    """Converte para JPEG de verdade; o sistema que consome os links só aceita JPEG."""
    if conteudo.startswith(b"\xff\xd8\xff"):
        return conteudo
    with Image.open(io.BytesIO(conteudo)) as img:
        return _salvar_jpeg(img)


def _redimensionar(conteudo: bytes, largura: int) -> bytes:
    with Image.open(io.BytesIO(conteudo)) as img:
        if largura >= img.width:
            return conteudo  # nunca amplia
        altura = max(1, round(img.height * largura / img.width))
        return _salvar_jpeg(img.resize((largura, altura), Image.LANCZOS))


def _gravar(path: Path, conteudo: bytes):
    # Grava em arquivo temporário e renomeia: nunca deixa arquivo pela metade no cache
    tmp_path = path.with_suffix(f".{threading.get_ident()}.tmp")
    tmp_path.write_bytes(conteudo)
    os.replace(tmp_path, path)


def _obter_redimensionada(codprod: int, original: bytes, largura: int) -> bytes:
    path = IMAGES_DIR / f"{codprod}_w{largura}.jpg"
    try:
        # Só vale se foi gerada depois da última atualização da original
        if path.stat().st_mtime >= _caminho(codprod).stat().st_mtime:
            return path.read_bytes()
    except FileNotFoundError:
        pass
    conteudo = _redimensionar(original, largura)
    _gravar(path, conteudo)
    return conteudo


def _remover_do_cache(codprod: int):
    # Redimensionadas primeiro: nunca sobra uma redimensionada sem a original
    for path in IMAGES_DIR.glob(f"{codprod}_w*.jpg"):
        path.unlink(missing_ok=True)
    _caminho(codprod).unlink(missing_ok=True)


def _consultar(sql: str):
    return consulta_sankhya(sql, "DbExplorerSP.executeQuery")


def _buscar_imagem_hex(codprod: int) -> Optional[str]:
    """Conteúdo do campo IMAGEM em hex; imagens grandes são buscadas em partes."""
    try:
        result = _consultar(f"SELECT IMAGEM FROM TGFPRO WHERE CODPROD = {codprod}")
        return result[0] if result else None
    except Exception:
        tamanho = _consultar(f"SELECT DATALENGTH(IMAGEM) FROM TGFPRO WHERE CODPROD = {codprod}")
        tamanho = int(tamanho[0] or 0) if tamanho else 0
        if tamanho <= LIMITE_CONSULTA_INTEIRA:
            raise  # não é problema de tamanho
        logger.info("codprod=%s: imagem de %.1fMB, buscando em partes", codprod, tamanho / 1e6)
        return "".join(
            _consultar(f"SELECT SUBSTRING(IMAGEM, {inicio}, {TAMANHO_PARTE}) FROM TGFPRO WHERE CODPROD = {codprod}")[0]
            for inicio in range(1, tamanho + 1, TAMANHO_PARTE)
        )


def consultar_e_salvar_imagem(codprod: int) -> bytes:
    inicio = time.monotonic()
    imagem_hex = _buscar_imagem_hex(codprod)
    logger.info("Consulta Sankhya codprod=%s em %.2fs", codprod, time.monotonic() - inicio)

    if not imagem_hex:
        raise ImagemNaoEncontrada("Imagem não encontrada no banco de dados.")

    try:
        imagem_bytes = _para_jpeg(bytes.fromhex(imagem_hex))
    except (ValueError, UnidentifiedImageError) as e:
        # O Sankhya às vezes guarda texto no lugar da imagem (ex.: "deletado")
        logger.warning("codprod=%s: conteúdo do campo IMAGEM não é uma imagem (%d bytes)", codprod, len(imagem_hex) // 2)
        raise ImagemNaoEncontrada("Imagem não encontrada no banco de dados.") from e
    _gravar(_caminho(codprod), imagem_bytes)
    return imagem_bytes


def _ler_cache(codprod: int):
    """Retorna (conteúdo, idade em segundos) ou (None, 0) se não houver arquivo."""
    image_path = _caminho(codprod)
    try:
        idade = time.time() - image_path.stat().st_mtime
        return image_path.read_bytes(), idade
    except FileNotFoundError:
        return None, 0


def _atualizar_em_segundo_plano(codprod: int):
    lock = _lock_do_produto(codprod)
    if not lock.acquire(blocking=False):
        return  # já há uma consulta deste produto em andamento
    try:
        consultar_e_salvar_imagem(codprod)
    except ImagemNaoEncontrada:
        # A imagem foi removida no ERP
        _sem_imagem[codprod] = time.time() + SEM_IMAGEM_TTL
        _remover_do_cache(codprod)
    except Exception as e:  # pylint: disable=broad-except
        # Mantém a imagem antiga; tenta de novo na próxima requisição
        logger.warning("Falha ao atualizar codprod=%s: %s", codprod, e)
    finally:
        lock.release()


def _obter_imagem(codprod: int) -> bytes:
    conteudo, idade = _ler_cache(codprod)
    if conteudo is not None:
        if idade > IMAGEM_TTL and not _lock_do_produto(codprod).locked():
            # Vencida: responde com a imagem atual e atualiza sem fazer o cliente esperar
            threading.Thread(target=_atualizar_em_segundo_plano, args=(codprod,), daemon=True).start()
        return conteudo

    if _sem_imagem.get(codprod, 0) > time.time():
        raise ImagemNaoEncontrada("Imagem não encontrada no banco de dados.")

    # Requisições simultâneas do mesmo produto fazem uma única consulta ao Sankhya
    with _lock_do_produto(codprod):
        conteudo, _ = _ler_cache(codprod)
        if conteudo is not None:
            return conteudo
        try:
            return consultar_e_salvar_imagem(codprod)
        except ImagemNaoEncontrada:
            _sem_imagem[codprod] = time.time() + SEM_IMAGEM_TTL
            raise


def _listar_produtos_com_imagem() -> list:
    """Códigos dos produtos ativos com imagem, paginando (o DbExplorer limita a 5000 linhas)."""
    codigos, ultimo = [], 0
    while True:
        lote = _consultar(
            # DATALENGTH > 100 descarta campos vazios ou com texto ("deletado")
            "SELECT CODPROD FROM TGFPRO WHERE DATALENGTH(IMAGEM) > 100 AND ATIVO = 'S' "
            f"AND CODPROD > {ultimo} ORDER BY CODPROD"
        )
        if not lote:
            return codigos
        codigos += lote
        ultimo = int(lote[-1])


def _aquecer_uma_vez() -> bool:
    """Baixa as imagens que faltam no cache. Retorna False se parou por falhas seguidas."""
    _aquecimento.update(estado="listando", processadas=0, baixadas=0, falhas=0, ultimo_erro=None)
    faltando = [c for c in _listar_produtos_com_imagem() if not _caminho(int(c)).exists()]
    logger.info("Aquecimento: %d imagens fora do cache", len(faltando))
    _aquecimento.update(estado="baixando", pendentes=len(faltando))

    baixadas = falhas_seguidas = 0
    for codprod in map(int, faltando):
        _aquecimento["processadas"] += 1
        lock = _lock_do_produto(codprod)
        if not lock.acquire(blocking=False):
            continue  # uma requisição já está buscando este produto
        try:
            if not _caminho(codprod).exists():
                consultar_e_salvar_imagem(codprod)
                baixadas += 1
                _aquecimento["baixadas"] = baixadas
            falhas_seguidas = 0
        except ImagemNaoEncontrada:
            falhas_seguidas = 0
        except Exception as e:  # pylint: disable=broad-except
            falhas_seguidas += 1
            _aquecimento["falhas"] += 1
            _aquecimento["ultimo_erro"] = f"codprod={codprod}: {e}"[:300]
            logger.warning("Aquecimento: falha em codprod=%s: %s", codprod, e)
            if falhas_seguidas >= AQUECIMENTO_MAX_FALHAS:
                logger.error("Aquecimento interrompido após %d falhas seguidas", falhas_seguidas)
                _aquecimento["estado"] = "interrompido"
                return False
        finally:
            lock.release()
        if baixadas and baixadas % 500 == 0:
            logger.info("Aquecimento: %d/%d imagens baixadas", baixadas, len(faltando))
        time.sleep(AQUECIMENTO_PAUSA)

    logger.info("Aquecimento concluído: %d imagens baixadas", baixadas)
    _aquecimento["estado"] = "concluido"
    return True


def _aquecer_cache():
    while True:
        try:
            concluido = _aquecer_uma_vez()
        except Exception as e:  # pylint: disable=broad-except
            logger.error("Falha no aquecimento do cache: %s", e)
            _aquecimento.update(estado="interrompido", ultimo_erro=str(e)[:300])
            concluido = False
        # Se o Sankhya estava com problema, tenta de novo em 1h em vez de esperar 1 dia
        time.sleep(AQUECIMENTO_INTERVALO if concluido else 3600)


@app.get("/health")
def health():
    # imagens_em_cache permite conferir se o disco persiste entre deploys
    originais = sum(1 for p in IMAGES_DIR.glob("*.jpg") if p.stem.isdigit())  # ignora as redimensionadas
    return {"status": "ok", "imagens_em_cache": originais, "aquecimento": _aquecimento}


@app.get("/{codprod}")
@app.get("/{codprod}.jpg")
def serve_image(
    codprod: int,
    request: Request,
    w: Optional[int] = Query(None, description=f"Largura máxima em pixels: {', '.join(map(str, LARGURAS))}"),
):
    # Função síncrona: o FastAPI executa em threadpool, então uma consulta lenta
    # ao Sankhya não bloqueia as demais requisições.
    if w is not None and w not in LARGURAS:
        return Response(content=f"w deve ser um destes valores: {', '.join(map(str, LARGURAS))}", status_code=422)

    try:
        conteudo = _obter_imagem(codprod)
    except ImagemNaoEncontrada as e:
        return Response(content=str(e), status_code=404, headers={"Cache-Control": "public, max-age=300"})
    except Exception as e:  # pylint: disable=broad-except
        logger.error("Falha ao buscar codprod=%s no Sankhya: %s", codprod, e)
        return Response(content="Erro ao consultar o Sankhya.", status_code=502)

    conteudo = _para_jpeg(conteudo)  # cobre arquivos gravados antes da conversão existir
    if w:
        conteudo = _obter_redimensionada(codprod, conteudo, w)

    etag = f'"{hashlib.md5(conteudo).hexdigest()}"'
    headers = {"Cache-Control": CACHE_CONTROL, "ETag": etag}

    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers=headers)

    return Response(content=conteudo, media_type="image/jpeg", headers=headers)
