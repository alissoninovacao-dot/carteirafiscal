from sqlalchemy import select

from .extensions import db

PAPEIS = {
    "diretoria": "Diretoria",
    "coordenador_fiscal": "Coordenador Fiscal",
    "analista_fiscal": "Analista Fiscal",
    "assistente_fiscal": "Assistente Fiscal",
    "auxiliar_fiscal": "Auxiliar Fiscal",
    "estagiario": "Estagiário",
}

CORES = ["#002068", "#F4673A", "#0d9488", "#7c3aed", "#db2777", "#2563eb", "#ca8a04", "#16a34a", "#475569", "#dc2626"]


# uma pessoa pode estar em mais de um bloco (equipe) ao mesmo tempo
time_membro = db.Table(
    "time_membro",
    db.Column("pessoa_id", db.Integer, db.ForeignKey("pessoa.id", ondelete="CASCADE"), primary_key=True),
    db.Column("time_id", db.Integer, db.ForeignKey("time.id", ondelete="CASCADE"), primary_key=True),
    # apoio = está no bloco ajudando; as carteiras dele continuam no bloco de origem e não entram neste
    db.Column("apoio", db.Boolean, nullable=False, default=False, server_default="0"))


class Pessoa(db.Model):
    """Usuário do sistema (equipe fiscal)."""
    __tablename__ = "pessoa"
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(160))
    papel = db.Column(db.String(40), nullable=False, default="analista_fiscal")
    cor = db.Column(db.String(9), default="#002068")
    ativo = db.Column(db.Boolean, default=True, nullable=False)
    times = db.relationship("Time", secondary=time_membro, back_populates="membros", lazy="selectin")
    # posição no organograma (usada pelo coordenador, que é a raiz)
    pos_x = db.Column(db.Float)
    pos_y = db.Column(db.Float)

    @property
    def papel_nome(self):
        return PAPEIS.get(self.papel, self.papel)

    @property
    def time(self):
        """Equipe principal (onde é titular; senão a primeira) — usada onde só cabe uma."""
        if not self.times:
            return None
        apoio = {r[0] for r in db.session.execute(select(time_membro.c.time_id).where(
            time_membro.c.pessoa_id == self.id, time_membro.c.apoio.is_(True)))} if self.id else set()
        return min([t for t in self.times if t.id not in apoio] or self.times, key=lambda t: t.id)

    @property
    def time_id(self):
        return self.time.id if self.time else None

    @property
    def times_ids(self):
        return sorted(t.id for t in self.times)

    def colegas(self):
        """Quem divide algum bloco com esta pessoa (sem repetir)."""
        vistos = {}
        for t in self.times:
            for m in t.membros:
                vistos[m.id] = m
        return sorted(vistos.values(), key=lambda p: p.nome)

    def carteiras_escopo(self):
        """Carteiras que este colaborador acompanha: as de todas as equipes em que está e, sem equipe, as suas."""
        if self.times:
            vistas = {c.id: c for c in self.carteiras_resp}
            for t in self.times:
                for c in t.carteiras:
                    vistas[c.id] = c
            return [vistas[i] for i in sorted(vistas)]
        return sorted(self.carteiras_resp, key=lambda c: c.id)

    @property
    def cargo(self):
        """Cargo curto, exibido sob o boneco (Analista, Assistente, Auxiliar, Estagiário...)."""
        return self.papel_nome.replace(" Fiscal", "")

    @property
    def e_coordenador(self):
        return self.papel == "coordenador_fiscal"

    @property
    def e_diretoria(self):
        return self.papel == "diretoria"

    @property
    def e_gestao(self):
        """Coordenação e diretoria ficam acima das equipes: não entram em equipes nem recebem carteiras como analistas."""
        return self.e_coordenador or self.e_diretoria

    @property
    def iniciais(self):
        p = [x for x in self.nome.split() if x]
        return (p[0][0] + (p[-1][0] if len(p) > 1 else "")).upper() if p else "?"

    def to_dict(self):
        return dict(id=self.id, nome=self.nome, email=self.email or "", papel=self.papel, papel_nome=self.papel_nome, cargo=self.cargo,
                    cor=self.cor, ativo=self.ativo, time_id=self.time_id, times_ids=self.times_ids, pos_x=self.pos_x, pos_y=self.pos_y,
                    coordenador=self.e_coordenador, diretoria=self.e_diretoria, equipe=" · ".join(t.nome for t in sorted(self.times, key=lambda t: t.id)),
                    carteiras=[c.nome for c in self.carteiras_resp],
                    carteiras_info=[dict(id=c.id, nome=c.nome, resp=self.nome, total=c.total_clientes)
                                    for c in sorted(self.carteiras_resp, key=lambda c: c.id)],
                    empresas=resumo(Cliente.carteira_id.in_([c.id for c in self.carteiras_resp]))
                    if self.carteiras_resp else resumo(None))


