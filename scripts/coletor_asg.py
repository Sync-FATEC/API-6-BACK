"""
Coletor de dados ASG (Ambiental, Social, Governança)
para propriedades rurais do Estado de São Paulo.

Fontes:
- FUNAI: Terras Indígenas (WFS)
- INPE DETER: Alertas de desmatamento (WFS)
- INPE Queimadas: Focos de incêndio (CSV)
- INPE PRODES: Desmatamento anual (WFS)
- ICMBio/MMA: Unidades de Conservação (download shapefile -> JSON)
- SICAR: Cadastro Ambiental Rural (WFS)
- Palmares: Comunidades Quilombolas (CSV/dados abertos)
"""

import argparse
import json
import os
import csv
import io
import time
import logging
import zipfile
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from pathlib import Path

import requests

BASE_DIR = Path(__file__).resolve().parent.parent / "dados"
LOG_FORMAT = "%(asctime)s [%(levelname)s] %(message)s"
TIMEOUT = 120
UF_SP = "SP"
BBOX_SP = "-53.2,-25.4,-44.1,-19.8"

logging.basicConfig(level=logging.INFO, format=LOG_FORMAT)
logger = logging.getLogger(__name__)


def salvar_json(dados, nome_arquivo):
    """Salva dados em arquivo JSON na pasta dados/."""
    caminho = BASE_DIR / nome_arquivo
    with open(caminho, "w", encoding="utf-8") as f:
        json.dump(dados, f, ensure_ascii=False, indent=2)
    tamanho_mb = caminho.stat().st_size / (1024 * 1024)
    logger.info("Salvo: %s (%.2f MB)", caminho, tamanho_mb)


def criar_metadados(fonte, descricao, url, total_registros):
    """Cria objeto de metadados padronizado para rastreabilidade."""
    return {
        "fonte": fonte,
        "descricao": descricao,
        "url_origem": url,
        "data_coleta": datetime.now().isoformat(),
        "total_registros": total_registros,
        "escopo": "Estado de São Paulo"
    }


def coletar_funai():
    """Coleta Terras Indígenas da FUNAI via WFS (GeoJSON)."""
    logger.info("Coletando FUNAI - Terras Indígenas...")
    url = "https://geoserver.funai.gov.br/geoserver/Funai/wfs"
    params = {
        "service": "WFS",
        "version": "2.0.0",
        "request": "GetFeature",
        "typeName": "Funai:tis_poligonais",
        "outputFormat": "application/json",
        "srsName": "EPSG:4674",
        "CQL_FILTER": "uf_sigla='SP' OR uf_sigla LIKE '%SP%'"
    }

    response = requests.get(url, params=params, timeout=TIMEOUT)
    response.raise_for_status()
    geojson = response.json()

    features = geojson.get("features", [])
    total = len(features)
    logger.info("FUNAI: %d terras indígenas encontradas em SP", total)

    resultado = {
        "metadados": criar_metadados(
            "FUNAI",
            "Terras Indígenas no Estado de São Paulo",
            url,
            total
        ),
        "type": "FeatureCollection",
        "features": features
    }

    salvar_json(resultado, "funai_terras_indigenas_sp.json")
    return total


def coletar_deter():
    """Coleta alertas de desmatamento DETER do último ano via WFS."""
    logger.info("Coletando INPE DETER - Alertas de desmatamento...")

    data_fim = datetime.now().strftime("%Y-%m-%d")
    data_inicio = (datetime.now() - timedelta(days=365)).strftime("%Y-%m-%d")

    url = "https://terrabrasilis.dpi.inpe.br/geoserver/deter-cerrado-nb/wfs"
    params = {
        "service": "WFS",
        "version": "2.0.0",
        "request": "GetFeature",
        "typeName": "deter-cerrado-nb:deter_cerrado",
        "outputFormat": "application/json",
        "srsName": "EPSG:4674",
        "CQL_FILTER": (
            f"view_date BETWEEN '{data_inicio}' AND '{data_fim}' "
            f"AND uf='SP'"
        ),
        "maxFeatures": "10000"
    }

    response = requests.get(url, params=params, timeout=TIMEOUT)
    response.raise_for_status()
    geojson = response.json()

    features = geojson.get("features", [])
    total = len(features)
    logger.info("DETER Cerrado: %d alertas encontrados na região de SP", total)

    resultado = {
        "metadados": criar_metadados(
            "INPE/DETER",
            f"Alertas de desmatamento Cerrado ({data_inicio} a {data_fim})",
            url,
            total
        ),
        "type": "FeatureCollection",
        "features": features
    }

    salvar_json(resultado, "deter_desmatamento_sp.json")
    return total


