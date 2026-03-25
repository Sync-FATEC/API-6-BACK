"""Executa o schema.sql para criar as tabelas no PostgreSQL."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from asg_sistema.db.conexao import engine

SCHEMA_PATH = Path(__file__).resolve().parent.parent / "asg_sistema" / "db" / "schema.sql"


def main():
    print("Criando tabelas no banco de dados...")
    sql = SCHEMA_PATH.read_text(encoding="utf-8")

    with engine.connect() as conn:
        conn.execute(__import__("sqlalchemy").text(sql))
        conn.commit()

    print("Tabelas criadas com sucesso.")


if __name__ == "__main__":
    main()