class Time(db.Model):
    """Dupla / trio / quarteto... que cuida de carteiras."""
    __tablename__ = "time"
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(80), nullable=False)
    cor = db.Column(db.String(9), default="#F4673A")
    pos_x = db.Column(db.Float, default=0)
    pos_y = db.Column(db.Float, default=0)
    membros = db.relationship("Pessoa", secondary=time_membro, back_populates="times", lazy="selectin")

    @property
    def apoio_ids(self):
        """Quem está neste bloco só como apoio."""
        return {r[0] for r in db.session.execute(select(time_membro.c.pessoa_id).where(
            time_membro.c.time_id == self.id, time_membro.c.apoio.is_(True)))}

    @property
    def carteiras(self):
        """Carteiras da equipe = carteiras dos titulares (quem está de apoio não traz a sua carteira para cá)."""
        apoio = self.apoio_ids
        return sorted((c for p in self.membros if p.id not in apoio for c in p.carteiras_resp), key=lambda c: c.id)

    @property
    def formato(self):
        n = len(self.membros)
        return {0: "Vazia", 1: "Individual", 2: "Dupla", 3: "Trio", 4: "Quarteto", 5: "Quinteto"}.get(n, f"Equipe de {n}")

    @property
    def empresas(self):
        """Empresas ativas das carteiras da equipe: total, movimento e regimes."""
        ids = [c.id for c in self.carteiras]
        return resumo(Cliente.carteira_id.in_(ids)) if ids else resumo(None)

    def to_dict(self):
        apoio = self.apoio_ids
        return dict(id=self.id, nome=self.nome, cor=self.cor, pos_x=self.pos_x, pos_y=self.pos_y, formato=self.formato,
                    empresas=self.empresas,
                    membros=[dict(m.to_dict(), apoio=m.id in apoio) for m in sorted(self.membros, key=lambda p: p.nome)],
                    carteiras=[c.nome for c in self.carteiras],
                    carteiras_info=[dict(id=c.id, nome=c.nome, resp=c.responsavel.nome if c.responsavel else "",
                                         total=c.total_clientes) for c in self.carteiras])


