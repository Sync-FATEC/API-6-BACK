"""Testes unitarios para a injecao de qgis_url no agregador.

Regras de negocio cobertas:
1. Resposta com 1 sub-consulta -> qgis_url aponta para /api/geo/consulta com a pergunta.
2. Resposta multi-grupo -> qgis_url unica aponta para /api/geo/consulta (mesmo geojson).
3. Pergunta vazia -> nao injeta qgis_url.
4. cod_imovel nas entidades vira parametro adicional na qgis_url.
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


def _parse(url: str) -> tuple[str, dict[str, list[str]]]:
    parts = urlsplit(url)
    return parts.path, parse_qs(parts.query)


# --------------------------------------------------------------------------
# Sub unica
# --------------------------------------------------------------------------

class TestRespostaUnica:
    def test_deve_injetar_qgis_url_apontando_para_endpoint_de_consulta(self):
        # Arrange
        plano = um_plano(intencao_principal="consultar_queimadas")
        parciais = [uma_parcial(intencao="consultar_queimadas")]

        # Act
        resposta = agregar("queimadas em ubatuba", plano, {}, parciais, GeradorFalso())

        # Assert
        assert "qgis_url" in resposta
        path, query = _parse(resposta["qgis_url"])
        assert path == "/api/geo/consulta"
        assert query["pergunta"] == ["queimadas em ubatuba"]

    def test_deve_passar_cod_imovel_quando_presente_nas_entidades(self):
        # Arrange
        plano = um_plano(intencao_principal="consultar_imovel_rural")
        parciais = [uma_parcial(intencao="consultar_imovel_rural")]
        entidades = {"cod_imovel": "SP-3555406-ABC"}

        # Act
        resposta = agregar("ameacas no SP-3555406-ABC", plano, entidades, parciais, GeradorFalso())

        # Assert
        _, query = _parse(resposta["qgis_url"])
        assert query["cod_imovel"] == ["SP-3555406-ABC"]

    def test_deve_nao_ter_qgis_urls_em_resposta_de_sub_unica(self):
        # Arrange
        plano = um_plano(intencao_principal="consultar_queimadas")
        parciais = [uma_parcial(intencao="consultar_queimadas")]

        # Act
        resposta = agregar("q", plano, {}, parciais, GeradorFalso())

        # Assert — nao expomos mais qgis_urls, apenas o unico campo qgis_url
        assert "qgis_urls" not in resposta


# --------------------------------------------------------------------------
# Multi-grupo
# --------------------------------------------------------------------------

class TestRespostaMultiGrupo:
    def test_deve_injetar_unica_qgis_url_quando_resposta_tem_multiplos_grupos(self):
        # Arrange
        plano = um_plano(intencao_principal="consultar_queimadas", eixo_agrupamento="municipio")
        parciais = [
            uma_parcial(intencao="consultar_queimadas", municipio="Campinas", rotulo="Campinas"),
            uma_parcial(intencao="consultar_queimadas", municipio="Sorocaba", rotulo="Sorocaba"),
        ]

        # Act
        resposta = agregar(
            "queimadas em campinas e sorocaba", plano, {}, parciais, GeradorFalso(),
        )

        # Assert — a URL unica encapsula multi-grupo via /api/geo/consulta
        assert "qgis_url" in resposta
        path, query = _parse(resposta["qgis_url"])
        assert path == "/api/geo/consulta"
        assert query["pergunta"] == ["queimadas em campinas e sorocaba"]


# --------------------------------------------------------------------------
# Casos negativos
# --------------------------------------------------------------------------

class TestFiltroZerosResumoMunicipal:
    def test_deve_remover_grupos_sem_resultados_quando_intencao_principal_e_resumo_municipal(self):
        plano = um_plano(
            intencao_principal="resumo_municipal", eixo_agrupamento="intencao",
        )
        com_dados = uma_parcial(intencao="consultar_queimadas", rotulo="queimadas")
        com_dados["total_resultados"] = 37
        sem_dados = uma_parcial(intencao="consultar_quilombola", rotulo="quilombolas")
        sem_dados["total_resultados"] = 0

        resposta = agregar(
            "situação de caçapava", plano, {}, [com_dados, sem_dados], GeradorFalso(),
        )

        rotulos = [g["rotulo"] for g in resposta["grupos"]]
        assert rotulos == ["queimadas"]

    def test_deve_filtrar_intencoes_detectadas_para_apenas_temas_com_dados(self):
        plano = um_plano(
            intencao_principal="resumo_municipal", eixo_agrupamento="intencao",
        )
        plano.intencoes_detectadas = [
            {"intencao": "consultar_queimadas", "confianca": 0.9},
            {"intencao": "consultar_quilombola", "confianca": 0.9},
        ]
        com_dados = uma_parcial(intencao="consultar_queimadas", rotulo="queimadas")
        com_dados["total_resultados"] = 37
        sem_dados = uma_parcial(intencao="consultar_quilombola", rotulo="quilombolas")
        sem_dados["total_resultados"] = 0

        resposta = agregar(
            "situação de caçapava", plano, {}, [com_dados, sem_dados], GeradorFalso(),
        )

        intents = {d["intencao"] for d in resposta["intencoes_detectadas"]}
        assert intents == {"consultar_queimadas"}

    def test_deve_preservar_grupos_zero_em_intencao_normal(self):
        # Multi-municipio com queimadas: "Sorocaba: sem registros" é informação válida.
        plano = um_plano(
            intencao_principal="consultar_queimadas", eixo_agrupamento="municipio",
        )
        com_dados = uma_parcial(
            intencao="consultar_queimadas", municipio="Campinas", rotulo="Campinas",
        )
        com_dados["total_resultados"] = 12
        sem_dados = uma_parcial(
            intencao="consultar_queimadas", municipio="Sorocaba", rotulo="Sorocaba",
        )
        sem_dados["total_resultados"] = 0

        resposta = agregar(
            "queimadas em campinas e sorocaba",
            plano, {}, [com_dados, sem_dados], GeradorFalso(),
        )

        rotulos = {g["rotulo"] for g in resposta["grupos"]}
        assert rotulos == {"Campinas", "Sorocaba"}


class TestCasosNegativos:
    def test_deve_omitir_qgis_url_quando_pergunta_eh_string_vazia(self):
        # Arrange
        plano = um_plano(intencao_principal="consultar_queimadas")
        parciais = [uma_parcial(intencao="consultar_queimadas")]

        # Act
        resposta = agregar("", plano, {}, parciais, GeradorFalso())

        # Assert
        assert "qgis_url" not in resposta
