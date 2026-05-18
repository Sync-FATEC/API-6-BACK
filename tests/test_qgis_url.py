"""Testes unitarios para asg_sistema.motor.qgis_url.construir_qgis_url.

Regras de negocio cobertas:
1. Intencao mapeada -> retorna URL com path correspondente.
2. Intencao desconhecida -> retorna None.
3. Municipio com sufixo "(SP)" -> sufixo removido.
4. Municipio lista com virgula -> usa apenas o primeiro.
5. Periodo {inicio, fim} -> emite data_inicio/data_fim para intencoes que aceitam.
6. cod_imovel -> normalizado (upper, trim) e usado apenas em SICAR.
7. PRODES -> ano derivado de periodo.inicio.
8. base_url prefixado quando fornecido.
9. Filtros nao permitidos pelo path nao aparecem na URL.
"""

from urllib.parse import parse_qs, urlsplit

from asg_sistema.motor.qgis_url import construir_qgis_url


# --------------------------------------------------------------------------
# Builders / Object Mothers
# --------------------------------------------------------------------------

def uma_entidade(
    municipios=None,
    periodo=None,
    cod_imovel=None,
) -> dict:
    out: dict = {}
    if municipios is not None:
        out["municipios"] = municipios
    if periodo is not None:
        out["periodo"] = periodo
    if cod_imovel is not None:
        out["cod_imovel"] = cod_imovel
    return out


def _parse(url: str) -> tuple[str, dict[str, list[str]]]:
    parts = urlsplit(url)
    return parts.path, parse_qs(parts.query)


# --------------------------------------------------------------------------
# Mapeamento intencao -> path
# --------------------------------------------------------------------------

class TestMapeamentoIntencao:
    def test_deve_retornar_path_de_queimadas_quando_intencao_eh_consultar_queimadas(self):
        url = construir_qgis_url("consultar_queimadas", uma_entidade())
        path, _ = _parse(url)
        assert path == "/api/geo/queimadas"

    def test_deve_retornar_path_de_desmatamento_quando_intencao_eh_consultar_desmatamento(self):
        url = construir_qgis_url("consultar_desmatamento", uma_entidade())
        path, _ = _parse(url)
        assert path == "/api/geo/desmatamento"

    def test_deve_retornar_path_de_terras_indigenas_quando_intencao_eh_consultar_terra_indigena(self):
        url = construir_qgis_url("consultar_terra_indigena", uma_entidade())
        path, _ = _parse(url)
        assert path == "/api/geo/terras-indigenas"

    def test_deve_retornar_path_de_ucs_quando_intencao_eh_consultar_unidade_conservacao(self):
        url = construir_qgis_url("consultar_unidade_conservacao", uma_entidade())
        path, _ = _parse(url)
        assert path == "/api/geo/unidades-conservacao"

    def test_deve_retornar_path_de_quilombolas_quando_intencao_eh_consultar_quilombola(self):
        url = construir_qgis_url("consultar_quilombola", uma_entidade())
        path, _ = _parse(url)
        assert path == "/api/geo/quilombolas"

    def test_deve_retornar_path_de_prodes_quando_intencao_eh_consultar_prodes(self):
        url = construir_qgis_url("consultar_prodes", uma_entidade())
        path, _ = _parse(url)
        assert path == "/api/geo/prodes"

    def test_deve_retornar_path_de_sicar_quando_intencao_eh_consultar_imovel_rural(self):
        url = construir_qgis_url("consultar_imovel_rural", uma_entidade())
        path, _ = _parse(url)
        assert path == "/api/geo/sicar"


# --------------------------------------------------------------------------
# Intencao desconhecida
# --------------------------------------------------------------------------

class TestIntencaoSemMapeamento:
    def test_deve_retornar_none_quando_intencao_nao_tem_endpoint_geo(self):
        assert construir_qgis_url("resumo_municipal", uma_entidade()) is None

    def test_deve_retornar_none_quando_intencao_eh_string_vazia(self):
        assert construir_qgis_url("", uma_entidade()) is None

    def test_deve_retornar_none_quando_intencao_eh_desconhecida(self):
        assert construir_qgis_url("consultar_qualquer_coisa", uma_entidade()) is None


# --------------------------------------------------------------------------
# Normalizacao de municipio
# --------------------------------------------------------------------------

class TestNormalizacaoMunicipio:
    def test_deve_remover_sufixo_uf_quando_municipio_termina_com_parenteses(self):
        url = construir_qgis_url(
            "consultar_queimadas", uma_entidade(municipios=["Ubatuba (SP)"]),
        )
        _, query = _parse(url)
        assert query["municipio"] == ["Ubatuba"]

    def test_deve_usar_apenas_o_primeiro_quando_municipio_eh_lista_separada_por_virgula(self):
        url = construir_qgis_url(
            "consultar_queimadas",
            uma_entidade(municipios=["AGUDOS (SP), BAURU (SP), PEDERNEIRAS (SP)"]),
        )
        _, query = _parse(url)
        assert query["municipio"] == ["AGUDOS"]

    def test_deve_usar_primeiro_municipio_da_lista_quando_ha_varios_no_array(self):
        url = construir_qgis_url(
            "consultar_queimadas",
            uma_entidade(municipios=["Campinas", "Sorocaba"]),
        )
        _, query = _parse(url)
        assert query["municipio"] == ["Campinas"]

    def test_deve_omitir_filtro_municipio_quando_lista_esta_vazia(self):
        url = construir_qgis_url("consultar_queimadas", uma_entidade(municipios=[]))
        _, query = _parse(url)
        assert "municipio" not in query


