"""Carrega dados dos JSONs coletados para o PostgreSQL.
Insere nas tabelas estruturadas e gera o corpus textualizado.
"""

import json
import logging
from datetime import datetime
from pathlib import Path

from asg_sistema.db.conexao import executar_sql, executar_consulta, executar_sql_many
from asg_sistema.ingestao.textualizador import (
    textualizar_queimada,
    textualizar_terra_indigena,
    textualizar_desmatamento,
    textualizar_unidade_conservacao,
    textualizar_prodes,
    textualizar_quilombola,
    textualizar_sicar,
)

logger = logging.getLogger(__name__)


def carregar_tudo(caminho_dados: Path):
    logger.info("Iniciando carga de dados ASG...")
    _carregar_queimadas(caminho_dados / "queimadas_focos_sp.json")
    _carregar_funai(caminho_dados / "funai_terras_indigenas_sp.json")
    _carregar_deter(caminho_dados / "deter_desmatamento_sp.json")
    _carregar_ucs(caminho_dados / "unidades_conservacao_sp.json")
    _carregar_prodes(caminho_dados / "prodes_desmatamento_sp.json")
    _carregar_palmares(caminho_dados / "palmares_quilombolas_sp.json")
    _carregar_sicar(caminho_dados / "geojson" / "SP_AREA_IMOVEL.geojson")
    logger.info("Carga finalizada.")


def _inserir_fonte(metadados: dict) -> int:
    resultado = executar_consulta(
        """INSERT INTO fontes (nome, descricao, url_origem, data_coleta, total_registros, escopo)
        VALUES (:nome, :descricao, :url, :data, :total, :escopo)
        RETURNING id""",
        {
            "nome": metadados.get("fonte", ""),
            "descricao": metadados.get("descricao", ""),
            "url": metadados.get("url_origem", ""),
            "data": metadados.get("data_coleta"),
            "total": metadados.get("total_registros", 0),
            "escopo": metadados.get("escopo", "Estado de São Paulo"),
        },
    )
    return resultado[0]["id"]


def _inserir_corpus(doc: dict):
    executar_sql(
        """INSERT INTO corpus_asg
        (fonte, tipo_registro, municipio, data_referencia, texto, metadados_json)
        VALUES (:fonte, :tipo, :municipio, :data_ref, :texto, :meta)""",
        {
            "fonte": doc["fonte"],
            "tipo": doc["tipo_registro"],
            "municipio": doc["municipio"],
            "data_ref": doc["data_referencia"],
            "texto": doc["texto"],
            "meta": json.dumps(doc["metadados_json"], ensure_ascii=False),
        },
    )


def _carregar_queimadas(caminho: Path):
    if not caminho.exists():
        logger.warning("Arquivo de queimadas nao encontrado: %s", caminho)
        return

    with open(caminho, "r", encoding="utf-8") as f:
        dados = json.load(f)

    fonte_id = _inserir_fonte(dados.get("metadados", {}))
    registros = dados.get("dados", [])
    logger.info("Carregando %d focos de queimada...", len(registros))

    for i, reg in enumerate(registros):
        lat = _para_float(reg.get("latitude"))
        lon = _para_float(reg.get("longitude"))

        executar_sql(
            """INSERT INTO queimadas
            (fonte_id, latitude, longitude, data_hora, satelite, municipio,
             estado, bioma, frp, risco_fogo, precipitacao, geom)
            VALUES (:fid, :lat, :lon, :dt, :sat, :mun, :est, :bio, :frp,
                    :risco, :prec,
                    CASE WHEN :lat IS NOT NULL AND :lon IS NOT NULL
                         THEN ST_SetSRID(ST_MakePoint(:lon, :lat), 4674)
                         ELSE NULL END)""",
            {
                "fid": fonte_id,
                "lat": lat,
                "lon": lon,
                "dt": reg.get("data_hora"),
                "sat": reg.get("satelite", ""),
                "mun": reg.get("municipio", ""),
                "est": reg.get("estado", ""),
                "bio": reg.get("bioma", ""),
                "frp": _para_float(reg.get("frp")),
                "risco": _para_float(reg.get("risco_fogo")),
                "prec": _para_float(reg.get("precipitacao")),
            },
        )

        doc = textualizar_queimada(reg)
        _inserir_corpus(doc)

        if (i + 1) % 2000 == 0:
            logger.info("  %d/%d queimadas inseridas", i + 1, len(registros))

    logger.info("Queimadas: %d registros carregados", len(registros))