def coletar_deter_amazonia():
    """Coleta desmatamento complementar (Cerrado e Pantanal) em SP.
    SP nao esta na Amazonia Legal, entao busca PRODES de outros biomas.
    """
    logger.info("Coletando INPE - Desmatamento complementar (Cerrado+Pantanal em SP)...")

    total_features = []

    camadas = [
        ("prodes-cerrado-nb", "prodes-cerrado-nb:yearly_deforestation", "PRODES Cerrado"),
        ("prodes-pantanal-nb", "prodes-pantanal-nb:yearly_deforestation", "PRODES Pantanal"),
    ]

    for workspace, layer, nome in camadas:
        try:
            url = f"https://terrabrasilis.dpi.inpe.br/geoserver/{workspace}/wfs"
            params = {
                "service": "WFS",
                "version": "2.0.0",
                "request": "GetFeature",
                "typeName": layer,
                "outputFormat": "application/json",
                "srsName": "EPSG:4674",
                "CQL_FILTER": f"BBOX(geom,{BBOX_SP})",
                "maxFeatures": "2000"
            }
            response = requests.get(url, params=params, timeout=TIMEOUT)
            if response.status_code == 200:
                geojson = response.json()
                features = geojson.get("features", [])
                logger.info("  %s: %d registros em SP", nome, len(features))
                for f in features:
                    if f.get("properties"):
                        f["properties"]["fonte_camada"] = nome
                total_features.extend(features)
        except Exception as e:
            logger.warning("  %s falhou: %s", nome, str(e)[:100])

    total = len(total_features)
    logger.info("Desmatamento complementar: %d registros totais", total)

    resultado = {
        "metadados": criar_metadados(
            "INPE/PRODES",
            "Desmatamento anual Cerrado e Pantanal em SP",
            "https://terrabrasilis.dpi.inpe.br/geoserver/",
            total
        ),
        "type": "FeatureCollection",
        "features": total_features
    }

    if total == 0:
        resultado["nota"] = (
            "São Paulo não possui área na Amazônia Legal. "
            "Dados de desmatamento do Cerrado e Mata Atlântica são cobertos "
            "pelos coletores DETER Cerrado e PRODES Mata Atlântica."
        )

    salvar_json(resultado, "deter_amazonia_sp.json")
    return total


