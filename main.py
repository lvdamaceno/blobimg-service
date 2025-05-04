from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.responses import FileResponse
import os
from sankhya_api.sk_api_utils import consulta_sankhya

app = FastAPI()

IMAGE_DIR = "images"
os.makedirs(IMAGE_DIR, exist_ok=True)


def get_image(codprod: int) -> str:
    """
    Consulta a imagem no banco de dados Sankhya e salva na pasta 'images'.
    Retorna o caminho do arquivo salvo.
    """
    sankhya_service = "DbExplorerSP.executeQuery"
    query = f"SELECT IMAGEM FROM TGFPRO WHERE CODPROD = {codprod}"
    result = consulta_sankhya(query, sankhya_service)

    if not result:
        raise ValueError(f"Imagem não encontrada para o produto {codprod}")

    imagem_hex = result[0]
    imagem_bytes = bytes.fromhex(imagem_hex)

    filepath = os.path.join(IMAGE_DIR, f"{codprod}.jpg")

    with open(filepath, "wb") as f:
        f.write(imagem_bytes)

    return filepath


def remove_file(path: str):
    """Remove o arquivo salvo após o envio."""
    try:
        os.remove(path)
        print(f"[INFO] Arquivo removido: {path}")
    except Exception as e:
        print(f"[ERRO] Falha ao remover {path}: {e}")


@app.get("/{codprod}.jpg")
def serve_image(codprod: int, background_tasks: BackgroundTasks):
    """
    Endpoint que gera a imagem, serve ao cliente e agenda sua remoção após envio.
    """
    try:
        filepath = get_image(codprod)
        background_tasks.add_task(remove_file, filepath)
        return FileResponse(filepath, media_type="image/jpeg")
    except Exception as e:
        raise HTTPException(status_code=404, detail=str(e))
