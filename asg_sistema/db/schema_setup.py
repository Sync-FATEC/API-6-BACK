"""Aplica o DDL definido em schema.sql (idempotente: IF NOT EXISTS)."""

from pathlib import Path

from sqlalchemy import text

from asg_sistema.db.conexao import engine

SCHEMA_PATH = Path(__file__).resolve().parent / "schema.sql"


def aplicar_schema() -> None:
    sql = SCHEMA_PATH.read_text(encoding="utf-8")
    with engine.connect() as conn:
        conn.execute(text(sql))
        conn.commit()
