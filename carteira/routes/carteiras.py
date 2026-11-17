from flask import Blueprint, abort, flash, jsonify, redirect, render_template, request, url_for

from ..extensions import db
from ..models import CORES, Carteira, Cliente, Pessoa, Time, resumo
from ..seguranca import usuario_logado

bp = Blueprint("carteiras", __name__, url_prefix="/carteiras")


@bp.route("/", strict_slashes=False)
def lista():
    if usuario_logado().e_colaborador:
        return redirect(url_for("carteiras.minha"))
    carteiras = Carteira.query.order_by(Carteira.id).all()
    # mesma estrutura do organograma: uma seção por equipe, com as carteiras dos membros
    grupos = [dict(time=t, carteiras=t.carteiras, resumo=t.empresas) for t in Time.query.order_by(Time.id)]
    do_coord = [c for c in carteiras if c.responsavel and c.responsavel.e_coordenador]
    em_equipe = {c.id for g in grupos for c in g['carteiras']}
    soltas = [c for c in carteiras if c.id not in em_equipe and c not in do_coord]
    if do_coord:
        coord = do_coord[0].responsavel
        grupos.insert(0, dict(time=None, coord=coord, carteiras=do_coord,
                              resumo=resumo(Cliente.carteira_id.in_([c.id for c in do_coord]))))
    if soltas:
        grupos.append(dict(time=None, carteiras=soltas, resumo=None))
    return render_template("carteiras/lista.html", carteiras=carteiras, grupos=grupos,
                           pessoas=_pessoas(), cores=CORES, proximo=Carteira.query.count() + 1)


def _pessoas():
    return [p for p in Pessoa.query.filter_by(ativo=True).order_by(Pessoa.nome) if not p.e_diretoria]


@bp.post("/<int:cid>/responsavel")
def responsavel(cid):
    c = db.session.get(Carteira, cid) or abort(404)
    rid = request.form.get("responsavel_id")
    c.responsavel_id = int(rid) if rid else None
    db.session.commit()
    flash("Responsável atualizado.", "success")
    return redirect(url_for("carteiras.detalhe", cid=cid))


def _salvar(c):
    f = request.form
    c.nome = (f.get("nome") or "").strip()
    c.descricao = (f.get("descricao") or "").strip() or None
    c.cor = f.get("cor") or CORES[0]
    c.responsavel_id = int(f["responsavel_id"]) if f.get("responsavel_id") else None
    if not c.nome:
        flash("Informe o nome da carteira.", "danger")
        return False
    db.session.add(c)
    db.session.commit()
    return True


@bp.post("/nova")
def nova():
    c = Carteira()
    if _salvar(c):
        flash("Carteira criada. Agora é só inserir os clientes.", "success")
        return redirect(url_for("carteiras.detalhe", cid=c.id))
    return redirect(url_for("carteiras.lista"))


@bp.post("/<int:cid>/editar")
def editar(cid):
    c = db.session.get(Carteira, cid) or abort(404)
    if _salvar(c):
        flash("Carteira atualizada.", "success")
    return redirect(request.referrer or url_for("carteiras.lista"))


@bp.post("/<int:cid>/excluir")
def excluir(cid):
    c = db.session.get(Carteira, cid) or abort(404)
    Cliente.query.filter_by(carteira_id=cid).update({"carteira_id": None})
    db.session.delete(c)
    db.session.commit()
    flash("Carteira excluída; os clientes voltaram para \"sem carteira\".", "success")
    return redirect(url_for("carteiras.lista"))


