"""Rotas GeoJSON para mapa e integracao com QGIS."""

from fastapi import APIRouter, Query

from asg_sistema.db.conexao import executar_consulta

router = APIRouter()


@router.get("/queimadas")
def geojson_queimadas(municipio: str | None = Query(None), limite: int = Query(1000, le=10000)):
    filtro = "WHERE geom IS NOT NULL"
    params = {"limite": limite}
    if municipio:
        filtro += " AND municipio ILIKE :mun"
        params["mun"] = f"%{municipio}%"

    rows = executar_consulta(
        f"""SELECT ST_AsGeoJSON(geom) as geometry, municipio, satelite,
                   data_hora, bioma, frp
            FROM queimadas {filtro}
            ORDER BY data_hora DESC LIMIT :limite""",
        params,
    )
    return _montar_feature_collection(rows, fonte="queimadas")


@router.get("/terras-indigenas")
@router.get("/terras_indigenas")
def geojson_terras_indigenas():
    rows = executar_consulta(
        """SELECT ST_AsGeoJSON(geom) as geometry, nome, etnia,
                  municipio, area_ha, fase
           FROM terras_indigenas WHERE geom IS NOT NULL"""
    )
    return _montar_feature_collection(rows, fonte="funai")


@router.get("/desmatamento")
def geojson_desmatamento():
    rows = executar_consulta(
        """SELECT ST_AsGeoJSON(geom) as geometry, classe, municipio,
                  data_avistamento, area_total_km2
           FROM desmatamento_alertas WHERE geom IS NOT NULL"""
    )
    return _montar_feature_collection(rows, fonte="deter")


@router.get("/unidades-conservacao")
@router.get("/unidades_conservacao")
def geojson_unidades_conservacao():
    rows = executar_consulta(
        """SELECT nome, categoria, grupo, esfera, municipio, area_ha
           FROM unidades_conservacao LIMIT 500"""
    )
    return {"type": "FeatureCollection", "features": [], "dados": rows, "nota": "UCs sem geometria no banco"}


@router.get("/prodes")
def geojson_prodes(ano: int | None = Query(None), limite: int = Query(2000, le=10000)):
    filtro = "WHERE geom IS NOT NULL"
    params = {"limite": limite}
    if ano:
        filtro += " AND ano = :ano"
        params["ano"] = ano

    rows = executar_consulta(
        f"""SELECT ST_AsGeoJSON(geom) as geometry, estado, classe_nome,
                   data_imagem, ano, area_km, fonte_bioma, satelite
            FROM prodes_desmatamento {filtro}
            ORDER BY ano DESC, area_km DESC LIMIT :limite""",
        params,
    )
    return _montar_feature_collection(rows, fonte="prodes")


@router.get("/quilombolas")
def geojson_quilombolas(municipio: str | None = Query(None)):
    filtro = ""
    params = {}
    if municipio:
        filtro = "WHERE municipio ILIKE :mun"
        params["mun"] = f"%{municipio}%"

    rows = executar_consulta(
        f"""SELECT comunidade, municipio, uf, ano_certificacao,
                  processo_fcp, processo_incra
           FROM comunidades_quilombolas {filtro}
           ORDER BY municipio LIMIT 200""",
        params,
    )
    features = []
    for row in rows:
        features.append({
            "type": "Feature",
            "geometry": None,
            "properties": {
                "fonte": "palmares",
                "municipio": row.get("municipio", ""),
                "comunidade": row.get("comunidade", ""),
                "ano_certificacao": str(row.get("ano_certificacao", "")),
                "processo_fcp": row.get("processo_fcp", ""),
            },
        })
    return {
        "type": "FeatureCollection",
        "features": features,
        "nota": "Quilombolas sem coordenadas - dados tabulares da Fundação Cultural Palmares",
    }


def _montar_feature_collection(rows: list[dict], fonte: str = "") -> dict:
    import json
    features = []
    for row in rows:
        geom_str = row.pop("geometry", None)
        if not geom_str:
            continue
        props = {k: str(v) if v is not None else None for k, v in row.items()}
        if fonte:
            props["fonte"] = fonte
        features.append({
            "type": "Feature",
            "geometry": json.loads(geom_str),
            "properties": props,
        })
    return {"type": "FeatureCollection", "features": features}
