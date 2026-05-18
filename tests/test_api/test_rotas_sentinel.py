"""Testes unitários e de integração para asg_sistema/api/rotas_sentinel.py."""

import os

os.environ.setdefault("ASG_JWT_SEGREDO", "chave-secreta-de-testes-nao-usar-em-producao")

import io
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch, mock_open

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import asg_sistema.api.rotas_sentinel as rotas_sentinel
from asg_sistema.api.rotas_sentinel import _chave_cache, _gerar_imagem_sentinel, router


# ──────────────────────────────────────────────────────────────────────────────
# App mínima para testes
# ──────────────────────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def client():
    app = FastAPI()
    app.include_router(router)
    return TestClient(app, raise_server_exceptions=False)


# ──────────────────────────────────────────────────────────────────────────────
# _chave_cache
# ──────────────────────────────────────────────────────────────────────────────


class TestChaveCache:
    def test_retorna_string(self):
        chave = _chave_cache(-23.5, -47.0, "2024-01-15")
        assert isinstance(chave, str)

    def test_termina_com_png(self):
        chave = _chave_cache(-23.5, -47.0, "2024-01-15")
        assert chave.endswith(".png")

    def test_sem_tracos_negativos_na_chave(self):
        """Traços negativos devem ser substituídos por 'm'."""
        chave = _chave_cache(-23.5, -47.0, "2024-01-15")
        # O sinal negativo deve ser representado como 'm', não '-'
        assert "-" not in chave.replace(".png", "").replace("_", "")

    def test_data_no_nome(self):
        chave = _chave_cache(-23.0, -47.0, "2024-03-15")
        assert "20240315" in chave

    def test_mesma_entrada_mesma_chave(self):
        c1 = _chave_cache(-23.5, -47.0, "2024-01-15")
        c2 = _chave_cache(-23.5, -47.0, "2024-01-15")
        assert c1 == c2

    def test_entradas_diferentes_chaves_diferentes(self):
        c1 = _chave_cache(-23.5, -47.0, "2024-01-15")
        c2 = _chave_cache(-24.0, -47.0, "2024-01-15")
        assert c1 != c2

    def test_data_truncada_para_10_chars(self):
        """Data com hora deve usar apenas os 10 primeiros caracteres (YYYY-MM-DD)."""
        c1 = _chave_cache(-23.0, -47.0, "2024-01-15")
        c2 = _chave_cache(-23.0, -47.0, "2024-01-15T10:30:00")
        assert c1 == c2


# ──────────────────────────────────────────────────────────────────────────────
# Endpoint /queimadas/{id}/imagem-satelite
# ──────────────────────────────────────────────────────────────────────────────

_PNG_MINIMO = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100


