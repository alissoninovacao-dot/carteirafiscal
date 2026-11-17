from flask import Blueprint, abort, jsonify, render_template, request
from sqlalchemy import update

from ..acessos import garantir_usuario, remover_usuario
from ..extensions import db
from ..seguranca import usuario_logado
from ..models import CORES, PAPEIS, Carteira, Cliente, Pessoa, Time, time_membro

bp = Blueprint("equipe", __name__)


def _ocultar(d):
    """Tira números e carteiras (o colaborador só vê os totais da própria equipe)."""
    d["empresas"] = None
    d["carteiras"], d["carteiras_info"] = [], []


def _estado():
    pessoas = Pessoa.query.order_by(Pessoa.nome).all()
    e = dict(
        diretoria=[p.to_dict() for p in pessoas if p.e_diretoria],
        coordenadores=[p.to_dict() for p in pessoas if p.e_coordenador],
        livres=[p.to_dict() for p in pessoas if not p.e_gestao and not p.times],
        times=[t.to_dict() for t in Time.query.order_by(Time.id).all()],
    )
    u = usuario_logado()
    if u and u.e_colaborador:
        meus = set(u.pessoa.times_ids) if u.pessoa else set()
        for p in e["diretoria"] + e["coordenadores"] + e["livres"] + [m for t in e["times"] if t["id"] not in meus for m in t["membros"]]:
            if not (u.pessoa and p["id"] == u.pessoa.id):
                _ocultar(p)
        for t in e["times"]:
            if t["id"] not in meus:
                _ocultar(t)
    return e


@bp.route("/equipe")
def pagina():
    u = usuario_logado()
    leitura = u.e_colaborador
    meus = u.pessoa.times_ids if leitura and u.pessoa else []
    return render_template("equipe.html", estado=_estado(), papeis=PAPEIS, cores=CORES, leitura=leitura,
                           meus_times=meus, meu_id=u.pessoa_id if leitura else None)


@bp.get("/api/equipe")
def estado():
    return jsonify(_estado())


@bp.post("/api/pessoas")
def criar_pessoa():
    d = request.get_json(force=True)
    nome = (d.get("nome") or "").strip()
    if not nome:
        return jsonify(erro="Informe o nome."), 400
    p = Pessoa(nome=nome, email=(d.get("email") or "").strip() or None, papel=d.get("papel") or "analista_fiscal",
               cor=d.get("cor") or CORES[Pessoa.query.count() % len(CORES)])
    db.session.add(p)
    db.session.flush()
    garantir_usuario(p, commit=False)
    db.session.commit()
    return jsonify(_estado())


@bp.put("/api/pessoas/<int:pid>")
def editar_pessoa(pid):
    p = db.session.get(Pessoa, pid) or abort(404)
    d = request.get_json(force=True)
    if "nome" in d:
        if not d["nome"].strip():
            return jsonify(erro="Informe o nome."), 400
        p.nome = d["nome"].strip()
    if "email" in d:
        p.email = (d["email"] or "").strip() or None
    for k in ("papel", "cor", "ativo", "pos_x", "pos_y"):
        if k in d:
            setattr(p, k, d[k])
    if p.e_gestao:
        p.times = []
    garantir_usuario(p, commit=False)
    db.session.commit()
    return jsonify(_estado())


@bp.delete("/api/pessoas/<int:pid>")
def excluir_pessoa(pid):
    p = db.session.get(Pessoa, pid) or abort(404)
    if p.e_coordenador and Pessoa.query.filter_by(papel="coordenador_fiscal").count() == 1:
        return jsonify(erro="O organograma precisa de pelo menos um coordenador."), 400
    remover_usuario(p)
    db.session.delete(p)
    db.session.commit()
    return jsonify(_estado())


