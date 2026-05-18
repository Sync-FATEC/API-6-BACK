"""Testes unitarios para a injecao de qgis_url no agregador.

Regras de negocio cobertas:
1. Resposta com 1 sub-consulta -> qgis_url da intencao principal.
2. Resposta multi-grupo -> qgis_url principal + qgis_urls (uma por grupo).
3. Cada grupo tambem ganha qgis_url no proprio objeto.
4. Intencao sem mapeamento -> nem qgis_url nem qgis_urls aparecem.
5. Filtros do grupo (municipio/cod_imovel) sobrescrevem entidades base.
"""

from urllib.parse import parse_qs, urlsplit

from asg_sistema.motor.agregador import agregar
from asg_sistema.motor.planner import ExecutionPlan


# --------------------------------------------------------------------------
# Builders
# --------------------------------------------------------------------------

def um_plano(
    intencao_principal: str = "consultar_queimadas",
    confianca: float = 0.85,
    eixo_agrupamento: str = "unico",
) -> ExecutionPlan:
    return ExecutionPlan(
        subconsultas=[],
        eixo_agrupamento=eixo_agrupamento,  # type: ignore[arg-type]
        intencao_principal=intencao_principal,
        confianca_principal=confianca,
        intencoes_detectadas=[],
    )


def uma_parcial(
    intencao: str = "consultar_queimadas",
    municipio: str | None = None,
    cod_imovel: str | None = None,
    rotulo: str = "principal",
    confianca: float = 0.85,
) -> dict:
    return {
        "intencao_detectada": intencao,
        "confianca": confianca,
        "entidades": {},
        "resumo": "Resumo gerado",
        "estatisticas": {},
        "dados": [],
        "fontes": [],
        "geojson": None,
        "total_resultados": 0,
        "_sub": {
            "rotulo": rotulo,
            "municipio": municipio,
            "intencao": intencao,
            "confianca": confianca,
            "cod_imovel": cod_imovel,
        },
        "_raw_resultados": [],
        "_raw_resultados_geo": [],
    }


class GeradorFalso:
    """Fake do GeradorResposta — implementa apenas o metodo usado por agregar()."""

    def gerar(self, **kwargs):  # noqa: ANN003
        return {
            "intencao_detectada": kwargs.get("intencao"),
            "confianca": kwargs.get("confianca", 0.5),
            "entidades": kwargs.get("entidades", {}),
            "resumo": "Resposta consolidada",
            "estatisticas": {},
            "dados": [],
            "fontes": [],
            "geojson": None,
            "total_resultados": 0,
        }


def _parse_qs(url: str) -> dict[str, list[str]]:
    return parse_qs(urlsplit(url).query)


# --------------------------------------------------------------------------
# Sub unica
# --------------------------------------------------------------------------

class TestRespostaUnica:
    def test_deve_injetar_qgis_url_principal_quando_uma_unica_subconsulta(self):
        # Arrange
        plano = um_plano(intencao_principal="consultar_queimadas")
        entidades = {"municipios": ["Ubatuba"]}
        parciais = [uma_parcial(intencao="consultar_queimadas")]

        # Act
        resposta = agregar("queimadas em ubatuba", plano, entidades, parciais, GeradorFalso())

        # Assert
        assert "qgis_url" in resposta
        assert resposta["qgis_url"].startswith("/api/geo/queimadas")
        assert _parse_qs(resposta["qgis_url"])["municipio"] == ["Ubatuba"]

    def test_deve_omitir_qgis_url_quando_intencao_nao_tem_endpoint_geo(self):
        # Arrange
        plano = um_plano(intencao_principal="resumo_municipal")
        parciais = [uma_parcial(intencao="resumo_municipal")]

        # Act
        resposta = agregar("resumo de campinas", plano, {}, parciais, GeradorFalso())

        # Assert
        assert "qgis_url" not in resposta

    def test_deve_nao_ter_qgis_urls_em_resposta_de_sub_unica(self):
        # Arrange
        plano = um_plano(intencao_principal="consultar_queimadas")
        parciais = [uma_parcial(intencao="consultar_queimadas")]

        # Act
        resposta = agregar("q", plano, {}, parciais, GeradorFalso())

        # Assert
        assert "qgis_urls" not in resposta


