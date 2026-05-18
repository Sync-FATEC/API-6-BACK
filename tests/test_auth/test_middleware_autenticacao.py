"""Testes unitários para asg_sistema/auth/middleware_autenticacao.py."""

import os

os.environ.setdefault("ASG_JWT_SEGREDO", "chave-secreta-de-testes-nao-usar-em-producao")

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from jose import jwt
from starlette.testclient import TestClient
from fastapi import FastAPI
from fastapi.responses import JSONResponse

from asg_sistema.auth.middleware_autenticacao import (
    MiddlewareAutenticacao,
    _rota_exige_token,
)
from asg_sistema.auth.jwt_tokens import criar_token_acesso
from asg_sistema.config import config


# ──────────────────────────────────────────────────────────────────────────────
# Testes para _rota_exige_token (função pura)
# ──────────────────────────────────────────────────────────────────────────────


class TestRotaExigeToken:
    """Testes para a função _rota_exige_token."""

    def test_rota_api_v1_raiz_exige_token(self):
        assert _rota_exige_token("/api/v1") is True

    def test_rota_api_v1_sub_exige_token(self):
        assert _rota_exige_token("/api/v1/agendamentos") is True
        assert _rota_exige_token("/api/v1/agendamentos/") is True
        assert _rota_exige_token("/api/v1/agendamentos/123") is True

    def test_rota_auth_nao_exige_token(self):
        assert _rota_exige_token("/api/v1/auth") is False
        assert _rota_exige_token("/api/v1/auth/login") is False
        assert _rota_exige_token("/api/v1/auth/cadastro") is False

    def test_rota_api_sem_v1_nao_exige_token(self):
        assert _rota_exige_token("/api/geo/queimadas") is False
        assert _rota_exige_token("/api/saude") is False
        assert _rota_exige_token("/api/consulta") is False

    def test_rota_raiz_nao_exige_token(self):
        assert _rota_exige_token("/") is False

    def test_rota_docs_nao_exige_token(self):
        assert _rota_exige_token("/docs") is False
        assert _rota_exige_token("/openapi.json") is False

    def test_rota_api_v1_qualquer_sub_exige_token(self):
        assert _rota_exige_token("/api/v1/usuarios") is True
        assert _rota_exige_token("/api/v1/qualquer/coisa") is True


# ──────────────────────────────────────────────────────────────────────────────
# App mínimo para testar o middleware
# ──────────────────────────────────────────────────────────────────────────────


def _criar_app_teste():
    """Cria uma app FastAPI mínima com o middleware de autenticação."""
    app = FastAPI()
    app.add_middleware(MiddlewareAutenticacao)

    @app.get("/api/v1/recurso-protegido")
    def recurso_protegido():
        return {"status": "ok"}

    @app.get("/api/v1/auth/login")
    def login_publico():
        return {"status": "login-publico"}

    @app.get("/api/saude")
    def saude():
        return {"status": "vivo"}

    return app


class TestMiddlewareAutenticacao:
    """Testes de integração do MiddlewareAutenticacao via TestClient."""

    @pytest.fixture(autouse=True)
    def setup_client(self):
        self.app = _criar_app_teste()
        self.client = TestClient(self.app, raise_server_exceptions=False)

    def _token_valido(self):
        return criar_token_acesso(usuario_id=1, email="u@test.com", papel="USER")

    # -- Rotas protegidas sem token --

    def test_rota_protegida_sem_header_retorna_401(self):
        resp = self.client.get("/api/v1/recurso-protegido")
        assert resp.status_code == 401

    def test_rota_protegida_sem_token_contem_detalhe(self):
        resp = self.client.get("/api/v1/recurso-protegido")
        assert "detail" in resp.json()

    def test_rota_protegida_sem_header_retorna_www_authenticate(self):
        resp = self.client.get("/api/v1/recurso-protegido")
        assert "WWW-Authenticate" in resp.headers

    # -- Rotas protegidas com token inválido --

    def test_rota_protegida_token_invalido_retorna_401(self):
        resp = self.client.get(
            "/api/v1/recurso-protegido",
            headers={"Authorization": "Bearer token.invalido.xyz"},
        )
        assert resp.status_code == 401

    def test_rota_protegida_token_malformado(self):
        resp = self.client.get(
            "/api/v1/recurso-protegido",
            headers={"Authorization": "Bearer "},
        )
        assert resp.status_code == 401

    def test_rota_protegida_header_sem_bearer(self):
        """Autorização sem 'Bearer ' deve retornar 401."""
        resp = self.client.get(
            "/api/v1/recurso-protegido",
            headers={"Authorization": "Basic user:pass"},
        )
        assert resp.status_code == 401

    def test_rota_protegida_token_expirado_retorna_401(self):
        payload = {
            "sub": "1",
            "exp": datetime.now(timezone.utc) - timedelta(seconds=10),
            "email": "a@b.com",
            "papel": "USER",
            "typ": "access",
        }
        token_expirado = jwt.encode(
            payload, config.jwt_segredo, algorithm=config.jwt_algoritmo
        )
        resp = self.client.get(
            "/api/v1/recurso-protegido",
            headers={"Authorization": f"Bearer {token_expirado}"},
        )
        assert resp.status_code == 401

    # -- Rotas protegidas com token válido --

    def test_rota_protegida_token_valido_retorna_200(self):
        token = self._token_valido()
        resp = self.client.get(
            "/api/v1/recurso-protegido",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200

    def test_rota_protegida_token_valido_resposta_correta(self):
        token = self._token_valido()
        resp = self.client.get(
            "/api/v1/recurso-protegido",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.json() == {"status": "ok"}

    # -- Rotas públicas --

    def test_rota_auth_login_sem_token_retorna_200(self):
        """Rota /api/v1/auth/... é pública e não deve exigir token."""
        resp = self.client.get("/api/v1/auth/login")
        assert resp.status_code == 200

    def test_rota_saude_sem_token_retorna_200(self):
        resp = self.client.get("/api/saude")
        assert resp.status_code == 200

    # -- Preflight OPTIONS --

    def test_options_rota_protegida_passa_sem_token(self):
        """OPTIONS (preflight CORS) deve ser passado sem verificar token."""
        resp = self.client.options("/api/v1/recurso-protegido")
        # Deve chegar ao endpoint (ou retornar 405 por não ter OPTIONS handler),
        # mas nunca deve ser um 401 do middleware.
        assert resp.status_code != 401