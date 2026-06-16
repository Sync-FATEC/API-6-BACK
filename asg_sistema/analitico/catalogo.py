"""Catálogo curado do schema para o caminho analítico.

Três papéis:
- allowlist (segurança): TABELAS_PERMITIDAS / VIEWS_PERMITIDAS (tabela -> colunas).
- conhecimento de construção: METRICAS / DIMENSOES por tabela.
- schema linking: CATALOGO_SEMANTICO (frases-âncora em PT embedadas pelo linker).
- fallback generativo: CATALOGO_TEXTO (descrição compacta p/ o modelo opcional).

Só inclui tabelas/views consultáveis. Esconde corpus_asg, embeddings, usuarios,
conversas, mensagens e qualquer coisa interna.
"""

# Allowlist: tabela -> conjunto de colunas expostas (usada pelo validador via AST).
TABELAS_PERMITIDAS: dict[str, set[str]] = {
    "queimadas": {
        "id", "municipio", "estado", "data_hora", "satelite", "bioma",
        "frp", "risco_fogo", "precipitacao", "latitude", "longitude", "geom",
    },
    "desmatamento_alertas": {
        "id", "classe", "municipio", "uf", "data_avistamento", "sensor",
        "satelite", "area_total_km2", "area_uc_km2", "nome_uc", "geom",
    },
    "prodes_desmatamento": {
        "id", "uid", "estado", "classe_principal", "classe_nome", "data_imagem",
        "ano", "area_km", "fonte_bioma", "satelite", "sensor", "geom",
    },
    "sicar_imoveis": {
        "id", "cod_imovel", "cod_tema", "nom_tema", "ind_status", "ind_tipo",
        "des_condic", "municipio", "cod_estado", "num_area", "mod_fiscal",
        "dat_criacao", "dat_atualizacao", "geom",
    },
    "terras_indigenas": {
        "id", "codigo", "nome", "etnia", "municipio", "uf", "area_ha",
        "fase", "modalidade", "geom",
    },
    "unidades_conservacao": {
        "id", "nome", "categoria", "grupo", "esfera", "uf", "municipio",
        "area_ha", "situacao", "geom",
    },
    "comunidades_quilombolas": {
        "id", "municipio", "uf", "comunidade", "codigo_ibge", "processo_fcp",
        "ano_certificacao", "processo_incra", "regiao", "geom",
    },
    "fontes": {
        "id", "nome", "descricao", "url_origem", "data_coleta",
        "total_registros", "escopo",
    },
    # Feature store de propriedades (pré-calculada por feature_store.py).
    "fato_propriedade_ambiental": {
        "cod_imovel", "municipio", "uf", "area_ha",
        "focos_total", "focos_internos", "focos_recentes_12m", "focos_recentes_6m",
        "queimadas_anos_distintos_3a", "frp_medio", "dist_queimada_km",
        "alertas_deter_total", "alertas_deter_recentes_12m", "area_impactada_deter_km2", "dist_deter_km",
        "prodes_total_poligonos", "prodes_area_km2", "prodes_poligonos_recentes",
        "prodes_poligonos_antigos", "dist_prodes_km",
        "sobrepoe_ti", "ti_area_sobreposicao_ha", "ti_proximas_10km", "dist_ti_km",
        "uc_total", "uc_protecao_integral", "uc_uso_sustentavel", "quilombola_total_municipio",
        "area_impactada_total_km2", "area_impactada_pct", "fogo_apos_alerta",
        "n_fatores_risco", "nota_risco", "nivel_risco", "fatores_json",
        "geom", "atualizado_em",
    },
}

# Tabelas cujo alvo é a PROPRIEDADE (rota PROPRIEDADE: ranking/filtro sem GROUP BY).
TABELAS_PROPRIEDADE = {"fato_propriedade_ambiental"}

# Views da camada semântica (asg_sistema/db/schema_views.sql).
VIEWS_PERMITIDAS: dict[str, set[str]] = {
    "vw_desmatamento_municipio": {"municipio", "ano", "mes", "qtd_alertas", "area_km2"},
    "vw_queimadas_municipio": {"municipio", "ano", "mes", "qtd_focos", "frp_medio", "risco_fogo_medio"},
    "vw_prodes_ano": {"ano", "classe_nome", "area_km2", "qtd_poligonos"},
    "vw_eventos_municipio_ano": {"municipio", "ano", "tipo", "n_eventos", "area_km2"},
    "vw_eventos_municipio": {"municipio", "total_eventos", "area_km2"},
    "vw_queimadas_crescimento_municipio": {
        "municipio", "ano_ini", "ano_fim", "focos_total",
        "focos_ano_ini", "focos_ano_fim", "crescimento_abs", "crescimento_pct",
    },
}

# Métricas conhecidas por tabela: nome lógico -> (agregação, coluna|None).
METRICAS: dict[str, dict[str, tuple[str, str | None]]] = {
    "queimadas": {"focos": ("COUNT", None), "frp_medio": ("AVG", "frp"), "risco_medio": ("AVG", "risco_fogo")},
    "desmatamento_alertas": {"alertas": ("COUNT", None), "area": ("SUM", "area_total_km2")},
    "prodes_desmatamento": {"area": ("SUM", "area_km"), "poligonos": ("COUNT", None)},
    "sicar_imoveis": {"imoveis": ("COUNT", None), "area": ("SUM", "num_area")},
}

