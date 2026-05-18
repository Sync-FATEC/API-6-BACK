"""Testes unitários e de integração para asg_sistema/api/rotas_geo.py.

Testa as funções auxiliares puras e os endpoints via TestClient com mock
de executar_consulta.
"""

import os

os.environ.setdefault("ASG_JWT_SEGREDO", "chave-secreta-de-testes-nao-usar-em-producao")

import json
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

import asg_sistema.api.rotas_geo as rotas_geo
from asg_sistema.api.rotas_geo import (
    _aplicar_bbox,
    _filtro_bbox,
    _montar_feature_collection,
    _nome_simples,
    _parse_bbox,
    _resposta_geojson,
    router,
)


# ──────────────────────────────────────────────────────────────────────────────
# App para testes
# ──────────────────────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def client():
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


# ──────────────────────────────────────────────────────────────────────────────
# _parse_bbox
# ──────────────────────────────────────────────────────────────────────────────


class TestParseBbox:
    def test_none_retorna_none(self):
        assert _parse_bbox(None) is None

    def test_string_vazia_retorna_none(self):
        assert _parse_bbox("") is None

    def test_bbox_valido(self):
        resultado = _parse_bbox("-48.5,-23.5,-47.5,-22.5")
        assert resultado == (-48.5, -23.5, -47.5, -22.5)

    def test_bbox_partes_insuficientes_levanta_400(self):
        with pytest.raises(HTTPException) as exc:
            _parse_bbox("1,2,3")
        assert exc.value.status_code == 400

    def test_bbox_partes_demais_levanta_400(self):
        with pytest.raises(HTTPException) as exc:
            _parse_bbox("1,2,3,4,5")
        assert exc.value.status_code == 400

    def test_bbox_valores_nao_numericos_levanta_400(self):
        with pytest.raises(HTTPException) as exc:
            _parse_bbox("a,b,c,d")
        assert exc.value.status_code == 400

    def test_bbox_minx_maior_maxx_levanta_400(self):
        with pytest.raises(HTTPException) as exc:
            _parse_bbox("10,0,5,10")
        assert exc.value.status_code == 400

    def test_bbox_miny_maior_maxy_levanta_400(self):
        with pytest.raises(HTTPException) as exc:
            _parse_bbox("0,10,10,5")
        assert exc.value.status_code == 400

    def test_bbox_minx_igual_maxx_levanta_400(self):
        with pytest.raises(HTTPException) as exc:
            _parse_bbox("5,0,5,10")
        assert exc.value.status_code == 400

    def test_bbox_retorna_floats(self):
        resultado = _parse_bbox("-48,-23,-47,-22")
        assert all(isinstance(v, float) for v in resultado)


# ──────────────────────────────────────────────────────────────────────────────
# _filtro_bbox
# ──────────────────────────────────────────────────────────────────────────────


class TestFiltroBbox:
    def test_retorna_string_sql(self):
        resultado = _filtro_bbox("geom")
        assert isinstance(resultado, str)
        assert "geom" in resultado

    def test_contem_st_makeenvelope(self):
        resultado = _filtro_bbox("geom")
        assert "ST_MakeEnvelope" in resultado

    def test_srid_padrao_4674(self):
        resultado = _filtro_bbox("geom")
        assert "4674" in resultado

    def test_srid_customizado(self):
        resultado = _filtro_bbox("geom", srid=4326)
        assert "4326" in resultado

    def test_contem_coluna_geom_correta(self):
        resultado = _filtro_bbox("minha_geom")
        assert "minha_geom" in resultado


# ──────────────────────────────────────────────────────────────────────────────
# _aplicar_bbox
# ──────────────────────────────────────────────────────────────────────────────


class TestAplicarBbox:
    def test_bbox_none_nao_modifica_params(self):
        params = {}
        _aplicar_bbox(params, None)
        assert params == {}

    def test_bbox_valido_popula_params(self):
        params = {}
        _aplicar_bbox(params, (-48.5, -23.5, -47.5, -22.5))
        assert params["bbox_minx"] == -48.5
        assert params["bbox_miny"] == -23.5
        assert params["bbox_maxx"] == -47.5
        assert params["bbox_maxy"] == -22.5

    def test_bbox_populado_quatro_chaves(self):
        params = {}
        _aplicar_bbox(params, (1.0, 2.0, 3.0, 4.0))
        assert len(params) == 4


# ──────────────────────────────────────────────────────────────────────────────
# _montar_feature_collection
# ──────────────────────────────────────────────────────────────────────────────


