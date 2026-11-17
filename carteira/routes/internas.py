"""Demandas internas: coordenação/diretoria/administrador criam e atribuem; colaboradores acompanham e executam."""
import csv
import io
import os
import uuid
from datetime import date, timedelta

from flask import (Blueprint, Response, abort, current_app, flash, redirect, render_template, request, send_file, url_for)
from sqlalchemy import or_
from werkzeug.utils import secure_filename

from ..extensions import db
from ..models import Pessoa, Time
from ..models_internas import (CATEGORIA_DI_LABEL, CATEGORIAS_DI, PRIORIDADE_DI_PESO, PRIORIDADES_DI, STATUS_DI, STATUS_DI_ICONE,
                               STATUS_DI_LABEL, AnexoDemanda, ChecklistDemanda, DemandaInterna, EtiquetaDemanda, EventoDemanda, agora)
from ..seguranca import usuario_logado

bp = Blueprint("internas", __name__, url_prefix="/internas")

ORDENACOES = {
    "prazo": lambda d: (d.prazo or date.max, d.id),
    "prioridade": lambda d: (PRIORIDADE_DI_PESO.get(d.prioridade, 9), d.prazo or date.max),
    "recentes": lambda d: -d.id,
    "atualizacao": lambda d: -d.atualizado_em.timestamp(),
    "titulo": lambda d: d.titulo.lower(),
}


# ------------------------------------------------------------------ utilitários
def _gestor():
    return not usuario_logado().e_colaborador


def _exigir_gestor():
    if not _gestor():
        abort(403)


def _pessoa():
    return usuario_logado().pessoa


def _carregar(did):
    """Carrega a demanda; o colaborador só alcança as que lhe foram atribuídas (direto ou pela equipe)."""
    d = db.get_or_404(DemandaInterna, did)
    if not _gestor() and not d.envolve(_pessoa()):
        abort(404)
    return d


