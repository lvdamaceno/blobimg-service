# Servidor de Imagens de Produtos (Sankhya)

Expõe a imagem de cada produto cadastrada no Sankhya (`TGFPRO.IMAGEM`) como um link HTTP.

Produção: https://blobimg-service.onrender.com (Render, deploy automático a partir da `main`).

## 🌐 Como usar

```
GET /{codprod}.jpg          # ex.: /406676.jpg
GET /{codprod}              # mesmo resultado
GET /{codprod}.jpg?w=400    # no máximo 400px de largura (w: 100, 200, 400 ou 800)
GET /health                 # health check
```

- A resposta é sempre um JPEG real (`image/jpeg`). Imagens salvas no Sankhya em outro formato (ex.: PNG) são convertidas, e as áreas transparentes ficam com fundo branco.
- Respostas:
  - `404`: o produto não tem imagem, ou o campo `IMAGEM` não contém uma imagem (o Sankhya grava o texto `deletado` quando a imagem é apagada).
  - `502`: falha ao consultar o Sankhya.
- Envia `Cache-Control` (1 dia) e `ETag`, e responde `304` quando o cliente já tem a imagem.

## ⚡ Cache

1. A imagem consultada no Sankhya é gravada em `IMAGES_DIR/{codprod}.jpg`.
2. Ela é considerada válida por `IMAGEM_TTL` segundos (padrão: 1 dia).
3. Depois disso, a imagem em disco continua sendo servida e é atualizada em segundo plano. Se o Sankhya falhar, a imagem antiga continua valendo.
4. Se a imagem foi removida no ERP, o arquivo é apagado e o produto passa a responder `404`.
5. Produtos sem imagem ficam 1h em cache de memória, para não consultar o Sankhya a cada acesso.
6. As versões redimensionadas (`?w=`) também ficam em disco (`{codprod}_w{w}.jpg`) e são refeitas quando a original é atualizada.
7. Requisições simultâneas do mesmo produto fazem uma única consulta.
8. **Aquecimento:** ao iniciar, e depois uma vez por dia, o serviço baixa em segundo plano as imagens dos produtos ativos que ainda não estão no cache. Só entram produtos com `DATALENGTH(IMAGEM) > 100`, o que descarta campos vazios e o texto `deletado`. As consultas são feitas uma de cada vez, com uma pausa entre elas. Depois de 10 falhas seguidas o aquecimento para e tenta de novo em 1h.

> No Render, o disco do serviço é apagado a cada deploy ou restart. Para manter o cache, anexe um disco persistente e aponte `IMAGES_DIR` para ele.

### Imagens grandes

O gateway do Sankhya devolve erro 500 quando a imagem é muito grande (há imagens de até 28MB no banco). Quando a consulta falha e a imagem tem mais de 2MB (`DATALENGTH`), o serviço busca o conteúdo em partes de 2MB com `SUBSTRING`. A primeira busca dessas imagens pode levar de 20 a 80 segundos; depois elas saem do cache.

## ⚙️ Configuração

Variáveis de ambiente (veja `sankhya_api/.env.example`):

| Variável | Descrição |
|---|---|
| `SANKHYA_TOKEN`, `SANKHYA_APPKEY`, `SANKHYA_USERNAME`, `SANKHYA_PASSWORD` | Credenciais da API Sankhya |
| `IMAGES_DIR` | Pasta do cache em disco (padrão: `images`) |
| `IMAGEM_TTL` | Validade da imagem em disco, em segundos (padrão: `86400`) |
| `AQUECER_CACHE` | `true`/`false`: liga o aquecimento do cache (padrão: ligado só no Render) |

## 🩺 Monitoramento

- `GET /health` retorna o status, a quantidade de imagens em cache e o estado do aquecimento:
  ```json
  {"status": "ok", "imagens_em_cache": 1132,
   "aquecimento": {"estado": "baixando", "pendentes": 10406, "processadas": 497,
                   "baixadas": 172, "falhas": 1, "ultimo_erro": "codprod=141795: ..."}}
  ```
  O `estado` pode ser `desligado`, `listando`, `baixando`, `concluido` ou `interrompido` (este último depois de 10 falhas seguidas; tenta de novo em 1h).
- O workflow `.github/workflows/monitor.yml` confere a cada 5 minutos se o serviço responde e se serve JPEG. Quando falha, o GitHub manda e-mail para quem alterou o agendamento do workflow por último.

## 🚀 Executando localmente

```bash
pip install -r requirements.txt
uvicorn main:app --port 8000
```

Acesse http://localhost:8000/406676.jpg

## 🧪 Testes

```bash
pip install -r requirements-dev.txt
pytest
```

Os testes usam um Sankhya simulado e não fazem nenhuma chamada real. Eles rodam no GitHub Actions a cada PR e a cada push na `main`.

## 📄 Licença

Uso interno / privado.
