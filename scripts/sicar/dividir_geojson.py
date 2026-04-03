"""
Divide um GeoJSON grande em partes menores.

Uso:
    python scripts/dividir_geojson.py
"""

import json
from pathlib import Path

PASTA_GEOJSON = Path(__file__).parent.parent.parent / "dados" / "geojson"
ARQUIVO       = PASTA_GEOJSON / "SP_AREA_IMOVEL.geojson"
PASTA_SAIDA   = PASTA_GEOJSON / "partes"
REGISTROS_POR_PARTE = 50_000


def main():
    print(f"Carregando {ARQUIVO.name}...")
    with open(ARQUIVO, encoding="utf-8") as f:
        data = json.load(f)

    features = data["features"]
    total = len(features)
    nome_base = ARQUIVO.stem

    PASTA_SAIDA.mkdir(parents=True, exist_ok=True)

    parte = 1
    for inicio in range(0, total, REGISTROS_POR_PARTE):
        fatia = features[inicio : inicio + REGISTROS_POR_PARTE]
        destino = PASTA_SAIDA / f"{nome_base}_parte{parte:02d}.geojson"

        geojson = {
            "type": "FeatureCollection",
            "name": f"{nome_base}_parte{parte:02d}",
            "features": fatia,
        }

        with open(destino, "w", encoding="utf-8") as f:
            json.dump(geojson, f, ensure_ascii=False, separators=(",", ":"))

        tamanho_mb = destino.stat().st_size / (1024 * 1024)
        print(f"  Parte {parte:02d}: {len(fatia):,} registros — {tamanho_mb:.1f} MB → {destino.name}")
        parte += 1

    print(f"\nConcluído: {parte - 1} partes em {PASTA_SAIDA.resolve()}")


if __name__ == "__main__":
    main()