def coletar_queimadas():
    """Coleta focos de queimadas do INPE via CSV público."""
    logger.info("Coletando INPE Queimadas - Focos de incêndio...")

    agora = datetime.now()
    focos_sp = []
    urls_tentadas = []

    for meses_atras in range(0, 6):
        data = agora - timedelta(days=30 * meses_atras)
        ano_mes = data.strftime("%Y%m")
        url = (
            f"https://dataserver-coids.inpe.br/queimadas/queimadas/"
            f"focos/csv/mensal/Brasil/focos_mensal_br_{ano_mes}.csv"
        )
        urls_tentadas.append(url)

        logger.info("Tentando CSV de queimadas: %s", ano_mes)
        try:
            response = requests.get(url, timeout=TIMEOUT)
            if response.status_code != 200:
                logger.warning("CSV %s não disponível (HTTP %d)", ano_mes, response.status_code)
                continue

            try:
                conteudo = response.content.decode("utf-8")
            except UnicodeDecodeError:
                conteudo = response.content.decode("latin-1")
            leitor = csv.DictReader(io.StringIO(conteudo))

            for linha in leitor:
                estado = linha.get("estado") or linha.get("uf") or ""
                if "PAULO" in estado.upper() or estado.upper() == "SP":
                    focos_sp.append({
                        "latitude": linha.get("latitude", linha.get("lat", "")),
                        "longitude": linha.get("longitude", linha.get("lon", "")),
                        "data_hora": linha.get("datahora", linha.get("data_hora_gmt", "")),
                        "satelite": linha.get("satelite", ""),
                        "municipio": linha.get("municipio", ""),
                        "estado": estado,
                        "bioma": linha.get("bioma", ""),
                        "frp": linha.get("frp", ""),
                        "risco_fogo": linha.get("risco_fogo", linha.get("riscofogo", "")),
                        "precipitacao": linha.get("precipitacao", ""),
                    })

            logger.info("Mês %s processado. Focos SP acumulados: %d", ano_mes, len(focos_sp))

        except requests.RequestException as e:
            logger.warning("Erro ao baixar CSV %s: %s", ano_mes, e)
            continue

    total = len(focos_sp)
    logger.info("Queimadas: %d focos encontrados em SP (últimos 6 meses)", total)

    resultado = {
        "metadados": criar_metadados(
            "INPE/Queimadas",
            "Focos de incêndio em SP (últimos 6 meses)",
            urls_tentadas[0] if urls_tentadas else "",
            total
        ),
        "dados": focos_sp
    }

    salvar_json(resultado, "queimadas_focos_sp.json")
    return total


def coletar_prodes():
    """Coleta dados de desmatamento PRODES via WFS do TerraBrasilis."""
    logger.info("Coletando INPE PRODES - Desmatamento Mata Atlântica...")

    url = "https://terrabrasilis.dpi.inpe.br/geoserver/prodes-mata-atlantica-nb/wfs"
    params = {
        "service": "WFS",
        "version": "2.0.0",
        "request": "GetFeature",
        "typeName": "prodes-mata-atlantica-nb:yearly_deforestation",
        "outputFormat": "application/json",
        "srsName": "EPSG:4674",
        "CQL_FILTER": "state='SP'",
        "maxFeatures": "10000"
    }

    response = requests.get(url, params=params, timeout=TIMEOUT)
    response.raise_for_status()
    geojson = response.json()

    features = geojson.get("features", [])
    total = len(features)
    logger.info("PRODES Mata Atlântica: %d registros na região de SP", total)

    resultado = {
        "metadados": criar_metadados(
            "INPE/PRODES",
            "Desmatamento anual Mata Atlântica - região de SP",
            url,
            total
        ),
        "type": "FeatureCollection",
        "features": features
    }

    salvar_json(resultado, "prodes_desmatamento_sp.json")
    return total


