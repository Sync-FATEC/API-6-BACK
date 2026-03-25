"""Conexao com PostgreSQL via SQLAlchemy."""

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from asg_sistema.config import config

engine = create_engine(
    config.db_url.replace("postgresql://", "postgresql+psycopg2://"),
    echo=False,
)
SessionLocal = sessionmaker(bind=engine)


def obter_sessao():
    sessao = SessionLocal()
    try:
        yield sessao
    finally:
        sessao.close()


def executar_sql(sql: str, params: dict | None = None):
    with engine.connect() as conn:
        resultado = conn.execute(text(sql), params or {})
        conn.commit()
        return resultado


def executar_consulta(sql: str, params: dict | None = None) -> list[dict]:
    with engine.connect() as conn:
        resultado = conn.execute(text(sql), params or {})
        colunas = resultado.keys()
        linhas = [dict(zip(colunas, row)) for row in resultado.fetchall()]
        conn.commit()
        return linhas
