import sqlite3
import unicodedata
from datetime import date, datetime

from flask import Blueprint, abort, jsonify, render_template, request
from sqlalchemy import event, func, or_
from sqlalchemy.engine import Engine

from ..extensions import db
from ..models import (CORES, REGIMES, REQUER, STATUS_ENTREGA, Carteira, Cliente, ClienteObrigacao, Entrega, Pessoa, Time,
                      TipoEntrega)
from ..obrigacoes import efetivas, obrigacoes_do_cliente
from ..prazos import REGRAS, nao_uteis
from ..seguranca import escopo_carteiras

bp = Blueprint("entregas", __name__)
STATUS_VALIDOS = {k for k, _, _ in STATUS_ENTREGA}


def _sem_acento(s):
    return "".join(ch for ch in unicodedata.normalize("NFD", s or "") if not unicodedata.combining(ch)).lower()


@event.listens_for(Engine, "connect")
def _registrar_sem_acento(conexao, _):               # permite buscar "contribuicoes" e achar "Contribuições"
    if isinstance(conexao, sqlite3.Connection):
        conexao.create_function("sem_acento", 1, _sem_acento, deterministic=True)


def _padrao_mensal():
    """Mês anterior ao atual (a rotina fiscal fecha o mês que acabou)."""
    h = date.today()
    return f"{h.year - 1}-12" if h.month == 1 else f"{h.year}-{h.month - 1:02d}"


def _padrao_anual():
    return str(date.today().year - 1)      # ano-calendário que acabou


def _periodicidade(periodo):
    return "anual" if len(periodo or "") == 4 else "mensal"


def _dict(e, c, t, k, p):
    hoje = date.today()
    return dict(
        id=e.id, cliente_id=c.id, cliente=c.empresa, cnpj=c.cnpj or "", tributacao=c.tributacao or "",
        movimento=c.movimento or "", uf=c.uf or "",
        tipo_id=t.id, tipo=t.nome, cor=t.cor, tipo_desc=t.descricao or "", tipo_fonte=t.fonte or "",
        periodicidade=t.periodicidade or "mensal", competencia=e.competencia,
        vencimento=e.vencimento.isoformat() if e.vencimento else "", status=e.status,
        entregue_em=e.entregue_em.isoformat() if e.entregue_em else "", obs=e.observacoes or "",
        atrasada=bool(e.vencimento and e.vencimento < hoje and e.status != "entregue"),
        dias=(e.vencimento - hoje).days if e.vencimento else None,
        carteira_id=k.id if k else None, carteira=k.nome if k else "",
        resp_id=p.id if p else None, resp=p.nome if p else "", resp_cor=p.cor if p else "#94a3b8",
        resp_ini=p.iniciais if p else "?", equipe_id=p.time_id if p else None)


def _consulta(args):
    q = (db.session.query(Entrega, Cliente, TipoEntrega, Carteira, Pessoa)
         .join(Cliente, Entrega.cliente_id == Cliente.id).join(TipoEntrega, Entrega.tipo_id == TipoEntrega.id)
         .outerjoin(Carteira, Cliente.carteira_id == Carteira.id).outerjoin(Pessoa, Carteira.responsavel_id == Pessoa.id))
    ids = escopo_carteiras()
    if ids is not None:                                  # colaborador: só as entregas da carteira dele
        q = q.filter(Cliente.carteira_id.in_(ids or [0]))
    if args.get("inicio") and args.get("fim"):          # calendário: por data de vencimento
        q = q.filter(Entrega.vencimento >= args["inicio"], Entrega.vencimento <= args["fim"])
    else:
        q = q.filter(Entrega.competencia == (args.get("competencia") or _padrao_mensal()))
    if v := args.get("responsavel"):
        q = q.filter(Pessoa.id.is_(None)) if v == "0" else q.filter(Pessoa.id == int(v))
    if v := args.get("equipe"):
        q = q.filter(or_(Pessoa.id.is_(None), ~Pessoa.times.any())) if v == "0" else q.filter(Pessoa.times.any(Time.id == int(v)))
    if v := args.get("carteira"):
        q = q.filter(Carteira.id.is_(None)) if v == "0" else q.filter(Carteira.id == int(v))
    if v := args.get("tipo"):
        q = q.filter(TipoEntrega.id == int(v))
    busca = " ".join(_sem_acento((args.get("q") or "")).split())
    if busca:
        nomes = [Cliente.empresa, TipoEntrega.nome, Carteira.nome, Pessoa.nome]
        frase = q.filter(or_(Pessoa.times.any(func.sem_acento(Time.nome).like(f"%{busca}%")), *[func.sem_acento(c).like(f"%{busca}%") for c in nomes]))   # "carteira 3", "efd icms" valem como frase
        if " " in busca and frase.first() is not None:
            return frase.order_by(Entrega.vencimento.is_(None), Entrega.vencimento, Cliente.empresa)
        campos = nomes + [Cliente.cnpj, Cliente.tributacao, Cliente.uf, Entrega.observacoes]
        for termo in busca.split():                     # senão, cada palavra precisa aparecer em algum campo
            cond = [func.sem_acento(c).like(f"%{termo}%") for c in campos] + [Pessoa.times.any(func.sem_acento(Time.nome).like(f"%{termo}%"))]
            digitos = "".join(ch for ch in termo if ch.isdigit())
            if len(digitos) >= 3:                       # CNPJ com ou sem pontuação
                cond.append(func.replace(func.replace(func.replace(Cliente.cnpj, ".", ""), "/", ""), "-", "").like(f"%{digitos}%"))
            status = [k for k, nome, _ in STATUS_ENTREGA if termo in _sem_acento(nome) or termo == k]
            if status:
                cond.append(Entrega.status.in_(status))
            q = q.filter(or_(*cond))
    return q.order_by(Entrega.vencimento.is_(None), Entrega.vencimento, Cliente.empresa)