def coletar_unidades_conservacao():
    """Coleta Unidades de Conservação do MMA/ICMBio (download shapefile convertido)."""
    logger.info("Coletando MMA/ICMBio - Unidades de Conservação...")

    urls = [
        "https://dados.mma.gov.br/dataset/"
        "44b6dc8a-dc82-4a84-8d95-1b0da7c85dac/resource/"
        "9ec98f66-44ad-4397-8583-a1d9cc3a9835/download/shp_cnuc_2024_02.zip",
        "https://raw.githubusercontent.com/ipeaGIT/geobr/master/data-raw/"
        "conservation_units/SNUC.zip",
    ]

    response = None
    for url in urls:
        logger.info("Baixando shapefile CNUC: %s", url[:80])
        try:
            response = requests.get(url, timeout=300, headers={"User-Agent": "Mozilla/5.0"})
            response.raise_for_status()
            if len(response.content) > 10000:
                logger.info("Download OK: %d bytes", len(response.content))
                break
            response = None
        except requests.RequestException as e:
            logger.warning("Falhou: %s", str(e)[:100])
            response = None

    if response is None:
        logger.warning("Nenhuma fonte de UCs disponivel")
        return coletar_ucs_alternativo()

    zip_path = BASE_DIR / "cnuc_temp.zip"
    with open(zip_path, "wb") as f:
        f.write(response.content)

    ucs_sp = []
    try:
        try:
            import geopandas as gpd
            import tempfile as _tempfile
            with _tempfile.TemporaryDirectory() as tmpdir:
                with zipfile.ZipFile(zip_path, "r") as zf:
                    zf.extractall(tmpdir)
                shp_files = list(Path(tmpdir).rglob("*.shp"))
                if shp_files:
                    try:
                        gdf = gpd.read_file(shp_files[0], encoding="latin-1")
                        gdf = gdf.to_crs(epsg=4326)
                        # Filtra por campo de UF quando disponível; fallback por bbox de SP
                        uf_cols = [c for c in gdf.columns if c.upper() in ("UF", "SG_UF", "SIGLA_UF", "ESTADO")]
                        if uf_cols:
                            sp_mask = gdf[uf_cols[0]].str.upper().str.strip() == "SP"
                        else:
                            # Bounding box do estado de SP: lon -53.1..-44.1, lat -25.3..-19.8
                            centroids = gdf.geometry.centroid
                            sp_mask = (
                                centroids.x.between(-53.1, -44.1)
                                & centroids.y.between(-25.3, -19.8)
                            )
                        gdf_sp = gdf[sp_mask].copy()
                        centroids = gdf_sp.geometry.centroid
                        for idx, row in gdf_sp.iterrows():
                            rec = row.drop("geometry").to_dict()
                            rec["centroid_lon"] = round(centroids[idx].x, 6)
                            rec["centroid_lat"] = round(centroids[idx].y, 6)
                            ucs_sp.append(rec)
                        logger.info("Geopandas: %d UCs em SP com centroides", len(ucs_sp))
                    except UnicodeDecodeError as e:
                        logger.warning("Falha de encoding no geopandas/pyogrio (%s). Usando fallback DBF.", e)
                        with zipfile.ZipFile(zip_path, "r") as zf_dbf:
                            dbf_files = [n for n in zf_dbf.namelist() if n.endswith(".dbf")]
                            if dbf_files:
                                ucs_sp = extrair_dbf_basico(zf_dbf, dbf_files[0], "SP")
        except ImportError:
            logger.info("Geopandas não disponível, extraindo apenas DBF...")
            with zipfile.ZipFile(zip_path, "r") as zf:
                dbf_files = [n for n in zf.namelist() if n.endswith(".dbf")]
                if dbf_files:
                    ucs_sp = extrair_dbf_basico(zf, dbf_files[0], "SP")
    except zipfile.BadZipFile:
        logger.warning("Arquivo ZIP corrompido")
    finally:
        if zip_path.exists():
            zip_path.unlink()

    total = len(ucs_sp)
    logger.info("Unidades de Conservação em SP: %d", total)

    resultado = {
        "metadados": criar_metadados(
            "MMA/ICMBio",
            "Unidades de Conservação em SP (CNUC)",
            url,
            total
        ),
        "dados": ucs_sp
    }

    salvar_json(resultado, "unidades_conservacao_sp.json")
    return total


