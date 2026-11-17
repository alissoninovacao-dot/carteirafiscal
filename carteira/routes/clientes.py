from datetime import datetime

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from sqlalchemy import or_

from ..extensions import db
from ..importar import importar_planilha
from ..seguranca import usuario_logado
from ..models import CAMPOS_CLIENTE, TRIBUTACOES, Carteira, Cliente, Pessoa, Time

bp = Blueprint("clientes", __name__, url_prefix="/clientes")
POR_PAGINA = 200                      # padrão
OPCOES_POR_PAGINA = (50, 100, 200, 400, 600)   # máximo: 600


def _filtrar(args):
    q = Cliente.query
    if t := args.get("q", "").strip():
        like = f"%{t}%"
        q = q.filter(or_(Cliente.empresa.ilike(like), Cliente.cnpj.ilike(like), Cliente.municipio.ilike(like)))
    for campo in ("situacao", "tributacao", "uf", "credenciamento"):
        if v := args.get(campo):
            q = q.filter(getattr(Cliente, campo) == v)
    if v := args.get("responsavel"):   # responsável = responsável pela carteira do cliente
        if v == "0":
            sem = [c.id for c in Carteira.query.filter(Carteira.responsavel_id.isnot(None))]
            q = q.filter(Cliente.carteira_id.is_(None) | ~Cliente.carteira_id.in_(sem)) if sem else q
        else:
            q = q.filter(Cliente.carteira_id.in_([c.id for c in Carteira.query.filter_by(responsavel_id=int(v))] or [0]))
    if v := args.get("equipe"):
        if v == "0":   # ativas fora de qualquer equipe (sem carteira ou com responsável sem equipe)
            ids = [c.id for t in Time.query.all() for c in t.carteiras]
            q = q.filter(Cliente.carteira_id.is_(None) | ~Cliente.carteira_id.in_(ids)) if ids else q
        else:
            t = db.session.get(Time, int(v))
            q = q.filter(Cliente.carteira_id.in_([c.id for c in t.carteiras] if t else [0]))
    if args.get("carteira_do_coord"):
        q = q.filter(Cliente.carteira_id.in_([c.id for p in Pessoa.query.filter_by(papel="coordenador_fiscal") for c in p.carteiras_resp] or [0]))
    if v := args.get("carteira"):
        q = q.filter(Cliente.carteira_id.is_(None)) if v == "0" else q.filter(Cliente.carteira_id == int(v))
    return q


@bp.route("/")
def lista():
    pag = request.args.get("p", 1, type=int)
    pp = request.args.get("pp", POR_PAGINA, type=int)
    pp = pp if pp in OPCOES_POR_PAGINA else POR_PAGINA
    p = _filtrar(request.args).order_by(Cliente.empresa).paginate(page=pag, per_page=pp, error_out=False)

    def distintos(col):
        return [v for (v,) in db.session.query(col).filter(col.isnot(None)).distinct().order_by(col)]

    # parâmetros da busca sem o número da página (para os links de paginação)
    filtros = {k: v for k, v in request.args.items() if k != "p" and v}
    return render_template(
        "clientes/lista.html", p=p, args=request.args, filtros=filtros, pp=pp, opcoes_pp=OPCOES_POR_PAGINA,
        op_responsaveis=[("0", "— sem responsável —")] + [(a.id, a.nome) for a in Pessoa.query.order_by(Pessoa.nome) if not a.e_diretoria],
        op_carteiras=[("0", "— sem carteira —")] + [(c.id, c.nome) for c in Carteira.query.order_by(Carteira.nome)],
        op_tribs=[(t, t) for t in distintos(Cliente.tributacao)],
        op_equipes=[("0", "— sem equipe —")] + [(t.id, f"{t.nome} · {' / '.join(m.nome for m in t.membros)}")
                                                for t in Time.query.order_by(Time.id)],
        op_creds=[(c, c) for c in distintos(Cliente.credenciamento)], op_ufs=[(u, u) for u in distintos(Cliente.uf)])


def _form(c):
    return render_template("clientes/form.html", c=c, leitura=bool(usuario_logado() and usuario_logado().e_colaborador),
                           analistas=[a for a in Pessoa.query.filter_by(ativo=True).order_by(Pessoa.nome) if not a.e_diretoria],
                           carteiras=Carteira.query.order_by(Carteira.nome).all(), tribs=TRIBUTACOES)


def _salvar(c):
    f = request.form
    for campo in CAMPOS_CLIENTE:
        if campo == "analista_id":
            continue
        v = (f.get(campo) or "").strip() or None
        if campo == "analista_id":
            v = int(v) if v else None
        elif campo == "inicio":
            v = datetime.strptime(v, "%Y-%m-%d").date() if v else None
        elif campo == "uf" and v:
            v = v.upper()[:2]
        elif campo == "situacao":
            v = v or "ATIVO"
        setattr(c, campo, v)
    c.carteira_id = int(f["carteira_id"]) if f.get("carteira_id") else None
    if not c.empresa:
        flash("Informe o nome da empresa.", "danger")
        return False
    db.session.add(c)
    db.session.commit()
    return True


@bp.route("/novo", methods=["GET", "POST"])
def novo():
    c = Cliente()
    if request.method == "POST" and _salvar(c):
        flash("Cliente cadastrado.", "success")
        return redirect(url_for("clientes.lista"))
    return _form(c)


@bp.route("/<int:cid>", methods=["GET", "POST"])
def editar(cid):
    c = db.session.get(Cliente, cid) or abort(404)
    if request.method == "POST" and _salvar(c):
        flash("Cliente atualizado.", "success")
        return redirect(url_for("clientes.lista"))
    return _form(c)


@bp.post("/<int:cid>/excluir")
def excluir(cid):
    c = db.session.get(Cliente, cid) or abort(404)
    db.session.delete(c)
    db.session.commit()
    flash("Cliente excluído.", "success")
    return redirect(url_for("clientes.lista"))


@bp.post("/importar")
def importar():
    arq = request.files.get("planilha")
    if not arq or not arq.filename.lower().endswith(".xlsx"):
        flash("Envie um arquivo .xlsx.", "danger")
    else:
        try:
            novos, ign = importar_planilha(arq)
            flash(f"Importação concluída: {novos} novos clientes, {ign} já existentes ignorados.", "success")
        except Exception as e:  # planilha fora do padrão
            db.session.rollback()
            flash(f"Não foi possível importar a planilha: {e}", "danger")
    return redirect(url_for("clientes.lista"))
