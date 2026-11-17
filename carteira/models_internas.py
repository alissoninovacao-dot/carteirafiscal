"""Demandas internas do setor: o coordenador/diretoria/administrador cria e atribui; os colaboradores executam.
Estrutura baseada no sistema Acompanhe (demandas, histórico, checklist, anexos), sem a parte de e-mails."""
from datetime import date, datetime

from .extensions import db

STATUS_DI = [("a_iniciar", "Falta iniciar"), ("em_andamento", "Em andamento"), ("concluido", "Concluída")]
STATUS_DI_LABEL = dict(STATUS_DI)
STATUS_DI_COR = {"a_iniciar": "#64748b", "em_andamento": "#2563eb", "concluido": "#16a34a"}
STATUS_DI_ICONE = {"a_iniciar": "bi-circle", "em_andamento": "bi-arrow-repeat", "concluido": "bi-check-circle-fill"}

PRIORIDADES_DI = [("baixa", "Baixa"), ("media", "Média"), ("alta", "Alta"), ("urgente", "Urgente")]
PRIORIDADE_DI_LABEL = dict(PRIORIDADES_DI)
PRIORIDADE_DI_PESO = {"urgente": 0, "alta": 1, "media": 2, "baixa": 3}
PRIORIDADE_DI_COR = {"baixa": "#64748b", "media": "#2563eb", "alta": "#ea580c", "urgente": "#dc2626"}

CATEGORIAS_DI = [("anotacao", "Anotação"), ("decisao", "Decisão"), ("cobranca", "Cobrança")]
CATEGORIA_DI_LABEL = dict(CATEGORIAS_DI + [("atualizacao", "Atualização")])
EVENTO_DI_ICONE = {"criacao": "bi-plus-circle-fill", "status": "bi-arrow-left-right", "comentario": "bi-chat-left-text-fill",
                   "anexo": "bi-paperclip", "edicao": "bi-pencil-fill", "checklist": "bi-check2-square",
                   "impedimento": "bi-exclamation-octagon-fill", "arquivamento": "bi-archive-fill", "atribuicao": "bi-people-fill"}


def agora():
    return datetime.now()


di_pessoa = db.Table(
    "demanda_interna_pessoa",
    db.Column("demanda_id", db.Integer, db.ForeignKey("demanda_interna.id", ondelete="CASCADE"), primary_key=True),
    db.Column("pessoa_id", db.Integer, db.ForeignKey("pessoa.id", ondelete="CASCADE"), primary_key=True))
di_time = db.Table(
    "demanda_interna_time",
    db.Column("demanda_id", db.Integer, db.ForeignKey("demanda_interna.id", ondelete="CASCADE"), primary_key=True),
    db.Column("time_id", db.Integer, db.ForeignKey("time.id", ondelete="CASCADE"), primary_key=True))
di_etiqueta = db.Table(
    "demanda_interna_etiqueta",
    db.Column("demanda_id", db.Integer, db.ForeignKey("demanda_interna.id", ondelete="CASCADE"), primary_key=True),
    db.Column("etiqueta_id", db.Integer, db.ForeignKey("etiqueta_demanda.id", ondelete="CASCADE"), primary_key=True))


class EtiquetaDemanda(db.Model):
    __tablename__ = "etiqueta_demanda"
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(60), nullable=False, unique=True)