class TestImagemSateliteQueimada:
    """Testes do endpoint imagem_satelite_queimada."""

    def _patch_consulta(self, rows):
        return patch.object(rotas_sentinel, "executar_consulta", return_value=rows)

    def _patch_gerar(self, retorno=_PNG_MINIMO):
        return patch.object(rotas_sentinel, "_gerar_imagem_sentinel", return_value=retorno)

    def _patch_cache_nao_existe(self):
        """Simula cache inexistente (Path.exists retorna False)."""
        return patch.object(Path, "exists", return_value=False)

    def _patch_cache_existe(self):
        """Simula hit de cache (Path.exists retorna True, open retorna bytes)."""
        return patch.object(Path, "exists", return_value=True)

    # ── Cache miss: busca no banco, gera imagem ──────────────────────────────

    def test_queimada_encontrada_retorna_200(self, client):
        row = {"latitude": -23.0, "longitude": -47.0, "data_hora": "2024-01-15 10:00:00"}
        with self._patch_consulta([row]), \
             self._patch_cache_nao_existe(), \
             self._patch_gerar(), \
             patch.object(Path, "write_bytes"):
            resp = client.get("/queimadas/1/imagem-satelite")
        assert resp.status_code == 200

    def test_queimada_encontrada_media_type_png(self, client):
        row = {"latitude": -23.0, "longitude": -47.0, "data_hora": "2024-01-15 10:00:00"}
        with self._patch_consulta([row]), \
             self._patch_cache_nao_existe(), \
             self._patch_gerar(), \
             patch.object(Path, "write_bytes"):
            resp = client.get("/queimadas/1/imagem-satelite")
        assert "image/png" in resp.headers["content-type"]

    def test_queimada_nao_encontrada_retorna_404(self, client):
        with self._patch_consulta([]), self._patch_cache_nao_existe():
            resp = client.get("/queimadas/999/imagem-satelite")
        assert resp.status_code == 404

    def test_gerar_imagem_falha_sem_imagem_retorna_404(self, client):
        row = {"latitude": -23.0, "longitude": -47.0, "data_hora": "2024-01-15"}
        with self._patch_consulta([row]), \
             self._patch_cache_nao_existe(), \
             patch.object(
                 rotas_sentinel, "_gerar_imagem_sentinel",
                 side_effect=ValueError("Nenhuma imagem encontrada")
             ):
            resp = client.get("/queimadas/1/imagem-satelite")
        assert resp.status_code == 404

    def test_dependencias_nao_instaladas_retorna_503(self, client):
        row = {"latitude": -23.0, "longitude": -47.0, "data_hora": "2024-01-15"}
        with self._patch_consulta([row]), \
             self._patch_cache_nao_existe(), \
             patch.object(
                 rotas_sentinel, "_gerar_imagem_sentinel",
                 side_effect=RuntimeError("Dependências não instaladas")
             ):
            resp = client.get("/queimadas/1/imagem-satelite")
        assert resp.status_code == 503

    def test_erro_interno_retorna_500(self, client):
        row = {"latitude": -23.0, "longitude": -47.0, "data_hora": "2024-01-15"}
        with self._patch_consulta([row]), \
             self._patch_cache_nao_existe(), \
             patch.object(
                 rotas_sentinel, "_gerar_imagem_sentinel",
                 side_effect=Exception("Erro genérico inesperado")
             ):
            resp = client.get("/queimadas/1/imagem-satelite")
        assert resp.status_code == 500

    # ── Parâmetros query sobrescrevem banco ───────────────────────────────────

    def test_lat_lon_passados_nao_consulta_banco(self, client):
        with self._patch_cache_nao_existe(), \
             self._patch_gerar(), \
             patch.object(Path, "write_bytes"), \
             patch.object(rotas_sentinel, "executar_consulta") as mock_db:
            resp = client.get(
                "/queimadas/1/imagem-satelite?lat=-23.0&lon=-47.0&data=2024-01-15"
            )
        mock_db.assert_not_called()
        assert resp.status_code == 200

    def test_data_passada_como_param(self, client):
        with self._patch_cache_nao_existe(), \
             self._patch_gerar(), \
             patch.object(Path, "write_bytes"), \
             patch.object(rotas_sentinel, "executar_consulta") as mock_db:
            resp = client.get(
                "/queimadas/99/imagem-satelite?lat=-22.0&lon=-48.0&data=2024-06-01"
            )
        assert resp.status_code == 200

    # ── Cache hit ─────────────────────────────────────────────────────────────

    def test_cache_hit_retorna_200(self, client):
        """Quando o arquivo de cache existe, deve retornar diretamente."""
        row = {"latitude": -23.0, "longitude": -47.0, "data_hora": "2024-01-15"}
        with self._patch_consulta([row]), \
             self._patch_cache_existe(), \
             patch("builtins.open", mock_open(read_data=_PNG_MINIMO)):
            resp = client.get("/queimadas/1/imagem-satelite")
        # Cache hit: 200
        assert resp.status_code == 200

    # ── Data inválida ─────────────────────────────────────────────────────────

    def test_data_invalida_retorna_422(self, client):
        with self._patch_cache_nao_existe(), \
             patch.object(rotas_sentinel, "executar_consulta", return_value=[]):
            resp = client.get(
                "/queimadas/1/imagem-satelite?lat=-23.0&lon=-47.0&data=nao-e-data"
            )
        assert resp.status_code in (422, 404)

    # ── Headers de resposta ───────────────────────────────────────────────────

    def test_cache_miss_header_x_cache(self, client):
        row = {"latitude": -23.0, "longitude": -47.0, "data_hora": "2024-01-15"}
        with self._patch_consulta([row]), \
             self._patch_cache_nao_existe(), \
             self._patch_gerar(), \
             patch.object(Path, "write_bytes"):
            resp = client.get("/queimadas/1/imagem-satelite")
        assert resp.headers.get("X-Cache") == "MISS"

    def test_cache_control_presente(self, client):
        row = {"latitude": -23.0, "longitude": -47.0, "data_hora": "2024-01-15"}
        with self._patch_consulta([row]), \
             self._patch_cache_nao_existe(), \
             self._patch_gerar(), \
             patch.object(Path, "write_bytes"):
            resp = client.get("/queimadas/1/imagem-satelite")
        assert "Cache-Control" in resp.headers


# ──────────────────────────────────────────────────────────────────────────────
# _gerar_imagem_sentinel — testa ImportError para deps opcionais
# ──────────────────────────────────────────────────────────────────────────────


class TestGerarImagemSentinel:
    def test_sem_pystac_levanta_runtime_error(self):
        """Se planetary_computer/pystac_client não estiverem instalados, deve
        levantar RuntimeError descritivo."""
        from datetime import datetime, timezone

        data_hora = datetime(2024, 1, 15, tzinfo=timezone.utc)

        import builtins
        real_import = builtins.__import__

        def _import_falso(name, *args, **kwargs):
            if name in ("planetary_computer", "pystac_client"):
                raise ImportError("Módulo não instalado")
            return real_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=_import_falso):
            with pytest.raises(RuntimeError) as exc_info:
                _gerar_imagem_sentinel(-23.0, -47.0, data_hora)
        assert "instalad" in str(exc_info.value).lower()