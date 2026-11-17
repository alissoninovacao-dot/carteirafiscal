from datetime import date

from flask import Blueprint, render_template, request
from sqlalchemy import case, func, or_

from ..extensions import db
from ..models import STATUS_ENTREGA, Carteira, Cliente, Entrega, Pessoa, Time, TipoEntrega, resumo
from ..seguranca import usuario_logado

bp = Blueprint("main", __name__)


@bp.route("/")
def painel():
    if usuario_logado().e_colaborador:
        return _painel_colaborador(usuario_logado())
    ativos = Cliente.query.filter_by(situacao="ATIVO")
    n_ativos = ativos.count()

    def agrupar(col, nulo, ordem_nome=False):
        q = db.session.query(col, func.count()).filter(Cliente.situacao == "ATIVO").group_by(col)
        q = q.order_by(func.count().desc())
        return [(k or nulo, n, k) for k, n in q.all()]

    # por equipe: empresas ativas das carteiras sob responsabilidade dos membros de cada equipe
    por_equipe, cobertas = [], set()
    for t in Time.query.order_by(Time.id).all():
        r = t.empresas
        cobertas.update(c.id for c in t.carteiras)
        por_equipe.append(dict(nome=t.nome, id=t.id, formato=t.formato, membros=[m.nome for m in sorted(t.membros, key=lambda p: p.nome)], total=r["total"], com=r["com"], sem=r["sem"],
                               nd=r["total"] - r["com"] - r["sem"]))
    cc = [c.id for p in Pessoa.query.filter_by(papel="coordenador_fiscal") for c in p.carteiras_resp]
    if cc:
        r = resumo(Cliente.carteira_id.in_(cc))
        por_equipe.insert(0, dict(nome="Coordenação", id=None, formato="", membros=[p.nome for p in Pessoa.query.filter_by(papel="coordenador_fiscal")],
                                  total=r["total"], com=r["com"], sem=r["sem"], nd=r["total"] - r["com"] - r["sem"]))
        cobertas.update(cc)
    r = resumo(or_(Cliente.carteira_id.is_(None), ~Cliente.carteira_id.in_(cobertas or {0})))   # ativas fora de qualquer bloco
    if r["total"]:
        por_equipe.append(dict(nome="Sem equipe", id=0, formato="", total=r["total"], com=r["com"], sem=r["sem"], nd=r["total"] - r["com"] - r["sem"]))
    return render_template(
        "painel.html", g=_gestao(request.args.get("competencia")), total=Cliente.query.count(), n_ativos=n_ativos,
        n_inativos=Cliente.query.filter_by(situacao="INATIVO").count(),
        sem_carteira=ativos.filter(Cliente.carteira_id.is_(None)).count(),
        com_movimento=ativos.filter_by(movimento="SIM").count(), sem_movimento=ativos.filter_by(movimento="NÃO").count(),
        trib=agrupar(Cliente.tributacao, "Não informada"), cred=agrupar(Cliente.credenciamento, "Não informado"),
        ufs=agrupar(Cliente.uf, "Não informada"), por_equipe=por_equipe,
        carteiras=Carteira.query.order_by(Carteira.nome).all(),
        n_pessoas=Pessoa.query.filter(Pessoa.ativo.is_(True), Pessoa.papel != "diretoria").count(), n_times=Time.query.count())


