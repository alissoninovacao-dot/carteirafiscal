"""Importação da planilha CONTABILIZA - CLIENTES.xlsx.

As colunas LOGIN, Senha e TERMINO são ignoradas de propósito (credenciais de portais).
"""
import datetime as dt

import openpyxl

from .extensions import db
from .models import CORES, Cliente, Pessoa

TRIB = {"PRESUMIDO": "LUCRO PRESUMIDO", "REAL": "LUCRO REAL"}
CRED = {"SERVIÇOS": "SERVIÇO", "SERVICO": "SERVIÇO", "SERVIÇO/VAREJO": "SERVIÇO / VAREJO", "COMÉRCIO VAREJO": "VAREJO",
        "ATACADISTA": "ATACADO"}


def _s(v):
    """Texto limpo; 'x', '-' e vazio viram None (na planilha são marcadores)."""
    if v is None:
        return None
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    v = str(v).strip()
    if v == "" or v.lower() in ("x", "-", "nan"):
        return None
    return v


def _analista(nome, cache):
    nome = _s(nome)
    if not nome:
        return None
    chave = nome.upper()
    if chave not in cache:
        p = Pessoa.query.filter(db.func.upper(Pessoa.nome) == chave).first()
        if not p:
            p = Pessoa(nome=nome.title(), papel="analista_fiscal", cor=CORES[(len(cache) + 2) % len(CORES)])
            db.session.add(p)
            db.session.flush()
        cache[chave] = p
    return cache[chave].id


def importar_planilha(origem):
    """origem: caminho ou arquivo. Retorna (novos, ignorados)."""
    ws = openpyxl.load_workbook(origem, data_only=True, read_only=True).worksheets[0]
    linhas = ws.iter_rows(min_row=1, values_only=True)
    cab = [str(c).strip().upper() if c else "" for c in next(linhas)]
    col = {n: i for i, n in enumerate(cab)}

    def g(r, nome):
        i = col.get(nome)
        return r[i] if i is not None and i < len(r) else None

    existentes = {((c.cnpj or "").strip(), c.empresa.strip().upper()) for c in Cliente.query.all()}
    cache, novos, ignorados = {}, 0, 0
    for r in linhas:
        empresa = _s(g(r, "EMPRESAS"))
        if not empresa:
            continue
        cnpj = _s(g(r, "CNPJ"))
        chave = ((cnpj or ""), empresa.upper())
        if chave in existentes:
            ignorados += 1
            continue
        existentes.add(chave)
        trib = (_s(g(r, "TRIBUTAÇÃO")) or "").upper() or None
        cred = (_s(g(r, "CREDENCIAMENTO")) or "").upper() or None
        ini = g(r, "INICIO")
        db.session.add(Cliente(
            situacao=(_s(g(r, "SITUAÇÃO")) or "ATIVO").upper(), empresa=empresa, cnpj=cnpj,
            analista_id=_analista(g(r, "FISCAL"), cache),
            contabil=_s(g(r, "CONTÁBIL")), dp=_s(g(r, "DP")), movimento=_s(g(r, "MOVIMENTO")),
            cpf=_s(g(r, "CPF")), ie=_s(g(r, "I.E")), im=_s(g(r, "I.M")), nire=_s(g(r, "NIRE")),
            tributacao=TRIB.get(trib, trib), credenciamento=CRED.get(cred, cred),
            uf=(_s(g(r, "UF")) or "")[:2].upper() or None, municipio=_s(g(r, "MUNICÍPIO")),
            st_detentores=_s(g(r, "ST DETENTORES")), email=_s(g(r, "EMAIL")),
            email_contabil=_s(g(r, "EMAIL (CONTÁBIL)")), email_dp=_s(g(r, "EMAIL (DP)")),
            email_fiscal=_s(g(r, "EMAIL (FISCAL)")), telefone=_s(g(r, "NÚMERO")),
            inicio=ini.date() if isinstance(ini, dt.datetime) else None,
        ))
        novos += 1
    db.session.commit()
    return novos, ignorados
