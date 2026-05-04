"""Carrega dados dos JSONs coletados para o PostgreSQL.
Insere nas tabelas estruturadas e gera o corpus textualizado de forma incremental.
"""

import json
import logging
import hashlib
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


def carregar_tudo(caminho_dados: Path, entidades: list[str] = None):
    if entidades is None:
        entidades = ["tudo"]
        
    logger.info(f"Iniciando carga ASG (Entidades: {entidades})...")
    
    _garantir_coluna_uf_corpus()

    if "tudo" in entidades or "queimadas" in entidades:
        _carregar_queimadas(caminho_dados / "queimadas_focos_sp.json")
        
    if "tudo" in entidades or "terras_indigenas" in entidades:
        _carregar_funai(caminho_dados / "funai_terras_indigenas_sp.json")
        
    if "tudo" in entidades or "desmatamentos" in entidades:
        _carregar_deter(caminho_dados / "deter_desmatamento_sp.json")
        _carregar_prodes(caminho_dados / "prodes_desmatamento_sp.json")
        
    if "tudo" in entidades or "unidades_conservacao" in entidades:
        _carregar_ucs(caminho_dados / "unidades_conservacao_sp.json")
        
    if "tudo" in entidades or "quilombos" in entidades:
        _carregar_palmares(caminho_dados / "palmares_quilombolas_sp.json")
        
    if "tudo" in entidades or "sicar" in entidades:
        _carregar_sicar(caminho_dados / "geojson" / "SP_AREA_IMOVEL.geojson")

    logger.info("Carga finalizada.")


def _inserir_fonte(metadados: dict) -> int:
    nome = metadados.get("fonte", "")
    payload = {
        "nome": nome,
        "descricao": metadados.get("descricao", ""),
        "url": metadados.get("url_origem", ""),
        "data": metadados.get("data_coleta"),
        "total": metadados.get("total_registros", 0),
        "escopo": metadados.get("escopo", "Estado de São Paulo"),
    }
    existente = executar_consulta(
        "SELECT id FROM fontes WHERE nome = :nome ORDER BY id LIMIT 1",
        {"nome": nome},
    )
    if existente:
        executar_sql(
            """UPDATE fontes
               SET descricao = :descricao,
                   url_origem = :url,
                   data_coleta = :data,
                   total_registros = :total,
                   escopo = :escopo
               WHERE id = :id""",
            {**payload, "id": existente[0]["id"]},
        )
        return existente[0]["id"]

    resultado = executar_consulta(
        """INSERT INTO fontes (nome, descricao, url_origem, data_coleta, total_registros, escopo)
           VALUES (:nome, :descricao, :url, :data, :total, :escopo)
           RETURNING id""",
        payload,
    )
    return resultado[0]["id"]


def _inserir_corpus(doc: dict):
    uf_sigla = _normalizar_uf(doc.get("uf_sigla"))
    if not _eh_sp(uf_sigla):
        raise ValueError("uf_sigla ausente ou invalida no corpus_asg (esperado: SP)")

    conteudo_base = f"{doc['tipo_registro']}_{doc['municipio']}_{doc['texto']}"
    hash_reg = hashlib.md5(conteudo_base.encode('utf-8')).hexdigest()

    executar_sql(
        """INSERT INTO corpus_asg
        (fonte, tipo_registro, uf_sigla, municipio, data_referencia, texto, metadados_json, hash_registro)
        VALUES (:fonte, :tipo, :uf_sigla, :municipio, :data_ref, :texto, :meta, :hash_reg)
        ON CONFLICT (hash_registro) DO UPDATE
        SET fonte = EXCLUDED.fonte,
            tipo_registro = EXCLUDED.tipo_registro,
            uf_sigla = EXCLUDED.uf_sigla,
            municipio = EXCLUDED.municipio,
            data_referencia = EXCLUDED.data_referencia,
            texto = EXCLUDED.texto,
            metadados_json = EXCLUDED.metadados_json,
            embedding = NULL""",
        {
            "fonte": doc["fonte"],
            "tipo": doc["tipo_registro"],
            "uf_sigla": uf_sigla,
            "municipio": doc["municipio"],
            "data_ref": doc["data_referencia"],
            "texto": doc["texto"],
            "meta": json.dumps(doc["metadados_json"], ensure_ascii=False),
            "hash_reg": hash_reg
        },
    )


def _garantir_coluna_uf_corpus():
    executar_sql("ALTER TABLE corpus_asg ADD COLUMN IF NOT EXISTS uf_sigla VARCHAR(5)")
    executar_sql("UPDATE corpus_asg SET uf_sigla = 'SP' WHERE uf_sigla IS NULL OR TRIM(uf_sigla) = ''")
    try:
        executar_sql("ALTER TABLE corpus_asg ALTER COLUMN uf_sigla SET NOT NULL")
    except Exception:
        pass
    executar_sql("CREATE INDEX IF NOT EXISTS idx_corpus_uf_sigla ON corpus_asg(uf_sigla)")


