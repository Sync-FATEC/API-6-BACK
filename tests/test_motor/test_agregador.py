"""Testes unitários para as funções novas/modificadas em asg_sistema/motor/agregador.py.

Escopo do PR: _injetar_qgis_url (nova) e a lógica de chamada dela em agregar().
"""

import os

os.environ.setdefault("ASG_JWT_SEGREDO", "chave-secreta-de-testes-nao-usar-em-producao")

from unittest.mock import MagicMock, patch

import pytest

from asg_sistema.motor.agregador import _injetar_qgis_url, agregar
from asg_sistema.motor.planner import ExecutionPlan


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────


def _plano(intencao="consultar_queimadas", confianca=0.9, eixo="unico", intencoes=None):
    """Cria um ExecutionPlan mínimo para uso nos testes."""
    return ExecutionPlan(
        subconsultas=[],
        eixo_agrupamento=eixo,
        intencao_principal=intencao,
        confianca_principal=confianca,
        intencoes_detectadas=intencoes or [],
    )


def _parcial_basico(**extras):
    """Dicionário simulando uma resposta parcial do executor."""
    base = {
        "resumo": "Resumo de teste",
        "estatisticas": {},
        "total_resultados": 5,
        "dados": [],
        "fontes": [],
        "geojson": None,
        "intencao_detectada": "consultar_queimadas",
        "confianca": 0.9,
        "entidades": {},
        "_raw_resultados": [],
        "_raw_resultados_geo": [],
        "_sub": {
            "intencao": "consultar_queimadas",
            "confianca": 0.9,
            "municipio": None,
            "cod_imovel": None,
            "rotulo": "Consulta 1",
        },
    }
    base.update(extras)
    return base


# ──────────────────────────────────────────────────────────────────────────────
# Testes para _injetar_qgis_url
# ──────────────────────────────────────────────────────────────────────────────


class TestInjetarQgisUrl:
    """Testes para a nova função _injetar_qgis_url."""

    def test_injeta_qgis_url_intencao_conhecida(self):
        plano = _plano("consultar_queimadas")
        resposta = {}
        _injetar_qgis_url(resposta, plano, {})
        assert "qgis_url" in resposta
        assert "/api/geo/queimadas" in resposta["qgis_url"]

    def test_nao_injeta_qgis_url_intencao_desconhecida(self):
        plano = _plano("resumo_municipal")
        resposta = {}
        _injetar_qgis_url(resposta, plano, {})
        assert "qgis_url" not in resposta

    def test_injeta_municipio_de_entidades_base(self):
        plano = _plano("consultar_queimadas")
        resposta = {}
        entidades = {"municipios": ["Campinas"]}
        _injetar_qgis_url(resposta, plano, entidades)
        assert "municipio=Campinas" in resposta["qgis_url"]

    def test_entidades_da_resposta_complementam_base(self):
        """Entidades dentro da resposta devem ser adicionadas às entidades base."""
        plano = _plano("consultar_queimadas")
        resposta = {"entidades": {"municipios": ["Santos"]}}
        _injetar_qgis_url(resposta, plano, {})
        assert "municipio=Santos" in resposta["qgis_url"]

    def test_entidades_base_tem_precedencia_sobre_resposta(self):
        """Entidades base não devem ser sobrescritas pelas da resposta (setdefault)."""
        plano = _plano("consultar_queimadas")
        resposta = {"entidades": {"municipios": ["Santos"]}}
        entidades_base = {"municipios": ["Campinas"]}
        _injetar_qgis_url(resposta, plano, entidades_base)
        # Campinas (de entidades_base) tem precedência
        assert "municipio=Campinas" in resposta["qgis_url"]

    def test_sem_grupos_nao_injeta_qgis_urls(self):
        plano = _plano("consultar_queimadas")
        resposta = {}
        _injetar_qgis_url(resposta, plano, {})
        assert "qgis_urls" not in resposta

    def test_grupos_com_intencao_geram_qgis_urls(self):
        plano = _plano("consultar_queimadas")
        resposta = {
            "grupos": [
                {
                    "rotulo": "Campinas",
                    "filtros": {
                        "intencao": "consultar_queimadas",
                        "municipio": "Campinas",
                        "cod_imovel": None,
                    },
                },
            ]
        }
        _injetar_qgis_url(resposta, plano, {})
        assert "qgis_urls" in resposta
        assert len(resposta["qgis_urls"]) == 1

    def test_grupos_sem_intencao_nao_geram_qgis_urls(self):
        plano = _plano("consultar_queimadas")
        resposta = {
            "grupos": [
                {"rotulo": "X", "filtros": {}},
            ]
        }
        _injetar_qgis_url(resposta, plano, {})
        assert "qgis_urls" not in resposta

    def test_grupo_com_cod_imovel_inclui_no_url(self):
        plano = _plano("consultar_imovel_rural")
        resposta = {
            "grupos": [
                {
                    "rotulo": "CAR",
                    "filtros": {
                        "intencao": "consultar_imovel_rural",
                        "municipio": None,
                        "cod_imovel": "SP-12345",
                    },
                },
            ]
        }
        _injetar_qgis_url(resposta, plano, {})
        assert "qgis_urls" in resposta
        grupo_url = resposta["qgis_urls"][0]["url"]
        assert "SP-12345" in grupo_url

    def test_grupo_recebe_qgis_url_injetado(self):
        """O grupo em si deve ter 'qgis_url' inserido."""
        plano = _plano("consultar_queimadas")
        grupo = {
            "rotulo": "SP",
            "filtros": {
                "intencao": "consultar_queimadas",
                "municipio": "São Paulo",
                "cod_imovel": None,
            },
        }
        resposta = {"grupos": [grupo]}
        _injetar_qgis_url(resposta, plano, {})
        assert "qgis_url" in grupo

    def test_entidades_nao_dict_ignoradas(self):
        """Se entidades_resposta não é dict, deve ser ignorado sem exceção."""
        plano = _plano("consultar_queimadas")
        resposta = {"entidades": "string-invalida"}
        # Não deve levantar exceção
        _injetar_qgis_url(resposta, plano, {})

    def test_entidades_base_none_sem_excecao(self):
        plano = _plano("consultar_queimadas")
        resposta = {}
        _injetar_qgis_url(resposta, plano, None)
        # Não deve levantar exceção
        assert "qgis_url" in resposta