def resumo(filtro):
    """Indicadores das empresas que atendem ao filtro (mesmos do painel): total, ativas/inativas,
    com/sem movimento, regimes e detalhamento por tributação, analista, UF e credenciamento (só ativas)."""
    from collections import Counter
    r = dict(todas=0, total=0, inativas=0, com=0, sem=0, simples=0, presumido=0, real=0, outros=0,
             detalhes=dict(tributacao=[], carteira=[], uf=[], credenciamento=[]))
    if filtro is None:
        return r
    rows = (db.session.query(Cliente.situacao, Cliente.movimento, Cliente.tributacao, Cliente.uf,
                             Cliente.credenciamento, Carteira.nome, Pessoa.nome)
            .outerjoin(Carteira, Cliente.carteira_id == Carteira.id)
            .outerjoin(Pessoa, Carteira.responsavel_id == Pessoa.id).filter(filtro).all())
    trib, uf, cred = Counter(), Counter(), Counter()
    ana = {}
    for sit, mov, t, u, c, cart, resp in rows:
        r["todas"] += 1
        if sit != "ATIVO":
            r["inativas"] += 1
            continue
        r["total"] += 1
        r["com"] += mov == "SIM"
        r["sem"] += mov == "NÃO"
        r[{"SIMPLES NACIONAL": "simples", "LUCRO PRESUMIDO": "presumido", "LUCRO REAL": "real"}.get(t, "outros")] += 1
        trib[t or "Não informada"] += 1
        uf[u or "Não informada"] += 1
        cred[c or "Não informado"] += 1
        rotulo = f"{cart} · {resp}" if cart and resp else (cart or "Sem carteira")
        a = ana.setdefault(rotulo, dict(nome=rotulo, total=0, com=0, sem=0))
        a["total"] += 1
        a["com"] += mov == "SIM"
        a["sem"] += mov == "NÃO"
    ordenar = lambda c: [[k, v] for k, v in c.most_common()]
    r["detalhes"] = dict(tributacao=ordenar(trib), uf=ordenar(uf), credenciamento=ordenar(cred),
                         carteira=sorted(ana.values(), key=lambda x: -x["total"]))
    return r


class Carteira(db.Model):
    __tablename__ = "carteira"
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(120), nullable=False)
    descricao = db.Column(db.String(400))
    cor = db.Column(db.String(9), default="#002068")
    # toda carteira tem um colaborador responsável (analista, assistente, auxiliar...)
    responsavel_id = db.Column(db.Integer, db.ForeignKey("pessoa.id", ondelete="SET NULL"))
    responsavel = db.relationship("Pessoa", foreign_keys=[responsavel_id], backref="carteiras_resp")
    clientes = db.relationship("Cliente", backref="carteira", lazy="dynamic")

    @property
    def time(self):
        return self.responsavel.time if self.responsavel else None

    @property
    def total_clientes(self):
        return self.clientes.count()

    @property
    def resumo(self):
        return resumo(Cliente.carteira_id == self.id)


class Cliente(db.Model):
    __tablename__ = "cliente"
    id = db.Column(db.Integer, primary_key=True)
    situacao = db.Column(db.String(10), default="ATIVO", nullable=False, index=True)
    empresa = db.Column(db.String(255), nullable=False, index=True)
    cnpj = db.Column(db.String(40), index=True)
    analista_id = db.Column(db.Integer, db.ForeignKey("pessoa.id", ondelete="SET NULL"))
    analista = db.relationship("Pessoa", foreign_keys=[analista_id])
    carteira_id = db.Column(db.Integer, db.ForeignKey("carteira.id", ondelete="SET NULL"), index=True)
    contabil = db.Column(db.String(80))
    dp = db.Column(db.String(80))
    movimento = db.Column(db.String(10))
    cpf = db.Column(db.String(30))
    ie = db.Column(db.String(40))
    im = db.Column(db.String(40))
    nire = db.Column(db.String(40))
    tributacao = db.Column(db.String(40), index=True)
    credenciamento = db.Column(db.String(60))
    uf = db.Column(db.String(2))
    municipio = db.Column(db.String(80))
    st_detentores = db.Column(db.String(10))
    email = db.Column(db.String(255))
    email_contabil = db.Column(db.String(255))
    email_dp = db.Column(db.String(255))
    email_fiscal = db.Column(db.String(255))
    telefone = db.Column(db.String(60))
    inicio = db.Column(db.Date)
    observacoes = db.Column(db.Text)

    @property
    def ativo(self):
        return self.situacao == "ATIVO"

    def to_dict(self):
        return dict(id=self.id, empresa=self.empresa, cnpj=self.cnpj or "", tributacao=self.tributacao or "",
                    uf=self.uf or "", analista_id=self.analista_id, analista=self.analista.nome if self.analista else "",
                    situacao=self.situacao, credenciamento=self.credenciamento or "", carteira_id=self.carteira_id)


