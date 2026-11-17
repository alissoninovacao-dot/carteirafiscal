import os

from flask import Flask

from config import Config
from .extensions import db


def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)
    _garantir_chave_secreta(app)
    os.makedirs(os.path.join(app.root_path, "..", "instance"), exist_ok=True)
    db.init_app(app)

    from .routes import auth, carteiras, clientes, entregas, equipe, internas, main, perfil, usuarios
    from . import models_internas  # noqa: F401  (registra as tabelas)
    for m in (auth, main, clientes, equipe, carteiras, entregas, usuarios, perfil, internas):
        app.register_blueprint(m.bp)
    from .seguranca import carregar_usuario, csrf_campo, csrf_token, verificar_csrf, usuario_logado
    app.before_request(carregar_usuario)
    app.before_request(verificar_csrf)
    app.jinja_env.globals.update(csrf_token=csrf_token, csrf_campo=csrf_campo, usuario_logado=usuario_logado)

    with app.app_context():
        db.create_all()
        _migrar()
        _semear()
        _tipos_padrao()
        _semear_usuarios()
    return app


def _garantir_chave_secreta(app):
    """Sem SECRET_KEY no ambiente, gera uma chave aleatória e a guarda em instance/ (fora do código)."""
    if os.environ.get("SECRET_KEY"):
        return
    caminho = os.path.join(app.root_path, "..", "instance", "secret_key")
    os.makedirs(os.path.dirname(caminho), exist_ok=True)
    if not os.path.exists(caminho):
        import secrets
        with open(caminho, "w", encoding="utf-8") as f:
            f.write(secrets.token_hex(32))
    with open(caminho, encoding="utf-8") as f:
        app.config["SECRET_KEY"] = f.read().strip()


def _semear_usuarios():
    from .acessos import semear_usuarios
    semear_usuarios()


def _migrar():
    """Banco já existente: adiciona o responsável da carteira e renomeia 'Carteira <Analista>' para 'Carteira N'."""
    from sqlalchemy import text
    from .models import Carteira, Pessoa
    cols = [r[1] for r in db.session.execute(text("PRAGMA table_info(carteira)"))] if db.engine.dialect.name == "sqlite" else None
    if cols is not None and "responsavel_id" not in cols:
        db.session.execute(text("ALTER TABLE carteira ADD COLUMN responsavel_id INTEGER REFERENCES pessoa(id)"))
        db.session.commit()
    cols_p = [r[1] for r in db.session.execute(text("PRAGMA table_info(pessoa)"))] if db.engine.dialect.name == "sqlite" else None
    cols_t = [r[1] for r in db.session.execute(text("PRAGMA table_info(tipo_entrega)"))] if db.engine.dialect.name == "sqlite" else None
    novas = {"descricao": "TEXT", "fonte": "VARCHAR(255)", "periodicidade": "VARCHAR(10) DEFAULT 'mensal'", "regra": "VARCHAR(30)",
             "mes_anual": "INTEGER", "requer": "VARCHAR(20) DEFAULT ''", "geracao": "VARCHAR(10) DEFAULT 'auto'", "padrao": "BOOLEAN DEFAULT 0"}
    if cols_t:
        for nome, tipo in novas.items():
            if nome not in cols_t:
                db.session.execute(text(f"ALTER TABLE tipo_entrega ADD COLUMN {nome} {tipo}"))
        db.session.commit()
    cols_m = [r[1] for r in db.session.execute(text("PRAGMA table_info(time_membro)"))] if db.engine.dialect.name == "sqlite" else None
    if cols_m and "apoio" not in cols_m:
        db.session.execute(text("ALTER TABLE time_membro ADD COLUMN apoio BOOLEAN NOT NULL DEFAULT 0"))
        db.session.commit()
    # equipes: da coluna única antiga (pessoa.time_id) para a tabela de vínculos (uma pessoa em vários blocos)
    if cols_p and "time_id" in cols_p:
        db.session.execute(text("INSERT OR IGNORE INTO time_membro (pessoa_id, time_id) SELECT id, time_id FROM pessoa WHERE time_id IS NOT NULL"))
        db.session.execute(text("UPDATE pessoa SET time_id = NULL WHERE time_id IS NOT NULL"))
        db.session.commit()
    for i, c in enumerate(Carteira.query.order_by(Carteira.id), 1):
        if c.nome.startswith("Carteira ") and not c.nome[9:].isdigit():
            p = Pessoa.query.filter_by(nome=c.nome[9:]).first()
            if p and not c.responsavel_id:
                c.responsavel_id = p.id
            c.nome, c.descricao = f"Carteira {i}", None
    db.session.commit()


def _semear():
    """Cria o coordenador fiscal e importa a planilha na primeira execução."""
    from .models import Pessoa
    if Pessoa.query.first():
        return
    db.session.add(Pessoa(nome="Coordenador Fiscal", papel="coordenador_fiscal", cor="#002068"))
    db.session.commit()
    if os.path.exists(Config.PLANILHA_PADRAO):
        from .importar import importar_planilha
        importar_planilha(Config.PLANILHA_PADRAO)


def _tipos_padrao():
    """Cria/atualiza o catálogo padrão de obrigações acessórias (editável na tela Entregas)."""
    from .obrigacoes import semear_catalogo
    semear_catalogo()
