"""Rotas GeoJSON para mapa e integracao com QGIS.

Todas as geometrias sao reprojetadas para EPSG:4326 (WGS84) conforme RFC 7946.
Filtros suportados (quando aplicavel a camada):
  - municipio: ILIKE no nome
  - data_inicio, data_fim: ISO date (YYYY-MM-DD)
  - bbox: "minx,miny,maxx,maxy" em EPSG:4326
  - limite, offset: paginacao
"""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse

from asg_sistema.db.conexao import executar_consulta

router = APIRouter()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

GEOJSON_MEDIA_TYPE = "application/geo+json"


def _parse_bbox(bbox: str | None) -> tuple[float, float, float, float] | None:
    if not bbox:
        return None
    partes = bbox.split(",")
    if len(partes) != 4:
        raise HTTPException(
            status_code=400,
            detail="bbox invalido. Use 'minx,miny,maxx,maxy' em EPSG:4326.",
        )
    try:
        minx, miny, maxx, maxy = (float(p) for p in partes)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"bbox invalido: {e}") from e
    if minx >= maxx or miny >= maxy:
        raise HTTPException(
            status_code=400,
            detail="bbox invalido: minx<maxx e miny<maxy sao obrigatorios.",
        )
    return minx, miny, maxx, maxy


def _filtro_bbox(coluna_geom: str, srid: int = 4674) -> str:
    return (
        f"{coluna_geom} && ST_Transform("
        f"ST_MakeEnvelope(:bbox_minx, :bbox_miny, :bbox_maxx, :bbox_maxy, 4326), {srid}"
        f")"
    )


def _aplicar_bbox(params: dict, bbox: tuple[float, float, float, float] | None) -> None:
    if not bbox:
        return
    params["bbox_minx"], params["bbox_miny"], params["bbox_maxx"], params["bbox_maxy"] = bbox


def _resposta_geojson(payload: dict[str, Any]) -> JSONResponse:
    return JSONResponse(content=payload, media_type=GEOJSON_MEDIA_TYPE)




def _montar_feature_collection(rows: list[dict], fonte: str = "") -> dict:
    features = []
    for row in rows:
        geom_str = row.pop("geometry", None)
        if not geom_str:
            continue
        props = {k: (str(v) if v is not None else None) for k, v in row.items()}
        if fonte:
            props["fonte"] = fonte
        features.append({
            "type": "Feature",
            "geometry": json.loads(geom_str),
            "properties": props,
        })
    return {
        "type": "FeatureCollection",
        "features": features,
        "totalFeatures": len(features),
    }


# ---------------------------------------------------------------------------
# Catalogo (capabilities)
# ---------------------------------------------------------------------------

_LIMITES_BASE = {
    "offset": {"min": 0},
    "bbox": {"formato": "minx,miny,maxx,maxy"},
}

