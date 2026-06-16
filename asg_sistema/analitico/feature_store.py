"""Builder da feature store de propriedades (fato_propriedade_ambiental).

Estratégia (performance): sinais espaciais via SQL set-based (PostGIS + GiST),
processados POR MUNICÍPIO em lotes; depois o risco AHP é calculado em Python
reusando `calcular_score_ahp` (sem PostGIS nesta etapa — barato).

Uso:
    from asg_sistema.analitico.feature_store import construir_features
    construir_features()                 # todos os municípios
    construir_features(municipios=[...]) # subconjunto
"""

import json
import logging

from sqlalchemy import text

from asg_sistema.db.conexao import engine
from asg_sistema.motor.calculadora_risco import calcular_score_ahp

logger = logging.getLogger("asg.feature_store")

# ~0.045° ≈ 5 km; ~0.09° ≈ 10 km (prefiltro usa índice GiST de geometria).
_RAIO_5KM = 0.045
_RAIO_10KM = 0.09

# Pass 1: sinais espaciais por imóvel (de um município), via LATERAL joins.
_SQL_SINAIS = text(f"""
INSERT INTO fato_propriedade_ambiental (
    cod_imovel, municipio, uf, area_ha,
    focos_total, focos_internos, focos_recentes_12m, focos_recentes_6m,
    queimadas_anos_distintos_3a, frp_medio, dist_queimada_km,
    alertas_deter_total, alertas_deter_recentes_12m, area_impactada_deter_km2, dist_deter_km,
    prodes_total_poligonos, prodes_area_km2, prodes_poligonos_recentes,
    prodes_poligonos_antigos, dist_prodes_km,
    sobrepoe_ti, ti_area_sobreposicao_ha, ti_proximas_10km, dist_ti_km,
    uc_total, uc_protecao_integral, uc_uso_sustentavel, quilombola_total_municipio,
    area_impactada_total_km2, area_impactada_pct, fogo_apos_alerta,
    geom, atualizado_em
)
SELECT
    p.cod_imovel, p.municipio, p.cod_estado AS uf, COALESCE(p.num_area, 0) AS area_ha,
    COALESCE(q.focos_total,0), COALESCE(q.focos_internos,0),
    COALESCE(q.focos_12m,0), COALESCE(q.focos_6m,0),
    COALESCE(q.anos_3a,0), COALESCE(q.frp_medio,0), q.dist_km,
    COALESCE(d.total_alertas,0), COALESCE(d.recentes_12m,0),
    COALESCE(d.area_inter_km2,0), d.dist_km,
    COALESCE(pr.total_poligonos,0), COALESCE(pr.area_km2,0),
    COALESCE(pr.recentes,0), COALESCE(pr.antigos,0), pr.dist_km,
    COALESCE(t.sobrepoe,FALSE), COALESCE(t.area_ha,0), COALESCE(t.proximas,0), t.dist_km,
    COALESCE(uc.total,0), COALESCE(uc.pi,0), COALESCE(uc.us,0), COALESCE(ql.total,0),
    COALESCE(d.area_inter_km2,0) + COALESCE(pr.area_km2,0) AS area_imp,
    CASE WHEN COALESCE(p.num_area,0) > 0
         THEN (COALESCE(d.area_inter_km2,0) + COALESCE(pr.area_km2,0)) / (p.num_area/100.0)
         ELSE 0 END AS area_pct,
    COALESCE(fa.n,0),
    p.geom, NOW()
FROM sicar_imoveis p
LEFT JOIN LATERAL (
    SELECT count(*) AS focos_total,
           count(*) FILTER (WHERE ST_Intersects(p.geom, q.geom)) AS focos_internos,
           count(*) FILTER (WHERE q.data_hora >= now() - interval '12 months') AS focos_12m,
           count(*) FILTER (WHERE q.data_hora >= now() - interval '6 months') AS focos_6m,
           count(DISTINCT date_part('year', q.data_hora))
                 FILTER (WHERE q.data_hora >= now() - interval '3 years') AS anos_3a,
           COALESCE(avg(q.frp), 0) AS frp_medio,
           MIN(ST_Distance(p.geom::geography, q.geom::geography))/1000.0 AS dist_km
    FROM queimadas q
    WHERE ST_DWithin(p.geom, q.geom, {_RAIO_5KM})
) q ON TRUE
LEFT JOIN LATERAL (
    SELECT count(*) AS total_alertas,
           count(*) FILTER (WHERE d.data_avistamento >= (now() - interval '12 months')::date) AS recentes_12m,
           COALESCE(SUM(ST_Area(ST_Intersection(ST_MakeValid(p.geom), ST_MakeValid(d.geom))::geography))/1e6, 0) AS area_inter_km2,
           MIN(ST_Distance(p.geom::geography, d.geom::geography))/1000.0 AS dist_km,
           MIN(d.data_avistamento) AS primeira_data
    FROM desmatamento_alertas d
    WHERE ST_DWithin(p.geom, d.geom, {_RAIO_5KM})
) d ON TRUE
LEFT JOIN LATERAL (
    SELECT count(*) AS total_poligonos,
           COALESCE(SUM(ST_Area(ST_Intersection(ST_MakeValid(p.geom), ST_MakeValid(pr.geom))::geography))/1e6, 0) AS area_km2,
           count(*) FILTER (WHERE pr.ano >= date_part('year', now()) - 3) AS recentes,
           count(*) FILTER (WHERE pr.ano <  date_part('year', now()) - 3) AS antigos,
           MIN(ST_Distance(p.geom::geography, pr.geom::geography))/1000.0 AS dist_km
    FROM prodes_desmatamento pr
    WHERE ST_DWithin(p.geom, pr.geom, {_RAIO_5KM})
) pr ON TRUE
LEFT JOIN LATERAL (
    SELECT bool_or(ST_Intersects(p.geom, t.geom)) AS sobrepoe,
           COALESCE(SUM(ST_Area(ST_Intersection(ST_MakeValid(p.geom), ST_MakeValid(t.geom))::geography))/10000.0, 0) AS area_ha,
           count(*) FILTER (WHERE NOT ST_Intersects(p.geom, t.geom)) AS proximas,
           MIN(ST_Distance(p.geom::geography, t.geom::geography))/1000.0 AS dist_km
    FROM terras_indigenas t
    WHERE ST_DWithin(p.geom, t.geom, {_RAIO_10KM})
) t ON TRUE
LEFT JOIN LATERAL (
    SELECT count(*) AS n
    FROM queimadas q2
    WHERE d.primeira_data IS NOT NULL
      AND ST_DWithin(p.geom, q2.geom, {_RAIO_5KM})
      AND q2.data_hora::date > d.primeira_data
) fa ON TRUE
LEFT JOIN LATERAL (
    SELECT count(*) AS total,
           count(*) FILTER (WHERE u.grupo ILIKE '%integral%') AS pi,
           count(*) FILTER (WHERE u.grupo ILIKE '%sustent%')  AS us
    FROM unidades_conservacao u WHERE u.municipio = p.municipio
) uc ON TRUE
LEFT JOIN LATERAL (
    SELECT count(*) AS total FROM comunidades_quilombolas c WHERE c.municipio = p.municipio
) ql ON TRUE
WHERE p.geom IS NOT NULL AND p.municipio = :mun
ON CONFLICT (cod_imovel) DO UPDATE SET
    municipio = EXCLUDED.municipio, uf = EXCLUDED.uf, area_ha = EXCLUDED.area_ha,
    focos_total = EXCLUDED.focos_total, focos_internos = EXCLUDED.focos_internos,
    focos_recentes_12m = EXCLUDED.focos_recentes_12m, focos_recentes_6m = EXCLUDED.focos_recentes_6m,
    queimadas_anos_distintos_3a = EXCLUDED.queimadas_anos_distintos_3a,
    frp_medio = EXCLUDED.frp_medio, dist_queimada_km = EXCLUDED.dist_queimada_km,
    alertas_deter_total = EXCLUDED.alertas_deter_total,
    alertas_deter_recentes_12m = EXCLUDED.alertas_deter_recentes_12m,
    area_impactada_deter_km2 = EXCLUDED.area_impactada_deter_km2, dist_deter_km = EXCLUDED.dist_deter_km,
    prodes_total_poligonos = EXCLUDED.prodes_total_poligonos, prodes_area_km2 = EXCLUDED.prodes_area_km2,
    prodes_poligonos_recentes = EXCLUDED.prodes_poligonos_recentes,
    prodes_poligonos_antigos = EXCLUDED.prodes_poligonos_antigos, dist_prodes_km = EXCLUDED.dist_prodes_km,
    sobrepoe_ti = EXCLUDED.sobrepoe_ti, ti_area_sobreposicao_ha = EXCLUDED.ti_area_sobreposicao_ha,
    ti_proximas_10km = EXCLUDED.ti_proximas_10km, dist_ti_km = EXCLUDED.dist_ti_km,
    uc_total = EXCLUDED.uc_total, uc_protecao_integral = EXCLUDED.uc_protecao_integral,
    uc_uso_sustentavel = EXCLUDED.uc_uso_sustentavel,
    quilombola_total_municipio = EXCLUDED.quilombola_total_municipio,
    area_impactada_total_km2 = EXCLUDED.area_impactada_total_km2,
    area_impactada_pct = EXCLUDED.area_impactada_pct, fogo_apos_alerta = EXCLUDED.fogo_apos_alerta,
    geom = EXCLUDED.geom, atualizado_em = NOW()
""")