def _minha(cid):
    ids = escopo_carteiras()
    return ids is None or cid in ids


@bp.route("/entregas")
def pagina():
    return render_template(
        "entregas.html", colab=escopo_carteiras() is not None, mensal=_padrao_mensal(), anual=_padrao_anual(), status=STATUS_ENTREGA, regimes=REGIMES,
        regras=REGRAS, requer=REQUER, cores=CORES,
        equipes=[dict(id=t.id, nome=t.nome) for t in Time.query.order_by(Time.id)],
        pessoas=[dict(id=p.id, nome=p.nome, cargo=p.cargo, time_id=p.time_id, times_ids=p.times_ids)
                 for p in Pessoa.query.filter_by(ativo=True).order_by(Pessoa.nome) if not p.e_gestao],
        carteiras=[dict(id=k.id, nome=k.nome, resp_id=k.responsavel_id, resp=k.responsavel.nome if k.responsavel else "")
                   for k in Carteira.query.order_by(Carteira.id) if _minha(k.id)],
        tipos=[t.to_dict() for t in TipoEntrega.query.order_by(TipoEntrega.id)],
        clientes=[dict(id=c.id, nome=c.empresa, cnpj=c.cnpj or "") for c in
                  Cliente.query.filter_by(situacao="ATIVO").order_by(Cliente.empresa)])


@bp.route("/calendario")
def calendario():
    ano = date.today().year
    folgas = sorted(d.isoformat() for a in range(ano - 1, ano + 3) for d in nao_uteis(a))
    return render_template(
        "calendario.html", colab=escopo_carteiras() is not None, status=STATUS_ENTREGA, folgas=folgas,
        equipes=[dict(id=t.id, nome=t.nome) for t in Time.query.order_by(Time.id)],
        pessoas=[dict(id=p.id, nome=p.nome, cargo=p.cargo, time_id=p.time_id, times_ids=p.times_ids)
                 for p in Pessoa.query.filter_by(ativo=True).order_by(Pessoa.nome) if not p.e_gestao],
        carteiras=[dict(id=k.id, nome=k.nome, resp=k.responsavel.nome if k.responsavel else "") for k in Carteira.query.order_by(Carteira.id) if _minha(k.id)],
        tipos=[t.to_dict() for t in TipoEntrega.query.filter_by(ativo=True).order_by(TipoEntrega.id)])


@bp.route("/demandas")
def demandas():
    return render_template("demandas.html", leitura=escopo_carteiras() is not None, regimes=REGIMES, regras=REGRAS, requer=REQUER, cores=CORES,
                           tipos=[t.to_dict() for t in TipoEntrega.query.order_by(TipoEntrega.id)])


@bp.get("/api/entregas")
def listar():
    return jsonify([_dict(*row) for row in _consulta(request.args).all()])


def _um(eid):
    row = _consulta({"competencia": db.session.get(Entrega, eid).competencia}).filter(Entrega.id == eid).first()
    return _dict(*row)


