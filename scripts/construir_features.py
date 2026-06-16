"""CLI: (re)constrói a feature store de propriedades (fato_propriedade_ambiental).

Pré-requisitos: banco populado e a tabela criada (asg_sistema/db/fato_propriedade.sql).

Uso:
    python scripts/construir_features.py                 # todos os municípios
    python scripts/construir_features.py Bauru Marília   # apenas alguns
"""

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")


def main() -> None:
    from asg_sistema.analitico.feature_store import construir_features

    municipios = sys.argv[1:] or None
    resumo = construir_features(municipios=municipios)
    print(f"Feature store concluída: {resumo['propriedades']} propriedades "
          f"em {resumo['municipios']} município(s).")


if __name__ == "__main__":
    main()