# --------------------------------------------------------------------------
# Multi-grupo
# --------------------------------------------------------------------------

class TestRespostaMultiGrupo:
    def test_deve_injetar_qgis_urls_quando_resposta_tem_multiplos_grupos(self):
        # Arrange
        plano = um_plano(intencao_principal="consultar_queimadas", eixo_agrupamento="municipio")
        entidades = {}
        parciais = [
            uma_parcial(intencao="consultar_queimadas", municipio="Campinas", rotulo="Campinas"),
            uma_parcial(intencao="consultar_queimadas", municipio="Sorocaba", rotulo="Sorocaba"),
        ]

        # Act
        resposta = agregar("queimadas em campinas e sorocaba", plano, entidades, parciais, GeradorFalso())

        # Assert
        assert isinstance(resposta.get("qgis_urls"), list)
        assert len(resposta["qgis_urls"]) == 2
        rotulos = [u["rotulo"] for u in resposta["qgis_urls"]]
        assert "Campinas" in rotulos and "Sorocaba" in rotulos

    def test_deve_usar_municipio_do_grupo_quando_diferente_das_entidades_base(self):
        # Arrange
        plano = um_plano(intencao_principal="consultar_queimadas", eixo_agrupamento="municipio")
        entidades = {"municipios": ["EntidadeBase"]}
        parciais = [
            uma_parcial(intencao="consultar_queimadas", municipio="Campinas", rotulo="Campinas"),
            uma_parcial(intencao="consultar_queimadas", municipio="Sorocaba", rotulo="Sorocaba"),
        ]

        # Act
        resposta = agregar("q", plano, entidades, parciais, GeradorFalso())

        # Assert
        urls = {u["rotulo"]: u["url"] for u in resposta["qgis_urls"]}
        assert _parse_qs(urls["Campinas"])["municipio"] == ["Campinas"]
        assert _parse_qs(urls["Sorocaba"])["municipio"] == ["Sorocaba"]

    def test_deve_anexar_qgis_url_no_proprio_objeto_de_cada_grupo(self):
        # Arrange
        plano = um_plano(intencao_principal="consultar_queimadas", eixo_agrupamento="municipio")
        parciais = [
            uma_parcial(intencao="consultar_queimadas", municipio="Campinas", rotulo="Campinas"),
            uma_parcial(intencao="consultar_queimadas", municipio="Sorocaba", rotulo="Sorocaba"),
        ]

        # Act
        resposta = agregar("q", plano, {}, parciais, GeradorFalso())

        # Assert
        grupos = resposta.get("grupos") or []
        assert len(grupos) == 2
        for g in grupos:
            assert "qgis_url" in g
            assert g["qgis_url"].startswith("/api/geo/queimadas")

    def test_deve_ignorar_grupo_cuja_intencao_nao_tem_endpoint_geo(self):
        # Arrange — um grupo com intencao mapeada, outro sem
        plano = um_plano(intencao_principal="consultar_queimadas", eixo_agrupamento="intencao")
        parciais = [
            uma_parcial(intencao="consultar_queimadas", municipio="Campinas", rotulo="Queimadas"),
            uma_parcial(intencao="resumo_municipal", municipio="Campinas", rotulo="Resumo"),
        ]

        # Act
        resposta = agregar("q", plano, {}, parciais, GeradorFalso())

        # Assert
        urls = resposta.get("qgis_urls") or []
        rotulos = [u["rotulo"] for u in urls]
        assert "Queimadas" in rotulos
        assert "Resumo" not in rotulos