@bp.post("/api/entregas")
def criar():
    d = request.get_json(force=True)
    c = db.session.get(Cliente, int(d.get("cliente_id") or 0))
    t = db.session.get(TipoEntrega, int(d.get("tipo_id") or 0))
    comp = d.get("competencia") or ""
    if not c or not t:
        return jsonify(erro="Escolha o cliente e o tipo de entrega."), 400
    if _periodicidade(comp) != (t.periodicidade or "mensal"):
        return jsonify(erro=f"{t.nome} é uma obrigação {t.periodicidade}: use "
                            f"{'o ano-calendário (AAAA)' if t.periodicidade == 'anual' else 'o mês (AAAA-MM)'}."), 400
    if Entrega.query.filter_by(cliente_id=c.id, tipo_id=t.id, competencia=comp).first():
        return jsonify(erro="Esta entrega já existe para o cliente nesse período."), 409
    venc = datetime.strptime(d["vencimento"], "%Y-%m-%d").date() if d.get("vencimento") else t.vencimento_para(comp)
    e = Entrega(cliente_id=c.id, tipo_id=t.id, competencia=comp, vencimento=venc)
    db.session.add(e)
    db.session.commit()
    return jsonify(_um(e.id)), 201


@bp.put("/api/entregas/<int:eid>")
def editar(eid):
    e = db.session.get(Entrega, eid) or abort(404)
    d = request.get_json(force=True)
    ids = escopo_carteiras()
    if ids is not None:
        cli = db.session.get(Cliente, e.cliente_id)
        if not cli or cli.carteira_id not in ids:
            abort(403)
        d.pop("vencimento", None)                       # prazos são definidos pelo coordenador
    if "status" in d:
        if d["status"] not in STATUS_VALIDOS:
            return jsonify(erro="Status inválido."), 400
        if d["status"] == "entregue" and e.status != "entregue":
            e.entregue_em = e.entregue_em or date.today()
        elif d["status"] != "entregue":
            e.entregue_em = None
        e.status = d["status"]
    if "vencimento" in d:
        e.vencimento = datetime.strptime(d["vencimento"], "%Y-%m-%d").date() if d["vencimento"] else None
    if "entregue_em" in d and e.status == "entregue":
        e.entregue_em = datetime.strptime(d["entregue_em"], "%Y-%m-%d").date() if d["entregue_em"] else date.today()
    if "obs" in d:
        e.observacoes = (d["obs"] or "").strip() or None
    db.session.commit()
    return jsonify(_um(eid))


@bp.post("/api/entregas/mover")
def mover_vencimento():
    """Muda a data de vencimento de várias entregas de uma vez (calendário)."""
    d = request.get_json(force=True)
    try:
        novo = datetime.strptime(d.get("vencimento") or "", "%Y-%m-%d").date()
    except ValueError:
        return jsonify(erro="Informe uma data válida."), 400
    ids = [int(i) for i in d.get("ids", [])]
    if not ids:
        return jsonify(erro="Nenhuma entrega selecionada."), 400
    n = Entrega.query.filter(Entrega.id.in_(ids)).update({Entrega.vencimento: novo}, synchronize_session=False)
    db.session.commit()
    return jsonify(movidas=n, vencimento=novo.isoformat())


@bp.delete("/api/entregas/<int:eid>")
def excluir(eid):
    e = db.session.get(Entrega, eid) or abort(404)
    db.session.delete(e)
    db.session.commit()
    return jsonify(ok=True)


@bp.post("/api/entregas/gerar")
def gerar():
    """Cria as entregas do período (mês AAAA-MM ou ano-calendário AAAA) para cada empresa ATIVA,
    somente das obrigações que ela possui (regra por regime/ICMS/serviço + ajustes feitos na empresa)."""
    periodo = request.get_json(force=True).get("competencia") or _padrao_mensal()
    per = _periodicidade(periodo)
    existentes = {(e.cliente_id, e.tipo_id) for e in Entrega.query.filter_by(competencia=periodo)}
    tipos = TipoEntrega.query.filter_by(ativo=True, periodicidade=per).all()
    novas, por_tipo = 0, {}
    for c in Cliente.query.filter_by(situacao="ATIVO"):
        for t in efetivas(c, tipos):
            if (c.id, t.id) in existentes:
                continue
            db.session.add(Entrega(cliente_id=c.id, tipo_id=t.id, competencia=periodo, vencimento=t.vencimento_para(periodo)))
            novas += 1
            por_tipo[t.nome] = por_tipo.get(t.nome, 0) + 1
    db.session.commit()
    return jsonify(ok=True, novas=novas, por_tipo=por_tipo)