class DemandaInterna(db.Model):
    __tablename__ = "demanda_interna"
    id = db.Column(db.Integer, primary_key=True)
    titulo = db.Column(db.String(250), nullable=False)
    descricao = db.Column(db.Text)
    status = db.Column(db.String(20), nullable=False, default="a_iniciar", index=True)
    prioridade = db.Column(db.String(20), nullable=False, default="media")
    data_inicio = db.Column(db.Date)
    prazo = db.Column(db.Date, index=True)
    proximo_acompanhamento = db.Column(db.Date)
    concluido_em = db.Column(db.DateTime)
    impedimento = db.Column(db.Text)
    # o colaborador avisa que terminou; quem criou/coordena confirma (Concluída) ou devolve
    conclusao_informada_em = db.Column(db.DateTime)
    conclusao_informada_por = db.Column(db.String(150))
    arquivada = db.Column(db.Boolean, nullable=False, default=False, index=True)
    criado_por_id = db.Column(db.Integer, db.ForeignKey("usuario.id", ondelete="SET NULL"))
    criado_por_nome = db.Column(db.String(150))
    criado_em = db.Column(db.DateTime, nullable=False, default=agora)
    atualizado_em = db.Column(db.DateTime, nullable=False, default=agora)

    pessoas = db.relationship("Pessoa", secondary=di_pessoa, order_by="Pessoa.nome", backref=db.backref("demandas_internas", lazy="dynamic"))
    equipes = db.relationship("Time", secondary=di_time, order_by="Time.id")
    etiquetas = db.relationship("EtiquetaDemanda", secondary=di_etiqueta, order_by="EtiquetaDemanda.nome")
    eventos = db.relationship("EventoDemanda", back_populates="demanda", cascade="all, delete-orphan", order_by="EventoDemanda.criado_em.desc()")
    anexos = db.relationship("AnexoDemanda", back_populates="demanda", cascade="all, delete-orphan", order_by="AnexoDemanda.criado_em.desc()")
    checklist = db.relationship("ChecklistDemanda", back_populates="demanda", cascade="all, delete-orphan", order_by="ChecklistDemanda.ordem, ChecklistDemanda.id")

    @property
    def codigo(self):
        return f"DI-{self.id:04d}" if self.id else "DI-nova"

    @property
    def status_label(self):
        return STATUS_DI_LABEL.get(self.status, self.status)

    @property
    def status_cor(self):
        return STATUS_DI_COR.get(self.status, "#64748b")

    @property
    def prioridade_label(self):
        return PRIORIDADE_DI_LABEL.get(self.prioridade, self.prioridade)

    @property
    def prioridade_cor(self):
        return PRIORIDADE_DI_COR.get(self.prioridade, "#64748b")

    @property
    def concluida(self):
        return self.status == "concluido"

    @property
    def aguardando_validacao(self):
        return bool(self.conclusao_informada_em and not self.concluida)

    @property
    def atrasada(self):
        return bool(self.prazo and not self.concluida and self.prazo < date.today())

    @property
    def dias_para_prazo(self):
        return (self.prazo - date.today()).days if self.prazo else None

    def situacao_prazo(self):
        if not self.prazo:
            return "sem"
        if self.concluida:
            return "concluida_atrasada" if self.concluido_em and self.concluido_em.date() > self.prazo else "concluida_no_prazo"
        d = self.dias_para_prazo
        return "atrasada" if d < 0 else "hoje" if d == 0 else "proxima" if d <= 3 else "ok"

    @property
    def checklist_total(self):
        return len(self.checklist)

    @property
    def checklist_feitos(self):
        return sum(1 for i in self.checklist if i.concluido)

    @property
    def progresso(self):
        if self.concluida:
            return 100
        return round(100 * self.checklist_feitos / self.checklist_total) if self.checklist else None

    @property
    def responsaveis(self):
        """Todos os colaboradores que executam: os escolhidos diretamente + os membros das equipes escolhidas."""
        vistos = {p.id: p for p in self.pessoas}
        for t in self.equipes:
            for m in t.membros:
                vistos.setdefault(m.id, m)
        return sorted((p for p in vistos.values() if p.ativo), key=lambda p: p.nome)

    def envolve(self, pessoa):
        return bool(pessoa) and any(p.id == pessoa.id for p in self.responsaveis)

    @property
    def atribuicao_resumo(self):
        partes = [t.nome for t in self.equipes] + [p.nome for p in self.pessoas]
        return ", ".join(partes) or "ninguém"