CATALOGO_CAMADAS = [
    {
        "id": "queimadas",
        "nome": "Focos de Queimadas (INPE)",
        "fonte": "INPE",
        "geometria": "Point",
        "srid": 4326,
        "atributos": [
            "id", "municipio", "satelite", "data_hora",
            "bioma", "frp", "risco_fogo", "latitude", "longitude",
        ],
        "filtros": ["municipio", "data_inicio", "data_fim", "bbox", "limite", "offset"],
        "limites": {**_LIMITES_BASE, "limite": {"min": 1, "max": 10000, "default": 1000}},
        "url": "/geo/queimadas",
        "descricao": "Focos de calor detectados por satelite no Estado de SP.",
    },
    {
        "id": "terras_indigenas",
        "nome": "Terras Indigenas (FUNAI)",
        "fonte": "FUNAI",
        "geometria": "MultiPolygon",
        "srid": 4326,
        "atributos": ["nome", "etnia", "municipio", "area_ha", "fase", "modalidade"],
        "filtros": ["municipio", "bbox", "limite", "offset"],
        "limites": {**_LIMITES_BASE, "limite": {"min": 1, "max": 5000, "default": 500}},
        "url": "/geo/terras-indigenas",
        "descricao": "Areas indigenas demarcadas em SP.",
    },
    {
        "id": "desmatamento",
        "nome": "Alertas de Desmatamento (DETER)",
        "fonte": "DETER/INPE",
        "geometria": "MultiPolygon",
        "srid": 4326,
        "atributos": ["classe", "municipio", "data_avistamento", "area_total_km2", "sensor"],
        "filtros": ["municipio", "data_inicio", "data_fim", "classe", "bbox", "limite", "offset"],
        "limites": {**_LIMITES_BASE, "limite": {"min": 1, "max": 10000, "default": 1000}},
        "url": "/geo/desmatamento",
        "descricao": "Alertas DETER de supressao da vegetacao.",
    },
    {
        "id": "prodes",
        "nome": "Desmatamento Anual (PRODES)",
        "fonte": "PRODES/INPE",
        "geometria": "MultiPolygon",
        "srid": 4326,
        "atributos": ["classe_nome", "ano", "data_imagem", "area_km", "fonte_bioma", "satelite"],
        "filtros": ["ano", "bbox", "limite", "offset"],
        "limites": {**_LIMITES_BASE, "limite": {"min": 1, "max": 10000, "default": 2000}},
        "url": "/geo/prodes",
        "descricao": "Mapeamento PRODES de desmatamento consolidado por ano.",
    },
    {
        "id": "sicar",
        "nome": "Imoveis Rurais (SICAR/CAR)",
        "fonte": "SICAR",
        "geometria": "Geometry",
        "srid": 4326,
        "atributos": [
            "cod_imovel", "municipio", "num_area", "ind_status",
            "ind_tipo", "des_condic", "mod_fiscal", "dat_atualizacao",
        ],
        "filtros": [
            "cod_imovel", "municipio", "ind_status",
            "bbox", "simplify", "limite", "offset",
        ],
        "limites": {
            **_LIMITES_BASE,
            "limite": {"min": 1, "max": 5000, "default": 500},
            "simplify": {"min": 0, "max": 0.01},
        },
        "url": "/geo/sicar",
        "descricao": "Cadastro Ambiental Rural - imoveis rurais com geometrias.",
    },
    {
        "id": "unidades_conservacao",
        "nome": "Unidades de Conservacao (ICMBio/MMA)",
        "fonte": "ICMBio/MMA",
        "geometria": "Point",
        "srid": 4326,
        "atributos": ["nome", "categoria", "grupo", "esfera", "municipio", "area_ha", "situacao"],
        "filtros": ["municipio", "limite", "offset"],
        "limites": {**_LIMITES_BASE, "limite": {"min": 1, "max": 5000, "default": 500}},
        "url": "/geo/unidades-conservacao",
        "descricao": (
            "Unidades de Conservacao do CNUC. Posicao aproximada pelo centroide "
            "municipal — fontes oficiais nao expoem poligonos via API publica."
        ),
    },
    {
        "id": "quilombolas",
        "nome": "Comunidades Quilombolas (Palmares)",
        "fonte": "Fundacao Cultural Palmares",
        "geometria": "Point",
        "srid": 4326,
        "atributos": [
            "comunidade", "municipio", "ano_certificacao",
            "processo_fcp", "processo_incra", "regiao",
        ],
        "filtros": ["municipio", "limite", "offset"],
        "limites": {**_LIMITES_BASE, "limite": {"min": 1, "max": 5000, "default": 500}},
        "url": "/geo/quilombolas",
        "descricao": (
            "Comunidades quilombolas certificadas. Posicao aproximada pelo centroide "
            "municipal — Palmares nao publica coordenadas oficiais por comunidade."
        ),
    },
]


@router.get("/catalogo")
def catalogo_camadas():
    """Lista todas as camadas disponiveis para integracao QGIS/GeoJSON."""
    return {
        "versao": "1.0",
        "srid_saida": 4326,
        "media_type": GEOJSON_MEDIA_TYPE,
        "instrucoes_qgis": (
            "No QGIS: Layer -> Add Layer -> Add Vector Layer -> "
            "Source Type: Protocol HTTP(S) -> cole a URL do endpoint -> Add."
        ),
        "camadas": CATALOGO_CAMADAS,
    }


# ---------------------------------------------------------------------------
# Camadas com geometria
# ---------------------------------------------------------------------------