@bp.get("/api/pessoas/<int:pid>/empresas")
def empresas_pessoa(pid):
    """Empresas das carteiras sob responsabilidade da pessoa + destinos possíveis para movê-las."""
    p = db.session.get(Pessoa, pid) or abort(404)
    cids = [c.id for c in p.carteiras_resp]
    cli = Cliente.query.filter(Cliente.carteira_id.in_(cids)).order_by(Cliente.empresa).all() if cids else []
    return jsonify(
        empresas=[dict(id=c.id, empresa=c.empresa, cnpj=c.cnpj or "", tributacao=c.tributacao or "", uf=c.uf or "",
                       situacao=c.situacao, movimento=c.movimento or "", carteira=c.carteira.nome) for c in cli],
        carteiras=[dict(id=k.id, nome=k.nome, resp_id=k.responsavel_id, resp=k.responsavel.nome if k.responsavel else "",
                        total=k.total_clientes) for k in Carteira.query.order_by(Carteira.id)],
        pessoas=[dict(id=x.id, nome=x.nome, cargo=x.cargo) for x in Pessoa.query.filter_by(ativo=True)
                 .order_by(Pessoa.nome) if not x.e_gestao])


@bp.put("/api/carteiras/<int:cid>/responsavel")
def definir_responsavel(cid):
    """Mover a carteira para outra equipe = passar a responsabilidade a um membro dessa equipe."""
    c = db.session.get(Carteira, cid) or abort(404)
    pid = request.get_json(force=True).get("responsavel_id")
    p = db.session.get(Pessoa, int(pid)) if pid else None
    if pid and not p:
        return jsonify(erro="Pessoa não encontrada."), 404
    c.responsavel_id = p.id if p else None
    db.session.commit()
    return jsonify(_estado())


@bp.post("/api/pessoas/<int:pid>/mover")
def mover_pessoa(pid):
    p = db.session.get(Pessoa, pid) or abort(404)
    if p.e_gestao:
        return jsonify(erro="Diretoria e coordenação não entram em equipes."), 400
    d = request.get_json(force=True)
    tid, origem = d.get("time_id"), d.get("origem_id")
    destino = (db.session.get(Time, int(tid)) or abort(404)) if tid else None
    if destino and destino not in p.times:              # entra no bloco sem sair dos outros
        apoio = destino.apoio_ids
        ja_tem_titular = any(m.id not in apoio for m in destino.membros)
        p.times.append(destino)
        db.session.flush()
        if ja_tem_titular:                              # o bloco já tem responsável pelas carteiras: quem chega entra como apoio
            db.session.execute(update(time_membro).where(time_membro.c.pessoa_id == p.id, time_membro.c.time_id == destino.id).values(apoio=True))
    if d.get("mover") and origem and (not destino or int(origem) != destino.id):
        p.times = [t for t in p.times if t.id != int(origem)]
    db.session.commit()
    return jsonify(_estado())


@bp.delete("/api/times/<int:tid>/membros/<int:pid>")
def remover_do_bloco(tid, pid):
    """Botão direito no boneco: tira a pessoa só deste bloco."""
    p = db.session.get(Pessoa, pid) or abort(404)
    p.times = [t for t in p.times if t.id != tid]
    db.session.commit()
    return jsonify(_estado())


@bp.post("/api/times")
def criar_time():
    d = request.get_json(force=True)
    n = Time.query.count()
    t = Time(nome=(d.get("nome") or f"Equipe {n + 1}").strip(), cor=d.get("cor") or CORES[(n + 1) % len(CORES)],
             pos_x=d.get("pos_x", 40 + (n % 4) * 290), pos_y=d.get("pos_y", 250 + (n // 4) * 250))
    db.session.add(t)
    db.session.commit()
    return jsonify(_estado())


@bp.put("/api/times/<int:tid>")
def editar_time(tid):
    t = db.session.get(Time, tid) or abort(404)
    d = request.get_json(force=True)
    for k in ("nome", "cor", "pos_x", "pos_y"):
        if k in d:
            setattr(t, k, d[k])
    db.session.commit()
    return jsonify(_estado())


@bp.post("/api/times/posicoes")
def posicoes():
    for item in request.get_json(force=True):
        t = db.session.get(Time, item["id"])
        if t:
            t.pos_x, t.pos_y = item["pos_x"], item["pos_y"]
    db.session.commit()
    return jsonify(_estado())


@bp.delete("/api/times/<int:tid>")
def excluir_time(tid):
    t = db.session.get(Time, tid) or abort(404)
    db.session.delete(t)
    db.session.commit()
    return jsonify(_estado())
