"""
Coletor de dados do SICAR para o estado de São Paulo.

Baixa todos os polígonos disponíveis do estado de SP usando a biblioteca SICAR.
Os arquivos são salvos na pasta 'dados/SP/'.
"""

import os
from pathlib import Path
from SICAR import Sicar, State, Polygon
from SICAR.drivers import Tesseract


ESTADO = State.SP
PASTA_SAIDA = str(Path(__file__).parent.parent.parent / "dados")

POLIGONOS = [
    Polygon.AREA_PROPERTY,       # Perímetros dos imóveis --> Baixe somente essa por enquanto
    Polygon.APPS,                # Área de Preservação Permanente
    Polygon.NATIVE_VEGETATION,   # Remanescente de Vegetação Nativa
    Polygon.CONSOLIDATED_AREA,   # Área Consolidada
    Polygon.AREA_FALL,           # Área de Pousio
    Polygon.HYDROGRAPHY,         # Hidrografia
    Polygon.RESTRICTED_USE,      # Uso Restrito
    Polygon.ADMINISTRATIVE_SERVICE,  # Servidão Administrativa
    Polygon.LEGAL_RESERVE,       # Reserva Legal
]


def main():
    os.makedirs(PASTA_SAIDA, exist_ok=True)

    print("Inicializando conexão com o SICAR...")
    car = Sicar(driver=Tesseract)

    print("Consultando datas de atualização dos estados...")
    datas = car.get_release_dates()
    data_sp = datas.get(ESTADO)
    print(f"Última atualização de SP: {data_sp}")

    for poligono in POLIGONOS:
        print(f"\nBaixando polígono: {poligono.name} para o estado SP...")
        try:
            car.download_state(
                state=ESTADO,
                polygon=poligono,
                folder=PASTA_SAIDA,
            )
            print(f"  -> {poligono.name} baixado com sucesso.")
        except Exception as e:
            print(f"  -> Erro ao baixar {poligono.name}: {e}")

    print(f"\nColeta concluída. Arquivos salvos em: {PASTA_SAIDA}")


if __name__ == "__main__":
    main()