def _carregar_funai(caminho: Path):
    if not caminho.exists():
        logger.warning("Arquivo FUNAI nao encontrado: %s", caminho)
        return

    with open(caminho, "r", encoding="utf-8") as f:
        dados = json.load(f)

    fonte_id = _inserir_fonte(dados.get("metadados", {}))
    features = dados.get("features", [])
    logger.info("Carregando %d terras indigenas...", len(features))

    for feat in features:
        props = feat.get("properties", {})
        geom_json = json.dumps(feat.get("geometry", {}))

        executar_sql(
            """INSERT INTO terras_indigenas
            (fonte_id, codigo, nome, etnia, municipio, uf, area_ha, fase, modalidade, geom)
            VALUES (:fid, :cod, :nome, :etnia, :mun, :uf, :area, :fase, :mod,
                    ST_SetSRID(ST_GeomFromGeoJSON(:geom), 4674))""",
            {
                "fid": fonte_id,
                "cod": props.get("terrai_codigo"),
                "nome": props.get("terrai_nome", ""),
                "etnia": props.get("etnia_nome", ""),
                "mun": props.get("municipio_nome", ""),
                "uf": props.get("uf_sigla", "SP"),
                "area": props.get("superficie_perimetro_ha"),
                "fase": props.get("fase_ti", ""),
                "mod": props.get("modalidade_ti", ""),
                "geom": geom_json,
            },
        )

        bbox = feat.get("bbox")
        doc = textualizar_terra_indigena(props, bbox=bbox)
        _inserir_corpus(doc)

    logger.info("FUNAI: %d registros carregados", len(features))


def _carregar_deter(caminho: Path):
    if not caminho.exists():
        logger.warning("Arquivo DETER nao encontrado: %s", caminho)
        return

    with open(caminho, "r", encoding="utf-8") as f:
        dados = json.load(f)

    fonte_id = _inserir_fonte(dados.get("metadados", {}))
    features = dados.get("features", [])
    logger.info("Carregando %d alertas de desmatamento...", len(features))

    for feat in features:
        props = feat.get("properties", {})
        geom = feat.get("geometry")
        geom_json = json.dumps(geom) if geom else None

        executar_sql(
            """INSERT INTO desmatamento_alertas
            (fonte_id, classe, municipio, uf, data_avistamento, sensor,
             satelite, area_total_km2, area_uc_km2, nome_uc, geom)
            VALUES (:fid, :cls, :mun, :uf, :dt, :sensor, :sat,
                    :area, :area_uc, :uc,
                    CASE WHEN CAST(:geom AS TEXT) IS NOT NULL
                         THEN ST_SetSRID(ST_GeomFromGeoJSON(CAST(:geom AS TEXT)), 4674)
                         ELSE NULL END)""",
            {
                "fid": fonte_id,
                "cls": props.get("classname", ""),
                "mun": props.get("municipality", ""),
                "uf": props.get("uf", "SP"),
                "dt": props.get("view_date"),
                "sensor": props.get("sensor", ""),
                "sat": props.get("satellite", ""),
                "area": _para_float(props.get("areatotalkm")),
                "area_uc": _para_float(props.get("areauckm")),
                "uc": props.get("uc", ""),
                "geom": geom_json,
            },
        )

        doc = textualizar_desmatamento(props)
        _inserir_corpus(doc)

    logger.info("DETER: %d registros carregados", len(features))


