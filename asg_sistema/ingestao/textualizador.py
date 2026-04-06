"""Converte registros estruturados ASG em frases em portugues.
Cada registro vira um documento no corpus para busca semantica.
"""


def textualizar_queimada(registro: dict) -> dict:
    lat = registro.get("latitude", "")
    lon = registro.get("longitude", "")
    texto = (
        f"Foco de queimada detectado pelo satélite {registro.get('satelite', 'N/I')} "
        f"no município de {registro.get('municipio', 'N/I')}, São Paulo, "
        f"em {registro.get('data_hora', 'N/I')}, "
        f"no bioma {registro.get('bioma', 'N/I')}. "
        f"Potência radiativa do fogo (FRP): {registro.get('frp', 'N/I')} MW. "
        f"Risco de fogo: {registro.get('risco_fogo', 'N/I')}. "
        f"Coordenadas: {lat}, {lon}. "
        f"Fonte: INPE/Queimadas."
    )
    return {
        "fonte": "queimadas",
        "tipo_registro": "foco_queimada",
        "municipio": registro.get("municipio", ""),
        "data_referencia": _extrair_data(registro.get("data_hora", "")),
        "texto": texto,
        "metadados_json": {
            "latitude": lat,
            "longitude": lon,
            "satelite": registro.get("satelite", ""),
            "bioma": registro.get("bioma", ""),
            "frp": registro.get("frp", ""),
            "risco_fogo": registro.get("risco_fogo", ""),
        },
    }


def textualizar_terra_indigena(props: dict, bbox: list | None = None) -> dict:
    centroid_lon = None
    centroid_lat = None
    if bbox and len(bbox) == 4:
        centroid_lon = (bbox[0] + bbox[2]) / 2
        centroid_lat = (bbox[1] + bbox[3]) / 2

    texto = (
        f"Terra Indígena {props.get('terrai_nome', 'N/I')}, "
        f"do povo {props.get('etnia_nome', 'N/I')}, "
        f"localizada no município de {props.get('municipio_nome', 'N/I')}, São Paulo. "
        f"Área: {props.get('superficie_perimetro_ha', 'N/I')} hectares. "
        f"Fase: {props.get('fase_ti', 'N/I')}. "
        f"Modalidade: {props.get('modalidade_ti', 'N/I')}. "
        f"Fonte: FUNAI."
    )
    return {
        "fonte": "funai",
        "tipo_registro": "terra_indigena",
        "municipio": props.get("municipio_nome", ""),
        "data_referencia": None,
        "texto": texto,
        "metadados_json": {
            "nome": props.get("terrai_nome", ""),
            "etnia": props.get("etnia_nome", ""),
            "area_ha": props.get("superficie_perimetro_ha", ""),
            "fase": props.get("fase_ti", ""),
            "centroid_lon": centroid_lon,
            "centroid_lat": centroid_lat,
        },
    }


def textualizar_desmatamento(props: dict) -> dict:
    uc_info = ""
    if props.get("uc"):
        uc_info = f" dentro da unidade de conservação {props['uc']}"
    texto = (
        f"Alerta de desmatamento ({props.get('classname', 'N/I')}) detectado "
        f"no município de {props.get('municipality', 'N/I')}, São Paulo, "
        f"em {props.get('view_date', 'N/I')}, "
        f"pelo satélite {props.get('satellite', 'N/I')}. "
        f"Área total afetada: {props.get('areatotalkm', 'N/I')} km²"
        f"{uc_info}. "
        f"Fonte: INPE/DETER."
    )
    return {
        "fonte": "deter",
        "tipo_registro": "alerta_desmatamento",
        "municipio": props.get("municipality", ""),
        "data_referencia": _extrair_data(props.get("view_date", "")),
        "texto": texto,
        "metadados_json": {
            "classe": props.get("classname", ""),
            "area_km2": props.get("areatotalkm", ""),
            "satelite": props.get("satellite", ""),
        },
    }


def textualizar_unidade_conservacao(registro: dict) -> dict:
    nome = _corrigir_encoding(registro.get("nome_uc", registro.get("NOME", "")))
    categoria = _corrigir_encoding(registro.get("CATEGORI3", registro.get("categoria", "")))
    grupo = _corrigir_encoding(registro.get("GRUPO", registro.get("grupo", "")))
    esfera = _corrigir_encoding(registro.get("ESFERA", registro.get("esfera", "")))
    municipio = _corrigir_encoding(registro.get("MUNICIPIO", registro.get("municipio", "")))
    uf = _corrigir_encoding(registro.get("UF", registro.get("uf", "")))
    area = registro.get("AREA_HA", registro.get("area_ha", ""))

    texto = (
        f"Unidade de conservação {nome}, "
        f"categoria {categoria}, "
        f"grupo {grupo}, "
        f"esfera {esfera}, "
        f"localizada em {municipio}, {uf}. "
        f"Área: {area} hectares. "
        f"Fonte: MMA/ICMBio."
    )
    return {
        "fonte": "icmbio",
        "tipo_registro": "unidade_conservacao",
        "municipio": municipio,
        "data_referencia": None,
        "texto": texto,
        "metadados_json": {
            "nome": nome,
            "categoria": categoria,
            "grupo": grupo,
            "esfera": esfera,
            "area_ha": area,
            "centroid_lon": registro.get("centroid_lon"),
            "centroid_lat": registro.get("centroid_lat"),
        },
    }