_SQL_LER_PARA_AHP = text("""
SELECT cod_imovel, area_ha, focos_internos, focos_total, frp_medio, focos_recentes_6m,
       dist_queimada_km, alertas_deter_total, area_impactada_deter_km2,
       alertas_deter_recentes_12m, dist_deter_km, prodes_total_poligonos, prodes_area_km2,
       prodes_poligonos_recentes, prodes_poligonos_antigos, dist_prodes_km,
       sobrepoe_ti, ti_area_sobreposicao_ha, ti_proximas_10km,
       quilombola_total_municipio, uc_total, uc_protecao_integral, uc_uso_sustentavel
FROM fato_propriedade_ambiental WHERE municipio = :mun
""")

_SQL_UPDATE_AHP = text("""
UPDATE fato_propriedade_ambiental
SET nota_risco = :nota, nivel_risco = :nivel, n_fatores_risco = :nf, fatores_json = :fat
WHERE cod_imovel = :cod
""")


def _cruzamento_de_linha(r) -> dict:
    """Reconstrói o dict de cruzamento esperado por calcular_score_ahp."""
    return {
        "queimadas": {
            "focos_internos": r.focos_internos, "focos_total": r.focos_total,
            "frp_medio": r.frp_medio, "focos_recentes_6m": r.focos_recentes_6m,
            "distancia_min_km": r.dist_queimada_km or 0,
        },
        "deter": {
            "total_alertas": r.alertas_deter_total,
            "area_intersecao_km2": r.area_impactada_deter_km2,
            "alertas_recentes_12m": r.alertas_deter_recentes_12m,
            "distancia_min_km": r.dist_deter_km or 0,
        },
        "prodes": {
            "total_poligonos": r.prodes_total_poligonos, "area_hist_km2": r.prodes_area_km2,
            "poligonos_recentes": r.prodes_poligonos_recentes,
            "poligonos_antigos": r.prodes_poligonos_antigos,
            "distancia_min_km": r.dist_prodes_km or 0,
        },
        "terras_indigenas": {
            "sobrepoe": bool(r.sobrepoe_ti),
            "sobreposicoes": ([{"nome": "Terra Indígena",
                                "area_sobreposicao_ha": r.ti_area_sobreposicao_ha}]
                              if r.sobrepoe_ti else []),
            "proximas_10km": [{}] * int(r.ti_proximas_10km or 0),
        },
        "quilombolas": {
            "sobreposicoes": [], "proximas_10km": [],
            "total_municipio": r.quilombola_total_municipio,
        },
        "unidades_conservacao": {
            "total": r.uc_total, "protecao_integral": r.uc_protecao_integral,
            "uso_sustentavel": r.uc_uso_sustentavel,
        },
    }