# Dimensões de agrupamento por tabela: nome lógico -> expressão SQL.
DIMENSOES: dict[str, dict[str, str]] = {
    "queimadas": {
        "municipio": "municipio", "bioma": "bioma", "satelite": "satelite",
        "ano": "EXTRACT(YEAR FROM data_hora)::int", "mes": "EXTRACT(MONTH FROM data_hora)::int",
    },
    "desmatamento_alertas": {
        "municipio": "municipio", "classe": "classe",
        "ano": "EXTRACT(YEAR FROM data_avistamento)::int",
    },
    "prodes_desmatamento": {"ano": "ano", "classe": "classe_nome", "estado": "estado"},
    "sicar_imoveis": {"municipio": "municipio", "status": "ind_status"},
}


def nomes_permitidos() -> set[str]:
    """Todos os nomes de relação (tabelas + views) válidos no FROM/JOIN."""
    return set(TABELAS_PERMITIDAS) | set(VIEWS_PERMITIDAS)


def colunas_de(nome: str) -> set[str]:
    return TABELAS_PERMITIDAS.get(nome) or VIEWS_PERMITIDAS.get(nome) or set()


def todas_as_colunas() -> set[str]:
    cols: set[str] = set()
    for c in list(TABELAS_PERMITIDAS.values()) + list(VIEWS_PERMITIDAS.values()):
        cols |= c
    return cols


# Frases-âncora em PT-BR para schema linking por embedding (MiniLM).
# Várias âncoras por tabela aumentam o recall (o linker pega a de maior cosseno).
CATALOGO_SEMANTICO: list[dict] = [
    # ---- tabela base (múltiplas âncoras por tabela) ----
    {"frase": "queimadas focos de calor incêndio fogo", "tipo": "tabela", "alvo": "queimadas"},
    {"frase": "queimadas frp potência radiativa do fogo risco de fogo satélite bioma", "tipo": "tabela", "alvo": "queimadas"},
    {"frase": "desmatamento alertas deter supressão de vegetação área desmatada recente", "tipo": "tabela", "alvo": "desmatamento_alertas"},
    {"frase": "desmatamento consolidado anual prodes área desmatada por ano histórico", "tipo": "tabela", "alvo": "prodes_desmatamento"},
    {"frase": "imóveis rurais fazendas car sicar propriedades cadastro ambiental rural", "tipo": "tabela", "alvo": "sicar_imoveis"},
    {"frase": "imóveis status ativo pendente suspenso cancelado área módulos fiscais", "tipo": "tabela", "alvo": "sicar_imoveis"},
    # NOTA: views agregadas (vw_eventos_municipio, vw_queimadas_crescimento_municipio) e o
    # fato de propriedade NÃO entram como âncoras de embedding de propósito — senão "roubam"
    # consultas analíticas normais. Elas são alcançadas só por regex (_caso_especial_view /
    # rota PROPRIEDADE).
    # ---- métricas ----
    {"frase": "quantidade contagem número de ocorrências quantos quantas total de registros", "tipo": "metrica", "alvo": "COUNT"},
    {"frase": "área total somatório soma de área em quilômetros quadrados hectares", "tipo": "metrica", "alvo": "SUM"},
    {"frase": "média valor médio em média", "tipo": "metrica", "alvo": "AVG"},
    # ---- dimensões ----
    {"frase": "por município por cidade cidades", "tipo": "dimensao", "alvo": "municipio"},
    {"frase": "por ano anual ao longo dos anos", "tipo": "dimensao", "alvo": "ano"},
    {"frase": "por mês mensal", "tipo": "dimensao", "alvo": "mes"},
    {"frase": "por bioma cerrado mata atlântica", "tipo": "dimensao", "alvo": "bioma"},
    {"frase": "por classe tipo categoria", "tipo": "dimensao", "alvo": "classe"},
]

CATALOGO_TEXTO = """\
TABELA queimadas (municipio, estado, data_hora TIMESTAMP, bioma, frp NUMERIC, risco_fogo NUMERIC, geom)
TABELA desmatamento_alertas (municipio, classe, data_avistamento DATE, area_total_km2 NUMERIC, geom)
TABELA prodes_desmatamento (estado, ano INT, area_km NUMERIC, classe_nome, geom)
TABELA sicar_imoveis (cod_imovel, municipio, num_area NUMERIC ha, ind_status AT|PE|SU|CA, mod_fiscal, geom)
VIEW vw_desmatamento_municipio (municipio, ano, mes, qtd_alertas, area_km2)
VIEW vw_queimadas_municipio (municipio, ano, mes, qtd_focos, frp_medio, risco_fogo_medio)
VIEW vw_prodes_ano (ano, classe_nome, area_km2, qtd_poligonos)
VIEW vw_eventos_municipio (municipio, total_eventos, area_km2)
VIEW vw_queimadas_crescimento_municipio (municipio, ano_ini, ano_fim, focos_ano_ini, focos_ano_fim, crescimento_abs, crescimento_pct)
TABELA fato_propriedade_ambiental — uma linha por imóvel rural com sinais derivados
  cod_imovel, municipio, area_ha
  focos_recentes_12m, focos_total           contagem de focos de queimada
  alertas_deter_recentes_12m                alertas DETER recentes
  area_impactada_pct                        % da área do imóvel impactada
  dist_ti_km, sobrepoe_ti                   proximidade/sobreposição com terra indígena
  queimadas_anos_distintos_3a               recorrência de queimadas em 3 anos
  fogo_apos_alerta                          focos ocorridos após alerta de desmatamento
  n_fatores_risco                           nº de fatores de risco ativos
  nota_risco, nivel_risco                   risco ambiental (AHP)
"""
