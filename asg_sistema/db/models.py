"""
Modelos SQLAlchemy para agendamento de atualização da base de dados.
Complementa o schema.sql existente.
"""

from datetime import datetime
from sqlalchemy import Column, Integer, String, Boolean, DateTime, Text, ForeignKey, JSON, func, text
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


class AgendamentoAtualizacao(Base):
    __tablename__ = "agendamentos_atualizacao"

    id               = Column(Integer, primary_key=True, index=True)

    # Recorrência em linguagem simples (ex: a cada 2 semanas às 03:00)
    intervalo        = Column(Integer, nullable=False)          # ex: 1, 2, 3…
    unidade          = Column(String(10), nullable=False)       # "hora" | "dia" | "semana" | "mes"
    horario          = Column(String(5), nullable=False, default="02:00")  # "HH:MM"
    etapa            = Column(String(20), nullable=False, default="full")  # "extract" | "load" | "embed" | "validate" | "full"

    # Expressão cron derivada (gerada automaticamente a partir dos 3 campos acima)
    cron_expressao   = Column(String(100), nullable=False)

    ativo            = Column(Boolean, default=True, nullable=False)
    criado_em        = Column(DateTime, default=datetime.utcnow)
    atualizado_em    = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    ultima_execucao_em = Column(DateTime, nullable=True)
    ultimo_status    = Column(String(20), nullable=True)        # "sucesso" | "erro" | "executando"
    ultima_mensagem  = Column(Text, nullable=True)


class Usuario(Base):
    __tablename__ = "usuarios"

    id = Column(Integer, primary_key=True, index=True)
    nome = Column(String(255), nullable=False)
    cargo = Column(String(200), nullable=False)
    email = Column(String(255), unique=True, nullable=False, index=True)
    papel = Column(String(20), nullable=False, server_default=text("'USER'"), default="USER")  # ADMIN | USER
    senha_hash = Column(String(255), nullable=False)
    criado_em = Column(DateTime, server_default=func.now())
    atualizado_em = Column(DateTime, server_default=func.now(), onupdate=func.now())


class Conversa(Base):
    __tablename__ = "conversas"

    id = Column(Integer, primary_key=True, index=True)
    usuario_id = Column(Integer, ForeignKey("usuarios.id", ondelete="CASCADE"), nullable=False, index=True)
    titulo = Column(String(500), nullable=False)
    criado_em = Column(DateTime, server_default=func.now())
    atualizado_em = Column(DateTime, server_default=func.now(), onupdate=func.now())


class Mensagem(Base):
    __tablename__ = "mensagens"

    id = Column(Integer, primary_key=True, index=True)
    conversa_id = Column(Integer, ForeignKey("conversas.id", ondelete="CASCADE"), nullable=False, index=True)
    papel = Column(String(20), nullable=False)  # "usuario" | "sistema"
    conteudo_texto = Column(Text, nullable=False)
    intencao_detectada = Column(String(100), nullable=True)
    entidades_json = Column(JSON, nullable=True)
    tem_dados_geo = Column(Boolean, default=False, nullable=False)
    criado_em = Column(DateTime, server_default=func.now())


class MensagemDados(Base):
    """Payload pesado separado — carregado só sob demanda."""
    __tablename__ = "mensagens_dados"

    mensagem_id = Column(Integer, ForeignKey("mensagens.id", ondelete="CASCADE"), primary_key=True)
    geojson = Column(JSON, nullable=True)
    estatisticas = Column(JSON, nullable=True)
    nota_risco = Column(JSON, nullable=True)
    grupos = Column(JSON, nullable=True)
    fontes = Column(JSON, nullable=True)