def _municipios_alvo(municipios: list[str] | None) -> list[str]:
    if municipios:
        return municipios
    with engine.connect() as conn:
        rows = conn.execute(text(
            "SELECT DISTINCT municipio FROM sicar_imoveis "
            "WHERE municipio IS NOT NULL AND geom IS NOT NULL ORDER BY municipio"
        ))
        return [r[0] for r in rows]


def construir_features(municipios: list[str] | None = None) -> dict:
    """(Re)constrói a feature store. Uma transação por município (atômica)."""
    total_props = 0
    muns_processados = 0
    alvos = _municipios_alvo(municipios)
    logger.info("feature_store_inicio", extra={"municipios": len(alvos)})
    for mun in alvos:
        try:
            # engine.begin() abre uma transação nova e commita ao sair do with.
            with engine.begin() as conn:
                conn.execute(_SQL_SINAIS, {"mun": mun})
                linhas = conn.execute(_SQL_LER_PARA_AHP, {"mun": mun}).fetchall()
                for r in linhas:
                    area_km2 = (r.area_ha or 0) / 100.0
                    res = calcular_score_ahp(_cruzamento_de_linha(r), area_km2)
                    nf = sum(1 for v in res["por_dimensao"].values() if v > 0)
                    conn.execute(_SQL_UPDATE_AHP, {
                        "nota": res["nota"], "nivel": res["nivel"], "nf": nf,
                        "fat": json.dumps(res["fatores"], ensure_ascii=False),
                        "cod": r.cod_imovel,
                    })
            total_props += len(linhas)
            muns_processados += 1
            if muns_processados % 25 == 0:
                logger.info("feature_store_progresso",
                            extra={"municipios": muns_processados, "props": total_props})
        except Exception:
            logger.exception("feature_store_falha_municipio", extra={"municipio": mun})
    logger.info("feature_store_fim", extra={"municipios": muns_processados, "props": total_props})
    return {"municipios": muns_processados, "propriedades": total_props}
