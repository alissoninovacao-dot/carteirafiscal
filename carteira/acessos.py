"""Criação e sincronização dos acessos (um usuário por pessoa da equipe)."""
import unicodedata

from config import Config
from .extensions import db
from .models import Pessoa, Usuario

DOMINIO = "contabilizape.com.br"


def email_padrao(nome):
    """Padrão da casa: primeironome.fiscal@contabilizape.com.br (sem acentos)."""
    primeiro = (nome or "usuario").split()[0]
    primeiro = unicodedata.normalize("NFKD", primeiro).encode("ascii", "ignore").decode().lower()
    return f"{primeiro}.fiscal@{DOMINIO}"


def perfil_da_pessoa(p):
    return "diretoria" if p.e_diretoria else "coordenador_fiscal" if p.e_coordenador else "colaborador"


def garantir_usuario(p, commit=True):
    """Cria (com a senha padrão) ou atualiza o acesso da pessoa. Nunca redefine a senha de quem já existe."""
    if not p.email:
        p.email = email_padrao(p.nome)
    email = p.email.strip().lower()
    u = Usuario.query.filter_by(pessoa_id=p.id).first()
    if u is None:
        u = Usuario.query.filter(db.func.lower(Usuario.email) == email).first()
        if u is not None and u.perfil == "admin":
            return u
    if u is None:
        u = Usuario(nome=p.nome, email=email, perfil=perfil_da_pessoa(p), pessoa_id=p.id)
        u.definir_senha(Config.SENHA_PADRAO)
        db.session.add(u)
    else:
        outro = Usuario.query.filter(db.func.lower(Usuario.email) == email, Usuario.id != u.id).first()
        u.nome, u.pessoa_id, u.perfil = p.nome, p.id, perfil_da_pessoa(p)
        if not outro:
            u.email = email
    u.ativo = bool(p.ativo)
    if commit:
        db.session.commit()
    return u


def remover_usuario(p):
    Usuario.query.filter_by(pessoa_id=p.id).delete()


def semear_usuarios():
    """Administrador master + um acesso para cada pessoa da equipe (coordenador e colaboradores)."""
    if not Usuario.query.filter(db.func.lower(Usuario.email) == Config.ADMIN_EMAIL.lower()).first():
        u = Usuario(nome="Suporte ContabilizaPharma", email=Config.ADMIN_EMAIL, perfil="admin")
        u.definir_senha(Config.SENHA_PADRAO)
        db.session.add(u)
    db.session.flush()
    for p in Pessoa.query.order_by(Pessoa.id):
        garantir_usuario(p, commit=False)
    db.session.commit()