def extrair_dbf_basico(zip_file, dbf_nome, uf_filtro):
    """Extrai registros de um DBF filtrando por UF (parser básico sem dependências)."""
    registros = []
    try:
        with zip_file.open(dbf_nome) as dbf:
            dados_brutos = dbf.read()

        num_registros = int.from_bytes(dados_brutos[4:8], "little")
        header_size = int.from_bytes(dados_brutos[8:10], "little")
        record_size = int.from_bytes(dados_brutos[10:12], "little")

        campos = []
        pos = 32
        while pos < header_size - 1 and dados_brutos[pos] != 0x0D:
            nome_campo = dados_brutos[pos:pos + 11].split(b"\x00")[0].decode("ascii", errors="ignore")
            tipo_campo = chr(dados_brutos[pos + 11])
            tam_campo = dados_brutos[pos + 16]
            campos.append((nome_campo, tipo_campo, tam_campo))
            pos += 32

        for i in range(min(num_registros, 50000)):
            offset = header_size + (i * record_size)
            registro_bruto = dados_brutos[offset:offset + record_size]

            if not registro_bruto or registro_bruto[0:1] == b"*":
                continue

            registro = {}
            campo_pos = 1
            for nome, tipo, tam in campos:
                valor = registro_bruto[campo_pos:campo_pos + tam]
                try:
                    registro[nome] = valor.decode("latin-1").strip()
                except (UnicodeDecodeError, AttributeError):
                    registro[nome] = ""
                campo_pos += tam

            # Prefere campo explícito de UF; caso ausente inclui tudo
            # (geopandas já filtrou por bbox; DBF não tem coordenadas para refiltrar)
            uf_valor = ""
            for uf_col in ("UF", "SG_UF", "SIGLA_UF", "ESTADO"):
                if uf_col in registro:
                    uf_valor = registro[uf_col].strip().upper()
                    break
            if uf_valor and uf_valor != uf_filtro.upper():
                continue
            registros.append(registro)

    except Exception as e:
        logger.warning("Erro ao processar DBF: %s", e)

    return registros


def coletar_ucs_alternativo():
    """Fallback: tenta coletar UCs via dados.gov.br ou ICMBio."""
    logger.info("Tentando fonte alternativa para Unidades de Conservação...")

    resultado = {
        "metadados": criar_metadados(
            "MMA/ICMBio",
            "Unidades de Conservação - fonte indisponível no momento",
            "https://dados.mma.gov.br/dataset/unidadesdeconservacao",
            0
        ),
        "dados": [],
        "nota": (
            "Download automático falhou. Acesse manualmente: "
            "https://dados.mma.gov.br/dataset/unidadesdeconservacao"
        )
    }

    salvar_json(resultado, "unidades_conservacao_sp.json")
    return 0


def coletar_sicar():
    """Coleta dados do SICAR/CAR - tenta WFS e fallback para consulta publica."""
    logger.info("Coletando SICAR - Cadastro Ambiental Rural...")

    # Tentar WFS do GeoServer primeiro
    url_wfs = "https://geoserver.car.gov.br/geoserver/sicar/wfs"
    try:
        response = requests.get(url_wfs, params={
            "service": "WFS", "version": "2.0.0", "request": "GetFeature",
            "typeName": "sicar:sicar_imoveis_sp", "outputFormat": "application/json",
            "srsName": "EPSG:4674", "maxFeatures": "5000"
        }, timeout=30, verify=False)
        response.raise_for_status()
        geojson = response.json()
        features = geojson.get("features", [])
        if features:
            logger.info("SICAR WFS: %d imoveis encontrados", len(features))
            resultado = {
                "metadados": criar_metadados("SICAR/CAR", "Imoveis rurais em SP (WFS)", url_wfs, len(features)),
                "type": "FeatureCollection", "features": features
            }
            salvar_json(resultado, "sicar_imoveis_sp.json")
            return len(features)
    except Exception as e:
        logger.warning("WFS SICAR indisponivel: %s", str(e)[:100])

    # Fallback: consulta publica do CAR por municipio
    logger.info("Tentando consulta publica do CAR...")
    url_consulta = "https://consultapublica.car.gov.br/publico/municipios/downloads"
    url_api = "https://www.car.gov.br/publico/municipios/listMunicipiosPorEstado"

    dados_car = []
    try:
        headers = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}

        # Tenta API de listagem de municipios de SP (codigo IBGE SP = 35)
        resp = requests.get(url_api, params={"siglaUf": "SP"}, headers=headers, timeout=30)
        if resp.status_code == 200:
            try:
                municipios_car = resp.json()
                if isinstance(municipios_car, list):
                    for mun in municipios_car:
                        dados_car.append({
                            "municipio": mun.get("nomeMunicipio", mun.get("nome", "")),
                            "codigo_ibge": mun.get("codigoIbge", mun.get("codigo", "")),
                            "total_imoveis": mun.get("totalImoveis", mun.get("quantidadeImovel", "")),
                            "area_total_ha": mun.get("areaTotal", ""),
                        })
                    logger.info("CAR consulta publica: %d municipios com dados", len(dados_car))
            except (json.JSONDecodeError, ValueError):
                pass

        if not dados_car:
            # Fallback: estatisticas gerais de SP no CAR
            resp2 = requests.get(
                "https://www.car.gov.br/publico/estados/downloadsPorEstado",
                params={"siglaUf": "SP"}, headers=headers, timeout=30
            )
            if resp2.status_code == 200:
                try:
                    dados_estado = resp2.json()
                    if isinstance(dados_estado, dict):
                        dados_car.append({
                            "uf": "SP",
                            "total_imoveis": dados_estado.get("quantidadeImovel", ""),
                            "area_total_ha": dados_estado.get("areaTotal", ""),
                            "nota": "Dados agregados do estado"
                        })
                except (json.JSONDecodeError, ValueError):
                    pass
    except requests.RequestException as e:
        logger.warning("Consulta publica CAR falhou: %s", str(e)[:100])

    total = len(dados_car)
    logger.info("SICAR: %d registros obtidos", total)

    resultado = {
        "metadados": criar_metadados(
            "SICAR/CAR",
            "Cadastro Ambiental Rural - Estado de Sao Paulo",
            url_consulta,
            total
        ),
        "dados": dados_car
    }

    if total == 0:
        resultado["nota"] = (
            "GeoServer SICAR indisponivel (bloqueio SSL). "
            "Dados podem ser baixados manualmente em: "
            "https://www.car.gov.br/publico/municipios/downloads "
            "ou via biblioteca Python: https://github.com/urbanogilson/SICAR"
        )

    salvar_json(resultado, "sicar_imoveis_sp.json")
    return total