class TestMontarFeatureCollection:
    def _geom_point(self):
        return json.dumps({"type": "Point", "coordinates": [-47.0, -23.0]})

    def test_lista_vazia_retorna_collection_vazia(self):
        fc = _montar_feature_collection([])
        assert fc["type"] == "FeatureCollection"
        assert fc["features"] == []
        assert fc["totalFeatures"] == 0

    def test_rows_com_geometry_retorna_features(self):
        rows = [
            {"geometry": self._geom_point(), "municipio": "Campinas", "frp": "5.0"}
        ]
        fc = _montar_feature_collection(rows)
        assert len(fc["features"]) == 1

    def test_row_sem_geometry_ignorado(self):
        rows = [{"municipio": "SP", "frp": "1.0"}]
        fc = _montar_feature_collection(rows)
        assert fc["features"] == []

    def test_geometry_none_ignorado(self):
        rows = [{"geometry": None, "municipio": "SP"}]
        fc = _montar_feature_collection(rows)
        assert fc["features"] == []

    def test_fonte_adicionada_nas_propriedades(self):
        rows = [{"geometry": self._geom_point(), "municipio": "SP"}]
        fc = _montar_feature_collection(rows, fonte="queimadas")
        assert fc["features"][0]["properties"]["fonte"] == "queimadas"

    def test_sem_fonte_nao_adiciona_campo(self):
        rows = [{"geometry": self._geom_point(), "municipio": "SP"}]
        fc = _montar_feature_collection(rows, fonte="")
        assert "fonte" not in fc["features"][0]["properties"]

    def test_valores_none_mantidos(self):
        rows = [{"geometry": self._geom_point(), "campo": None}]
        fc = _montar_feature_collection(rows)
        assert fc["features"][0]["properties"]["campo"] is None

    def test_valores_nao_none_convertidos_para_string(self):
        rows = [{"geometry": self._geom_point(), "numero": 42}]
        fc = _montar_feature_collection(rows)
        assert fc["features"][0]["properties"]["numero"] == "42"

    def test_total_features_correto(self):
        rows = [
            {"geometry": self._geom_point(), "a": "1"},
            {"geometry": self._geom_point(), "a": "2"},
        ]
        fc = _montar_feature_collection(rows)
        assert fc["totalFeatures"] == 2

    def test_geometry_removida_das_props(self):
        rows = [{"geometry": self._geom_point(), "outro": "val"}]
        fc = _montar_feature_collection(rows)
        assert "geometry" not in fc["features"][0]["properties"]

    def test_tipo_feature(self):
        rows = [{"geometry": self._geom_point()}]
        fc = _montar_feature_collection(rows)
        assert fc["features"][0]["type"] == "Feature"


# ──────────────────────────────────────────────────────────────────────────────
# _nome_simples
# ──────────────────────────────────────────────────────────────────────────────


class TestNomeSimples:
    def test_nome_sem_uf(self):
        assert _nome_simples("Campinas") == "Campinas"

    def test_nome_com_uf_parenteses(self):
        assert _nome_simples("Campinas (SP)") == "Campinas"

    def test_nome_com_virgula(self):
        assert _nome_simples("Santos, SP") == "Santos"

    def test_nome_vazio(self):
        assert _nome_simples("") == ""

    def test_nome_com_espaco_antes_uf(self):
        assert _nome_simples("São Paulo (SP)") == "São Paulo"


# ──────────────────────────────────────────────────────────────────────────────
# Endpoints via TestClient
# ──────────────────────────────────────────────────────────────────────────────

GEOM_POINT = json.dumps({"type": "Point", "coordinates": [-47.0, -23.0]})
GEOM_POLY = json.dumps({"type": "MultiPolygon", "coordinates": [[[[0, 0], [1, 0], [1, 1], [0, 0]]]]})


def _row_queimada(**kwargs):
    base = {
        "geometry": GEOM_POINT,
        "id": 1,
        "municipio": "Campinas",
        "satelite": "NPP-375",
        "data_hora": "2024-01-15 10:00:00",
        "bioma": "Cerrado",
        "frp": "5.0",
        "risco_fogo": "Alto",
        "latitude": "-23.0",
        "longitude": "-47.0",
    }
    base.update(kwargs)
    return base


class TestEndpointQueimadas:
    def test_retorna_200(self, client):
        with patch.object(rotas_geo, "executar_consulta", return_value=[]):
            resp = client.get("/queimadas")
        assert resp.status_code == 200

    def test_retorna_feature_collection(self, client):
        with patch.object(rotas_geo, "executar_consulta", return_value=[]):
            resp = client.get("/queimadas")
        assert resp.json()["type"] == "FeatureCollection"

    def test_media_type_geo_json(self, client):
        with patch.object(rotas_geo, "executar_consulta", return_value=[]):
            resp = client.get("/queimadas")
        assert "geo+json" in resp.headers["content-type"]

    def test_com_dados_retorna_features(self, client):
        rows = [_row_queimada()]
        with patch.object(rotas_geo, "executar_consulta", return_value=rows):
            resp = client.get("/queimadas")
        data = resp.json()
        assert len(data["features"]) == 1

    def test_filtro_municipio_passado(self, client):
        capturado = {}

        def _mock(sql, params=None):
            capturado.update(params or {})
            return []

        with patch.object(rotas_geo, "executar_consulta", side_effect=_mock):
            client.get("/queimadas?municipio=Campinas")

        assert "mun" in capturado
        assert "Campinas" in capturado["mun"]

    def test_filtro_data_inicio_passado(self, client):
        capturado = {}

        def _mock(sql, params=None):
            capturado.update(params or {})
            return []

        with patch.object(rotas_geo, "executar_consulta", side_effect=_mock):
            client.get("/queimadas?data_inicio=2024-01-01")

        assert "data_inicio" in capturado

    def test_bbox_invalido_retorna_400(self, client):
        resp = client.get("/queimadas?bbox=invalido")
        assert resp.status_code == 400

    def test_limite_muito_alto_retorna_422(self, client):
        resp = client.get("/queimadas?limite=99999")
        assert resp.status_code == 422

    def test_offset_negativo_retorna_422(self, client):
        resp = client.get("/queimadas?offset=-1")
        assert resp.status_code == 422