def textualizar_prodes(props: dict) -> dict:
    texto = (
        f"Desmatamento anual detectado pelo PRODES/INPE "
        f"no bioma {props.get('source', 'N/I')}, "
        f"classe {props.get('class_name', 'N/I')}, "
        f"em {props.get('image_date', 'N/I')} (ano {props.get('year', 'N/I')}). "
        f"Área desmatada: {props.get('area_km', 'N/I')} km². "
        f"Satélite: {props.get('satellite', 'N/I')}, sensor: {props.get('sensor', 'N/I')}. "
        f"Fonte: INPE/PRODES."
    )
    return {
        "fonte": "prodes",
        "tipo_registro": "desmatamento_prodes",
        "municipio": "",
        "data_referencia": _extrair_data(props.get("image_date", "")),
        "texto": texto,
        "metadados_json": {
            "uid": props.get("uid", ""),
            "ano": props.get("year", ""),
            "area_km": props.get("area_km", ""),
            "classe": props.get("class_name", ""),
            "bioma_fonte": props.get("source", ""),
            "satelite": props.get("satellite", ""),
        },
    }


def textualizar_quilombola(registro: dict) -> dict:
    comunidade = registro.get("COMUNIDADE", "")
    municipio = registro.get("MUNICÍPIO", registro.get("MUNICIPIO", ""))
    ano = registro.get("ANO CERTIFICAÇÃO", registro.get("ANO CERTIFICACAO", ""))
    processo = registro.get("Nº PROCESSO NA FCP", "")
    texto = (
        f"Comunidade quilombola {comunidade}, "
        f"localizada no município de {municipio}, São Paulo. "
        f"Certificada pela Fundação Cultural Palmares em {ano}. "
        f"Processo FCP: {processo}. "
        f"Fonte: Fundação Cultural Palmares."
    )
    return {
        "fonte": "palmares",
        "tipo_registro": "comunidade_quilombola",
        "municipio": municipio,
        "data_referencia": None,
        "texto": texto,
        "metadados_json": {
            "comunidade": comunidade,
            "ano_certificacao": str(ano),
            "processo_fcp": processo,
            "processo_incra": registro.get("Nº PROCESSO INCRA", ""),
        },
    }


def textualizar_sicar(props: dict) -> dict:
    status_map = {"AT": "ativo", "PE": "pendente", "SU": "suspenso", "CA": "cancelado"}
    tipo_map = {"IRU": "imóvel rural", "ICA": "imóvel de categoria especial"}
    status = status_map.get(props.get("ind_status", ""), props.get("ind_status", "N/I"))
    tipo = tipo_map.get(props.get("ind_tipo", ""), props.get("ind_tipo", "N/I"))
    texto = (
        f"Imóvel rural cadastrado no SICAR/CAR com código {props.get('cod_imovel', 'N/I')}, "
        f"classificado como {tipo}, situação {status}, "
        f"localizado no município de {props.get('municipio', 'N/I')}, São Paulo. "
        f"Área total: {props.get('num_area', 'N/I')} hectares "
        f"({props.get('mod_fiscal', 'N/I')} módulos fiscais). "
        f"Condição: {props.get('des_condic', 'N/I')}. "
        f"Cadastro criado em {props.get('dat_criaca', 'N/I')}, "
        f"atualizado em {props.get('dat_atuali', 'N/I')}. "
        f"Fonte: SICAR — Cadastro Ambiental Rural."
    )
    return {
        "fonte": "sicar",
        "tipo_registro": "imovel_rural",
        "municipio": props.get("municipio", ""),
        "data_referencia": _converter_data_sicar(props.get("dat_atuali", "")),
        "texto": texto,
        "metadados_json": {
            "cod_imovel": props.get("cod_imovel", ""),
            "ind_status": props.get("ind_status", ""),
            "ind_tipo": props.get("ind_tipo", ""),
            "num_area": props.get("num_area"),
            "mod_fiscal": props.get("mod_fiscal"),
            "des_condic": props.get("des_condic", ""),
        },
    }


def _converter_data_sicar(valor: str) -> str | None:
    """Converte DD/MM/YYYY para YYYY-MM-DD."""
    if not valor:
        return None
    try:
        partes = str(valor).strip().split("/")
        if len(partes) == 3:
            return f"{partes[2]}-{partes[1]}-{partes[0]}"
    except Exception:
        pass
    return None


def _extrair_data(valor: str) -> str | None:
    if not valor:
        return None
    return str(valor)[:10]


def _corrigir_encoding(texto: str) -> str:
    if not texto or not isinstance(texto, str):
        return str(texto) if texto else ""
    try:
        return texto.encode("latin-1").decode("utf-8")
    except (UnicodeDecodeError, UnicodeEncodeError):
        return texto