def _carregar_ucs(caminho: Path):
    if not caminho.exists():
        logger.warning("Arquivo UCs nao encontrado: %s", caminho)
        return

    with open(caminho, "r", encoding="utf-8") as f:
        dados = json.load(f)

    fonte_id = _inserir_fonte(dados.get("metadados", {}))
    registros = dados.get("dados", [])
    logger.info("Carregando %d unidades de conservacao...", len(registros))

    for reg in registros:
        executar_sql(
            """INSERT INTO unidades_conservacao
            (fonte_id, nome, categoria, grupo, esfera, uf, municipio, area_ha)
            VALUES (:fid, :nome, :cat, :grupo, :esfera, :uf, :mun, :area)""",
            {
                "fid": fonte_id,
                "nome": reg.get("NOME", reg.get("nome", "")),
                "cat": reg.get("CATEGORI3", reg.get("categoria", "")),
                "grupo": reg.get("GRUPO", reg.get("grupo", "")),
                "esfera": reg.get("ESFERA", reg.get("esfera", "")),
                "uf": reg.get("UF", reg.get("uf", "")),
                "mun": reg.get("MUNICIPIO", reg.get("municipio", "")),
                "area": _para_float(
                    reg.get("AREA_HA", reg.get("area_ha"))
                ),
            },
        )

        doc = textualizar_unidade_conservacao(reg)
        _inserir_corpus(doc)

    logger.info("UCs: %d registros carregados", len(registros))


def _carregar_prodes(caminho: Path):
    if not caminho.exists():
        logger.warning("Arquivo PRODES nao encontrado: %s", caminho)
        return

    with open(caminho, "r", encoding="utf-8") as f:
        dados = json.load(f)

    fonte_id = _inserir_fonte(dados.get("metadados", {}))
    features = dados.get("features", [])
    logger.info("Carregando %d registros PRODES...", len(features))

    AMOSTRA_CORPUS = 50  # insere no corpus 1 a cada N registros

    for i, feat in enumerate(features):
        props = feat.get("properties", {})
        geom = feat.get("geometry")
        geom_json = json.dumps(geom) if geom else None

        executar_sql(
            """INSERT INTO prodes_desmatamento
            (fonte_id, uid, estado, classe_principal, classe_nome,
             data_imagem, ano, area_km, fonte_bioma, satelite, sensor, geom)
            VALUES (:fid, :uid, :estado, :cls_princ, :cls_nome,
                    :dt, :ano, :area, :bioma, :sat, :sensor,
                    CASE WHEN CAST(:geom AS TEXT) IS NOT NULL
                         THEN ST_SetSRID(ST_GeomFromGeoJSON(CAST(:geom AS TEXT)), 4674)
                         ELSE NULL END)""",
            {
                "fid": fonte_id,
                "uid": props.get("uid"),
                "estado": props.get("state", "SP"),
                "cls_princ": props.get("main_class", ""),
                "cls_nome": props.get("class_name", ""),
                "dt": props.get("image_date"),
                "ano": props.get("year"),
                "area": _para_float(props.get("area_km")),
                "bioma": props.get("source", ""),
                "sat": props.get("satellite", ""),
                "sensor": props.get("sensor", ""),
                "geom": geom_json,
            },
        )

        if i % AMOSTRA_CORPUS == 0:
            doc = textualizar_prodes(props)
            _inserir_corpus(doc)

        if (i + 1) % 5000 == 0:
            logger.info("  %d/%d PRODES inseridos", i + 1, len(features))

    corpus_total = len(features) // AMOSTRA_CORPUS + 1
    logger.info("PRODES: %d registros na tabela, %d amostras no corpus", len(features), corpus_total)


def _carregar_palmares(caminho: Path):
    if not caminho.exists():
        logger.warning("Arquivo Palmares nao encontrado: %s", caminho)
        return

    with open(caminho, "r", encoding="utf-8") as f:
        dados = json.load(f)

    fonte_id = _inserir_fonte(dados.get("metadados", {}))
    registros = dados.get("dados", [])
    logger.info("Carregando %d comunidades quilombolas...", len(registros))

    for reg in registros:
        municipio = reg.get("MUNICÍPIO", reg.get("MUNICIPIO", ""))
        ano_str = reg.get("ANO CERTIFICAÇÃO", reg.get("ANO CERTIFICACAO", ""))
        ano = None
        try:
            ano = int(ano_str) if ano_str and str(ano_str).strip() else None
        except (ValueError, TypeError):
            ano = None

        executar_sql(
            """INSERT INTO comunidades_quilombolas
            (fonte_id, municipio, uf, comunidade, codigo_ibge,
             processo_fcp, ano_certificacao, processo_incra, regiao)
            VALUES (:fid, :mun, :uf, :com, :ibge, :proc, :ano, :incra, :regiao)""",
            {
                "fid": fonte_id,
                "mun": municipio,
                "uf": reg.get(" ", reg.get("UF", "SP")).strip(),
                "com": reg.get("COMUNIDADE", ""),
                "ibge": reg.get("CÓDIGO DO IBGE", reg.get("CODIGO DO IBGE", "")),
                "proc": reg.get("Nº PROCESSO NA FCP", ""),
                "ano": ano,
                "incra": reg.get("Nº PROCESSO INCRA", ""),
                "regiao": reg.get(" REGIÃO", reg.get(" REGIAO", "")).strip(),
            },
        )

        doc = textualizar_quilombola(reg)
        _inserir_corpus(doc)

    logger.info("Palmares: %d registros carregados", len(registros))