def coletar_quilombolas():
    """Coleta dados de comunidades quilombolas da Fundação Palmares."""
    logger.info("Coletando Palmares - Comunidades Quilombolas...")

    urls = [
        "https://docs.google.com/spreadsheets/d/"
        "1WBjixnnjJWrDXsA2WvElj65rrZ4nkNM-u5LclRV0lGs/"
        "export?format=csv&gid=680278480",
        "https://dados.cultura.gov.br/dataset/"
        "comunidades-quilombolas-certificadas/resource/"
        "comunidades-quilombolas-certificadas.csv",
    ]

    dados_palmares = None
    url_usada = ""
    for url in urls:
        try:
            response = requests.get(url, timeout=TIMEOUT, headers={"User-Agent": "Mozilla/5.0"})
            if response.status_code == 200 and len(response.content) > 500:
                dados_palmares = response.content
                url_usada = url
                logger.info("Dados Palmares obtidos de: %s (%d bytes)", url, len(response.content))
                break
        except requests.RequestException as e:
            logger.warning("Falha ao acessar %s: %s", url, e)
            continue

    comunidades_sp = []

    if dados_palmares:
        for encoding in ("utf-8", "latin-1", "cp1252"):
            for delimitador in (",", ";", "\t"):
                try:
                    conteudo = dados_palmares.decode(encoding)
                    leitor = csv.DictReader(io.StringIO(conteudo), delimiter=delimitador)
                    campos = leitor.fieldnames or []

                    if len(campos) < 3:
                        continue

                    logger.info("Palmares CSV: %d colunas, delimitador='%s', encoding=%s",
                                len(campos), delimitador, encoding)
                    logger.info("Palmares colunas: %s", campos[:8])

                    for linha in leitor:
                        valores = list(linha.values())
                        # Coluna UF eh a segunda (indice 1), header pode ser ' ' ou 'UF'
                        uf_valor = ""
                        if len(valores) > 1:
                            uf_valor = str(valores[1]).strip().upper()
                        # Tambem tenta por nome de coluna
                        for chave in linha:
                            if chave and chave.strip().upper() in ("UF", "SIGLA_UF", ""):
                                v = str(linha[chave]).strip().upper()
                                if len(v) == 2:
                                    uf_valor = v
                                    break
                        if uf_valor == "SP":
                            comunidades_sp.append(linha)

                    if comunidades_sp:
                        break
                except (UnicodeDecodeError, csv.Error):
                    continue
            if comunidades_sp:
                break

    total = len(comunidades_sp)
    logger.info("Palmares: %d comunidades quilombolas em SP", total)

    resultado = {
        "metadados": criar_metadados(
            "Fundação Cultural Palmares",
            "Comunidades quilombolas certificadas em SP",
            url_usada or urls[0],
            total
        ),
        "dados": comunidades_sp
    }

    if total == 0:
        resultado["nota"] = (
            "Dados podem estar indisponíveis via download direto. "
            "Consulte: https://www.gov.br/palmares/pt-br/acesso-a-informacao/dados-abertos"
        )

    salvar_json(resultado, "palmares_quilombolas_sp.json")
    return total


