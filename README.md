# Carteira Fiscal · ContabilizaPharma

Sistema web (Flask + SQLite) para gestão da carteira fiscal. Visão atual: **Coordenador Fiscal** (sem login).

Módulos: **Clientes**, **Equipe** (organograma visual) e **Carteiras**.

## Rodar
```
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python app.py        # http://localhost:5050
```
Na primeira execução o banco (`instance/carteira.db`) é criado e a planilha de clientes é importada
(caminho em `PLANILHA_CLIENTES` ou o padrão em `config.py`). Novas planilhas podem ser importadas pela tela Clientes.

## Migrar para outro banco
Defina `DATABASE_URL` (ex.: `postgresql+psycopg://user:senha@host/db`) e instale o driver. As tabelas são criadas via SQLAlchemy.