def _carregar_sicar(caminho_geojson: Path):
    if not caminho_geojson.exists():
        logger.warning("GeoJSON do SICAR nao encontrado: %s", caminho_geojson)
        return

    with open(caminho_geojson, encoding="utf-8") as f:
        data = json.load(f)

    features = data.get("features", [])
    total = len(features)
    logger.info("Carregando %d imoveis rurais (SICAR)...", total)

    fonte_id = _inserir_fonte({
        "fonte": f"SICAR - {caminho_geojson.stem}",
        "descricao": "Cadastro Ambiental Rural — polígonos do estado de SP",
        "url_origem": "https://consultapublica.car.gov.br/publico/estados/downloads",
        "data_coleta": datetime.now().isoformat(),
        "total_registros": total,
        "escopo": "Estado de São Paulo",
    })

    sql = """
        INSERT INTO sicar_imoveis (
            fonte_id, cod_imovel, cod_tema, nom_tema,
            ind_status, ind_tipo, des_condic,
            municipio, cod_estado, num_area, mod_fiscal,
            dat_criacao, dat_atualizacao, geom
        ) VALUES (
            :fid, :cod_imovel, :cod_tema, :nom_tema,
            :ind_status, :ind_tipo, :des_condic,
            :municipio, :cod_estado, :num_area, :mod_fiscal,
            :dat_criacao, :dat_atualizacao,
            CASE WHEN CAST(:geom AS TEXT) IS NOT NULL
                 THEN ST_SetSRID(ST_GeomFromGeoJSON(CAST(:geom AS TEXT)), 4674)
                 ELSE NULL END
        )
    """

    BATCH_SIZE = 1000
    AMOSTRA_CORPUS = 50
    batch = []
    inseridos = 0

    for i, feat in enumerate(features):
        props = feat.get("properties") or {}
        geom = feat.get("geometry")
        batch.append({
            "fid": fonte_id,
            "cod_imovel": props.get("cod_imovel"),
            "cod_tema": props.get("cod_tema"),
            "nom_tema": props.get("nom_tema"),
            "ind_status": props.get("ind_status"),
            "ind_tipo": props.get("ind_tipo"),
            "des_condic": props.get("des_condic"),
            "municipio": props.get("municipio"),
            "cod_estado": props.get("cod_estado"),
            "num_area": _para_float(props.get("num_area")),
            "mod_fiscal": _para_float(props.get("mod_fiscal")),
            "dat_criacao": props.get("dat_criaca"),
            "dat_atualizacao": props.get("dat_atuali"),
            "geom": json.dumps(geom) if geom else None,
        })

        if i % AMOSTRA_CORPUS == 0:
            doc = textualizar_sicar(props)
            _inserir_corpus(doc)

        if len(batch) >= BATCH_SIZE:
            executar_sql_many(sql, batch)
            inseridos += len(batch)
            batch = []
            logger.info("  %d/%d imoveis inseridos", inseridos, total)

    if batch:
        executar_sql_many(sql, batch)
        inseridos += len(batch)

    corpus_total = total // AMOSTRA_CORPUS + 1
    logger.info("SICAR: %d registros na tabela, %d amostras no corpus", inseridos, corpus_total)


def _para_float(valor) -> float | None:
    if valor is None or valor == "":
        return None
    try:
        return float(valor)
    except (ValueError, TypeError):
        return None