def gerar_resumo(resultados):
    """Gera arquivo de resumo com totais coletados."""
    resumo = {
        "titulo": "Coleta de Dados ASG - Estado de São Paulo",
        "data_execucao": datetime.now().isoformat(),
        "fontes": resultados,
        "total_geral": sum(r["registros"] for r in resultados),
        "arquivos_gerados": [
            str(p.name) for p in BASE_DIR.iterdir() if p.suffix == ".json"
        ]
    }
    salvar_json(resumo, "resumo_coleta.json")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--entidades", nargs="+", default=["tudo"])
    args = parser.parse_args()

    logger.info("=" * 60)
    logger.info(f"COLETOR ASG - Iniciando com entidades: {args.entidades}")
    logger.info("=" * 60)

    BASE_DIR.mkdir(parents=True, exist_ok=True)

    todos_coletores = {
        "terras_indigenas": [("FUNAI - Terras Indígenas", coletar_funai)],
        "desmatamentos": [
            ("INPE/DETER - Desmatamento Cerrado", coletar_deter),
            ("INPE/DETER - Desmatamento Amazônia", coletar_deter_amazonia),
            ("INPE/PRODES - Desmatamento Anual", coletar_prodes)
        ],
        "queimadas": [("INPE/Queimadas - Focos de Incêndio", coletar_queimadas)],
        "unidades_conservacao": [("MMA/ICMBio - Unidades de Conservação", coletar_unidades_conservacao)],
        "sicar": [("SICAR - Cadastro Ambiental Rural", coletar_sicar)],
        "quilombos": [("Palmares - Comunidades Quilombolas", coletar_quilombolas)],
    }

    coletores_executar = []
    
    if "tudo" in args.entidades:
        for coletores in todos_coletores.values():
            coletores_executar.extend(coletores)
    else:
        for entidade in args.entidades:
            if entidade in todos_coletores:
                coletores_executar.extend(todos_coletores[entidade])
            else:
                logger.warning("Entidade desconhecida ignorada: %s", entidade)

    resultados = []

    for nome, coletor in coletores_executar:
        logger.info("-" * 40)
        logger.info("Iniciando: %s", nome)
        inicio = time.time()
        try:
            total = coletor()
            duracao = time.time() - inicio
            status = "OK"
            logger.info("%s concluído: %d registros (%.1fs)", nome, total, duracao)
        except Exception as e:
            total = 0
            duracao = time.time() - inicio
            status = f"FALHA (PULADO): {e}"
            logger.error("%s falhou ao baixar e será ignorado nesta rodada: %s", nome, e)

        resultados.append({
            "fonte": nome,
            "registros": total,
            "status": status,
            "duracao_segundos": round(duracao, 1)
        })

    logger.info("=" * 60)
    gerar_resumo(resultados)

    logger.info("COLETA FINALIZADA")
    logger.info("Arquivos salvos em: %s", BASE_DIR.resolve())
    logger.info("-" * 40)
    for r in resultados:
        emoji = "OK" if r["status"] == "OK" else "FALHA"
        logger.info(
            "  [%s] %s: %d registros (%.1fs)",
            emoji, r["fonte"], r["registros"], r["duracao_segundos"]
        )
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
