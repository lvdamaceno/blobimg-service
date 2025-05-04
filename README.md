# Servidor de Imagens de Produtos via FastAPI

Este projeto expõe imagens de produtos salvas no banco de dados Sankhya via URL HTTP.

## 📦 Requisitos

- Python 3.9+
- FastAPI
- Uvicorn
- sankhya_api (módulo personalizado de acesso à API Sankhya)

## ⚙️ Instalação

```bash
pip install fastapi uvicorn
```

Adicione o módulo `sankhya_api` ao seu projeto (estrutura esperada: `from sankhya_api.sk_api_utils import consulta_sankhya`).

## 🚀 Executando localmente

```bash
uvicorn main:app --host 0.0.0.0 --port 8000
```

## 🌐 Como usar

Acesse via navegador ou ferramenta HTTP:

```
http://localhost:8000/406676.jpg
```

Esse endpoint irá:

1. Buscar a imagem no banco de dados Sankhya.
2. Gerar o arquivo temporário na pasta `images/`.
3. Servir a imagem como `image/jpeg`.
4. Apagar o arquivo automaticamente após envio.

## 🧹 Limpeza automática

O arquivo de imagem é removido logo após ser enviado para evitar acúmulo no servidor.

## 📁 Estrutura esperada

```
.
├── main.py
├── images/          # Pasta criada automaticamente
└── sankhya_api/
    └── sk_api_utils.py  # Deve conter a função consulta_sankhya()
```

## 🛠️ Personalização

Se desejar manter as imagens no servidor, basta remover o uso de `BackgroundTasks`.

## 📄 Licença

Uso interno / privado.