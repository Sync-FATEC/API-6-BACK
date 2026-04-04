"""Executa o schema.sql para criar as tabelas no PostgreSQL."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from asg_sistema.db.schema_setup import aplicar_schema


def main():
    print("Criando tabelas no banco de dados...")
    aplicar_schema()
    print("Tabelas criadas com sucesso.")


if __name__ == "__main__":
    main()
