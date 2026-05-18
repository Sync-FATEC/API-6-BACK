"""Testes unitários para asg_sistema/auth/jwt_tokens.py."""

import os

os.environ.setdefault("ASG_JWT_SEGREDO", "chave-secreta-de-testes-nao-usar-em-producao")

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from jose import ExpiredSignatureError, JWTError, jwt

from asg_sistema.auth.jwt_tokens import criar_token_acesso, decodificar_token
from asg_sistema.config import config


class TestCriarTokenAcesso:
    """Testes para criar_token_acesso."""

    def test_criar_token_acesso_retorna_string(self):
        token = criar_token_acesso(usuario_id=1, email="teste@email.com", papel="USER")
        assert isinstance(token, str)
        assert len(token) > 0

    def test_criar_token_acesso_contem_sub_correto(self):
        token = criar_token_acesso(usuario_id=42, email="u@email.com", papel="USER")
        payload = decodificar_token(token)
        assert payload["sub"] == "42"

    def test_criar_token_acesso_contem_email(self):
        email = "usuario@exemplo.com"
        token = criar_token_acesso(usuario_id=1, email=email, papel="USER")
        payload = decodificar_token(token)
        assert payload["email"] == email

    def test_criar_token_acesso_contem_papel(self):
        token = criar_token_acesso(usuario_id=1, email="a@b.com", papel="ADMIN")
        payload = decodificar_token(token)
        assert payload["papel"] == "ADMIN"

    def test_criar_token_acesso_typ_access(self):
        token = criar_token_acesso(usuario_id=1, email="a@b.com", papel="USER")
        payload = decodificar_token(token)
        assert payload["typ"] == "access"

    def test_criar_token_acesso_exp_no_futuro(self):
        token = criar_token_acesso(usuario_id=1, email="a@b.com", papel="USER")
        payload = decodificar_token(token)
        exp = payload["exp"]
        agora = datetime.now(timezone.utc).timestamp()
        assert exp > agora

    def test_criar_token_acesso_sub_como_string(self):
        """sub deve ser str mesmo quando usuario_id é int."""
        token = criar_token_acesso(usuario_id=99, email="a@b.com", papel="USER")
        payload = decodificar_token(token)
        assert isinstance(payload["sub"], str)

    def test_criar_token_admin_papel_preservado(self):
        token = criar_token_acesso(usuario_id=5, email="admin@sys.com", papel="ADMIN")
        payload = decodificar_token(token)
        assert payload["papel"] == "ADMIN"

    def test_criar_token_usa_segredo_configurado(self):
        """Token deve ser decodificável somente com o segredo correto."""
        token = criar_token_acesso(usuario_id=1, email="a@b.com", papel="USER")
        with pytest.raises(JWTError):
            jwt.decode(token, "segredo-errado", algorithms=[config.jwt_algoritmo])


class TestDecodificarToken:
    """Testes para decodificar_token."""

    def test_decodificar_token_valido(self):
        token = criar_token_acesso(usuario_id=7, email="x@y.com", papel="USER")
        payload = decodificar_token(token)
        assert payload["sub"] == "7"

    def test_decodificar_token_invalido_levanta_jwterror(self):
        with pytest.raises(JWTError):
            decodificar_token("token.invalido.qualquer")

    def test_decodificar_token_expirado_levanta_erro(self):
        """Token com exp no passado deve ser rejeitado."""
        payload = {
            "sub": "1",
            "exp": datetime.now(timezone.utc) - timedelta(seconds=1),
            "email": "a@b.com",
            "papel": "USER",
            "typ": "access",
        }
        token_expirado = jwt.encode(
            payload, config.jwt_segredo, algorithm=config.jwt_algoritmo
        )
        with pytest.raises(JWTError):
            decodificar_token(token_expirado)

    def test_decodificar_token_assinado_com_outro_segredo(self):
        payload = {
            "sub": "1",
            "exp": datetime.now(timezone.utc) + timedelta(hours=1),
            "email": "a@b.com",
            "papel": "USER",
            "typ": "access",
        }
        token = jwt.encode(payload, "outro-segredo", algorithm="HS256")
        with pytest.raises(JWTError):
            decodificar_token(token)

    def test_decodificar_token_vazio_levanta_erro(self):
        with pytest.raises(JWTError):
            decodificar_token("")

    def test_decodificar_token_retorna_dict(self):
        token = criar_token_acesso(usuario_id=1, email="a@b.com", papel="USER")
        resultado = decodificar_token(token)
        assert isinstance(resultado, dict)

    def test_decodificar_token_todos_campos_presentes(self):
        token = criar_token_acesso(usuario_id=3, email="c@d.com", papel="ADMIN")
        payload = decodificar_token(token)
        for campo in ("sub", "exp", "email", "papel", "typ"):
            assert campo in payload, f"Campo '{campo}' ausente no payload"