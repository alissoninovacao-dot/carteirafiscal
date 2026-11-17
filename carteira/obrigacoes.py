"""Quais obrigações acessórias cada empresa possui (regra automática + ajuste manual) e catálogo padrão."""
from .extensions import db
from .models import Cliente, ClienteObrigacao, TipoEntrega, REQUER


def avaliar(tipo, c):
    """Regra automática: (aplica?, motivo). Depende do regime, da inscrição estadual (ICMS) e da atividade (ISS)."""
    regime = c.tributacao or ""
    if tipo.lista_regimes and regime not in tipo.lista_regimes:
        quem = ", ".join(r.title() for r in tipo.lista_regimes)
        return False, f"Regime {regime.title() or 'não informado'} (aplica-se a: {quem})"
    if tipo.requer == "icms" and not c.ie:
        return False, "Sem inscrição estadual cadastrada (não contribuinte de ICMS)"
    if tipo.requer == "servico" and "SERV" not in (c.credenciamento or "").upper():
        return False, "Atividade sem prestação de serviços"
    extra = {"icms": " · contribuinte de ICMS", "servico": " · presta serviços"}.get(tipo.requer or "", "")
    return True, f"Regime {regime.title() or 'qualquer'}{extra}"


def obrigacoes_do_cliente(c):
    """Lista completa dos tipos com: aplica pela regra, ajuste manual e resultado efetivo."""
    ajustes = {a.tipo_id: a.aplica for a in ClienteObrigacao.query.filter_by(cliente_id=c.id)}
    saida = []
    for t in TipoEntrega.query.filter_by(ativo=True).order_by(TipoEntrega.periodicidade.desc(), TipoEntrega.id):
        auto, motivo = avaliar(t, c)
        auto = auto and t.geracao == "auto"
        if t.geracao != "auto" and not (t.lista_regimes and (c.tributacao or "") not in t.lista_regimes):
            motivo = "Obrigação condicional: marque se a empresa estiver sujeita"
        aj = ajustes.get(t.id)
        saida.append(dict(tipo=t, auto=auto, motivo=motivo, ajuste=aj, efetivo=auto if aj is None else aj))
    return saida


def efetivas(c, tipos):
    """Tipos (da lista dada) que a empresa efetivamente possui."""
    ajustes = {a.tipo_id: a.aplica for a in ClienteObrigacao.query.filter_by(cliente_id=c.id)}
    res = []
    for t in tipos:
        auto = avaliar(t, c)[0] and t.geracao == "auto"
        if ajustes.get(t.id, auto):
            res.append(t)
    return res


