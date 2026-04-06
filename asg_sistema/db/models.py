"""
Modelos SQLAlchemy para agendamento de atualização da base de dados.
Complementa o schema.sql existente.
"""

from datetime import datetime
from sqlalchemy import Column, Integer, String, Boolean, DateTime, Text
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

    # Expressão cron derivada (gerada automaticamente a partir dos 3 campos acima)
    cron_expressao   = Column(String(100), nullable=False)

    ativo            = Column(Boolean, default=True, nullable=False)
    criado_em        = Column(DateTime, default=datetime.utcnow)
    atualizado_em    = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    ultima_execucao_em = Column(DateTime, nullable=True)
    ultimo_status    = Column(String(20), nullable=True)        # "sucesso" | "erro" | "executando"
    ultima_mensagem  = Column(Text, nullable=True)