CAMPOS_CLIENTE = ["situacao", "empresa", "cnpj", "analista_id", "contabil", "dp", "movimento", "cpf", "ie", "im", "nire",
                  "tributacao", "credenciamento", "uf", "municipio", "st_detentores", "email", "email_contabil",
                  "email_dp", "email_fiscal", "telefone", "inicio", "observacoes"]
TRIBUTACOES = ["SIMPLES NACIONAL", "LUCRO PRESUMIDO", "LUCRO REAL", "MEI", "CONSULTORIA", "PESSOA FÍSICA", "E-SOCIAL"]


# ---------------------------------------------------------------- Entregas fiscais
STATUS_ENTREGA = [
    ("a_fazer", "A fazer", "#64748b"),
    ("em_andamento", "Em andamento", "#2563eb"),
    ("aguardando_cliente", "Aguardando cliente", "#ca8a04"),
    ("em_revisao", "Em revisão", "#7c3aed"),
    ("entregue", "Entregue", "#16a34a"),
]
REGIMES = ["MEI", "SIMPLES NACIONAL", "LUCRO PRESUMIDO", "LUCRO REAL"]
REQUER = {"": "Nenhuma condição", "icms": "Contribuinte de ICMS (tem inscrição estadual)", "servico": "Presta serviços (ISS)"}


class TipoEntrega(db.Model):
    """Tipo de obrigação/entrega fiscal (ex.: PGDAS-D, EFD ICMS/IPI). Cadastro editável."""
    __tablename__ = "tipo_entrega"
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(80), nullable=False)
    regimes = db.Column(db.String(120), default="")      # regimes separados por ';' (vazio = todos)
    dia_vencimento = db.Column(db.Integer)               # dia do mês SEGUINTE à competência (vazio = sem data)
    cor = db.Column(db.String(9), default="#2563eb")
    ativo = db.Column(db.Boolean, default=True, nullable=False)
    descricao = db.Column(db.Text)
    fonte = db.Column(db.String(255))
    periodicidade = db.Column(db.String(10), default="mensal")    # mensal | anual
    regra = db.Column(db.String(30))                                  # ver prazos.REGRAS (None = formato antigo)
    mes_anual = db.Column(db.Integer)                                 # mês do vencimento (obrigações anuais)
    requer = db.Column(db.String(20), default="")                     # '' | icms | servico
    geracao = db.Column(db.String(10), default="auto")                # auto (gerada p/ todos que se enquadram) | manual
    padrao = db.Column(db.Boolean, default=False, nullable=False)

    def vencimento_para(self, periodo):
        from .prazos import calcular
        return calcular(self.regra or "dia_seguinte", self.dia_vencimento, self.mes_anual, periodo)

    @property
    def lista_regimes(self):
        return [r for r in (self.regimes or "").split(";") if r]

    def vale_para(self, tributacao):
        return not self.lista_regimes or (tributacao or "") in self.lista_regimes

    def to_dict(self):
        return dict(id=self.id, nome=self.nome, regimes=self.lista_regimes, dia_vencimento=self.dia_vencimento,
                    cor=self.cor, ativo=self.ativo, total=Entrega.query.filter_by(tipo_id=self.id).count(),
                    descricao=self.descricao or "", fonte=self.fonte or "", periodicidade=self.periodicidade or "mensal",
                    regra=self.regra or "sem_data", mes_anual=self.mes_anual, requer=self.requer or "",
                    geracao=self.geracao or "auto", padrao=self.padrao)