@router.get("/queimadas")
def geojson_queimadas(
    municipio: str | None = Query(None),
    data_inicio: str | None = Query(None, description="YYYY-MM-DD"),
    data_fim: str | None = Query(None, description="YYYY-MM-DD"),
    bbox: str | None = Query(None, description="minx,miny,maxx,maxy em EPSG:4326"),
    limite: int = Query(1000, le=10000, ge=1),
    offset: int = Query(0, ge=0),
):
    bbox_t = _parse_bbox(bbox)
    filtros_sql = [
        "geom IS NOT NULL",
        "UPPER(TRIM(estado)) IN ('SP', 'SAO PAULO', 'SÃO PAULO')",
    ]
    params: dict[str, Any] = {"limite": limite, "offset": offset}

    if municipio:
        filtros_sql.append("municipio ILIKE :mun")
        params["mun"] = f"%{municipio}%"
    if data_inicio:
        filtros_sql.append("data_hora >= :data_inicio")
        params["data_inicio"] = data_inicio
    if data_fim:
        filtros_sql.append("data_hora <= :data_fim")
        params["data_fim"] = data_fim
    if bbox_t:
        filtros_sql.append(_filtro_bbox("geom"))
        _aplicar_bbox(params, bbox_t)

    where = " WHERE " + " AND ".join(filtros_sql)
    sql = f"""
        SELECT
            ST_AsGeoJSON(ST_Transform(geom, 4326), 6) AS geometry,
            id, municipio, satelite, data_hora, bioma, frp, risco_fogo,
            latitude, longitude
        FROM queimadas
        {where}
        ORDER BY data_hora DESC
        LIMIT :limite OFFSET :offset
    """
    rows = executar_consulta(sql, params)
    return _resposta_geojson(_montar_feature_collection(rows, fonte="queimadas"))


@router.get("/terras-indigenas")
@router.get("/terras_indigenas")
def geojson_terras_indigenas(
    municipio: str | None = Query(None),
    bbox: str | None = Query(None),
    limite: int = Query(500, le=5000, ge=1),
    offset: int = Query(0, ge=0),
):
    bbox_t = _parse_bbox(bbox)
    filtros_sql = ["geom IS NOT NULL", "UPPER(TRIM(uf)) = 'SP'"]
    params: dict[str, Any] = {"limite": limite, "offset": offset}

    if municipio:
        filtros_sql.append("municipio ILIKE :mun")
        params["mun"] = f"%{municipio}%"
    if bbox_t:
        filtros_sql.append(_filtro_bbox("geom"))
        _aplicar_bbox(params, bbox_t)

    where = " WHERE " + " AND ".join(filtros_sql)
    sql = f"""
        SELECT
            ST_AsGeoJSON(ST_Transform(geom, 4326), 6) AS geometry,
            nome, etnia, municipio, area_ha, fase, modalidade
        FROM terras_indigenas
        {where}
        ORDER BY nome
        LIMIT :limite OFFSET :offset
    """
    rows = executar_consulta(sql, params)
    return _resposta_geojson(_montar_feature_collection(rows, fonte="funai"))


@router.get("/desmatamento")
def geojson_desmatamento(
    municipio: str | None = Query(None),
    data_inicio: str | None = Query(None),
    data_fim: str | None = Query(None),
    classe: str | None = Query(None),
    bbox: str | None = Query(None),
    limite: int = Query(1000, le=10000, ge=1),
    offset: int = Query(0, ge=0),
):
    bbox_t = _parse_bbox(bbox)
    filtros_sql = ["geom IS NOT NULL", "UPPER(TRIM(uf)) = 'SP'"]
    params: dict[str, Any] = {"limite": limite, "offset": offset}

    if municipio:
        filtros_sql.append("municipio ILIKE :mun")
        params["mun"] = f"%{municipio}%"
    if data_inicio:
        filtros_sql.append("data_avistamento >= :data_inicio")
        params["data_inicio"] = data_inicio
    if data_fim:
        filtros_sql.append("data_avistamento <= :data_fim")
        params["data_fim"] = data_fim
    if classe:
        filtros_sql.append("classe ILIKE :classe")
        params["classe"] = f"%{classe}%"
    if bbox_t:
        filtros_sql.append(_filtro_bbox("geom"))
        _aplicar_bbox(params, bbox_t)

    where = " WHERE " + " AND ".join(filtros_sql)
    sql = f"""
        SELECT
            ST_AsGeoJSON(ST_Transform(geom, 4326), 6) AS geometry,
            classe, municipio, data_avistamento, area_total_km2, sensor, satelite
        FROM desmatamento_alertas
        {where}
        ORDER BY data_avistamento DESC
        LIMIT :limite OFFSET :offset
    """
    rows = executar_consulta(sql, params)
    return _resposta_geojson(_montar_feature_collection(rows, fonte="deter"))