# ---------------- obrigações de cada empresa ----------------
def _ob_dict(o):
    t = o["tipo"]
    return dict(tipo_id=t.id, nome=t.nome, cor=t.cor, periodicidade=t.periodicidade, descricao=t.descricao or "",
                geracao=t.geracao, auto=o["auto"], motivo=o["motivo"], ajuste=o["ajuste"], efetivo=o["efetivo"],
                vencimento=REGRAS.get(t.regra or "sem_data", "").replace("N", str(t.dia_vencimento or "N"))
                .replace("M", str(t.mes_anual or "M")))


@bp.get("/api/clientes/<int:cid>/obrigacoes")
def obrigacoes_cliente(cid):
    c = db.session.get(Cliente, cid) or abort(404)
    return jsonify([_ob_dict(o) for o in obrigacoes_do_cliente(c)])


@bp.put("/api/clientes/<int:cid>/obrigacoes/<int:tid>")
def ajustar_obrigacao(cid, tid):
    """aplica = true/false força; null volta para a regra automática."""
    c = db.session.get(Cliente, cid) or abort(404)
    t = db.session.get(TipoEntrega, tid) or abort(404)
    valor = request.get_json(force=True).get("aplica")
    a = ClienteObrigacao.query.filter_by(cliente_id=c.id, tipo_id=t.id).first()
    if valor is None:
        if a:
            db.session.delete(a)
    elif a:
        a.aplica = bool(valor)
    else:
        db.session.add(ClienteObrigacao(cliente_id=c.id, tipo_id=t.id, aplica=bool(valor)))
    db.session.commit()
    return jsonify([_ob_dict(o) for o in obrigacoes_do_cliente(c)])


# ---------------- tipos de entrega (catálogo de obrigações) ----------------
def _aplicar_tipo(t, d):
    nome = (d.get("nome") or "").strip()
    if not nome:
        return "Informe o nome do tipo."
    t.nome = nome
    t.regimes = ";".join(r for r in d.get("regimes", []) if r in REGIMES)
    t.periodicidade = "anual" if d.get("periodicidade") == "anual" else "mensal"
    t.regra = d.get("regra") if d.get("regra") in REGRAS else "sem_data"
    dia = d.get("dia_vencimento")
    t.dia_vencimento = int(dia) if str(dia or "").strip() else None
    mes = d.get("mes_anual")
    t.mes_anual = int(mes) if str(mes or "").strip() else None
    if t.dia_vencimento is not None and not 1 <= t.dia_vencimento <= 31:
        return "O dia deve estar entre 1 e 31."
    if t.mes_anual is not None and not 1 <= t.mes_anual <= 12:
        return "O mês deve estar entre 1 e 12."
    if t.regra in ("anual_dia", "anual_ultimo_util") and (t.periodicidade != "anual" or not t.mes_anual):
        return "Regras anuais exigem periodicidade anual e o mês do vencimento."
    if t.regra in ("dia_seguinte", "dia_2m", "dia_util_2m", "anual_dia") and not t.dia_vencimento:
        return "Informe o dia (ou o N-º dia útil) para esta regra."
    t.requer = d.get("requer") if d.get("requer") in REQUER else ""
    t.geracao = "manual" if d.get("geracao") == "manual" else "auto"
    t.cor = d.get("cor") or t.cor or CORES[0]
    t.ativo = bool(d.get("ativo", True))
    if "descricao" in d:
        t.descricao = (d["descricao"] or "").strip() or None
    return None


def _lista_tipos():
    return [x.to_dict() for x in TipoEntrega.query.order_by(TipoEntrega.id)]


@bp.post("/api/entrega-tipos")
def criar_tipo():
    t = TipoEntrega()
    if erro := _aplicar_tipo(t, request.get_json(force=True)):
        return jsonify(erro=erro), 400
    db.session.add(t)
    db.session.commit()
    return jsonify(_lista_tipos())


@bp.put("/api/entrega-tipos/<int:tid>")
def editar_tipo(tid):
    t = db.session.get(TipoEntrega, tid) or abort(404)
    if erro := _aplicar_tipo(t, request.get_json(force=True)):
        return jsonify(erro=erro), 400
    db.session.commit()
    return jsonify(_lista_tipos())


@bp.delete("/api/entrega-tipos/<int:tid>")
def excluir_tipo(tid):
    t = db.session.get(TipoEntrega, tid) or abort(404)
    if Entrega.query.filter_by(tipo_id=tid).count():
        return jsonify(erro="Há entregas deste tipo. Desative-o em vez de excluir."), 409
    db.session.delete(t)
    db.session.commit()
    return jsonify(_lista_tipos())
