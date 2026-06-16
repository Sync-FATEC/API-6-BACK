-- Camada de features por propriedade (feature store).
-- Uma linha por imóvel rural (sicar_imoveis) com sinais ambientais derivados,
-- pré-calculados por batch (asg_sistema/analitico/feature_store.py).
-- Permite responder rankings/filtros de propriedade com SELECT simples e rápido.

CREATE TABLE IF NOT EXISTS fato_propriedade_ambiental (
    cod_imovel                   VARCHAR(254) PRIMARY KEY,
    municipio                    VARCHAR(254),
    uf                           VARCHAR(5),
    area_ha                      DOUBLE PRECISION,

    -- Queimadas (focos dentro do imóvel e até 5km)
    focos_total                  INTEGER DEFAULT 0,
    focos_internos               INTEGER DEFAULT 0,
    focos_recentes_12m           INTEGER DEFAULT 0,
    focos_recentes_6m            INTEGER DEFAULT 0,   -- usado pelo AHP
    queimadas_anos_distintos_3a  INTEGER DEFAULT 0,   -- recorrência
    frp_medio                    DOUBLE PRECISION DEFAULT 0,
    dist_queimada_km             DOUBLE PRECISION,

    -- DETER (alertas de desmatamento)
    alertas_deter_total          INTEGER DEFAULT 0,
    alertas_deter_recentes_12m   INTEGER DEFAULT 0,
    area_impactada_deter_km2     DOUBLE PRECISION DEFAULT 0,
    dist_deter_km                DOUBLE PRECISION,

    -- PRODES (desmatamento consolidado)
    prodes_total_poligonos       INTEGER DEFAULT 0,
    prodes_area_km2              DOUBLE PRECISION DEFAULT 0,
    prodes_poligonos_recentes    INTEGER DEFAULT 0,
    prodes_poligonos_antigos     INTEGER DEFAULT 0,
    dist_prodes_km               DOUBLE PRECISION,

    -- Terras indígenas
    sobrepoe_ti                  BOOLEAN DEFAULT FALSE,
    ti_area_sobreposicao_ha      DOUBLE PRECISION DEFAULT 0,
    ti_proximas_10km             INTEGER DEFAULT 0,
    dist_ti_km                   DOUBLE PRECISION,

    -- Contexto municipal (UC + quilombolas, sem geometria → nível município)
    uc_total                     INTEGER DEFAULT 0,
    uc_protecao_integral         INTEGER DEFAULT 0,
    uc_uso_sustentavel           INTEGER DEFAULT 0,
    quilombola_total_municipio   INTEGER DEFAULT 0,

    -- Derivados de impacto
    area_impactada_total_km2     DOUBLE PRECISION DEFAULT 0,
    area_impactada_pct           DOUBLE PRECISION DEFAULT 0,
    fogo_apos_alerta             INTEGER DEFAULT 0,

    -- Risco AHP (calculado em Python reusando calcular_score_ahp)
    n_fatores_risco              INTEGER DEFAULT 0,
    nota_risco                   INTEGER DEFAULT 0,
    nivel_risco                  VARCHAR(20),
    fatores_json                 JSONB,

    geom                         GEOMETRY(Geometry, 4674),
    atualizado_em                TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_fato_prop_geom ON fato_propriedade_ambiental USING GIST(geom);
CREATE INDEX IF NOT EXISTS idx_fato_prop_municipio ON fato_propriedade_ambiental(municipio);
CREATE INDEX IF NOT EXISTS idx_fato_prop_nota ON fato_propriedade_ambiental(nota_risco);
CREATE INDEX IF NOT EXISTS idx_fato_prop_focos12 ON fato_propriedade_ambiental(focos_recentes_12m);
CREATE INDEX IF NOT EXISTS idx_fato_prop_nfatores ON fato_propriedade_ambiental(n_fatores_risco);
CREATE INDEX IF NOT EXISTS idx_fato_prop_areapct ON fato_propriedade_ambiental(area_impactada_pct);
