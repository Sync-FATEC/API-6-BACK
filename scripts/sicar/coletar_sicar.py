"""
Baixa o ZIP do SICAR (SP_AREA_IMOVEL) e converte para GeoJSON.

Pré-requisitos:
    pip install SICAR
    Tesseract instalado no sistema

Uso:
    python scripts/sicar/coletar_sicar.py

O GeoJSON gerado fica em dados/geojson/SP_AREA_IMOVEL.geojson
e será lido automaticamente pelo ingerir_dados.py.
"""

import json
import struct
import zipfile
from pathlib import Path

from SICAR import Sicar, State, Polygon
from SICAR.drivers import Tesseract


PASTA_DADOS = Path(__file__).parent.parent.parent / "dados"
PASTA_GEOJSON = PASTA_DADOS / "geojson"


# ---------------------------------------------------------------------------
# Download
# ---------------------------------------------------------------------------

def baixar_sicar() -> Path:
    zip_destino = PASTA_DADOS / "SP_AREA_IMOVEL.zip"
    PASTA_DADOS.mkdir(parents=True, exist_ok=True)
    print("Inicializando conexão com o SICAR...")
    car = Sicar(driver=Tesseract)

    datas = car.get_release_dates()
    print(f"Última atualização de SP: {datas.get(State.SP)}")

    print("\nBaixando SP_AREA_IMOVEL...")
    car.download_state(state=State.SP, polygon=Polygon.AREA_PROPERTY, folder=str(PASTA_DADOS))
    print(f"  -> Download concluído: {zip_destino}")
    return zip_destino


# ---------------------------------------------------------------------------
# Parser DBF
# ---------------------------------------------------------------------------

def ler_dbf(data: bytes) -> list[dict]:
    num_records = struct.unpack_from("<I", data, 4)[0]
    header_size = struct.unpack_from("<H", data, 8)[0]
    record_size = struct.unpack_from("<H", data, 10)[0]

    fields = []
    pos = 32
    while data[pos] != 0x0D:
        name  = data[pos : pos + 11].rstrip(b"\x00").decode("ascii", errors="replace")
        ftype = chr(data[pos + 11])
        length = data[pos + 16]
        fields.append((name, ftype, length))
        pos += 32

    records = []
    offset = header_size
    for _ in range(num_records):
        row = {}
        col_offset = offset + 1
        for name, ftype, length in fields:
            raw = data[col_offset : col_offset + length]
            value = raw.decode("latin-1", errors="replace").strip()
            if ftype == "N":
                try:
                    value = float(value) if "." in value else int(value)
                except ValueError:
                    value = None
            row[name] = value
            col_offset += length
        records.append(row)
        offset += record_size

    return records


# ---------------------------------------------------------------------------
# Parser SHP
# ---------------------------------------------------------------------------

def ler_geometria_polygon(data: bytes, offset: int) -> dict:
    num_parts  = struct.unpack_from("<i", data, offset + 36)[0]
    num_points = struct.unpack_from("<i", data, offset + 40)[0]

    parts_start = offset + 44
    parts = [struct.unpack_from("<i", data, parts_start + i * 4)[0] for i in range(num_parts)]
    parts.append(num_points)

    points_start = parts_start + num_parts * 4
    all_points = []
    for i in range(num_points):
        x, y = struct.unpack_from("<dd", data, points_start + i * 16)
        all_points.append([round(x, 6), round(y, 6)])

    rings = [all_points[parts[i] : parts[i + 1]] for i in range(num_parts)]
    return {"type": "Polygon", "coordinates": rings}


def ler_shp(data: bytes) -> list[dict | None]:
    file_length = struct.unpack_from(">i", data, 24)[0] * 2

    geometrias = []
    offset = 100

    while offset < file_length:
        content_length = struct.unpack_from(">i", data, offset + 4)[0] * 2
        rec_shape_type = struct.unpack_from("<i", data, offset + 8)[0]

        if rec_shape_type == 5:
            geometrias.append(ler_geometria_polygon(data, offset + 8))
        else:
            geometrias.append(None)

        offset += 8 + content_length

    return geometrias


# ---------------------------------------------------------------------------
# Conversão ZIP → GeoJSON
# ---------------------------------------------------------------------------

def converter_para_geojson(caminho_zip: Path) -> Path:
    nome = caminho_zip.stem
    destino = PASTA_GEOJSON / f"{nome}.geojson"
    PASTA_GEOJSON.mkdir(parents=True, exist_ok=True)
    print(f"\nAbrindo {caminho_zip.name}...")

    with zipfile.ZipFile(caminho_zip) as z:
        arquivos = z.namelist()
        shp_nome = next((a for a in arquivos if a.endswith(".shp")), None)
        dbf_nome = next((a for a in arquivos if a.endswith(".dbf")), None)

        if not shp_nome or not dbf_nome:
            raise ValueError(f"ZIP sem .shp/.dbf: {caminho_zip.name}")

        print(f"Lendo atributos ({dbf_nome})...")
        atributos = ler_dbf(z.read(dbf_nome))

        print(f"Lendo geometrias ({shp_nome})...")
        geometrias = ler_shp(z.read(shp_nome))

    total = len(atributos)
    print(f"Montando GeoJSON ({total:,} features)...")

    features = []
    for i, (props, geom) in enumerate(zip(atributos, geometrias)):
        features.append({"type": "Feature", "geometry": geom, "properties": props})
        if (i + 1) % 50_000 == 0:
            print(f"  {i + 1:,}/{total:,}...")

    geojson = {"type": "FeatureCollection", "name": nome, "features": features}

    print(f"Salvando {destino.name}...")
    with open(destino, "w", encoding="utf-8") as f:
        json.dump(geojson, f, ensure_ascii=False, separators=(",", ":"))

    tamanho_mb = destino.stat().st_size / (1024 * 1024)
    print(f"Salvo: {destino.name} ({tamanho_mb:.1f} MB, {total:,} features)")
    return destino


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    caminho_zip = baixar_sicar()
    converter_para_geojson(caminho_zip)
    print("\nConcluído. Execute agora: python scripts/ingerir_dados.py")


if __name__ == "__main__":
    main()