class Entrega(db.Model):
    """Uma entrega fiscal de um cliente em uma competência (cartão do quadro)."""
    __tablename__ = "entrega"
    __table_args__ = (db.UniqueConstraint("cliente_id", "tipo_id", "competencia", name="uq_entrega"),)
    id = db.Column(db.Integer, primary_key=True)
    cliente_id = db.Column(db.Integer, db.ForeignKey("cliente.id", ondelete="CASCADE"), nullable=False, index=True)
    tipo_id = db.Column(db.Integer, db.ForeignKey("tipo_entrega.id", ondelete="CASCADE"), nullable=False, index=True)
    competencia = db.Column(db.String(7), nullable=False, index=True)    # AAAA-MM
    vencimento = db.Column(db.Date)
    status = db.Column(db.String(30), default="a_fazer", nullable=False, index=True)
    entregue_em = db.Column(db.Date)
    observacoes = db.Column(db.Text)
    cliente = db.relationship("Cliente", backref=db.backref("entregas", cascade="all, delete-orphan"))
    tipo = db.relationship("TipoEntrega", backref=db.backref("entregas", cascade="all, delete-orphan"))


class ClienteObrigacao(db.Model):
    """Ajuste manual: força (True) ou dispensa (False) uma obrigação para uma empresa, acima da regra automática."""
    __tablename__ = "cliente_obrigacao"
    __table_args__ = (db.UniqueConstraint("cliente_id", "tipo_id", name="uq_cliente_obrigacao"),)
    id = db.Column(db.Integer, primary_key=True)
    cliente_id = db.Column(db.Integer, db.ForeignKey("cliente.id", ondelete="CASCADE"), nullable=False, index=True)
    tipo_id = db.Column(db.Integer, db.ForeignKey("tipo_entrega.id", ondelete="CASCADE"), nullable=False)
    aplica = db.Column(db.Boolean, nullable=False)
    cliente = db.relationship("Cliente", backref=db.backref("ajustes_obrigacao", cascade="all, delete-orphan"))
    tipo = db.relationship("TipoEntrega", backref=db.backref("ajustes", cascade="all, delete-orphan"))


PERFIS = {"admin": "Administrador master", "diretoria": "Diretoria", "coordenador_fiscal": "Coordenador Fiscal", "colaborador": "Colaborador"}


class Usuario(db.Model):
    """Acesso ao sistema. Por enquanto: administrador master e coordenador fiscal."""
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(150), nullable=False)
    email = db.Column(db.String(150), nullable=False, unique=True, index=True)
    senha_hash = db.Column(db.String(255), nullable=False)
    perfil = db.Column(db.String(30), nullable=False, default="coordenador_fiscal")
    pessoa_id = db.Column(db.Integer, db.ForeignKey("pessoa.id", ondelete="SET NULL"), unique=True)
    ativo = db.Column(db.Boolean, nullable=False, default=True)
    trocar_senha = db.Column(db.Boolean, nullable=False, default=False)   # por ora o sistema não exige troca
    tentativas_falhas = db.Column(db.Integer, nullable=False, default=0)
    bloqueado_ate = db.Column(db.DateTime)
    ultimo_acesso = db.Column(db.DateTime)
    senha_alterada_em = db.Column(db.DateTime)

    pessoa = db.relationship("Pessoa", backref=db.backref("usuario", uselist=False))

    def definir_senha(self, senha):
        from datetime import datetime
        from werkzeug.security import generate_password_hash
        self.senha_hash = generate_password_hash(senha)
        self.senha_alterada_em = datetime.now()

    def conferir_senha(self, senha):
        from werkzeug.security import check_password_hash
        return check_password_hash(self.senha_hash, senha or "")

    @property
    def perfil_label(self):
        return PERFIS.get(self.perfil, self.perfil)

    @property
    def e_colaborador(self):
        return self.perfil == "colaborador"

    @property
    def bloqueado(self):
        from datetime import datetime
        return bool(self.bloqueado_ate and self.bloqueado_ate > datetime.now())