# ──────────────────────────────────────────────────────────────────────────────
# Testes para agregar() — integração com _injetar_qgis_url
# ──────────────────────────────────────────────────────────────────────────────


class TestAgregarComQgisUrl:
    """Testa que agregar() chama _injetar_qgis_url corretamente."""

    def test_agregar_parcial_unico_injeta_qgis_url(self):
        plano = _plano("consultar_queimadas")
        parcial = _parcial_basico()
        gerador = MagicMock()

        resultado = agregar(
            pergunta="Queimadas em SP?",
            plano=plano,
            entidades_base={"municipios": ["Campinas"]},
            parciais=[parcial],
            gerador=gerador,
        )

        assert "qgis_url" in resultado
        assert "/api/geo/queimadas" in resultado["qgis_url"]

    def test_agregar_parcial_unico_municipio_no_url(self):
        plano = _plano("consultar_queimadas")
        parcial = _parcial_basico()

        resultado = agregar(
            pergunta="Queimadas?",
            plano=plano,
            entidades_base={"municipios": ["Santos"]},
            parciais=[parcial],
            gerador=MagicMock(),
        )

        assert "municipio=Santos" in resultado["qgis_url"]

    def test_agregar_zero_parciais_sem_qgis_url(self):
        """Resposta vazia não deve ter qgis_url."""
        plano = _plano("consultar_queimadas")
        resultado = agregar(
            pergunta="X",
            plano=plano,
            entidades_base={},
            parciais=[],
            gerador=MagicMock(),
        )
        assert "qgis_url" not in resultado

    def test_agregar_intencao_sem_endpoint_nao_injeta_url(self):
        plano = _plano("resumo_municipal")
        parcial = _parcial_basico()

        resultado = agregar(
            pergunta="Resumo?",
            plano=plano,
            entidades_base={},
            parciais=[parcial],
            gerador=MagicMock(),
        )

        assert "qgis_url" not in resultado

    def test_agregar_multi_parciais_injeta_qgis_url(self):
        plano = _plano("consultar_queimadas")

        parcial1 = _parcial_basico(
            **{
                "_sub": {
                    "intencao": "consultar_queimadas",
                    "confianca": 0.9,
                    "municipio": "Campinas",
                    "cod_imovel": None,
                    "rotulo": "Campinas",
                },
                "_raw_resultados": [{"id": 1, "similaridade": 0.9}],
                "_raw_resultados_geo": [],
            }
        )
        parcial2 = _parcial_basico(
            **{
                "_sub": {
                    "intencao": "consultar_queimadas",
                    "confianca": 0.8,
                    "municipio": "Santos",
                    "cod_imovel": None,
                    "rotulo": "Santos",
                },
                "_raw_resultados": [{"id": 2, "similaridade": 0.8}],
                "_raw_resultados_geo": [],
            }
        )

        gerador_mock = MagicMock()
        gerador_mock.gerar.return_value = {
            "resumo": "Consolidado",
            "total_resultados": 2,
            "geojson": None,
            "entidades": {},
        }

        resultado = agregar(
            pergunta="Queimadas em SP?",
            plano=plano,
            entidades_base={},
            parciais=[parcial1, parcial2],
            gerador=gerador_mock,
        )

        assert "qgis_url" in resultado