"""Meu perfil: dados cadastrais do próprio usuário e troca de senha (qualquer perfil)."""
from datetime import timedelta

from flask import Blueprint, jsonify, render_template, request, session

from config import Config
from ..extensions import db
from ..seguranca import MAX_TENTATIVAS, MINUTOS_BLOQUEIO, agora, usuario_logado

bp = Blueprint("perfil", __name__)


def _fmt(d, hora=True):
    return d.strftime("%d/%m/%Y %H:%M" if hora else "%d/%m/%Y") if d else "—"


@bp.route("/perfil")
def pagina():
    u = usuario_logado()
    p = u.pessoa
    carteiras = [c.nome for c in p.carteiras_escopo()] if p else []
    return render_template(
        "perfil.html", u=u, p=p, carteiras=carteiras, equipes=p.times if p else [], senha_em=_fmt(u.senha_alterada_em),
        ultimo=_fmt(u.ultimo_acesso), sessao_ate=_fmt(_expira()), padrao=u.conferir_senha(Config.SENHA_PADRAO))


def _expira():
    from datetime import datetime
    try:
        return datetime.fromisoformat(session.get("expira", ""))
    except ValueError:
        return None


@bp.post("/api/perfil/senha")
def alterar_senha():
    u = usuario_logado()
    d = request.get_json(force=True)
    atual, nova, conf = d.get("atual") or "", d.get("nova") or "", d.get("confirmar") or ""
    if not u.conferir_senha(atual):
        u.tentativas_falhas += 1
        if u.tentativas_falhas >= MAX_TENTATIVAS:       # mesmo limite do login: protege contra quem usa uma sessão deixada aberta
            u.bloqueado_ate, u.tentativas_falhas = agora() + timedelta(minutes=MINUTOS_BLOQUEIO), 0
        db.session.commit()
        return jsonify(erro="A senha atual está incorreta."), 400
    if len(nova) < 8:
        return jsonify(erro="A nova senha precisa ter pelo menos 8 caracteres."), 400
    if not (any(c.isalpha() for c in nova) and any(c.isdigit() for c in nova)):
        return jsonify(erro="Use letras e números na nova senha."), 400
    if nova != conf:
        return jsonify(erro="A confirmação não confere com a nova senha."), 400
    if nova == atual or nova == Config.SENHA_PADRAO:
        return jsonify(erro="Escolha uma senha diferente da atual e da senha padrão."), 400
    u.definir_senha(nova)
    u.tentativas_falhas = 0
    session["versao_senha"] = u.senha_alterada_em.isoformat()      # mantém este login; os demais caem
    db.session.commit()
    return jsonify(ok=True, senha_em=_fmt(u.senha_alterada_em))


@bp.post("/api/perfil/encerrar-outros")
def encerrar_outros():
    """Sai de todos os outros dispositivos/navegadores, mantendo este login."""
    u = usuario_logado()
    u.senha_alterada_em = agora()
    session["versao_senha"] = u.senha_alterada_em.isoformat()
    db.session.commit()
    return jsonify(ok=True)
