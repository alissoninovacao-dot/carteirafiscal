import os

BASE_DIR = os.path.abspath(os.path.dirname(__file__))


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-carteira-fiscal")
    # SQLite agora; para migrar basta trocar a URL (ex.: postgresql+psycopg://user:senha@host/db)
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "DATABASE_URL", "sqlite:///" + os.path.join(BASE_DIR, "instance", "carteira.db").replace("\\", "/")
    )
    PERMANENT_SESSION_LIFETIME = 60 * 60 * 24 * 30          # teto do cookie ("manter conectado": 30 dias)
    HORAS_SESSAO = int(os.environ.get("HORAS_SESSAO", 12))  # sem "manter conectado": expira após 12h sem uso
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = os.environ.get("SESSION_COOKIE_SECURE", "0") == "1"   # ligar em produção (HTTPS)
    SESSION_COOKIE_NAME = os.environ.get("SESSION_COOKIE_NAME", "carteira_fiscal_sessao")   # não colide com outros sistemas em localhost
    SENHA_PADRAO = os.environ.get("SENHA_PADRAO", "Contabiliza@2026")
    ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL", "suporte@contabilizape.com.br")
    MAX_CONTENT_LENGTH = 20 * 1024 * 1024
    UPLOAD_INTERNAS = os.environ.get("UPLOAD_INTERNAS", os.path.join(BASE_DIR, "instance", "uploads_internas"))   # anexos das demandas internas
    PLANILHA_PADRAO = os.environ.get(
        "PLANILHA_CLIENTES", r"C:\Users\alison.jesus\Desktop\CONTABILIZA - CLIENTES.xlsx"
    )
