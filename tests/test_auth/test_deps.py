"""Testes unitários para asg_sistema/auth/deps.py."""

import os

os.environ.setdefault("ASG_JWT_SEGREDO", "chave-secreta-de-testes-nao-usar-em-producao")

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from jose import jwt

from asg_sistema.auth.deps import exigir_admin, obter_usuario_atual
from asg_sistema.auth.jwt_tokens import criar_token_acesso
from asg_sistema.config import config
from asg_sistema.db.models import Usuario


def _criar_usuario(usuario_id=1, email="u@test.com", papel="USER"):
    """Cria um mock de Usuario para testes."""
    u = MagicMock(spec=Usuario)
    u.id = usuario_id
    u.email = email
    u.papel = papel
    return u


def _criar_db_mock(usuario=None):
    """Cria um mock de sessão SQLAlchemy."""
    db = MagicMock()
    query_mock = MagicMock()
    filter_mock = MagicMock()
    filter_mock.first.return_value = usuario
    query_mock.filter.return_value = filter_mock
    db.query.return_value = query_mock
    return db


def _criar_credenciais(token: str) -> HTTPAuthorizationCredentials:
    return HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)


class TestObterUsuarioAtual:
    """Testes para obter_usuario_atual."""

    def test_sem_credenciais_levanta_401(self):
        db = _criar_db_mock()
        with pytest.raises(HTTPException) as exc_info:
            obter_usuario_atual(credenciais=None, db=db)
        assert exc_info.value.status_code == 401

    def test_credenciais_vazias_levanta_401(self):
        cred = HTTPAuthorizationCredentials(scheme="Bearer", credentials="")
        db = _criar_db_mock()
        with pytest.raises(HTTPException) as exc_info:
            obter_usuario_atual(credenciais=cred, db=db)
        assert exc_info.value.status_code == 401

    def test_token_invalido_levanta_401(self):
        cred = _criar_credenciais("token.invalido.qualquer")
        db = _criar_db_mock()
        with pytest.raises(HTTPException) as exc_info:
            obter_usuario_atual(credenciais=cred, db=db)
        assert exc_info.value.status_code == 401

    def test_token_valido_usuario_encontrado_retorna_usuario(self):
        usuario = _criar_usuario(usuario_id=5, email="user@test.com", papel="USER")
        token = criar_token_acesso(usuario_id=5, email="user@test.com", papel="USER")
        cred = _criar_credenciais(token)
        db = _criar_db_mock(usuario=usuario)

        resultado = obter_usuario_atual(credenciais=cred, db=db)
        assert resultado is usuario

    def test_token_valido_usuario_nao_encontrado_levanta_401(self):
        token = criar_token_acesso(usuario_id=999, email="nao@existe.com", papel="USER")
        cred = _criar_credenciais(token)
        db = _criar_db_mock(usuario=None)

        with pytest.raises(HTTPException) as exc_info:
            obter_usuario_atual(credenciais=cred, db=db)
        assert exc_info.value.status_code == 401

    def test_papel_token_diferente_do_banco_levanta_401(self):
        """Se papel no token diverge do banco, deve retornar 401."""
        usuario = _criar_usuario(usuario_id=3, papel="USER")
        token = criar_token_acesso(usuario_id=3, email="a@b.com", papel="ADMIN")
        cred = _criar_credenciais(token)
        db = _criar_db_mock(usuario=usuario)

        with pytest.raises(HTTPException) as exc_info:
            obter_usuario_atual(credenciais=cred, db=db)
        assert exc_info.value.status_code == 401

    def test_token_expirado_levanta_401(self):
        payload = {
            "sub": "1",
            "exp": datetime.now(timezone.utc) - timedelta(seconds=5),
            "email": "a@b.com",
            "papel": "USER",
            "typ": "access",
        }
        token_expirado = jwt.encode(
            payload, config.jwt_segredo, algorithm=config.jwt_algoritmo
        )
        cred = _criar_credenciais(token_expirado)
        db = _criar_db_mock()

        with pytest.raises(HTTPException) as exc_info:
            obter_usuario_atual(credenciais=cred, db=db)
        assert exc_info.value.status_code == 401

    def test_token_sem_sub_levanta_401(self):
        payload = {
            "exp": datetime.now(timezone.utc) + timedelta(hours=1),
            "email": "a@b.com",
            "papel": "USER",
            "typ": "access",
        }
        token = jwt.encode(payload, config.jwt_segredo, algorithm=config.jwt_algoritmo)
        cred = _criar_credenciais(token)
        db = _criar_db_mock()

        with pytest.raises(HTTPException) as exc_info:
            obter_usuario_atual(credenciais=cred, db=db)
        assert exc_info.value.status_code == 401

    def test_papel_coincide_com_banco_retorna_usuario(self):
        """Papel do token igual ao do banco: deve retornar usuário."""
        usuario = _criar_usuario(usuario_id=2, papel="ADMIN")
        token = criar_token_acesso(usuario_id=2, email="admin@test.com", papel="ADMIN")
        cred = _criar_credenciais(token)
        db = _criar_db_mock(usuario=usuario)

        resultado = obter_usuario_atual(credenciais=cred, db=db)
        assert resultado is usuario


class TestExigirAdmin:
    """Testes para exigir_admin."""

    def test_usuario_admin_retorna_usuario(self):
        usuario = _criar_usuario(papel="ADMIN")
        resultado = exigir_admin(usuario=usuario)
        assert resultado is usuario

    def test_usuario_nao_admin_levanta_403(self):
        usuario = _criar_usuario(papel="USER")
        with pytest.raises(HTTPException) as exc_info:
            exigir_admin(usuario=usuario)
        assert exc_info.value.status_code == 403

    def test_usuario_nao_admin_detalhe_mensagem(self):
        usuario = _criar_usuario(papel="USER")
        with pytest.raises(HTTPException) as exc_info:
            exigir_admin(usuario=usuario)
        assert "administrador" in exc_info.value.detail.lower()