class TestEndpointTerrasIndigenas:
    def test_retorna_200(self, client):
        with patch.object(rotas_geo, "executar_consulta", return_value=[]):
            resp = client.get("/terras-indigenas")
        assert resp.status_code == 200

    def test_rota_alternativa_retorna_200(self, client):
        with patch.object(rotas_geo, "executar_consulta", return_value=[]):
            resp = client.get("/terras_indigenas")
        assert resp.status_code == 200

    def test_filtro_municipio_passado(self, client):
        capturado = {}

        def _mock(sql, params=None):
            capturado.update(params or {})
            return []

        with patch.object(rotas_geo, "executar_consulta", side_effect=_mock):
            client.get("/terras-indigenas?municipio=Santos")

        assert "mun" in capturado


class TestEndpointDesmatamento:
    def test_retorna_200(self, client):
        with patch.object(rotas_geo, "executar_consulta", return_value=[]):
            resp = client.get("/desmatamento")
        assert resp.status_code == 200

    def test_filtro_classe_passado(self, client):
        capturado = {}

        def _mock(sql, params=None):
            capturado.update(params or {})
            return []

        with patch.object(rotas_geo, "executar_consulta", side_effect=_mock):
            client.get("/desmatamento?classe=DESFLORESTAMENTO")

        assert "classe" in capturado


class TestEndpointProdes:
    def test_retorna_200(self, client):
        with patch.object(rotas_geo, "executar_consulta", return_value=[]):
            resp = client.get("/prodes")
        assert resp.status_code == 200

    def test_filtro_ano_passado(self, client):
        capturado = {}

        def _mock(sql, params=None):
            capturado.update(params or {})
            return []

        with patch.object(rotas_geo, "executar_consulta", side_effect=_mock):
            client.get("/prodes?ano=2023")

        assert "ano" in capturado
        assert capturado["ano"] == 2023


class TestEndpointSicar:
    def test_retorna_200(self, client):
        with patch.object(rotas_geo, "executar_consulta", return_value=[]):
            resp = client.get("/sicar")
        assert resp.status_code == 200

    def test_cod_imovel_convertido_para_maiusculo(self, client):
        capturado = {}

        def _mock(sql, params=None):
            capturado.update(params or {})
            return []

        with patch.object(rotas_geo, "executar_consulta", side_effect=_mock):
            client.get("/sicar?cod_imovel=sp-123")

        assert "cod" in capturado
        assert capturado["cod"] == "SP-123"

    def test_simplify_invalido_retorna_422(self, client):
        resp = client.get("/sicar?simplify=0.1")
        assert resp.status_code == 422


class TestEndpointCatalogo:
    def test_retorna_200(self, client):
        resp = client.get("/catalogo")
        assert resp.status_code == 200

    def test_retorna_versao(self, client):
        resp = client.get("/catalogo")
        assert "versao" in resp.json()

    def test_retorna_camadas(self, client):
        resp = client.get("/catalogo")
        data = resp.json()
        assert "camadas" in data
        assert len(data["camadas"]) > 0

    def test_camadas_tem_id(self, client):
        resp = client.get("/catalogo")
        for camada in resp.json()["camadas"]:
            assert "id" in camada

    def test_srid_saida_4326(self, client):
        resp = client.get("/catalogo")
        assert resp.json()["srid_saida"] == 4326


class TestEndpointUnidadesConservacao:
    def test_retorna_200(self, client):
        with patch.object(rotas_geo, "executar_consulta", return_value=[]):
            resp = client.get("/unidades-conservacao")
        assert resp.status_code == 200

    def test_rota_alternativa(self, client):
        with patch.object(rotas_geo, "executar_consulta", return_value=[]):
            resp = client.get("/unidades_conservacao")
        assert resp.status_code == 200

    def test_retorna_feature_collection(self, client):
        with patch.object(rotas_geo, "executar_consulta", return_value=[]):
            resp = client.get("/unidades-conservacao")
        assert resp.json()["type"] == "FeatureCollection"


class TestEndpointQuilombolas:
    def test_retorna_200(self, client):
        with patch.object(rotas_geo, "executar_consulta", return_value=[]):
            resp = client.get("/quilombolas")
        assert resp.status_code == 200

    def test_retorna_feature_collection(self, client):
        with patch.object(rotas_geo, "executar_consulta", return_value=[]):
            resp = client.get("/quilombolas")
        assert resp.json()["type"] == "FeatureCollection"