"""
Processa os ZIPs baixados do SICAR e converte para GeoJSON.

Sem dependências externas — usa apenas zipfile, struct, json (stdlib).
Saída: um arquivo .geojson por ZIP, em dados/SP/geojson/

Uso:
    python scripts/processar_sicar.py
"""

import json
import struct
import zipfile
from pathlib import Path

PASTA_ZIPS  = Path(__file__).parent.parent.parent / "dados"
PASTA_SAIDA = Path(__file__).parent.parent.parent / "dados" / "geojson"

# ---------------------------------------------------------------------------
# Parser DBF (atributos)
# ---------------------------------------------------------------------------

def ler_dbf(data: bytes) -> list[dict]:
    num_records = struct.unpack_from("<I", data, 4)[0]
    header_size = struct.unpack_from("<H", data, 8)[0]
    record_size = struct.unpack_from("<H", data, 10)[0]

    # Lê descritores de campos (32 bytes cada, a partir do byte 32, até 0x0D)
    fields = []
    pos = 32
    while data[pos] != 0x0D:
        name   = data[pos : pos + 11].rstrip(b"\x00").decode("ascii", errors="replace")
        ftype  = chr(data[pos + 11])
        length = data[pos + 16]
        fields.append((name, ftype, length))
        pos += 32

    records = []
    offset = header_size
    for _ in range(num_records):
        row = {}
        col_offset = offset + 1  # byte 0 é flag de deleção
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
# Parser SHP — Polygon (type 5) e Point (type 1)
# ---------------------------------------------------------------------------

def ler_geometria_polygon(data: bytes, offset: int) -> dict:
    """Lê um registro Polygon do SHP e retorna GeoJSON geometry."""
    # Pula: shape_type(4) + bbox(32) = 36 bytes
    num_parts  = struct.unpack_from("<i", data, offset + 36)[0]
    num_points = struct.unpack_from("<i", data, offset + 40)[0]

    parts_start = offset + 44
    parts = [
        struct.unpack_from("<i", data, parts_start + i * 4)[0]
        for i in range(num_parts)
    ]
    parts.append(num_points)  # sentinela

    points_start = parts_start + num_parts * 4
    all_points = []
    for i in range(num_points):
        x, y = struct.unpack_from("<dd", data, points_start + i * 16)
        all_points.append([round(x, 6), round(y, 6)])

    rings = [all_points[parts[i] : parts[i + 1]] for i in range(num_parts)]

    return {"type": "Polygon", "coordinates": rings}


def ler_geometria_point(data: bytes, offset: int) -> dict:
    x, y = struct.unpack_from("<dd", data, offset + 4)
    return {"type": "Point", "coordinates": [round(x, 6), round(y, 6)]}


def ler_shp(data: bytes) -> list[dict | None]:
    """Retorna lista de geometrias GeoJSON (ou None para registros nulos)."""
    file_length = struct.unpack_from(">i", data, 24)[0] * 2  # em bytes
    shape_type_global = struct.unpack_from("<i", data, 32)[0]

    geometrias = []
    offset = 100  # pula o header de 100 bytes

    while offset < file_length:
        # Cabeçalho do registro: content_length em words (big-endian)
        content_length = struct.unpack_from(">i", data, offset + 4)[0] * 2
        rec_shape_type = struct.unpack_from("<i", data, offset + 8)[0]

        if rec_shape_type == 0:
            geometrias.append(None)
        elif rec_shape_type == 5:  # Polygon
            geometrias.append(ler_geometria_polygon(data, offset + 8))
        elif rec_shape_type == 1:  # Point
            geometrias.append(ler_geometria_point(data, offset + 8))
        else:
            geometrias.append(None)

        offset += 8 + content_length

    return geometrias


# ---------------------------------------------------------------------------
# Processamento principal
# ---------------------------------------------------------------------------

def processar_zip(caminho_zip: Path) -> Path:
    nome = caminho_zip.stem  # ex: SP_AREA_IMOVEL
    destino = PASTA_SAIDA / f"{nome}.geojson"

    if destino.exists():
        print(f"  Já existe: {destino.name} — pulando.")
        return destino

    print(f"  Abrindo {caminho_zip.name}...")

    with zipfile.ZipFile(caminho_zip) as z:
        arquivos = z.namelist()

        shp_nome = next((a for a in arquivos if a.endswith(".shp")), None)
        dbf_nome = next((a for a in arquivos if a.endswith(".dbf")), None)

        if not shp_nome or not dbf_nome:
            print(f"  Sem .shp/.dbf em {caminho_zip.name}, pulando.")
            return None

        print(f"  Lendo atributos ({dbf_nome})...")
        dbf_data = z.read(dbf_nome)
        atributos = ler_dbf(dbf_data)

        print(f"  Lendo geometrias ({shp_nome})...")
        shp_data = z.read(shp_nome)
        geometrias = ler_shp(shp_data)

    total = len(atributos)
    print(f"  Montando GeoJSON ({total:,} features)...")

    features = []
    for i, (props, geom) in enumerate(zip(atributos, geometrias)):
        features.append({
            "type": "Feature",
            "geometry": geom,
            "properties": props,
        })
        if (i + 1) % 50_000 == 0:
            print(f"    {i + 1:,}/{total:,}...")

    geojson = {
        "type": "FeatureCollection",
        "name": nome,
        "features": features,
    }

    PASTA_SAIDA.mkdir(parents=True, exist_ok=True)
    print(f"  Salvando {destino.name}...")
    with open(destino, "w", encoding="utf-8") as f:
        json.dump(geojson, f, ensure_ascii=False, separators=(",", ":"))

    tamanho_mb = destino.stat().st_size / (1024 * 1024)
    print(f"  Salvo: {destino.name} ({tamanho_mb:.1f} MB, {total:,} features)")
    return destino


def main():
    zips = sorted(PASTA_ZIPS.glob("*.zip"))

    if not zips:
        print(f"Nenhum ZIP encontrado em {PASTA_ZIPS.resolve()}")
        return

    print(f"Encontrados {len(zips)} arquivo(s):\n")
    for z in zips:
        print(f"\n>>> {z.name}")
        try:
            processar_zip(z)
        except Exception as e:
            print(f"  ERRO: {e}")

    print(f"\nConcluído. GeoJSONs em: {PASTA_SAIDA.resolve()}")


if __name__ == "__main__":
    main()
