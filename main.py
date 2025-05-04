from fastapi import FastAPI, Response, BackgroundTasks
from sankhya_api.sk_api_utils import consulta_sankhya
from pathlib import Path

app = FastAPI()
IMAGES_DIR = Path("images")
IMAGES_DIR.mkdir(exist_ok=True)  # Garante que a pasta existe


def consultar_e_salvar_imagem(codprod: int) -> Path:
    sankhya_service = "DbExplorerSP.executeQuery"
    query = f"SELECT IMAGEM FROM TGFPRO WHERE CODPROD = {codprod}"
    result = consulta_sankhya(query, sankhya_service)

    if not result or not result[0]:
        raise ValueError("Imagem não encontrada no banco de dados.")

    imagem_hex = result[0]
    imagem_bytes = bytes.fromhex(imagem_hex)
    image_path = IMAGES_DIR / f"{codprod}.jpg"

    with open(image_path, "wb") as f:
        f.write(imagem_bytes)

    return image_path


@app.get("/{codprod}")
@app.get("/{codprod}.jpg")
async def serve_image(codprod: int):
    image_path = IMAGES_DIR / f"{codprod}.jpg"

    if image_path.exists():
        # Servindo imagem do cache
        return Response(content=image_path.read_bytes(), media_type="image/jpeg")

    try:
        # Buscar no banco e salvar
        image_path = consultar_e_salvar_imagem(codprod)
        return Response(content=image_path.read_bytes(), media_type="image/jpeg")
    except Exception as e:
        return Response(content=str(e), status_code=404)