class EventoDemanda(db.Model):
    __tablename__ = "evento_demanda"
    id = db.Column(db.Integer, primary_key=True)
    demanda_id = db.Column(db.Integer, db.ForeignKey("demanda_interna.id", ondelete="CASCADE"), nullable=False, index=True)
    tipo = db.Column(db.String(20), nullable=False, default="comentario")
    categoria = db.Column(db.String(20))
    texto = db.Column(db.Text)
    autor = db.Column(db.String(150))
    dados = db.Column(db.JSON)
    criado_em = db.Column(db.DateTime, nullable=False, default=agora, index=True)
    editado_em = db.Column(db.DateTime)
    interno = db.Column(db.Boolean, nullable=False, default=False)      # anotação reservada à coordenação/diretoria
    demanda = db.relationship("DemandaInterna", back_populates="eventos")
    anexos = db.relationship("AnexoDemanda", back_populates="evento")

    @property
    def icone(self):
        return EVENTO_DI_ICONE.get(self.tipo, "bi-dot")

    @property
    def categoria_label(self):
        return CATEGORIA_DI_LABEL.get(self.categoria or "", "")

    @property
    def e_manifestacao(self):
        return self.tipo == "comentario"


class AnexoDemanda(db.Model):
    __tablename__ = "anexo_demanda"
    id = db.Column(db.Integer, primary_key=True)
    demanda_id = db.Column(db.Integer, db.ForeignKey("demanda_interna.id", ondelete="CASCADE"), nullable=False, index=True)
    evento_id = db.Column(db.Integer, db.ForeignKey("evento_demanda.id", ondelete="SET NULL"))
    tipo = db.Column(db.String(10), nullable=False, default="arquivo")        # arquivo | link
    nome = db.Column(db.String(255), nullable=False)
    arquivo = db.Column(db.String(255))
    url = db.Column(db.String(1000))
    tamanho = db.Column(db.Integer)
    mimetype = db.Column(db.String(120))
    autor = db.Column(db.String(150))
    criado_em = db.Column(db.DateTime, nullable=False, default=agora)
    demanda = db.relationship("DemandaInterna", back_populates="anexos")
    evento = db.relationship("EventoDemanda", back_populates="anexos")

    @property
    def extensao(self):
        return self.nome.rsplit(".", 1)[-1].lower() if "." in self.nome else ""

    @property
    def is_imagem(self):
        return self.tipo == "arquivo" and self.extensao in {"png", "jpg", "jpeg", "gif", "webp", "bmp"}

    @property
    def icone(self):
        if self.tipo == "link":
            return "bi-link-45deg"
        mapa = {"pdf": "bi-file-earmark-pdf-fill text-danger", "doc": "bi-file-earmark-word-fill text-primary", "docx": "bi-file-earmark-word-fill text-primary",
                "xls": "bi-file-earmark-excel-fill text-success", "xlsx": "bi-file-earmark-excel-fill text-success", "csv": "bi-file-earmark-spreadsheet-fill text-success",
                "zip": "bi-file-earmark-zip-fill", "rar": "bi-file-earmark-zip-fill", "txt": "bi-file-earmark-text-fill", "xml": "bi-file-earmark-code-fill"}
        return "bi-file-earmark-image-fill text-info" if self.is_imagem else mapa.get(self.extensao, "bi-file-earmark-fill")


class ChecklistDemanda(db.Model):
    __tablename__ = "checklist_demanda"
    id = db.Column(db.Integer, primary_key=True)
    demanda_id = db.Column(db.Integer, db.ForeignKey("demanda_interna.id", ondelete="CASCADE"), nullable=False, index=True)
    texto = db.Column(db.String(300), nullable=False)
    concluido = db.Column(db.Boolean, nullable=False, default=False)
    ordem = db.Column(db.Integer, nullable=False, default=0)
    concluido_em = db.Column(db.DateTime)
    demanda = db.relationship("DemandaInterna", back_populates="checklist")