# Catálogo padrão (pesquisa: Agenda Tributária da Receita Federal, SEFAZ-PE, Portal do Simples Nacional).
CATALOGO = [
    dict(nome="PGDAS-D", periodicidade="mensal", regimes="SIMPLES NACIONAL", regra="dia_seguinte", dia_vencimento=20, cor="#0d9488",
         descricao="Declaração mensal do Simples Nacional (apura e gera o DAS). Entregue mesmo sem faturamento.",
         fonte="Agenda Tributária (Receita Federal) · Portal do Simples Nacional"),
    dict(nome="COOPERA", periodicidade="mensal", regimes="", requer="icms", regra="sem_data", cor="#0ea5e9", geracao="auto",
         descricao="Programa de Conformidade e Autorregularização da SEFAZ-PE: acompanhar e responder às comunicações de conformidade do mês. Ajuste o prazo conforme o aviso recebido.",
         fonte="SEFAZ-PE (Programa COOPERA)"),
    dict(nome="Fronteira", periodicidade="mensal", regimes="", requer="icms", regra="sem_data", cor="#f59e0b", geracao="auto",
         descricao="Controle do ICMS de fronteira (antecipação nas entradas interestaduais) em PE. Ajuste o prazo na tela Demandas.",
         fonte="SEFAZ-PE"),
    dict(nome="EFD ICMS/IPI", periodicidade="mensal", regimes="LUCRO PRESUMIDO;LUCRO REAL", requer="icms", regra="dia_seguinte", dia_vencimento=15, cor="#2563eb",
         descricao="Escrituração Fiscal Digital do ICMS/IPI (SPED Fiscal). Prazo de PE: dia 15 do mês seguinte; outras UFs podem ter outro dia.",
         fonte="SEFAZ-PE (Documentos Econômico-Fiscais)"),
    dict(nome="EFD-Contribuições", periodicidade="mensal", regimes="LUCRO PRESUMIDO;LUCRO REAL", regra="dia_util_2m", dia_vencimento=10, cor="#7c3aed",
         descricao="PIS/Cofins. Vence no 10º dia útil do 2º mês seguinte à competência.",
         fonte="Agenda Tributária (Receita Federal)"),
    dict(nome="EFD-Reinf", periodicidade="mensal", regimes="LUCRO PRESUMIDO;LUCRO REAL", regra="dia_seguinte", dia_vencimento=15, cor="#db2777",
         descricao="Retenções e informações previdenciárias/IR. Dia 15 do mês seguinte.",
         fonte="Agenda Tributária (Receita Federal)"),
    dict(nome="DCTFWeb", periodicidade="mensal", regimes="LUCRO PRESUMIDO;LUCRO REAL", regra="ultimo_util_seguinte", cor="#F4673A",
         descricao="Substitui a DCTF desde jan/2025. Vence no último dia útil do mês seguinte.",
         fonte="Agenda Tributária · IN RFB 2.237/2024 e 2.248/2025"),
    dict(nome="ISS (declaração municipal)", periodicidade="mensal", regimes="LUCRO PRESUMIDO;LUCRO REAL", requer="servico", regra="sem_data", cor="#ca8a04",
         descricao="Declaração/escrituração do ISS no município (no Simples o ISS vai no DAS; marque a empresa se o município exigir). Prazo e sistema variam por município: informe o vencimento em cada entrega.",
         fonte="Legislação municipal"),
    dict(nome="DEFIS", periodicidade="anual", regimes="SIMPLES NACIONAL", regra="anual_dia", dia_vencimento=31, mes_anual=3, cor="#0f766e",
         descricao="Declaração anual do Simples Nacional. Até 31/03 do ano seguinte.",
         fonte="Portal do Simples Nacional"),
    dict(nome="DASN-SIMEI", periodicidade="anual", regimes="MEI", regra="anual_dia", dia_vencimento=31, mes_anual=5, cor="#65a30d",
         descricao="Declaração anual do MEI. Até 31/05 do ano seguinte.",
         fonte="Portal do Simples Nacional"),
    dict(nome="ECF", periodicidade="anual", regimes="LUCRO PRESUMIDO;LUCRO REAL", regra="anual_ultimo_util", mes_anual=7, cor="#9333ea",
         descricao="Escrituração Contábil Fiscal. Último dia útil de julho do ano seguinte. Optantes do Simples são dispensados.",
         fonte="Receita Federal (Sped)"),
    dict(nome="ECD", periodicidade="anual", regimes="LUCRO REAL", regra="anual_ultimo_util", mes_anual=6, cor="#c026d3",
         descricao="Escrituração Contábil Digital. Obrigatória no Lucro Real; no Lucro Presumido só se distribuir lucros acima da base de cálculo sem IRRF (marque na empresa). Último dia útil de junho.",
         fonte="Receita Federal (Sped)"),
    # condicionais: não são geradas automaticamente; marque a empresa quando se aplicarem
    dict(nome="DIRBI", periodicidade="mensal", regimes="LUCRO PRESUMIDO;LUCRO REAL", regra="dia_2m", dia_vencimento=20, cor="#b45309", geracao="manual",
         descricao="Só para quem usa benefícios fiscais. Dia 20 do 2º mês seguinte (confira o ajuste quando cair em feriado).",
         fonte="Agenda Tributária (Receita Federal)"),
    dict(nome="DME", periodicidade="mensal", regra="ultimo_util_seguinte", cor="#64748b", geracao="manual",
         descricao="Declaração de operações liquidadas com moeda em espécie. Só quando houver operação.",
         fonte="Agenda Tributária (Receita Federal)"),
    dict(nome="DOI", periodicidade="mensal", regra="ultimo_util_seguinte", cor="#475569", geracao="manual",
         descricao="Declaração sobre operações imobiliárias (cartórios/imobiliárias). Só quando houver operação.",
         fonte="Agenda Tributária (Receita Federal)"),
]


REMOVIDOS = ("DeSTDA",)   # demandas retiradas do catálogo padrão


def semear_catalogo():
    """Cria/atualiza os tipos padrão. Tipos do formato antigo (sem regra) e sem entregas são substituídos."""
    antigos = TipoEntrega.query.filter(TipoEntrega.regra.is_(None)).all()
    for t in antigos:
        if not t.entregas:
            db.session.delete(t)
    for nome in REMOVIDOS:
        for t in TipoEntrega.query.filter_by(nome=nome).all():
            db.session.delete(t)
    db.session.flush()
    existentes = {t.nome: t for t in TipoEntrega.query.all()}
    for item in CATALOGO:
        t = existentes.get(item["nome"])
        if t is None:
            t = TipoEntrega(nome=item["nome"], padrao=True)
            db.session.add(t)
        elif not t.padrao and t.regra is not None:
            continue                       # tipo editado pelo usuário: não sobrescreve
        for k, v in item.items():
            setattr(t, k, v)
        t.padrao = True
        t.ativo = True if t.ativo is None else t.ativo
    db.session.commit()
