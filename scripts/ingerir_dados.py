"""Carrega todos os JSONs coletados para o PostgreSQL."""

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from asg_sistema.config import config
from asg_sistema.ingestao.carregador import carregar_tudo

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")


def main():
    print(f"Ingerindo dados de: {config.caminho_dados}")
    carregar_tudo(config.caminho_dados)
    print("Ingestao concluida.")


if __name__ == "__main__":
    main()