@bp.route("/<int:cid>")
def detalhe(cid):
    c = db.session.get(Carteira, cid) or abort(404)
    # clientes sem carteira + os desta carteira (a tela filtra no navegador)
    todos = (Cliente.query.filter((Cliente.carteira_id == cid) | (Cliente.carteira_id.is_(None)))
             .order_by(Cliente.empresa).all())
    return render_template("carteiras/detalhe.html", c=c, clientes=[x.to_dict() for x in todos],
                           pessoas=_pessoas(), proximo=0, cores=CORES,
                           destinos=[dict(id=k.id, nome=k.nome, resp_id=k.responsavel_id,
                                          resp=k.responsavel.nome if k.responsavel else "", total=k.total_clientes)
                                     for k in Carteira.query.filter(Carteira.id != cid).order_by(Carteira.id)],
                           pessoas_js=[dict(id=p.id, nome=p.nome, cargo=p.cargo) for p in _pessoas()
                                       if not p.e_gestao],
                           analistas=[p.to_dict() for p in Pessoa.query.filter_by(papel="analista_fiscal").order_by(Pessoa.nome)],
                           tribs=sorted({x.tributacao for x in todos if x.tributacao}),
                           ufs=sorted({x.uf for x in todos if x.uf}))


@bp.post("/remover")
def remover():
    """Tira empresas da carteira (qualquer uma): ficam sem carteira e, portanto, sem responsável."""
    ids = [int(i) for i in request.get_json(force=True).get("ids", [])]
    if not ids:
        return jsonify(erro="Selecione ao menos uma empresa."), 400
    Cliente.query.filter(Cliente.id.in_(ids)).update({"carteira_id": None})
    db.session.commit()
    return jsonify(ok=True, removidas=len(ids))


@bp.post("/mover")
def mover():
    """Move empresas para outra carteira, ou para outro responsável (usa uma carteira dele ou cria uma nova)."""
    d = request.get_json(force=True)
    ids = [int(i) for i in d.get("ids", [])]
    if not ids:
        return jsonify(erro="Selecione ao menos uma empresa."), 400
    if d.get("carteira_id"):
        dest = db.session.get(Carteira, int(d["carteira_id"])) or abort(404)
    else:
        pessoa = db.session.get(Pessoa, int(d.get("responsavel_id") or 0)) or abort(404)
        n = Carteira.query.count() + 1
        while Carteira.query.filter_by(nome=f"Carteira {n}").first():
            n += 1
        dest = Carteira(nome=f"Carteira {n}", cor=pessoa.cor, responsavel_id=pessoa.id)
        db.session.add(dest)
        db.session.flush()
    Cliente.query.filter(Cliente.id.in_(ids)).update({"carteira_id": dest.id})
    db.session.commit()
    return jsonify(ok=True, destino=dict(id=dest.id, nome=dest.nome,
                                         responsavel=dest.responsavel.nome if dest.responsavel else ""))


@bp.post("/<int:cid>/clientes")
def mover_clientes(cid):
    c = db.session.get(Carteira, cid) or abort(404)
    d = request.get_json(force=True)
    ids = [int(i) for i in d.get("ids", [])]
    if d.get("acao") == "remover":
        Cliente.query.filter(Cliente.id.in_(ids), Cliente.carteira_id == cid).update({"carteira_id": None})
    else:
        Cliente.query.filter(Cliente.id.in_(ids), Cliente.carteira_id.is_(None)).update({"carteira_id": c.id})
    db.session.commit()
    return jsonify(ok=True, total=c.total_clientes)


@bp.route("/minha", endpoint="minha")
def minha():
    """Detalhamento das carteiras do colaborador (as dele e/ou da dupla/equipe dele). Somente leitura."""
    u = usuario_logado()
    if not u.e_colaborador:
        return redirect(url_for("carteiras.lista"))
    pessoa = u.pessoa
    carteiras = pessoa.carteiras_escopo() if pessoa else []
    blocos = [dict(c=c, resumo=c.resumo,
                   envolvidos=([c.responsavel] + sorted([m for m in (c.responsavel.colegas() if c.responsavel else []) if m.id != c.responsavel_id], key=lambda m: m.nome)) if c.responsavel else [])
              for c in carteiras]
    clientes = (Cliente.query.filter(Cliente.carteira_id.in_([c.id for c in carteiras] or [0])).order_by(Cliente.empresa).all())
    return render_template("carteiras/minha.html", blocos=blocos, equipe=pessoa.time if pessoa else None, equipes=pessoa.times if pessoa else [], pessoa=pessoa, clientes=clientes)
