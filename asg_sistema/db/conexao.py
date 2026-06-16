"""Conexao com PostgreSQL via SQLAlchemy."""

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from asg_sistema.config import config

engine = create_engine(
    config.db_url.replace("postgresql://", "postgresql+psycopg2://"),
    echo=False,
)
SessionLocal = sessionmaker(bind=engine)

# Engine somente-leitura para SQL gerado pelo caminho analítico (Text-to-SQL local).
_ro_engine = create_engine(
    config.db_url_readonly.replace("postgresql://", "postgresql+psycopg2://"),
    echo=False,
    pool_pre_ping=True,
)


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


def executar_sql_many(sql: str, params_list: list[dict]):
    with engine.connect() as conn:
        conn.execute(text(sql), params_list)
        conn.commit()


def executar_consulta_readonly(
    sql: str, params: dict | None = None, timeout_ms: int | None = None,
) -> list[dict]:
    """Executa um SELECT já validado em transação READ ONLY com timeout, sem persistir.

    Use SOMENTE para SQL aprovado por validador_sql.validar_sql.
    """
    timeout_ms = int(timeout_ms or config.sql_timeout_ms)
    with _ro_engine.connect() as conn:
        trans = conn.begin()
        try:
            conn.execute(text(f"SET LOCAL statement_timeout = {timeout_ms}"))
            conn.execute(text("SET TRANSACTION READ ONLY"))
            res = conn.execute(text(sql), params or {})
            cols = list(res.keys())
            return [dict(zip(cols, row)) for row in res.fetchall()]
        finally:
            trans.rollback()


def explain_readonly(sql: str, params: dict | None = None) -> str | None:
    """Roda EXPLAIN <sql> sem executar. None se OK; senão a mensagem do Postgres."""
    from sqlalchemy.exc import SQLAlchemyError

    with _ro_engine.connect() as conn:
        trans = conn.begin()
        try:
            conn.execute(text("SET TRANSACTION READ ONLY"))
            conn.execute(text(f"EXPLAIN {sql}"), params or {})
            return None
        except SQLAlchemyError as e:
            return str(getattr(e, "orig", e))
        finally:
            trans.rollback()
