-- Camada semântica: views que pré-resolvem agregações comuns do caminho analítico.
-- O construtor de SQL e o fallback generativo podem preferir estas views.

CREATE OR REPLACE VIEW vw_desmatamento_municipio AS
  SELECT municipio,
         EXTRACT(YEAR  FROM data_avistamento)::int AS ano,
         EXTRACT(MONTH FROM data_avistamento)::int AS mes,
         COUNT(*)            AS qtd_alertas,
         SUM(area_total_km2) AS area_km2
  FROM desmatamento_alertas
  WHERE data_avistamento IS NOT NULL
  GROUP BY municipio, ano, mes;

CREATE OR REPLACE VIEW vw_queimadas_municipio AS
  SELECT municipio,
         EXTRACT(YEAR  FROM data_hora)::int AS ano,
         EXTRACT(MONTH FROM data_hora)::int AS mes,
         COUNT(*)        AS qtd_focos,
         AVG(frp)        AS frp_medio,
         AVG(risco_fogo) AS risco_fogo_medio
  FROM queimadas
  WHERE data_hora IS NOT NULL
  GROUP BY municipio, ano, mes;

CREATE OR REPLACE VIEW vw_prodes_ano AS
  SELECT ano, classe_nome,
         SUM(area_km) AS area_km2,
         COUNT(*)     AS qtd_poligonos
  FROM prodes_desmatamento
  GROUP BY ano, classe_nome;

-- ---------------------------------------------------------------------------
-- Eventos ambientais multi-fonte por município/ano (queimadas ∪ DETER ∪ PRODES).
-- Base para "municípios com mais eventos ambientais críticos".
-- ---------------------------------------------------------------------------
CREATE OR REPLACE VIEW vw_eventos_municipio_ano AS
  SELECT municipio,
         EXTRACT(YEAR FROM data_hora)::int AS ano,
         'queimada'::text AS tipo,
         COUNT(*)::bigint AS n_eventos,
         0::double precision AS area_km2
  FROM queimadas WHERE data_hora IS NOT NULL AND municipio IS NOT NULL
  GROUP BY municipio, ano
  UNION ALL
  SELECT municipio,
         EXTRACT(YEAR FROM data_avistamento)::int AS ano,
         'deter'::text AS tipo,
         COUNT(*)::bigint AS n_eventos,
         COALESCE(SUM(area_total_km2), 0) AS area_km2
  FROM desmatamento_alertas WHERE data_avistamento IS NOT NULL AND municipio IS NOT NULL
  GROUP BY municipio, ano;

-- Total de eventos por município (todas as fontes, todos os anos).
CREATE OR REPLACE VIEW vw_eventos_municipio AS
  SELECT municipio,
         SUM(n_eventos)::bigint AS total_eventos,
         SUM(area_km2)          AS area_km2
  FROM vw_eventos_municipio_ano
  GROUP BY municipio;

-- ---------------------------------------------------------------------------
-- Crescimento de queimadas por município: compara o primeiro vs o último ano
-- da janela disponível (base para "maior crescimento nos últimos N anos").
-- ---------------------------------------------------------------------------
CREATE OR REPLACE VIEW vw_queimadas_crescimento_municipio AS
  WITH por_ano AS (
    SELECT municipio,
           EXTRACT(YEAR FROM data_hora)::int AS ano,
           COUNT(*)::bigint AS focos
    FROM queimadas
    WHERE data_hora IS NOT NULL AND municipio IS NOT NULL
    GROUP BY municipio, ano
  ),
  bordas AS (
    SELECT municipio,
           MIN(ano) AS ano_ini,
           MAX(ano) AS ano_fim,
           SUM(focos) AS focos_total
    FROM por_ano GROUP BY municipio
  )
  SELECT b.municipio,
         b.ano_ini, b.ano_fim, b.focos_total,
         pi.focos AS focos_ano_ini,
         pf.focos AS focos_ano_fim,
         (pf.focos - pi.focos) AS crescimento_abs,
         CASE WHEN COALESCE(pi.focos, 0) > 0
              THEN ROUND(((pf.focos - pi.focos)::numeric / pi.focos) * 100, 1)
              ELSE NULL END AS crescimento_pct
  FROM bordas b
  LEFT JOIN por_ano pi ON pi.municipio = b.municipio AND pi.ano = b.ano_ini
  LEFT JOIN por_ano pf ON pf.municipio = b.municipio AND pf.ano = b.ano_fim
  WHERE b.ano_fim > b.ano_ini;
