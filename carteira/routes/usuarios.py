"""Gestão de usuários e senhas — exclusivo do administrador master."""
import re

from flask import Blueprint, abort, flash, jsonify, redirect, render_template, request, session, url_for

from config import Config
from ..extensions import db
from ..models import PERFIS, Usuario
from ..seguranca import agora, usuario_logado

bp = Blueprint("usuarios", __name__)
PERFIS_AVULSOS = ("admin", "diretoria", "coordenador_fiscal")      # sem vínculo com a equipe; colaborador nasce em Equipe
EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


@bp.before_request
def somente_admin():
    u = usuario_logado()
    if not u or u.perfil != "admin":
        if request.path.startswith("/api/"):
            return jsonify(erro="Somente o administrador master gerencia usuários."), 403
        flash("Somente o administrador master gerencia usuários.", "warning")
        return redirect(url_for("main.painel"))


def _dict(u):
    return dict(id=u.id, nome=u.nome, email=u.email, perfil=u.perfil, perfil_label=u.perfil_label, ativo=bool(u.ativo),
                bloqueado=u.bloqueado, vinculado=bool(u.pessoa_id), pessoa=u.pessoa.papel_nome if u.pessoa else "",
                master=u.email.lower() == Config.ADMIN_EMAIL.lower(), eu=u.id == usuario_logado().id,
                ultimo_acesso=u.ultimo_acesso.strftime("%d/%m/%Y %H:%M") if u.ultimo_acesso else "",
                senha_em=u.senha_alterada_em.strftime("%d/%m/%Y") if u.senha_alterada_em else "")


def _lista():
    return [_dict(u) for u in Usuario.query.order_by(Usuario.nome).all()]


def _admins_ativos(excluindo=None):
    q = Usuario.query.filter_by(perfil="admin", ativo=True)
    return q.filter(Usuario.id != excluindo).count() if excluindo else q.count()


def _validar_senha(s):
    if len(s or "") < 8:
        return "A senha precisa ter pelo menos 8 caracteres."
    return None


def _email_livre(email, ignorar=None):
    q = Usuario.query.filter(db.func.lower(Usuario.email) == email.lower())
    if ignorar:
        q = q.filter(Usuario.id != ignorar)
    return q.first() is None


@bp.route("/usuarios")
def pagina():
    return render_template("usuarios.html", lista=_lista(), perfis=PERFIS, avulsos=PERFIS_AVULSOS, padrao_len=len(Config.SENHA_PADRAO))


@bp.post("/api/usuarios")
def criar():
    d = request.get_json(force=True)
    nome, email, perfil = (d.get("nome") or "").strip(), (d.get("email") or "").strip().lower(), d.get("perfil")
    if not nome:
        return jsonify(erro="Informe o nome."), 400
    if not EMAIL.match(email):
        return jsonify(erro="Informe um e-mail válido."), 400
    if perfil not in PERFIS_AVULSOS:
        return jsonify(erro="Perfil inválido. Colaboradores são criados em Equipe, junto com a pessoa."), 400
    if not _email_livre(email):
        return jsonify(erro="Já existe um usuário com esse e-mail."), 400
    senha = d.get("senha") or Config.SENHA_PADRAO
    if d.get("senha") and (erro := _validar_senha(senha)):
        return jsonify(erro=erro), 400
    u = Usuario(nome=nome, email=email, perfil=perfil, ativo=True)
    u.definir_senha(senha)
    db.session.add(u)
    db.session.commit()
    return jsonify(_lista())


@bp.put("/api/usuarios/<int:uid>")
def editar(uid):
    u = db.session.get(Usuario, uid) or abort(404)
    d = request.get_json(force=True)
    eu = usuario_logado()
    nome = (d.get("nome", u.nome) or "").strip()
    email = (d.get("email", u.email) or "").strip().lower()
    if not nome:
        return jsonify(erro="Informe o nome."), 400
    if not EMAIL.match(email):
        return jsonify(erro="Informe um e-mail válido."), 400
    if not _email_livre(email, u.id):
        return jsonify(erro="Já existe um usuário com esse e-mail."), 400
    master = u.email.lower() == Config.ADMIN_EMAIL.lower()
    if master and email != u.email.lower():
        return jsonify(erro="O e-mail do administrador master não pode ser alterado."), 400
    ativo = bool(d.get("ativo", u.ativo))
    if not ativo and (u.id == eu.id or master):
        return jsonify(erro="Este usuário não pode ser desativado."), 400
    perfil = d.get("perfil", u.perfil)
    if not u.pessoa_id and perfil != u.perfil:
        if perfil not in PERFIS_AVULSOS:
            return jsonify(erro="Perfil inválido."), 400
        if u.perfil == "admin" and (u.id == eu.id or master or _admins_ativos(u.id) == 0):
            return jsonify(erro="Mantenha pelo menos um administrador master."), 400
        u.perfil = perfil
    u.nome, u.email, u.ativo = nome, email, ativo
    if u.pessoa:                                         # nome e e-mail seguem a pessoa da equipe
        u.pessoa.nome, u.pessoa.email, u.pessoa.ativo = nome, email, ativo
    if not ativo:
        u.bloqueado_ate, u.tentativas_falhas = None, 0
    db.session.commit()
    return jsonify(_lista())


@bp.post("/api/usuarios/<int:uid>/senha")
def redefinir_senha(uid):
    """Sem 'senha' no corpo = volta para a senha padrão. Encerra as sessões abertas do usuário."""
    u = db.session.get(Usuario, uid) or abort(404)
    d = request.get_json(force=True)
    senha = d.get("senha") or Config.SENHA_PADRAO
    if d.get("senha") and (erro := _validar_senha(senha)):
        return jsonify(erro=erro), 400
    u.definir_senha(senha)
    u.bloqueado_ate, u.tentativas_falhas = None, 0
    if u.id == usuario_logado().id:                      # não derruba a própria sessão
        session["versao_senha"] = u.senha_alterada_em.isoformat()
    db.session.commit()
    return jsonify(_lista())


@bp.post("/api/usuarios/<int:uid>/desbloquear")
def desbloquear(uid):
    u = db.session.get(Usuario, uid) or abort(404)
    u.bloqueado_ate, u.tentativas_falhas = None, 0
    db.session.commit()
    return jsonify(_lista())


@bp.post("/api/usuarios/<int:uid>/encerrar-sessoes")
def encerrar_sessoes(uid):
    """Invalida os logins abertos sem mudar a senha (renova a 'versão' da senha, que as sessões conferem)."""
    u = db.session.get(Usuario, uid) or abort(404)
    u.senha_alterada_em = agora()
    if u.id == usuario_logado().id:
        session["versao_senha"] = u.senha_alterada_em.isoformat()
    db.session.commit()
    return jsonify(_lista())


@bp.delete("/api/usuarios/<int:uid>")
def excluir(uid):
    u = db.session.get(Usuario, uid) or abort(404)
    if u.id == usuario_logado().id or u.email.lower() == Config.ADMIN_EMAIL.lower():
        return jsonify(erro="Este usuário não pode ser excluído."), 400
    if u.pessoa_id:
        return jsonify(erro="Usuário vinculado a uma pessoa da equipe: desative aqui ou exclua a pessoa em Equipe."), 400
    db.session.delete(u)
    db.session.commit()
    return jsonify(_lista())
