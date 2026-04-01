"""
Importa os GeoJSONs do SICAR para o PostgreSQL/PostGIS.

Pré-requisitos:
    pip install psycopg2-binary
    Docker rodando: cd API-6-BACK && docker-compose up -d db

Uso:
    python scripts/importar_sicar.py
"""

import json
import os
import psycopg2
from pathlib import Path
from datetime import datetime

PASTA_GEOJSON = Path(__file__).parent.parent.parent / "dados" / "geojson"

DB_CONFIG = {
    "host":     os.getenv("DB_HOST",     "localhost"),
    "port":     int(os.getenv("DB_PORT", "5433")),
    "dbname":   os.getenv("DB_NAME",     "asg_sp"),
    "user":     os.getenv("DB_USER",     "asg_user"),
    "password": os.getenv("DB_PASSWORD", "asg_pass"),
}

BATCH_SIZE = 1000


def conectar():
    return psycopg2.connect(**DB_CONFIG)


def registrar_fonte(cur, nome_arquivo: str, total: int) -> int:
    cur.execute(
        """
        INSERT INTO fontes (nome, descricao, url_origem, data_coleta, total_registros, escopo)
        VALUES (%s, %s, %s, %s, %s, %s)
        ON CONFLICT DO NOTHING
        RETURNING id
        """,
        (
            f"SICAR - {nome_arquivo}",
            "Cadastro Ambiental Rural — polígonos do estado de SP",
            "https://consultapublica.car.gov.br/publico/estados/downloads",
            datetime.now(),
            total,
            "Estado de São Paulo",
        ),
    )
    row = cur.fetchone()
    if row:
        return row[0]
    cur.execute("SELECT id FROM fontes WHERE nome = %s", (f"SICAR - {nome_arquivo}",))
    return cur.fetchone()[0]


def importar_geojson(conn, caminho: Path):
    print(f"\n>>> Importando {caminho.name}...")

    with open(caminho, encoding="utf-8") as f:
        data = json.load(f)

    features = data.get("features", [])
    total = len(features)
    print(f"  {total:,} features encontradas")

    with conn.cursor() as cur:
        fonte_id = registrar_fonte(cur, caminho.stem, total)
        conn.commit()

        inseridos = 0
        batch = []

        for feat in features:
            props = feat.get("properties") or {}
            geom  = feat.get("geometry")

            geom_json = json.dumps(geom) if geom else None

            batch.append((
                fonte_id,
                props.get("cod_imovel"),
                props.get("cod_tema"),
                props.get("nom_tema"),
                props.get("ind_status"),
                props.get("ind_tipo"),
                props.get("des_condic"),
                props.get("municipio"),
                props.get("cod_estado"),
                props.get("num_area"),
                props.get("mod_fiscal"),
                props.get("dat_criaca"),
                props.get("dat_atuali"),
                geom_json,
            ))

            if len(batch) >= BATCH_SIZE:
                _inserir_batch(cur, batch)
                inseridos += len(batch)
                batch = []
                print(f"\r  {inseridos:,}/{total:,}...", end="", flush=True)

        if batch:
            _inserir_batch(cur, batch)
            inseridos += len(batch)

        conn.commit()

    print(f"\n  Concluído: {inseridos:,} registros inseridos (fonte_id={fonte_id})")


def _inserir_batch(cur, batch: list):
    cur.executemany(
        """
        INSERT INTO sicar_imoveis (
            fonte_id, cod_imovel, cod_tema, nom_tema,
            ind_status, ind_tipo, des_condic,
            municipio, cod_estado,
            num_area, mod_fiscal,
            dat_criacao, dat_atualizacao,
            geom
        ) VALUES (
            %s, %s, %s, %s,
            %s, %s, %s,
            %s, %s,
            %s, %s,
            %s, %s,
            CASE WHEN %s IS NOT NULL
                 THEN ST_SetSRID(ST_GeomFromGeoJSON(%s), 4674)
                 ELSE NULL
            END
        )
        """,
        [row + (row[-1],) for row in batch],  # repete geom_json para o CASE
    )


def main():
    geojsons = sorted(PASTA_GEOJSON.glob("*.geojson"))

    if not geojsons:
        print(f"Nenhum GeoJSON encontrado em {PASTA_GEOJSON}")
        return

    print(f"Conectando ao banco {DB_CONFIG['dbname']} em {DB_CONFIG['host']}:{DB_CONFIG['port']}...")
    conn = conectar()
    print("Conectado.\n")

    for caminho in geojsons:
        try:
            importar_geojson(conn, caminho)
        except Exception as e:
            print(f"  ERRO em {caminho.name}: {e}")
            conn.rollback()

    conn.close()
    print("\nImportação finalizada.")


if __name__ == "__main__":
    main()
