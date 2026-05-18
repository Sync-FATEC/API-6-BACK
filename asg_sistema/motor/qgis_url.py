"""Constroi a URL do endpoint /api/geo correspondente a uma intencao + entidades.

Usado para anexar uma `qgis_url` em cada resposta de /api/consulta, permitindo
que o usuario abra a mesma consulta diretamente no QGIS.
"""

from __future__ import annotations

import re
from urllib.parse import urlencode

# Mapa intencao -> path do endpoint /api/geo
_INTENCAO_PARA_PATH: dict[str, str] = {
    "consultar_queimadas": "/api/geo/queimadas",
    "consultar_desmatamento": "/api/geo/desmatamento",
    "consultar_terra_indigena": "/api/geo/terras-indigenas",
    "consultar_unidade_conservacao": "/api/geo/unidades-conservacao",
    "consultar_quilombola": "/api/geo/quilombolas",
    "consultar_prodes": "/api/geo/prodes",
    "consultar_imovel_rural": "/api/geo/sicar",
}

# Filtros aceitos por cada path (espelho do catalogo).
_FILTROS_POR_PATH: dict[str, set[str]] = {
    "/api/geo/queimadas": {"municipio", "data_inicio", "data_fim", "limite"},
    "/api/geo/desmatamento": {"municipio", "data_inicio", "data_fim", "limite"},
    "/api/geo/terras-indigenas": {"municipio", "limite"},
    "/api/geo/unidades-conservacao": {"municipio", "limite"},
    "/api/geo/quilombolas": {"municipio", "limite"},
    "/api/geo/prodes": {"ano", "limite"},
    "/api/geo/sicar": {"cod_imovel", "municipio", "limite"},
}


def construir_qgis_url(
    intencao: str,
    entidades: dict,
    base_url: str = "",
) -> str | None:
    """Constroi a URL do /api/geo correspondente.

    Retorna None se a intencao nao tem endpoint geo direto (ex: resumo_municipal).
    """
    path = _INTENCAO_PARA_PATH.get(intencao)
    if not path:
        return None

    permitidos = _FILTROS_POR_PATH.get(path, set())
    params: dict[str, str] = {}

    municipios = entidades.get("municipios") or []
    if "municipio" in permitidos and municipios:
        primeiro = str(municipios[0]).split(",")[0].strip()
        primeiro = re.sub(r"\s*\([A-Z]{2}\)\s*$", "", primeiro).strip()
        if primeiro:
            params["municipio"] = primeiro

    periodo = entidades.get("periodo") or {}
    if "data_inicio" in permitidos and periodo.get("inicio"):
        params["data_inicio"] = str(periodo["inicio"])
    if "data_fim" in permitidos and periodo.get("fim"):
        params["data_fim"] = str(periodo["fim"])

    cod = entidades.get("cod_imovel")
    if "cod_imovel" in permitidos and cod:
        params["cod_imovel"] = str(cod).strip().upper()

    if "ano" in permitidos and periodo.get("inicio"):
        try:
            params["ano"] = str(int(str(periodo["inicio"])[:4]))
        except (ValueError, TypeError):
            pass

    query = urlencode(params)
    base = base_url.rstrip("/") if base_url else ""
    return f"{base}{path}?{query}" if query else f"{base}{path}"
