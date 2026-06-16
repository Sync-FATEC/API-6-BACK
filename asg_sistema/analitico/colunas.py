"""Catálogo semântico de COLUNAS + column-linking determinístico (leve).

Mapeia termos da pergunta para colunas filtráveis/ordenáveis de cada tabela, via
sinônimos PT-BR (substring normalizada). Não usa modelo — leve p/ EC2 pequena.
Permite filtros/ordenação genéricos sobre QUALQUER coluna sem código por pergunta.
"""

from asg_sistema.analitico.texto import normalizar

# tabela -> { coluna: {"tipo": num|texto|data|bool|enum, "sin": [sinônimos]} }
COLUNAS_SEMANTICAS: dict[str, dict[str, dict]] = {
    "queimadas": {
        "frp": {"tipo": "num", "sin": ["frp", "potencia radiativa", "potencia do fogo", "intensidade do fogo", "intensidade"]},
        "risco_fogo": {"tipo": "num", "sin": ["risco de fogo", "risco fogo"]},
        "bioma": {"tipo": "texto", "sin": ["bioma"]},
        "satelite": {"tipo": "texto", "sin": ["satelite"]},
        "municipio": {"tipo": "texto", "sin": ["municipio", "cidade"]},
        "data_hora": {"tipo": "data", "sin": ["data", "data do foco"]},
    },
    "desmatamento_alertas": {
        "area_total_km2": {"tipo": "num", "sin": ["area", "area desmatada", "area do alerta", "km2", "tamanho"]},
        "classe": {"tipo": "texto", "sin": ["classe", "tipo de alerta"]},
        "municipio": {"tipo": "texto", "sin": ["municipio", "cidade"]},
        "data_avistamento": {"tipo": "data", "sin": ["data", "data do alerta", "avistamento"]},
    },
    "prodes_desmatamento": {
        "area_km": {"tipo": "num", "sin": ["area", "area desmatada", "km2", "tamanho"]},
        "ano": {"tipo": "num", "sin": ["ano"]},
        "classe_nome": {"tipo": "texto", "sin": ["classe", "tipo"]},
        "estado": {"tipo": "texto", "sin": ["estado", "uf"]},
    },
    "sicar_imoveis": {
        "num_area": {"tipo": "num", "sin": ["area", "tamanho", "hectares", "ha", "area do imovel", "tamanho do imovel"]},
        "mod_fiscal": {"tipo": "num", "sin": ["modulos fiscais", "modulo fiscal", "modulos"]},
        "ind_status": {"tipo": "enum", "sin": ["status", "situacao", "regular", "ativo", "pendente", "suspenso", "cancelado"]},
        "municipio": {"tipo": "texto", "sin": ["municipio", "cidade"]},
        "nom_tema": {"tipo": "texto", "sin": ["nome", "nome do imovel", "tema"]},
        "dat_criacao": {"tipo": "data", "sin": ["data de cadastro", "cadastro", "data de criacao"]},
    },
    "terras_indigenas": {
        "area_ha": {"tipo": "num", "sin": ["area", "tamanho", "hectares"]},
        "etnia": {"tipo": "texto", "sin": ["etnia", "povo"]},
        "fase": {"tipo": "texto", "sin": ["fase", "situacao"]},
        "municipio": {"tipo": "texto", "sin": ["municipio", "cidade"]},
        "nome": {"tipo": "texto", "sin": ["nome"]},
    },
    "unidades_conservacao": {
        "area_ha": {"tipo": "num", "sin": ["area", "tamanho", "hectares"]},
        "categoria": {"tipo": "texto", "sin": ["categoria", "tipo"]},
        "grupo": {"tipo": "texto", "sin": ["grupo", "protecao integral", "uso sustentavel"]},
        "esfera": {"tipo": "texto", "sin": ["esfera", "federal", "estadual", "municipal"]},
        "municipio": {"tipo": "texto", "sin": ["municipio", "cidade"]},
        "nome": {"tipo": "texto", "sin": ["nome"]},
    },
    "comunidades_quilombolas": {
        "ano_certificacao": {"tipo": "num", "sin": ["ano de certificacao", "certificacao", "ano"]},
        "regiao": {"tipo": "texto", "sin": ["regiao"]},
        "municipio": {"tipo": "texto", "sin": ["municipio", "cidade"]},
        "comunidade": {"tipo": "texto", "sin": ["comunidade", "nome"]},
    },
    "fato_propriedade_ambiental": {
        "nota_risco": {"tipo": "num", "sin": ["risco", "nota de risco", "score", "score ahp", "risco ambiental"]},
        "n_fatores_risco": {"tipo": "num", "sin": ["fatores de risco", "fatores", "numero de fatores"]},
        "focos_recentes_12m": {"tipo": "num", "sin": ["focos", "focos recentes", "queimadas", "incendios"]},
        "focos_total": {"tipo": "num", "sin": ["focos totais", "total de focos"]},
        "alertas_deter_recentes_12m": {"tipo": "num", "sin": ["alertas", "alertas de desmatamento", "alertas recentes", "deter"]},
        "area_impactada_pct": {"tipo": "num", "sin": ["percentual de area impactada", "area impactada", "percentual impactado"]},
        "area_ha": {"tipo": "num", "sin": ["area", "tamanho", "hectares"]},
        "dist_ti_km": {"tipo": "num", "sin": ["distancia da terra indigena", "distancia ti"]},
        "municipio": {"tipo": "texto", "sin": ["municipio", "cidade"]},
    },
}


def ligar_coluna(termo: str, tabela: str) -> str | None:
    """Retorna a coluna cujos sinônimos melhor casam com o termo (substring normalizada)."""
    t = normalizar(termo)
    if not t or tabela not in COLUNAS_SEMANTICAS:
        return None
    melhor, melhor_len = None, 0
    for coluna, meta in COLUNAS_SEMANTICAS[tabela].items():
        for s in meta["sin"]:
            sn = normalizar(s)
            if sn and sn in t and len(sn) > melhor_len:
                melhor, melhor_len = coluna, len(sn)
    return melhor


def tipo_coluna(tabela: str, coluna: str) -> str | None:
    return (COLUNAS_SEMANTICAS.get(tabela, {}).get(coluna) or {}).get("tipo")


def colunas_numericas(tabela: str) -> dict[str, dict]:
    return {c: m for c, m in COLUNAS_SEMANTICAS.get(tabela, {}).items() if m["tipo"] == "num"}