def _normalizar_uf(valor: str | None) -> str:
    if not valor:
        return ""
    texto = str(valor).strip()
    try:
        texto = texto.encode("latin-1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        pass
    return texto.upper()


def _eh_sp(valor: str | None) -> bool:
    uf = _normalizar_uf(valor)
    if not uf:
        return False

    partes = [p.strip() for p in uf.replace(";", ",").replace("/", ",").split(",") if p.strip()]
    return any(p in {"SP", "SAO PAULO", "SÃO PAULO"} for p in partes)


def _eh_cod_estado_sp(valor) -> bool:
    if valor is None:
        return False
    texto = str(valor).strip().upper()
    if texto in {"SP", "SAO PAULO", "SÃO PAULO", "35", "035"}:
        return True
    try:
        return int(float(texto)) == 35
    except (ValueError, TypeError):
        return False


def _carregar_queimadas(caminho: Path):
    if not caminho.exists():
        logger.warning("Arquivo de queimadas nao encontrado: %s", caminho)
        return

    with open(caminho, "r", encoding="utf-8") as f:
        dados = json.load(f)

    fonte_id = _inserir_fonte(dados.get("metadados", {}))
    registros = dados.get("dados", [])
    logger.info("Carregando %d focos de queimada...", len(registros))

    inseridos = 0
    for i, reg in enumerate(registros):
        if not _eh_sp(reg.get("estado")):
            continue

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
                         ELSE NULL END)
            ON CONFLICT (data_hora, latitude, longitude) DO UPDATE
            SET fonte_id = EXCLUDED.fonte_id,
                satelite = EXCLUDED.satelite,
                municipio = EXCLUDED.municipio,
                estado = EXCLUDED.estado,
                bioma = EXCLUDED.bioma,
                frp = EXCLUDED.frp,
                risco_fogo = EXCLUDED.risco_fogo,
                precipitacao = EXCLUDED.precipitacao,
                geom = EXCLUDED.geom""",
            {
                "fid": fonte_id,
                "lat": lat,
                "lon": lon,
                "dt": reg.get("data_hora"),
                "sat": reg.get("satelite", ""),
                "mun": reg.get("municipio", ""),
                "est": _normalizar_uf(reg.get("estado")),
                "bio": reg.get("bioma", ""),
                "frp": _para_float(reg.get("frp")),
                "risco": _para_float(reg.get("risco_fogo")),
                "prec": _para_float(reg.get("precipitacao")),
            },
        )

        doc = textualizar_queimada(reg)
        doc["uf_sigla"] = "SP"
        _inserir_corpus(doc)
        inseridos += 1

    logger.info("Queimadas: %d registros processados", inseridos)


def _carregar_funai(caminho: Path):
    if not caminho.exists():
        logger.warning("Arquivo FUNAI nao encontrado: %s", caminho)
        return

    with open(caminho, "r", encoding="utf-8") as f:
        dados = json.load(f)

    fonte_id = _inserir_fonte(dados.get("metadados", {}))
    features = dados.get("features", [])
    logger.info("Carregando %d terras indigenas...", len(features))

    inseridos = 0
    for feat in features:
        props = feat.get("properties", {})
        if not _eh_sp(props.get("uf_sigla", "SP")):
            continue
        geom_json = json.dumps(feat.get("geometry", {}))

        executar_sql(
            """INSERT INTO terras_indigenas
            (fonte_id, codigo, nome, etnia, municipio, uf, area_ha, fase, modalidade, geom)
            VALUES (:fid, :cod, :nome, :etnia, :mun, :uf, :area, :fase, :mod,
                    ST_SetSRID(ST_GeomFromGeoJSON(:geom), 4674))
            ON CONFLICT (codigo) DO UPDATE 
            SET area_ha = EXCLUDED.area_ha, fase = EXCLUDED.fase, geom = EXCLUDED.geom""",
            {
                "fid": fonte_id,
                "cod": props.get("terrai_codigo"),
                "nome": props.get("terrai_nome", ""),
                "etnia": props.get("etnia_nome", ""),
                "mun": props.get("municipio_nome", ""),
                "uf": _normalizar_uf(props.get("uf_sigla", "SP")),
                "area": props.get("superficie_perimetro_ha"),
                "fase": props.get("fase_ti", ""),
                "mod": props.get("modalidade_ti", ""),
                "geom": geom_json,
            },
        )

        bbox = feat.get("bbox")
        doc = textualizar_terra_indigena(props, bbox=bbox)
        doc["uf_sigla"] = "SP"
        _inserir_corpus(doc)
        inseridos += 1

    logger.info("FUNAI: %d registros processados", inseridos)


def _carregar_deter(caminho: Path):
    if not caminho.exists():
        logger.warning("Arquivo DETER nao encontrado: %s", caminho)
        return

    with open(caminho, "r", encoding="utf-8") as f:
        dados = json.load(f)

    fonte_id = _inserir_fonte(dados.get("metadados", {}))
    features = dados.get("features", [])
    logger.info("Carregando %d alertas de desmatamento...", len(features))

    inseridos = 0
    for feat in features:
        props = feat.get("properties", {})
        if not _eh_sp(props.get("uf", "SP")):
            continue
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
                         ELSE NULL END)
            ON CONFLICT (data_avistamento, municipio, area_total_km2) DO UPDATE
            SET fonte_id = EXCLUDED.fonte_id,
                classe = EXCLUDED.classe,
                uf = EXCLUDED.uf,
                sensor = EXCLUDED.sensor,
                satelite = EXCLUDED.satelite,
                area_uc_km2 = EXCLUDED.area_uc_km2,
                nome_uc = EXCLUDED.nome_uc,
                geom = EXCLUDED.geom""",
            {
                "fid": fonte_id,
                "cls": props.get("classname", ""),
                "mun": props.get("municipality", ""),
                "uf": _normalizar_uf(props.get("uf", "SP")),
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
        doc["uf_sigla"] = "SP"
        _inserir_corpus(doc)
        inseridos += 1

    logger.info("DETER: %d registros processados", inseridos)


def _carregar_ucs(caminho: Path):
    if not caminho.exists():
        logger.warning("Arquivo UCs nao encontrado: %s", caminho)
        return

    with open(caminho, "r", encoding="utf-8") as f:
        dados = json.load(f)

    fonte_id = _inserir_fonte(dados.get("metadados", {}))
    registros = dados.get("dados", [])
    logger.info("Carregando %d unidades de conservacao...", len(registros))

    inseridos = 0
    for reg in registros:
        uf = reg.get("UF", reg.get("uf", "SP"))
        if not _eh_sp(uf):
            continue

        executar_sql(
            """INSERT INTO unidades_conservacao
            (fonte_id, nome, categoria, grupo, esfera, uf, municipio, area_ha)
            VALUES (:fid, :nome, :cat, :grupo, :esfera, :uf, :mun, :area)
            ON CONFLICT (nome, esfera) DO UPDATE
            SET fonte_id = EXCLUDED.fonte_id,
                categoria = EXCLUDED.categoria,
                grupo = EXCLUDED.grupo,
                uf = EXCLUDED.uf,
                municipio = EXCLUDED.municipio,
                area_ha = EXCLUDED.area_ha""",
            {
                "fid": fonte_id,
                "nome": reg.get("nome_uc", reg.get("NOME", reg.get("nome", ""))),
                "cat": reg.get("categoria", reg.get("CATEGORI3", "")),
                "grupo": reg.get("grupo", reg.get("GRUPO", "")),
                "esfera": reg.get("esfera", reg.get("ESFERA", "")),
                "uf": _normalizar_uf(uf),
                "mun": reg.get("municipio", reg.get("MUNICIPIO", "")),
                "area": _para_float(reg.get("area_ha", reg.get("AREA_HA"))),
            },
        )

        doc = textualizar_unidade_conservacao(reg)
        doc["uf_sigla"] = "SP"
        _inserir_corpus(doc)
        inseridos += 1

    logger.info("UCs: %d registros processados", inseridos)


def _carregar_prodes(caminho: Path):
    if not caminho.exists():
        logger.warning("Arquivo PRODES nao encontrado: %s", caminho)
        return

    with open(caminho, "r", encoding="utf-8") as f:
        dados = json.load(f)

    fonte_id = _inserir_fonte(dados.get("metadados", {}))
    features = dados.get("features", [])
    logger.info("Carregando %d registros PRODES...", len(features))

    AMOSTRA_CORPUS = 50

    inseridos = 0
    corpus_inseridos = 0
    for i, feat in enumerate(features):
        props = feat.get("properties", {})
        if not _eh_sp(props.get("state", "SP")):
            continue
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
                         ELSE NULL END)
            ON CONFLICT (uid) DO UPDATE
            SET fonte_id = EXCLUDED.fonte_id,
                estado = EXCLUDED.estado,
                classe_principal = EXCLUDED.classe_principal,
                classe_nome = EXCLUDED.classe_nome,
                data_imagem = EXCLUDED.data_imagem,
                ano = EXCLUDED.ano,
                area_km = EXCLUDED.area_km,
                fonte_bioma = EXCLUDED.fonte_bioma,
                satelite = EXCLUDED.satelite,
                sensor = EXCLUDED.sensor,
                geom = EXCLUDED.geom""",
            {
                "fid": fonte_id,
                "uid": props.get("uid"),
                "estado": _normalizar_uf(props.get("state", "SP")),
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
        inseridos += 1

        if i % AMOSTRA_CORPUS == 0:
            doc = textualizar_prodes(props)
            doc["uf_sigla"] = "SP"
            _inserir_corpus(doc)
            corpus_inseridos += 1

    logger.info("PRODES: %d registros na tabela, %d amostras no corpus", inseridos, corpus_inseridos)


def _carregar_palmares(caminho: Path):
    if not caminho.exists():
        logger.warning("Arquivo Palmares nao encontrado: %s", caminho)
        return

    with open(caminho, "r", encoding="utf-8") as f:
        dados = json.load(f)

    fonte_id = _inserir_fonte(dados.get("metadados", {}))
    registros = dados.get("dados", [])
    logger.info("Carregando %d comunidades quilombolas...", len(registros))

    inseridos = 0
    for reg in registros:
        municipio = reg.get("MUNICÍPIO", reg.get("MUNICIPIO", ""))
        ano_str = reg.get("ANO CERTIFICAÇÃO", reg.get("ANO CERTIFICACAO", ""))
        uf = reg.get(" ", reg.get("UF", "SP")).strip()
        if not _eh_sp(uf):
            continue

        ano = None
        try:
            ano = int(ano_str) if ano_str and str(ano_str).strip() else None
        except (ValueError, TypeError):
            ano = None

        executar_sql(
            """INSERT INTO comunidades_quilombolas
            (fonte_id, municipio, uf, comunidade, codigo_ibge,
             processo_fcp, ano_certificacao, processo_incra, regiao)
            VALUES (:fid, :mun, :uf, :com, :ibge, :proc, :ano, :incra, :regiao)
            ON CONFLICT (comunidade, municipio) DO UPDATE
            SET fonte_id = EXCLUDED.fonte_id,
                uf = EXCLUDED.uf,
                codigo_ibge = EXCLUDED.codigo_ibge,
                processo_fcp = EXCLUDED.processo_fcp,
                ano_certificacao = EXCLUDED.ano_certificacao,
                processo_incra = EXCLUDED.processo_incra,
                regiao = EXCLUDED.regiao""",
            {
                "fid": fonte_id,
                "mun": municipio,
                "uf": _normalizar_uf(uf),
                "com": reg.get("COMUNIDADE", ""),
                "ibge": reg.get("CÓDIGO DO IBGE", reg.get("CODIGO DO IBGE", "")),
                "proc": reg.get("Nº PROCESSO NA FCP", ""),
                "ano": ano,
                "incra": reg.get("Nº PROCESSO INCRA", ""),
                "regiao": reg.get(" REGIÃO", reg.get(" REGIAO", "")).strip(),
            },
        )

        doc = textualizar_quilombola(reg)
        doc["uf_sigla"] = "SP"
        _inserir_corpus(doc)
        inseridos += 1

    logger.info("Palmares: %d registros processados", inseridos)


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
        ON CONFLICT (cod_imovel) DO UPDATE 
        SET fonte_id = EXCLUDED.fonte_id,
            cod_tema = EXCLUDED.cod_tema,
            nom_tema = EXCLUDED.nom_tema,
            ind_status = EXCLUDED.ind_status,
            ind_tipo = EXCLUDED.ind_tipo,
            des_condic = EXCLUDED.des_condic,
            municipio = EXCLUDED.municipio,
            cod_estado = EXCLUDED.cod_estado,
            num_area = EXCLUDED.num_area,
            mod_fiscal = EXCLUDED.mod_fiscal,
            dat_criacao = EXCLUDED.dat_criacao,
            dat_atualizacao = EXCLUDED.dat_atualizacao,
            geom = EXCLUDED.geom
    """

    BATCH_SIZE = 1000
    AMOSTRA_CORPUS = 50
    batch = []
    inseridos = 0
    elegiveis_sp = 0
    corpus_total = 0

    for feat in features:
        props = feat.get("properties") or {}
        if not _eh_cod_estado_sp(props.get("cod_estado")):
            continue

        elegiveis_sp += 1
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

        if elegiveis_sp % AMOSTRA_CORPUS == 1:
            doc = textualizar_sicar(props)
            doc["uf_sigla"] = "SP"
            _inserir_corpus(doc)
            corpus_total += 1

        if len(batch) >= BATCH_SIZE:
            executar_sql_many(sql, batch)
            inseridos += len(batch)
            batch = []
            logger.info("  %d imoveis processados", inseridos)

    if batch:
        executar_sql_many(sql, batch)
        inseridos += len(batch)

    logger.info("SICAR: %d registros processados na tabela, %d amostras no corpus", inseridos, corpus_total)


def _para_float(valor) -> float | None:
    if valor is None or valor == "":
        return None
    try:
        return float(valor)
    except (ValueError, TypeError):
        return None