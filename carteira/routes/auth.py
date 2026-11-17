from datetime import timedelta
from urllib.parse import urlparse

from flask import Blueprint, flash, redirect, render_template, request, url_for

from ..extensions import db
from ..models import Usuario
from ..seguranca import (MAX_TENTATIVAS, MINUTOS_BLOQUEIO, agora, encerrar_sessao, iniciar_sessao, usuario_logado)

bp = Blueprint("auth", __name__)


def _destino_seguro(url):
    """Só permite redirecionar para caminhos do próprio sistema."""
    if not url:
        return None
    p = urlparse(url)
    if p.scheme or p.netloc or not url.startswith("/") or url.startswith("//"):
        return None
    return url.rstrip("?")


@bp.route("/entrar", methods=["GET", "POST"])
def login():
    if usuario_logado():
        return redirect(url_for("main.painel"))
    email = (request.form.get("email") or "").strip().lower()
    erro = None
    if request.method == "POST":
        u = Usuario.query.filter(db.func.lower(Usuario.email) == email).first()
        if u and u.bloqueado:
            minutos = max(1, int((u.bloqueado_ate - agora()).total_seconds() // 60) + 1)
            erro = f"Acesso temporariamente bloqueado por excesso de tentativas. Tente de novo em {minutos} min."
        elif u and u.ativo and u.conferir_senha(request.form.get("senha")):
            iniciar_sessao(u, manter=request.form.get("manter") == "1")
            db.session.commit()
            return redirect(_destino_seguro(request.form.get("proximo")) or url_for("main.painel"))
        else:
            erro = "E-mail ou senha incorretos."     # genérica: não revela se o e-mail existe
            if u and u.ativo:
                u.tentativas_falhas += 1
                if u.tentativas_falhas >= MAX_TENTATIVAS:
                    u.bloqueado_ate = agora() + timedelta(minutes=MINUTOS_BLOQUEIO)
                    u.tentativas_falhas = 0
                    erro = f"Muitas tentativas incorretas. Acesso bloqueado por {MINUTOS_BLOQUEIO} minutos."
        db.session.commit()
    return render_template("auth/login.html", email=email, erro=erro, proximo=_destino_seguro(request.values.get("proximo")) or "")


@bp.route("/esqueci-a-senha")
def esqueci():
    return render_template("auth/esqueci.html")


@bp.route("/sair", methods=["POST"])
def logout():
    encerrar_sessao()
    flash("Você saiu do sistema.", "info")
    return redirect(url_for("auth.login"))
