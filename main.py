from sankhya_api.sk_api_utils import consulta_sankhya


def get_image(codprod):
    sankhya_service = "DbExplorerSP.executeQuery"
    query = f"SELECT IMAGEM FROM TGFPRO WHERE CODPROD = {codprod}"
    result = consulta_sankhya(query, sankhya_service)
    imagem_hex = result[0]
    imagem_bytes = bytes.fromhex(imagem_hex)
    with open(f"{codprod}.jpg", "wb") as f:
        f.write(imagem_bytes)


if __name__ == '__main__':
    get_image(406676)