# --------------------------------------------------------------------------
# Filtros de periodo
# --------------------------------------------------------------------------

class TestPeriodo:
    def test_deve_incluir_data_inicio_e_data_fim_quando_periodo_completo_para_queimadas(self):
        url = construir_qgis_url(
            "consultar_queimadas",
            uma_entidade(periodo={"inicio": "2025-01-01", "fim": "2025-06-01"}),
        )
        _, query = _parse(url)
        assert query["data_inicio"] == ["2025-01-01"]
        assert query["data_fim"] == ["2025-06-01"]

    def test_deve_incluir_apenas_data_inicio_quando_fim_ausente(self):
        url = construir_qgis_url(
            "consultar_desmatamento",
            uma_entidade(periodo={"inicio": "2025-01-01"}),
        )
        _, query = _parse(url)
        assert query["data_inicio"] == ["2025-01-01"]
        assert "data_fim" not in query

    def test_deve_omitir_datas_quando_path_nao_aceita_filtros_de_data(self):
        url = construir_qgis_url(
            "consultar_terra_indigena",
            uma_entidade(periodo={"inicio": "2025-01-01", "fim": "2025-06-01"}),
        )
        _, query = _parse(url)
        assert "data_inicio" not in query
        assert "data_fim" not in query


# --------------------------------------------------------------------------
# PRODES: ano derivado do periodo
# --------------------------------------------------------------------------

class TestPRODESAno:
    def test_deve_derivar_ano_do_inicio_do_periodo_para_prodes(self):
        url = construir_qgis_url(
            "consultar_prodes",
            uma_entidade(periodo={"inicio": "2023-08-15"}),
        )
        _, query = _parse(url)
        assert query["ano"] == ["2023"]

    def test_deve_omitir_ano_quando_periodo_inicio_eh_invalido_para_prodes(self):
        url = construir_qgis_url(
            "consultar_prodes",
            uma_entidade(periodo={"inicio": "valor-invalido"}),
        )
        _, query = _parse(url)
        assert "ano" not in query

    def test_deve_omitir_ano_para_outras_intencoes_mesmo_com_periodo(self):
        url = construir_qgis_url(
            "consultar_queimadas",
            uma_entidade(periodo={"inicio": "2024-01-01"}),
        )
        _, query = _parse(url)
        assert "ano" not in query


# --------------------------------------------------------------------------
# SICAR: cod_imovel
# --------------------------------------------------------------------------

class TestSICARCodigoImovel:
    def test_deve_emitir_cod_imovel_em_uppercase_quando_intencao_eh_imovel_rural(self):
        url = construir_qgis_url(
            "consultar_imovel_rural",
            uma_entidade(cod_imovel=" sp-3555406-abc "),
        )
        _, query = _parse(url)
        assert query["cod_imovel"] == ["SP-3555406-ABC"]

    def test_deve_omitir_cod_imovel_quando_intencao_nao_eh_imovel_rural(self):
        url = construir_qgis_url(
            "consultar_queimadas",
            uma_entidade(cod_imovel="SP-3555406-ABC"),
        )
        _, query = _parse(url)
        assert "cod_imovel" not in query


# --------------------------------------------------------------------------
# base_url
# --------------------------------------------------------------------------

class TestBaseUrl:
    def test_deve_prefixar_base_url_quando_fornecida(self):
        url = construir_qgis_url(
            "consultar_queimadas",
            uma_entidade(municipios=["Campinas"]),
            base_url="http://api.exemplo.com",
        )
        assert url.startswith("http://api.exemplo.com/api/geo/queimadas")

    def test_deve_remover_barra_final_da_base_url_quando_presente(self):
        url = construir_qgis_url(
            "consultar_queimadas",
            uma_entidade(),
            base_url="http://api.exemplo.com/",
        )
        assert url.startswith("http://api.exemplo.com/api/geo/queimadas")
        assert "//api/geo" not in url

    def test_deve_retornar_path_relativo_quando_base_url_vazia(self):
        url = construir_qgis_url("consultar_queimadas", uma_entidade())
        assert url.startswith("/api/geo/queimadas")


# --------------------------------------------------------------------------
# URL final sem filtros: apenas path
# --------------------------------------------------------------------------

class TestURLSemFiltros:
    def test_deve_retornar_apenas_path_sem_query_quando_nenhum_filtro_aplicavel(self):
        url = construir_qgis_url("consultar_queimadas", uma_entidade())
        assert url == "/api/geo/queimadas"

    def test_deve_retornar_path_sem_query_quando_entidades_eh_dict_vazio(self):
        url = construir_qgis_url("consultar_unidade_conservacao", {})
        assert url == "/api/geo/unidades-conservacao"