@router.get("/prodes")
def geojson_prodes(
    ano: int | None = Query(None),
    bbox: str | None = Query(None),
    limite: int = Query(2000, le=10000, ge=1),
    offset: int = Query(0, ge=0),
):
    bbox_t = _parse_bbox(bbox)
    filtros_sql = ["geom IS NOT NULL", "UPPER(TRIM(estado)) = 'SP'"]
    params: dict[str, Any] = {"limite": limite, "offset": offset}

    if ano:
        filtros_sql.append("ano = :ano")
        params["ano"] = ano
    if bbox_t:
        filtros_sql.append(_filtro_bbox("geom"))
        _aplicar_bbox(params, bbox_t)

    where = " WHERE " + " AND ".join(filtros_sql)
    sql = f"""
        SELECT
            ST_AsGeoJSON(ST_Transform(geom, 4326), 6) AS geometry,
            estado, classe_nome, data_imagem, ano, area_km, fonte_bioma, satelite, sensor
        FROM prodes_desmatamento
        {where}
        ORDER BY ano DESC, area_km DESC
        LIMIT :limite OFFSET :offset
    """
    rows = executar_consulta(sql, params)
    return _resposta_geojson(_montar_feature_collection(rows, fonte="prodes"))


@router.get("/sicar")
def geojson_sicar(
    cod_imovel: str | None = Query(None, description="Codigo CAR exato"),
    municipio: str | None = Query(None),
    ind_status: str | None = Query(None, description="Ex: AT (Ativo)"),
    bbox: str | None = Query(None),
    simplify: float | None = Query(
        None, ge=0, le=0.01,
        description="Tolerancia em graus para ST_Simplify (ex: 0.0001).",
    ),
    limite: int = Query(500, le=5000, ge=1),
    offset: int = Query(0, ge=0),
):
    bbox_t = _parse_bbox(bbox)
    filtros_sql = ["geom IS NOT NULL"]
    params: dict[str, Any] = {"limite": limite, "offset": offset}

    if cod_imovel:
        filtros_sql.append("cod_imovel = :cod")
        params["cod"] = cod_imovel.strip().upper()
    if municipio:
        filtros_sql.append("municipio ILIKE :mun")
        params["mun"] = f"%{municipio}%"
    if ind_status:
        filtros_sql.append("UPPER(TRIM(ind_status)) = :status")
        params["status"] = ind_status.strip().upper()
    if bbox_t:
        filtros_sql.append(_filtro_bbox("geom"))
        _aplicar_bbox(params, bbox_t)

    where = " WHERE " + " AND ".join(filtros_sql)

    if simplify is not None:
        geom_sql = (
            f"ST_AsGeoJSON("
            f"ST_Simplify(ST_Transform(geom, 4326), :simplify, true), 6"
            f")"
        )
        params["simplify"] = simplify
    else:
        geom_sql = "ST_AsGeoJSON(ST_Transform(geom, 4326), 6)"

    sql = f"""
        SELECT
            {geom_sql} AS geometry,
            cod_imovel, municipio, num_area, ind_status, ind_tipo,
            des_condic, mod_fiscal, dat_criacao, dat_atualizacao
        FROM sicar_imoveis
        {where}
        ORDER BY cod_imovel
        LIMIT :limite OFFSET :offset
    """
    rows = executar_consulta(sql, params)
    return _resposta_geojson(_montar_feature_collection(rows, fonte="sicar"))


# ---------------------------------------------------------------------------
# Camadas sem geometria (tabulares) - retornadas como FeatureCollection vazia
# ---------------------------------------------------------------------------

import re as _re

_CENTROID_QUERIES_FALLBACK = [
    """SELECT AVG(longitude) AS lon, AVG(latitude) AS lat
       FROM queimadas
       WHERE municipio ILIKE :mun
         AND UPPER(TRIM(estado)) IN ('SP', 'SAO PAULO', 'SÃO PAULO')""",
    """SELECT ST_X(ST_Centroid(ST_Collect(geom))) AS lon,
              ST_Y(ST_Centroid(ST_Collect(geom))) AS lat
       FROM terras_indigenas
       WHERE municipio ILIKE :mun
         AND geom IS NOT NULL AND UPPER(TRIM(uf)) = 'SP'""",
    """SELECT AVG(ST_X(ST_Centroid(geom))) AS lon, AVG(ST_Y(ST_Centroid(geom))) AS lat
       FROM desmatamento_alertas
       WHERE municipio ILIKE :mun
         AND geom IS NOT NULL AND UPPER(TRIM(uf)) = 'SP'""",
]