def _gestao(comp):
    """Indicadores de entregas do setor inteiro para a gestão rápida do coordenador."""
    from .entregas import _padrao_mensal
    comp = comp or _padrao_mensal()
    hoje = date.today()
    linhas = (db.session.query(Entrega, Cliente, TipoEntrega, Carteira, Pessoa)
              .join(Cliente, Entrega.cliente_id == Cliente.id).join(TipoEntrega, Entrega.tipo_id == TipoEntrega.id)
              .outerjoin(Carteira, Cliente.carteira_id == Carteira.id).outerjoin(Pessoa, Carteira.responsavel_id == Pessoa.id)
              .filter(Entrega.competencia == comp).all())
    por_status = {k: 0 for k, _, _ in STATUS_ENTREGA}
    por_tipo, por_pessoa, atrasadas = {}, {}, []
    tot = dict(total=0, ok=0, atras=0, prox=0, hoje=0, sem_resp=0, sem_venc=0)

    def soma(d, e_ok, atras):
        d["total"] += 1; d["ok"] += e_ok; d["atras"] += atras

    for e, c, t, k, p in linhas:
        ok = e.status == "entregue"
        atras = bool(not ok and e.vencimento and e.vencimento < hoje)
        por_status[e.status] = por_status.get(e.status, 0) + 1
        tot["total"] += 1; tot["ok"] += ok; tot["atras"] += atras
        if not ok:
            tot["sem_resp"] += p is None
            tot["sem_venc"] += e.vencimento is None
            if e.vencimento and 0 <= (e.vencimento - hoje).days <= 3:
                tot["prox"] += 1
            if e.vencimento == hoje:
                tot["hoje"] += 1
        soma(por_tipo.setdefault(t.id, dict(id=t.id, nome=t.nome, cor=t.cor, total=0, ok=0, atras=0)), ok, atras)
        soma(por_pessoa.setdefault(p.id if p else 0, dict(id=p.id if p else 0, nome=p.nome if p else "Sem responsável", cor=p.cor if p else "#94a3b8",
                                                         total=0, ok=0, atras=0)), ok, atras)
        if atras:
            atrasadas.append(dict(cid=c.id, cliente=c.empresa, tipo=t.nome, cor=t.cor, venc=e.vencimento, dias=(hoje - e.vencimento).days,
                                  resp=p.nome if p else "sem responsável", carteira=k.nome if k else ""))
    atrasadas.sort(key=lambda x: -x["dias"])
    tot["pct"] = round(tot["ok"] / tot["total"] * 100) if tot["total"] else 0
    return dict(comp=comp, status=STATUS_ENTREGA, por_status=por_status, t=tot,
                por_tipo=sorted(por_tipo.values(), key=lambda x: (-x["atras"], -x["total"])),
                por_pessoa=sorted(por_pessoa.values(), key=lambda x: (-x["atras"], -x["total"])), criticas=atrasadas[:8])


def _painel_colaborador(u):
    """Só as empresas e as entregas da carteira do colaborador (ou da dupla/equipe dele)."""
    from .entregas import _padrao_mensal
    pessoa = u.pessoa
    carteiras = pessoa.carteiras_escopo() if pessoa else []
    ids = [c.id for c in carteiras] or [0]
    comp = request.args.get("competencia") or _padrao_mensal()
    r = resumo(Cliente.carteira_id.in_(ids))
    hoje = date.today()
    linhas = (db.session.query(Entrega, Cliente, TipoEntrega).join(Cliente, Entrega.cliente_id == Cliente.id)
              .join(TipoEntrega, Entrega.tipo_id == TipoEntrega.id)
              .filter(Cliente.carteira_id.in_(ids), Entrega.competencia == comp).all())
    por_status = {k: 0 for k, _, _ in STATUS_ENTREGA}
    por_tipo, por_cli = {}, {}
    atras = prox = 0
    proximas = []
    for e, c, t in linhas:
        por_status[e.status] = por_status.get(e.status, 0) + 1
        aberta = e.status != "entregue"
        atrasada = bool(aberta and e.vencimento and e.vencimento < hoje)
        atras += atrasada
        if aberta and e.vencimento and 0 <= (e.vencimento - hoje).days <= 3:
            prox += 1
        g = por_tipo.setdefault(t.id, dict(nome=t.nome, cor=t.cor, total=0, ok=0, atras=0))
        g["total"] += 1; g["ok"] += not aberta; g["atras"] += atrasada
        k = por_cli.setdefault(c.id, dict(total=0, ok=0, atras=0))
        k["total"] += 1; k["ok"] += not aberta; k["atras"] += atrasada
        if aberta:
            proximas.append(dict(cliente=c.empresa, cid=c.id, tipo=t.nome, cor=t.cor, venc=e.vencimento, atrasada=atrasada))
    proximas.sort(key=lambda x: (x["venc"] is None, x["venc"] or hoje))
    empresas = Cliente.query.filter(Cliente.carteira_id.in_(ids)).order_by(Cliente.empresa).all()
    ok = por_status.get("entregue", 0)
    return render_template(
        "painel_colab.html", u=u, pessoa=pessoa, carteiras=carteiras, equipe=pessoa.time if pessoa else None, comp=comp, r=r,
        status=STATUS_ENTREGA, por_status=por_status, total=len(linhas), ok=ok, atras=atras, prox=prox,
        por_tipo=sorted(por_tipo.values(), key=lambda g: -g["total"]), proximas=proximas[:10],
        empresas=[dict(id=c.id, empresa=c.empresa, cnpj=c.cnpj or "", trib=c.tributacao or "", mov=c.movimento or "", sit=c.situacao,
                       carteira=c.carteira.nome if c.carteira else "", **por_cli.get(c.id, dict(total=0, ok=0, atras=0))) for c in empresas])
