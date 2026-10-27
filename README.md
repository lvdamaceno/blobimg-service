# Servidor de Imagens de Produtos (Sankhya)

Expõe a imagem de cada produto cadastrada no Sankhya (`TGFPRO.IMAGEM`) como um link HTTP.

Produção: https://blobimg-service.onrender.com (Render, deploy automático a partir da `main`).

## 🌐 Como usar

```
GET /{codprod}.jpg          # ex.: /406676.jpg
GET /{codprod}              # mesmo resultado
GET /{codprod}.jpg?w=400    # redimensionada para no máximo 400px de largura (16–2000)
GET /health                 # health check
```

- A resposta é sempre um JPEG real (`image/jpeg`). Imagens salvas no Sankhya em outro formato (ex.: PNG) são convertidas, e as áreas transparentes ficam com fundo branco.
- Respostas:
  - `404`: o produto não tem imagem.
  - `502`: falha ao consultar o Sankhya.
- Envia `Cache-Control` (1 dia) e `ETag`, e responde `304` quando o cliente já tem a imagem.

## ⚡ Cache

1. A imagem consultada no Sankhya é gravada em `IMAGES_DIR/{codprod}.jpg`.
2. Ela é considerada válida por `IMAGEM_TTL` segundos (padrão: 1 dia).
3. Depois disso, a imagem em disco continua sendo servida e é atualizada em segundo plano. Se o Sankhya falhar, a imagem antiga continua valendo.
4. Se a imagem foi removida no ERP, o arquivo é apagado e o produto passa a responder `404`.
5. Produtos sem imagem ficam 1h em cache de memória, para não consultar o Sankhya a cada acesso.
6. Requisições simultâneas do mesmo produto fazem uma única consulta.
7. **Aquecimento:** ao iniciar, e depois uma vez por dia, o serviço baixa em segundo plano as imagens dos produtos ativos que ainda não estão no cache. As consultas são feitas uma de cada vez, com uma pausa entre elas. Depois de 10 falhas seguidas o aquecimento para e tenta de novo em 1h.

> No Render, o disco do serviço é apagado a cada deploy ou restart. Para manter o cache, anexe um disco persistente e aponte `IMAGES_DIR` para ele.

## ⚙️ Configuração

Variáveis de ambiente (veja `sankhya_api/.env.example`):

| Variável | Descrição |
|---|---|
| `SANKHYA_TOKEN`, `SANKHYA_APPKEY`, `SANKHYA_USERNAME`, `SANKHYA_PASSWORD` | Credenciais da API Sankhya |
| `IMAGES_DIR` | Pasta do cache em disco (padrão: `images`) |
| `IMAGEM_TTL` | Validade da imagem em disco, em segundos (padrão: `86400`) |
| `AQUECER_CACHE` | `true`/`false`: liga o aquecimento do cache (padrão: ligado só no Render) |

## 🩺 Monitoramento

- `GET /health` retorna `{"status": "ok", "imagens_em_cache": N}`.
- O workflow `.github/workflows/monitor.yml` confere a cada 5 minutos se o serviço responde e se serve JPEG. Quando falha, o GitHub manda e-mail para quem alterou o agendamento do workflow por último.

## 🚀 Executando localmente

```bash
pip install -r requirements.txt
uvicorn main:app --port 8000
```

Acesse http://localhost:8000/406676.jpg

## 📄 Licença

Uso interno / privado.