def _nome_simples(mun: str) -> str:
    """Igual ao _nome_simples do gerador_resposta.py: primeiro municipio sem '(UF)'."""
    primeiro = mun.split(",")[0].strip()
    primeiro = _re.sub(r"\s*\([A-Z]{2}\)\s*$", "", primeiro).strip()
    return primeiro


def _centroide_municipio(mun: str) -> tuple[float, float] | None:
    nome = _nome_simples(mun)
    if not nome:
        return None
    params = {"mun": f"%{nome}%"}
    for query in _CENTROID_QUERIES_FALLBACK:
        try:
            rows = executar_consulta(query, params)
            if rows and rows[0].get("lon") is not None and rows[0].get("lat") is not None:
                return (round(float(rows[0]["lon"]), 6), round(float(rows[0]["lat"]), 6))
        except Exception:
            continue
    return None


def _features_corpus(
    fonte: str,
    fonte_label: str,
    municipio: str | None,
    limite: int,
    offset: int,
) -> list[dict]:
    filtros = ["c.fonte = :fonte", "UPPER(TRIM(c.uf_sigla)) = 'SP'"]
    params: dict[str, Any] = {"fonte": fonte, "limite": limite, "offset": offset}
    if municipio:
        filtros.append("c.municipio ILIKE :mun")
        params["mun"] = f"%{municipio}%"

    where = " WHERE " + " AND ".join(filtros)
    sql = f"""
        SELECT
            c.municipio,
            c.data_referencia,
            c.metadados_json,
            c.texto
        FROM corpus_asg c
        {where}
        ORDER BY c.municipio
        LIMIT :limite OFFSET :offset
    """
    rows = executar_consulta(sql, params)

    # Cache de centroides por municipio (chave = nome bruto do registro).
    cache_centroides: dict[str, tuple[float, float] | None] = {}

    features = []
    for row in rows:
        mun_raw = row.get("municipio") or ""
        if mun_raw not in cache_centroides:
            cache_centroides[mun_raw] = _centroide_municipio(mun_raw)
        coords = cache_centroides[mun_raw]
        if coords is None:
            continue

        geom = {"type": "Point", "coordinates": [coords[0], coords[1]]}

        meta_raw = row.pop("metadados_json", None) or {}
        if isinstance(meta_raw, str):
            try:
                meta = json.loads(meta_raw)
            except (ValueError, TypeError):
                meta = {}
        else:
            meta = meta_raw

        props: dict[str, Any] = {"fonte": fonte_label, "posicao_aproximada": "true"}
        for k, v in row.items():
            if k == "metadados_json":
                continue
            props[k] = str(v) if v is not None else None
        if isinstance(meta, dict):
            for k, v in meta.items():
                if k not in props and v is not None:
                    props[k] = str(v)

        features.append({
            "type": "Feature",
            "geometry": geom,
            "properties": props,
        })
    return features


@router.get("/unidades-conservacao")
@router.get("/unidades_conservacao")
def geojson_unidades_conservacao(
    municipio: str | None = Query(None),
    limite: int = Query(500, le=5000, ge=1),
    offset: int = Query(0, ge=0),
):
    features = _features_corpus("icmbio", "icmbio", municipio, limite, offset)
    return _resposta_geojson({
        "type": "FeatureCollection",
        "features": features,
        "totalFeatures": len(features),
        "nota": (
            "Pontos derivados do centroide do municipio (queimadas). "
            "MMA/ICMBio nao publica poligonos via API."
        ),
    })


@router.get("/quilombolas")
def geojson_quilombolas(
    municipio: str | None = Query(None),
    limite: int = Query(500, le=5000, ge=1),
    offset: int = Query(0, ge=0),
):
    features = _features_corpus("palmares", "palmares", municipio, limite, offset)
    return _resposta_geojson({
        "type": "FeatureCollection",
        "features": features,
        "totalFeatures": len(features),
        "nota": (
            "Pontos derivados do centroide do municipio (queimadas). "
            "Palmares nao publica coordenadas oficiais por comunidade."
        ),
    })
