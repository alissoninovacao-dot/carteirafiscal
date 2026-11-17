"""Autenticação por sessão e proteção CSRF (mesmo modelo do sistema Acompanhe)."""
import hmac
import secrets
from datetime import datetime, timedelta

from flask import current_app, flash, g, jsonify, redirect, render_template, request, session, url_for
from markupsafe import Markup

from .extensions import db
from .models import Usuario

# O colaborador só enxerga/usa estas rotas (por método). O resto é exclusivo do coordenador/administrador.
COLAB_PERMITIDOS = {
    "GET": {"main.painel", "clientes.lista", "clientes.editar", "equipe.pagina", "equipe.estado", "carteiras.minha", "carteiras.lista",
            "entregas.pagina", "entregas.calendario", "entregas.listar", "entregas.obrigacoes_cliente", "perfil.pagina", "entregas.demandas", "internas.lista", "internas.detalhe", "internas.anexo"},
    "PUT": {"entregas.editar"},
    "POST": {"perfil.alterar_senha", "perfil.encerrar_outros", "internas.status", "internas.informar_conclusao", "internas.registro",
             "internas.impedimento", "internas.checklist_alternar"},
}
PUBLICOS = {"static", "auth.login", "auth.esqueci"}
MAX_TENTATIVAS = 5
MINUTOS_BLOQUEIO = 15


def agora():
    return datetime.now()


def usuario_logado():
    return g.get("usuario")


def iniciar_sessao(u, manter=False):
    session.clear()                      # evita fixação de sessão
    session["uid"] = u.id
    session["versao_senha"] = u.senha_alterada_em.isoformat() if u.senha_alterada_em else ""
    session.permanent = True
    horas = 24 * 30 if manter else current_app.config["HORAS_SESSAO"]
    session["expira"] = (agora() + timedelta(hours=horas)).isoformat()
    session["manter"] = bool(manter)
    u.ultimo_acesso = agora()
    u.tentativas_falhas = 0
    u.bloqueado_ate = None


def encerrar_sessao():
    session.clear()


def carregar_usuario():
    """before_request: identifica o usuário e barra quem não entrou."""
    g.usuario = None
    uid = session.get("uid")
    if uid:
        u = db.session.get(Usuario, uid)
        versao = u.senha_alterada_em.isoformat() if u and u.senha_alterada_em else ""
        if u and u.ativo and session.get("versao_senha", "") == versao and session.get("expira", "") >= agora().isoformat():
            g.usuario = u
            if not session.get("manter"):    # sessão deslizante: cada uso renova o prazo de inatividade
                session["expira"] = (agora() + timedelta(hours=current_app.config["HORAS_SESSAO"])).isoformat()
        else:
            session.clear()
    ep = request.endpoint or ""
    if ep in PUBLICOS:
        return None
    if g.usuario:
        if g.usuario.e_colaborador and ep not in COLAB_PERMITIDOS.get(request.method, set()) and ep not in ("auth.logout",):
            if request.path.startswith("/api/") or request.method != "GET":
                return jsonify(erro="Você não tem permissão para esta ação."), 403
            flash("Essa área é exclusiva do coordenador fiscal.", "warning")
            return redirect(url_for("main.painel"))
        return None
    if request.path.startswith("/api/"):
        return jsonify(erro="Sessão expirada. Faça login novamente."), 401
    proximo = request.full_path.rstrip("?") if request.method == "GET" and request.path != "/" else None
    return redirect(url_for("auth.login", proximo=proximo))


# ---- CSRF: token por sessão, em formulários (campo) e fetch (cabeçalho X-CSRFToken) ----
def csrf_token():
    if "_csrf" not in session:
        session["_csrf"] = secrets.token_urlsafe(32)
    return session["_csrf"]


def csrf_campo():
    return Markup(f'<input type="hidden" name="csrf_token" value="{csrf_token()}">')


def verificar_csrf():
    if request.method in ("GET", "HEAD", "OPTIONS") or request.endpoint == "static":
        return None
    enviado = request.headers.get("X-CSRFToken") or request.form.get("csrf_token") or ""
    esperado = session.get("_csrf") or ""
    if not esperado or not hmac.compare_digest(enviado, esperado):
        if request.path.startswith("/api/") or request.is_json:
            return jsonify(erro="Sessão expirada. Recarregue a página."), 400
        return render_template("auth/erro.html", mensagem="Sua sessão expirou ou o formulário ficou aberto por muito tempo. Volte, recarregue a página e tente novamente."), 400
    return None


def escopo_carteiras():
    """None = vê tudo (coordenador/admin). Colaborador: lista de ids das carteiras dele/da equipe dele."""
    u = usuario_logado()
    if not u or not u.e_colaborador:
        return None
    return [c.id for c in u.pessoa.carteiras_escopo()] if u.pessoa else []
