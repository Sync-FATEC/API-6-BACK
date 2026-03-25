"""Treina o classificador de intencao e salva o modelo."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from asg_sistema.config import config
from asg_sistema.pln.preprocessador import PreprocessadorPLN
from asg_sistema.pln.classificador import ClassificadorIntencao


def main():
    print("Treinando classificador de intencao...")
    preprocessador = PreprocessadorPLN()
    classificador = ClassificadorIntencao(preprocessador)

    caminho_intencoes = config.caminho_treinamento / "intencoes.json"
    classificador.treinar_de_arquivo(caminho_intencoes)

    classificador.salvar(config.caminho_modelos)
    print(f"Modelo salvo em: {config.caminho_modelos}")

    print("\nTestando classificador:")
    testes = [
        "Houve queimadas em Avaí nos últimos meses?",
        "Quais terras indígenas existem em Ubatuba?",
        "Existe desmatamento na mata atlântica?",
        "Qual a situação ambiental de Campinas?",
        "Unidades de conservação em Bertioga",
    ]
    for t in testes:
        intencao, confianca = classificador.classificar(t)
        print(f"  '{t}' -> {intencao} ({confianca:.2f})")


if __name__ == "__main__":
    main()