def _int(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _data(v):
    try:
        return date.fromisoformat((v or "").strip()) if v else None
    except ValueError:
        return None


def _fmt(d):
    return d.strftime("%d/%m/%Y") if d else "—"


def _evento(d, tipo, texto=None, dados=None, categoria=None, interno=False):
    u = usuario_logado()
    ev = EventoDemanda(demanda=d, tipo=tipo, texto=texto, dados=dados, categoria=categoria, autor=u.nome, interno=bool(interno))
    db.session.add(ev)
    d.atualizado_em = agora()
    return ev


def _voltar(d, ancora=""):
    return redirect(url_for("internas.detalhe", did=d.id) + ancora)


def _etiquetas(texto):
    tags = []
    for nome in (texto or "").split(","):
        nome = nome.strip()[:60]
        if not nome:
            continue
        with db.session.no_autoflush:
            t = EtiquetaDemanda.query.filter(db.func.lower(EtiquetaDemanda.nome) == nome.lower()).first() or EtiquetaDemanda(nome=nome)
        if t not in tags:
            tags.append(t)
    return tags


def _salvar_upload(arquivo, d, evento=None):
    if not arquivo or not arquivo.filename:
        return None
    seguro = secure_filename(arquivo.filename) or "arquivo"
    pasta = os.path.join(current_app.config["UPLOAD_INTERNAS"], str(d.id))
    os.makedirs(pasta, exist_ok=True)
    nome_disco = f"{uuid.uuid4().hex[:10]}_{seguro}"
    caminho = os.path.join(pasta, nome_disco)
    arquivo.save(caminho)
    a = AnexoDemanda(demanda=d, evento=evento, tipo="arquivo", nome=arquivo.filename[:255], arquivo=f"{d.id}/{nome_disco}",
                     tamanho=os.path.getsize(caminho), mimetype=arquivo.mimetype, autor=usuario_logado().nome)
    db.session.add(a)
    return a


def _caminho(a):
    return os.path.join(current_app.config["UPLOAD_INTERNAS"], *a.arquivo.split("/"))


def _remover_arquivo(a):
    if a.tipo == "arquivo" and a.arquivo:
        try:
            os.remove(_caminho(a))
        except OSError:
            pass


def _alterar_status(d, novo, comentario=None):
    if novo not in STATUS_DI_LABEL or novo == d.status:
        return False
    antigo = d.status
    d.status = novo
    if novo == "em_andamento" and not d.data_inicio:
        d.data_inicio = date.today()
    if novo == "concluido":
        d.concluido_em = agora()
        d.proximo_acompanhamento = None
    elif antigo == "concluido":
        d.concluido_em = None
    d.conclusao_informada_em = d.conclusao_informada_por = None
    _evento(d, "status", comentario, dados={"de": antigo, "para": novo, "de_label": STATUS_DI_LABEL[antigo], "para_label": STATUS_DI_LABEL[novo]})
    return True


def _aplicar_form(d, form, nova=False):
    """Aplica o formulário e devolve (erro, lista de alterações para o histórico)."""
    titulo = (form.get("titulo") or "").strip()[:250]
    if not titulo:
        return "Informe o título da demanda.", []
    pessoas = Pessoa.query.filter(Pessoa.id.in_([i for i in map(_int, form.getlist("pessoas")) if i])).order_by(Pessoa.nome).all()
    equipes = Time.query.filter(Time.id.in_([i for i in map(_int, form.getlist("equipes")) if i])).order_by(Time.id).all()
    if not pessoas and not equipes:
        return "Atribua a demanda a uma equipe ou a pelo menos um colaborador.", []
    novos = dict(titulo=titulo, descricao=(form.get("descricao") or "").strip() or None,
                 prioridade=form.get("prioridade") if form.get("prioridade") in PRIORIDADE_DI_PESO else "media",
                 prazo=_data(form.get("prazo")), data_inicio=_data(form.get("data_inicio")),
                 proximo_acompanhamento=_data(form.get("proximo_acompanhamento")))
    rotulos = dict(titulo="Título", descricao="Descrição", prioridade="Prioridade", prazo="Prazo", data_inicio="Início",
                   proximo_acompanhamento="Próximo acompanhamento")
    alteracoes = []
    for campo, valor in novos.items():
        antigo = getattr(d, campo)
        if not nova and antigo != valor:
            alteracoes.append(f"{rotulos[campo]} atualizada" if campo == "descricao" else
                              f"{rotulos[campo]}: {_fmt(antigo) if hasattr(antigo, 'year') else (antigo or '—')} → {_fmt(valor) if hasattr(valor, 'year') else (valor or '—')}")
        setattr(d, campo, valor)
    antes = d.atribuicao_resumo if not nova else ""
    d.pessoas, d.equipes = pessoas, equipes
    if not nova and antes != d.atribuicao_resumo:
        alteracoes.append(f"Atribuída a: {antes} → {d.atribuicao_resumo}")
    d.etiquetas = _etiquetas(form.get("etiquetas"))
    return None, alteracoes


def _opcoes():
    """Equipes e colaboradores para atribuição."""
    equipes = Time.query.order_by(Time.id).all()
    pessoas = [p for p in Pessoa.query.filter_by(ativo=True).order_by(Pessoa.nome) if not p.e_gestao]
    return equipes, pessoas


# ------------------------------------------------------------------ lista / quadro
def _filtrar(args):
    q = DemandaInterna.query
    q = q.filter(DemandaInterna.arquivada.is_(args.get("arquivadas") == "so"))
    texto = (args.get("q") or "").strip()
    if texto:
        like = f"%{texto}%"
        cond = [DemandaInterna.titulo.ilike(like), DemandaInterna.descricao.ilike(like), DemandaInterna.etiquetas.any(EtiquetaDemanda.nome.ilike(like))]
        cod = texto.upper().replace("DI-", "").lstrip("#")
        if cod.isdigit():
            cond.append(DemandaInterna.id == int(cod))
        q = q.filter(or_(*cond))
    if args.get("status") in STATUS_DI_LABEL:
        q = q.filter(DemandaInterna.status == args["status"])
    if args.get("prioridade") in PRIORIDADE_DI_PESO:
        q = q.filter(DemandaInterna.prioridade == args["prioridade"])
    hoje, abertas = date.today(), DemandaInterna.status != "concluido"
    prazo = args.get("prazo")
    if prazo == "atrasadas":
        q = q.filter(abertas, DemandaInterna.prazo < hoje)
    elif prazo == "hoje":
        q = q.filter(abertas, DemandaInterna.prazo == hoje)
    elif prazo == "semana":
        q = q.filter(abertas, DemandaInterna.prazo >= hoje, DemandaInterna.prazo <= hoje + timedelta(days=7))
    elif prazo == "sem_prazo":
        q = q.filter(DemandaInterna.prazo.is_(None))
    situacao = args.get("situacao")
    if situacao == "impedidas":
        q = q.filter(abertas, DemandaInterna.impedimento.isnot(None), DemandaInterna.impedimento != "")
    elif situacao == "validar":
        q = q.filter(abertas, DemandaInterna.conclusao_informada_em.isnot(None))
    itens = q.all()
    pessoa, equipe = _int(args.get("pessoa")), _int(args.get("equipe"))
    if pessoa:
        itens = [d for d in itens if any(p.id == pessoa for p in d.responsaveis)]
    if equipe:
        itens = [d for d in itens if any(t.id == equipe for t in d.equipes) or any(equipe in p.times_ids for p in d.pessoas)]
    if not _gestor():
        eu = _pessoa()
        itens = [d for d in itens if d.envolve(eu)]
    return itens


CHAVES_FILTRO = ("q", "status", "prioridade", "pessoa", "equipe", "prazo", "situacao", "arquivadas")


@bp.route("/")
def lista():
    itens = _filtrar(request.args)
    ordem = request.args.get("ordem", "prazo")
    itens.sort(key=ORDENACOES.get(ordem, ORDENACOES["prazo"]))
    equipes, pessoas = _opcoes()
    base = DemandaInterna.query.filter_by(arquivada=False).all()
    if not _gestor():
        base = [d for d in base if d.envolve(_pessoa())]
    resumo = dict(abertas=sum(not d.concluida for d in base), atrasadas=sum(d.atrasada for d in base),
                  validar=sum(d.aguardando_validacao for d in base), concluidas=sum(d.concluida for d in base))
    filtros = {k: request.args.get(k) for k in CHAVES_FILTRO if request.args.get(k)}
    return render_template("internas/lista.html", itens=itens, ordem=ordem, filtros=filtros, visao=request.args.get("visao", "lista"),
                           equipes=equipes, pessoas=pessoas, resumo=resumo, gestor=_gestor(), STATUS=STATUS_DI, PRIORIDADES=PRIORIDADES_DI,
                           STATUS_ICONE=STATUS_DI_ICONE)


@bp.route("/exportar.csv")
def exportar():
    _exigir_gestor()
    itens = sorted(_filtrar(request.args), key=lambda d: d.id)
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";")
    w.writerow(["Código", "Título", "Status", "Prioridade", "Atribuída a", "Criada por", "Criada em", "Início", "Prazo", "Concluída em",
                "Etiquetas", "Checklist", "Impedimento", "Descrição"])
    for d in itens:
        w.writerow([d.codigo, d.titulo, d.status_label, d.prioridade_label, ", ".join(p.nome for p in d.responsaveis), d.criado_por_nome or "",
                    d.criado_em.strftime("%d/%m/%Y"), _fmt(d.data_inicio), _fmt(d.prazo), d.concluido_em.strftime("%d/%m/%Y") if d.concluido_em else "",
                    ", ".join(t.nome for t in d.etiquetas), f"{d.checklist_feitos}/{d.checklist_total}" if d.checklist else "",
                    d.impedimento or "", (d.descricao or "").replace("\n", " ")])
    return Response("﻿" + buf.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": f"attachment; filename=demandas_internas_{date.today():%Y%m%d}.csv"})


# ------------------------------------------------------------------ criar / editar
@bp.route("/nova", methods=["GET", "POST"])
def nova():
    _exigir_gestor()
    equipes, pessoas = _opcoes()
    if request.method == "POST":
        d = DemandaInterna()
        erro, _ = _aplicar_form(d, request.form, nova=True)
        if erro:
            db.session.rollback()
            flash(erro, "warning")
            return render_template("internas/form.html", d=_rascunho(request.form), nova=True, equipes=equipes, pessoas=pessoas,
                                   PRIORIDADES=PRIORIDADES_DI, STATUS=STATUS_DI,
                                   sel_pessoas=set(map(_int, request.form.getlist("pessoas"))), sel_equipes=set(map(_int, request.form.getlist("equipes"))),
                                   etiquetas=request.form.get("etiquetas", ""))
        u = usuario_logado()
        d.criado_por_id, d.criado_por_nome = u.id, u.nome
        d.status = request.form.get("status") if request.form.get("status") in STATUS_DI_LABEL else "a_iniciar"
        if d.status == "em_andamento" and not d.data_inicio:
            d.data_inicio = date.today()
        if d.status == "concluido":
            d.concluido_em = agora()
        db.session.add(d)
        db.session.flush()
        _evento(d, "criacao", f"Demanda registrada e atribuída a {d.atribuicao_resumo}.")
        for i, linha in enumerate((request.form.get("checklist") or "").splitlines()):
            if linha.strip():
                db.session.add(ChecklistDemanda(demanda=d, texto=linha.strip()[:300], ordem=i))
        for arq in request.files.getlist("anexos"):
            if arq and arq.filename:
                _salvar_upload(arq, d)
        db.session.commit()
        flash(f"Demanda {d.codigo} criada e atribuída a {d.atribuicao_resumo}.", "success")
        return _voltar(d)
    d = DemandaInterna(prioridade="media", status="a_iniciar")
    return render_template("internas/form.html", d=d, nova=True, equipes=equipes, pessoas=pessoas, PRIORIDADES=PRIORIDADES_DI, STATUS=STATUS_DI,
                           sel_pessoas=set(map(_int, request.args.getlist("pessoa"))), sel_equipes=set(map(_int, request.args.getlist("equipe"))), etiquetas="")


def _rascunho(form):
    return DemandaInterna(titulo=form.get("titulo", ""), descricao=form.get("descricao", ""), prioridade=form.get("prioridade", "media"),
                          status=form.get("status", "a_iniciar"), prazo=_data(form.get("prazo")), data_inicio=_data(form.get("data_inicio")),
                          proximo_acompanhamento=_data(form.get("proximo_acompanhamento")))


@bp.route("/<int:did>/editar", methods=["GET", "POST"])
def editar(did):
    _exigir_gestor()
    d = db.get_or_404(DemandaInterna, did)
    equipes, pessoas = _opcoes()
    if request.method == "POST":
        erro, alteracoes = _aplicar_form(d, request.form)
        if erro:
            db.session.rollback()
            flash(erro, "warning")
            return redirect(url_for("internas.editar", did=did))
        if alteracoes:
            _evento(d, "edicao", "\n".join(alteracoes))
        db.session.commit()
        flash("Demanda atualizada.", "success")
        return _voltar(d)
    return render_template("internas/form.html", d=d, nova=False, equipes=equipes, pessoas=pessoas, PRIORIDADES=PRIORIDADES_DI, STATUS=STATUS_DI,
                           sel_pessoas={p.id for p in d.pessoas}, sel_equipes={t.id for t in d.equipes}, etiquetas=", ".join(t.nome for t in d.etiquetas))


# ------------------------------------------------------------------ detalhe
@bp.route("/<int:did>")
def detalhe(did):
    d = _carregar(did)
    gestor = _gestor()
    filtro = request.args.get("ver", "tudo")
    eventos = [e for e in d.eventos if gestor or not e.interno]
    if filtro == "registros":
        eventos = [e for e in eventos if e.tipo in ("comentario", "anexo")]
    eu = _pessoa()
    return render_template("internas/detalhe.html", d=d, eventos=eventos, filtro=filtro, gestor=gestor, STATUS=STATUS_DI, STATUS_ICONE=STATUS_DI_ICONE,
                           CATEGORIAS=CATEGORIAS_DI, souresponsavel=bool(eu and d.envolve(eu)))


@bp.post("/<int:did>/status")
def status(did):
    d = _carregar(did)
    novo = request.form.get("status")
    if not _gestor() and (novo not in ("a_iniciar", "em_andamento") or d.concluida):
        abort(403)
    if _alterar_status(d, novo, (request.form.get("comentario") or "").strip() or None):
        db.session.commit()
        flash(f"Status alterado para “{STATUS_DI_LABEL[novo]}”.", "success")
    return _voltar(d)


@bp.post("/<int:did>/informar-conclusao")
def informar_conclusao(did):
    d = _carregar(did)
    if d.concluida or d.aguardando_validacao:
        return _voltar(d)
    u = usuario_logado()
    d.conclusao_informada_em, d.conclusao_informada_por = agora(), u.nome
    _evento(d, "status", f"{u.nome} informou que concluiu a demanda.", categoria="atualizacao",
            dados={"de": d.status, "para": d.status, "de_label": d.status_label, "para_label": d.status_label, "informada": True})
    db.session.commit()
    flash("Conclusão informada. Agora a coordenação confere e confirma.", "success")
    return _voltar(d)


@bp.post("/<int:did>/validar-conclusao")
def validar_conclusao(did):
    _exigir_gestor()
    d = db.get_or_404(DemandaInterna, did)
    if not d.aguardando_validacao:
        return _voltar(d)
    comentario = (request.form.get("comentario") or "").strip() or None
    if request.form.get("acao") == "confirmar":
        _alterar_status(d, "concluido", comentario or f"Conclusão informada por {d.conclusao_informada_por} confirmada.")
        flash("Conclusão confirmada.", "success")
    else:
        quem = d.conclusao_informada_por
        d.conclusao_informada_em = d.conclusao_informada_por = None
        _evento(d, "status", "Conclusão devolvida para ajustes" + (f": {comentario}" if comentario else "."), categoria="cobranca",
                dados={"de": d.status, "para": d.status, "de_label": d.status_label, "para_label": d.status_label, "devolvida": True})
        flash(f"Demanda devolvida para {quem or 'os responsáveis'}.", "info")
    db.session.commit()
    return _voltar(d)


@bp.post("/<int:did>/registro")
def registro(did):
    d = _carregar(did)
    gestor = _gestor()
    texto = (request.form.get("texto") or "").strip()
    arquivos = [a for a in request.files.getlist("anexos") if a and a.filename]
    link_url = (request.form.get("link_url") or "").strip()
    categoria = request.form.get("categoria") if gestor and request.form.get("categoria") in CATEGORIA_DI_LABEL else "atualizacao"
    prox = _data(request.form.get("proximo_acompanhamento")) if gestor else None
    if not (texto or arquivos or link_url or prox):
        flash("Escreva algo, anexe um arquivo ou informe um link.", "warning")
        return _voltar(d)
    if texto or arquivos or link_url:
        ev = _evento(d, "comentario" if texto else "anexo", texto or None, categoria=categoria, interno=gestor and request.form.get("visibilidade") == "interno")
        db.session.flush()
        for arq in arquivos:
            _salvar_upload(arq, d, ev)
        if link_url:
            if not link_url.startswith(("http://", "https://")):
                link_url = "https://" + link_url
            db.session.add(AnexoDemanda(demanda=d, evento=ev, tipo="link", nome=((request.form.get("link_nome") or "").strip() or link_url)[:255],
                                        url=link_url[:1000], autor=usuario_logado().nome))
        if not texto:
            ev.texto = f"{len(arquivos) + (1 if link_url else 0)} anexo(s) adicionado(s)."
    if prox and prox != d.proximo_acompanhamento:
        d.proximo_acompanhamento = prox
        _evento(d, "edicao", f"Próximo acompanhamento agendado para {_fmt(prox)}")
    db.session.commit()
    flash("Registro adicionado ao histórico.", "success")
    return _voltar(d, "#historico")


@bp.post("/<int:did>/evento/<int:eid>/excluir")
def evento_excluir(did, eid):
    _exigir_gestor()
    ev = db.get_or_404(EventoDemanda, eid)
    if ev.demanda_id != did or ev.tipo not in ("comentario", "anexo"):
        abort(400)
    for a in list(ev.anexos):
        _remover_arquivo(a)
        db.session.delete(a)
    db.session.delete(ev)
    db.session.commit()
    flash("Registro excluído.", "info")
    return redirect(url_for("internas.detalhe", did=did))


@bp.post("/<int:did>/impedimento")
def impedimento(did):
    d = _carregar(did)
    texto = (request.form.get("impedimento") or "").strip()
    if texto:
        d.impedimento = texto
        _evento(d, "impedimento", f"Impedimento registrado: {texto}")
        flash("Impedimento registrado.", "warning")
    elif d.impedimento:
        _evento(d, "impedimento", f"Impedimento resolvido: {d.impedimento}")
        d.impedimento = None
        flash("Impedimento marcado como resolvido.", "success")
    db.session.commit()
    return _voltar(d)


# ------------------------------------------------------------------ anexos
@bp.route("/anexo/<int:aid>")
def anexo(aid):
    a = db.get_or_404(AnexoDemanda, aid)
    _carregar(a.demanda_id)
    if a.tipo == "link":
        return redirect(a.url)
    if not os.path.exists(_caminho(a)):
        abort(404)
    return send_file(_caminho(a), download_name=a.nome, as_attachment=request.args.get("baixar") == "1", mimetype=a.mimetype)


@bp.post("/anexo/<int:aid>/excluir")
def anexo_excluir(aid):
    _exigir_gestor()
    a = db.get_or_404(AnexoDemanda, aid)
    d = a.demanda
    _remover_arquivo(a)
    _evento(d, "anexo", f"Anexo removido: {a.nome}")
    db.session.delete(a)
    db.session.commit()
    flash("Anexo removido.", "info")
    return _voltar(d, "#anexos")


# ------------------------------------------------------------------ checklist
@bp.post("/<int:did>/checklist")
def checklist_add(did):
    _exigir_gestor()
    d = db.get_or_404(DemandaInterna, did)
    linhas = [l.strip() for l in (request.form.get("texto") or "").splitlines() if l.strip()]
    base = max([i.ordem for i in d.checklist] or [0]) + 1
    for i, linha in enumerate(linhas):
        db.session.add(ChecklistDemanda(demanda=d, texto=linha[:300], ordem=base + i))
    if linhas:
        d.atualizado_em = agora()
        db.session.commit()
    return _voltar(d, "#checklist")


@bp.post("/checklist/<int:iid>/alternar")
def checklist_alternar(iid):
    item = db.get_or_404(ChecklistDemanda, iid)
    d = _carregar(item.demanda_id)
    item.concluido = not item.concluido
    item.concluido_em = agora() if item.concluido else None
    _evento(d, "checklist", f"{'Concluiu' if item.concluido else 'Reabriu'} etapa: {item.texto}")
    db.session.commit()
    return _voltar(d, "#checklist")


@bp.post("/checklist/<int:iid>/excluir")
def checklist_excluir(iid):
    _exigir_gestor()
    item = db.get_or_404(ChecklistDemanda, iid)
    d = item.demanda
    db.session.delete(item)
    db.session.commit()
    return _voltar(d, "#checklist")


# ------------------------------------------------------------------ arquivar / duplicar / excluir
@bp.post("/<int:did>/arquivar")
def arquivar(did):
    _exigir_gestor()
    d = db.get_or_404(DemandaInterna, did)
    d.arquivada = not d.arquivada
    _evento(d, "arquivamento", "Demanda arquivada." if d.arquivada else "Demanda restaurada do arquivo.")
    db.session.commit()
    flash("Demanda arquivada." if d.arquivada else "Demanda restaurada.", "info")
    return _voltar(d)


@bp.post("/<int:did>/duplicar")
def duplicar(did):
    _exigir_gestor()
    o = db.get_or_404(DemandaInterna, did)
    u = usuario_logado()
    d = DemandaInterna(titulo=f"{o.titulo} (cópia)"[:250], descricao=o.descricao, prioridade=o.prioridade, prazo=o.prazo, status="a_iniciar",
                       pessoas=list(o.pessoas), equipes=list(o.equipes), etiquetas=list(o.etiquetas), criado_por_id=u.id, criado_por_nome=u.nome)
    db.session.add(d)
    db.session.flush()
    for item in o.checklist:
        db.session.add(ChecklistDemanda(demanda=d, texto=item.texto, ordem=item.ordem))
    _evento(d, "criacao", f"Demanda criada a partir de {o.codigo}.")
    db.session.commit()
    flash(f"Demanda duplicada como {d.codigo}.", "success")
    return redirect(url_for("internas.editar", did=d.id))


@bp.post("/<int:did>/excluir")
def excluir(did):
    _exigir_gestor()
    d = db.get_or_404(DemandaInterna, did)
    for a in d.anexos:
        _remover_arquivo(a)
    codigo = d.codigo
    db.session.delete(d)
    db.session.commit()
    flash(f"Demanda {codigo} excluída definitivamente.", "info")
    return redirect(url_for("internas.lista"))
