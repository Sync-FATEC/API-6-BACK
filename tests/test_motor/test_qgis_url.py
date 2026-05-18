"""Testes unitários para asg_sistema/motor/qgis_url.py."""

import os

os.environ.setdefault("ASG_JWT_SEGREDO", "chave-secreta-de-testes-nao-usar-em-producao")

import pytest
from urllib.parse import parse_qs, urlparse

from asg_sistema.motor.qgis_url import construir_qgis_url


class TestConstruirQgisUrl:
    """Testes para construir_qgis_url."""

    # ── Intencoes sem endpoint geo ──────────────────────────────────────────

    def test_intencao_desconhecida_retorna_none(self):
        assert construir_qgis_url("resumo_municipal", {}) is None

    def test_intencao_vazia_retorna_none(self):
        assert construir_qgis_url("", {}) is None

    def test_intencao_inexistente_retorna_none(self):
        assert construir_qgis_url("nao_existe_intencao", {}) is None

    # ── Intencoes com endpoint geo ──────────────────────────────────────────

    def test_queimadas_sem_entidades_retorna_path(self):
        url = construir_qgis_url("consultar_queimadas", {})
        assert url is not None
        assert url.startswith("/api/geo/queimadas")

    def test_desmatamento_retorna_path_correto(self):
        url = construir_qgis_url("consultar_desmatamento", {})
        assert url is not None
        assert "/api/geo/desmatamento" in url

    def test_terra_indigena_retorna_path_correto(self):
        url = construir_qgis_url("consultar_terra_indigena", {})
        assert url is not None
        assert "/api/geo/terras-indigenas" in url

    def test_unidade_conservacao_retorna_path_correto(self):
        url = construir_qgis_url("consultar_unidade_conservacao", {})
        assert "/api/geo/unidades-conservacao" in url

    def test_quilombola_retorna_path_correto(self):
        url = construir_qgis_url("consultar_quilombola", {})
        assert "/api/geo/quilombolas" in url

    def test_prodes_retorna_path_correto(self):
        url = construir_qgis_url("consultar_prodes", {})
        assert "/api/geo/prodes" in url

    def test_imovel_rural_retorna_path_correto(self):
        url = construir_qgis_url("consultar_imovel_rural", {})
        assert "/api/geo/sicar" in url

    # ── Filtro municipio ────────────────────────────────────────────────────

    def test_municipio_adicionado_como_query_param(self):
        url = construir_qgis_url(
            "consultar_queimadas", {"municipios": ["Campinas"]}
        )
        parsed = urlparse(url)
        params = parse_qs(parsed.query)
        assert "municipio" in params
        assert params["municipio"][0] == "Campinas"

    def test_municipio_com_uf_entre_parenteses_removido(self):
        """'Campinas (SP)' deve virar 'Campinas' no filtro."""
        url = construir_qgis_url(
            "consultar_queimadas", {"municipios": ["Campinas (SP)"]}
        )
        parsed = urlparse(url)
        params = parse_qs(parsed.query)
        assert params["municipio"][0] == "Campinas"

    def test_municipio_multiplos_usa_primeiro(self):
        url = construir_qgis_url(
            "consultar_queimadas",
            {"municipios": ["Santos", "São Paulo"]},
        )
        parsed = urlparse(url)
        params = parse_qs(parsed.query)
        assert params["municipio"][0] == "Santos"

    def test_municipio_com_virgula_usa_primeiro_segmento(self):
        url = construir_qgis_url(
            "consultar_queimadas",
            {"municipios": ["Santos, SP"]},
        )
        parsed = urlparse(url)
        params = parse_qs(parsed.query)
        assert params["municipio"][0] == "Santos"

    def test_intencao_sem_filtro_municipio_nao_adiciona_param(self):
        """PRODES não suporta municipio, não deve aparecer na URL."""
        url = construir_qgis_url(
            "consultar_prodes", {"municipios": ["Campinas"]}
        )
        assert "municipio" not in url

    # ── Filtros de data ─────────────────────────────────────────────────────

    def test_periodo_data_inicio_adicionado(self):
        url = construir_qgis_url(
            "consultar_queimadas",
            {"periodo": {"inicio": "2024-01-01", "fim": "2024-12-31"}},
        )
        parsed = urlparse(url)
        params = parse_qs(parsed.query)
        assert "data_inicio" in params
        assert params["data_inicio"][0] == "2024-01-01"

    def test_periodo_data_fim_adicionado(self):
        url = construir_qgis_url(
            "consultar_queimadas",
            {"periodo": {"inicio": "2024-01-01", "fim": "2024-12-31"}},
        )
        parsed = urlparse(url)
        params = parse_qs(parsed.query)
        assert "data_fim" in params
        assert params["data_fim"][0] == "2024-12-31"

    def test_periodo_sem_data_nao_adiciona_params(self):
        url = construir_qgis_url("consultar_queimadas", {"periodo": {}})
        parsed = urlparse(url)
        params = parse_qs(parsed.query)
        assert "data_inicio" not in params
        assert "data_fim" not in params

    def test_prodes_ano_extraido_de_periodo(self):
        url = construir_qgis_url(
            "consultar_prodes",
            {"periodo": {"inicio": "2023-01-01"}},
        )
        parsed = urlparse(url)
        params = parse_qs(parsed.query)
        assert "ano" in params
        assert params["ano"][0] == "2023"

    def test_desmatamento_nao_adiciona_ano(self):
        """Desmatamento não tem filtro 'ano'."""
        url = construir_qgis_url(
            "consultar_desmatamento",
            {"periodo": {"inicio": "2023-01-01"}},
        )
        assert "ano" not in url

    # ── Filtro cod_imovel ───────────────────────────────────────────────────

    def test_cod_imovel_adicionado(self):
        url = construir_qgis_url(
            "consultar_imovel_rural",
            {"cod_imovel": "sp-1234"},
        )
        parsed = urlparse(url)
        params = parse_qs(parsed.query)
        assert "cod_imovel" in params
        assert params["cod_imovel"][0] == "SP-1234"

    def test_cod_imovel_convertido_para_maiusculo(self):
        url = construir_qgis_url(
            "consultar_imovel_rural", {"cod_imovel": "sp-abc-123"}
        )
        assert "SP-ABC-123" in url

    def test_cod_imovel_nao_adicionado_em_queimadas(self):
        """queimadas não aceita cod_imovel."""
        url = construir_qgis_url(
            "consultar_queimadas", {"cod_imovel": "SP-123"}
        )
        assert "cod_imovel" not in url

    # ── base_url ────────────────────────────────────────────────────────────

    def test_base_url_prefixo_adicionado(self):
        url = construir_qgis_url(
            "consultar_queimadas", {}, base_url="https://api.example.com"
        )
        assert url.startswith("https://api.example.com/api/geo/queimadas")

    def test_base_url_trailing_slash_removida(self):
        url = construir_qgis_url(
            "consultar_queimadas", {}, base_url="https://api.example.com/"
        )
        assert not url.startswith("https://api.example.com//")

    def test_sem_base_url_retorna_path_relativo(self):
        url = construir_qgis_url("consultar_queimadas", {})
        assert url.startswith("/api/geo/queimadas")

    # ── Casos de borda ──────────────────────────────────────────────────────

    def test_entidades_vazias_retorna_url_sem_params(self):
        url = construir_qgis_url("consultar_queimadas", {})
        assert "?" not in url

    def test_prodes_ano_invalido_nao_quebra(self):
        """Período com início inválido não deve levantar exceção."""
        url = construir_qgis_url(
            "consultar_prodes", {"periodo": {"inicio": "invalido"}}
        )
        # Pode retornar URL sem 'ano' ou com ele, mas não deve levantar exceção
        assert url is not None
        assert "/api/geo/prodes" in url

    def test_retorno_e_string(self):
        url = construir_qgis_url("consultar_queimadas", {"municipios": ["SP"]})
        assert isinstance(url, str)