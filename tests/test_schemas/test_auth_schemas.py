"""Testes unitários para asg_sistema/schemas/auth.py."""

import os

os.environ.setdefault("ASG_JWT_SEGREDO", "chave-secreta-de-testes-nao-usar-em-producao")

import pytest
from pydantic import ValidationError

from asg_sistema.schemas.auth import (
    AlterarSenhaRequest,
    CadastroRequest,
    EditarUsuarioRequest,
    LoginRequest,
    LoginResponse,
    MensagemResponse,
    UsuarioPublico,
)


class TestLoginRequest:
    def test_valido(self):
        req = LoginRequest(email="user@example.com", senha="abc")
        assert req.email == "user@example.com"
        assert req.senha == "abc"

    def test_email_invalido(self):
        with pytest.raises(ValidationError):
            LoginRequest(email="nao-e-email", senha="abc")

    def test_senha_vazia(self):
        with pytest.raises(ValidationError):
            LoginRequest(email="u@e.com", senha="")

    def test_campos_obrigatorios(self):
        with pytest.raises(ValidationError):
            LoginRequest(email="u@e.com")

    def test_email_normalizado(self):
        req = LoginRequest(email="USER@EXAMPLE.COM", senha="abc")
        assert "@" in req.email


class TestUsuarioPublico:
    def test_campos_basicos(self):
        u = UsuarioPublico(nome="João", cargo="Dev", email="j@x.com", papel="USER")
        assert u.nome == "João"
        assert u.cargo == "Dev"
        assert u.email == "j@x.com"
        assert u.papel == "USER"

    def test_papel_invalido(self):
        with pytest.raises(ValidationError):
            UsuarioPublico(nome="X", cargo="Y", email="x@y.com", papel="SUPERUSER")

    def test_papel_admin(self):
        u = UsuarioPublico(nome="X", cargo="Y", email="x@y.com", papel="ADMIN")
        assert u.papel == "ADMIN"


class TestLoginResponse:
    def test_campos_obrigatorios(self):
        u = UsuarioPublico(nome="X", cargo="Y", email="x@y.com", papel="USER")
        resp = LoginResponse(access_token="tok123", usuario=u)
        assert resp.access_token == "tok123"
        assert resp.token_type == "bearer"
        assert resp.usuario is u

    def test_token_type_padrao(self):
        u = UsuarioPublico(nome="X", cargo="Y", email="x@y.com", papel="USER")
        resp = LoginResponse(access_token="tok", usuario=u)
        assert resp.token_type == "bearer"


class TestAlterarSenhaRequest:
    def test_valido(self):
        req = AlterarSenhaRequest(senha_atual="atual123", nova_senha="nova@12345")
        assert req.senha_atual == "atual123"
        assert req.nova_senha == "nova@12345"

    def test_nova_senha_curta_falha(self):
        with pytest.raises(ValidationError):
            AlterarSenhaRequest(senha_atual="atual", nova_senha="curta")

    def test_senha_atual_vazia_falha(self):
        with pytest.raises(ValidationError):
            AlterarSenhaRequest(senha_atual="", nova_senha="novaSenha123")

    def test_nova_senha_exatamente_8_chars(self):
        req = AlterarSenhaRequest(senha_atual="atual", nova_senha="12345678")
        assert len(req.nova_senha) == 8


class TestMensagemResponse:
    def test_valido(self):
        resp = MensagemResponse(mensagem="Operação concluída.")
        assert resp.mensagem == "Operação concluída."

    def test_mensagem_obrigatoria(self):
        with pytest.raises(ValidationError):
            MensagemResponse()


class TestCadastroRequest:
    def test_valido_user(self):
        req = CadastroRequest(
            nome="Maria",
            cargo="Analista",
            email="maria@ex.com",
            senha="senhaForte123",
            papel="USER",
        )
        assert req.papel == "USER"

    def test_valido_admin(self):
        req = CadastroRequest(
            nome="Admin",
            cargo="Dir",
            email="admin@ex.com",
            senha="senhaForte123",
            papel="ADMIN",
        )
        assert req.papel == "ADMIN"

    def test_papel_padrao_user(self):
        req = CadastroRequest(
            nome="X", cargo="Y", email="x@y.com", senha="senhaForte123"
        )
        assert req.papel == "USER"

    def test_papel_invalido(self):
        with pytest.raises(ValidationError):
            CadastroRequest(
                nome="X", cargo="Y", email="x@y.com", senha="senhaForte123", papel="DEUS"
            )

    def test_senha_curta(self):
        with pytest.raises(ValidationError):
            CadastroRequest(nome="X", cargo="Y", email="x@y.com", senha="abc")

    def test_email_invalido(self):
        with pytest.raises(ValidationError):
            CadastroRequest(nome="X", cargo="Y", email="invalido", senha="senhaForte123")

    def test_nome_vazio(self):
        with pytest.raises(ValidationError):
            CadastroRequest(nome="", cargo="Y", email="x@y.com", senha="senhaForte123")

    def test_cargo_vazio(self):
        with pytest.raises(ValidationError):
            CadastroRequest(nome="X", cargo="", email="x@y.com", senha="senhaForte123")

    def test_nome_muito_longo(self):
        with pytest.raises(ValidationError):
            CadastroRequest(
                nome="A" * 256,
                cargo="Y",
                email="x@y.com",
                senha="senhaForte123",
            )

    def test_cargo_muito_longo(self):
        with pytest.raises(ValidationError):
            CadastroRequest(
                nome="X",
                cargo="C" * 201,
                email="x@y.com",
                senha="senhaForte123",
            )


class TestEditarUsuarioRequest:
    def test_todos_nenhum_campo_obrigatorio(self):
        """EditarUsuarioRequest deve aceitar objeto vazio (todos opcionais)."""
        req = EditarUsuarioRequest()
        assert req.nome is None
        assert req.cargo is None
        assert req.email is None
        assert req.papel is None
        assert req.nova_senha is None

    def test_apenas_nome(self):
        req = EditarUsuarioRequest(nome="Novo Nome")
        assert req.nome == "Novo Nome"

    def test_nome_vazio_invalido(self):
        with pytest.raises(ValidationError):
            EditarUsuarioRequest(nome="")

    def test_papel_invalido(self):
        with pytest.raises(ValidationError):
            EditarUsuarioRequest(papel="MASTER")

    def test_nova_senha_curta_invalida(self):
        with pytest.raises(ValidationError):
            EditarUsuarioRequest(nova_senha="short")

    def test_email_invalido(self):
        with pytest.raises(ValidationError):
            EditarUsuarioRequest(email="nao-e-email")

    def test_todos_campos_validos(self):
        req = EditarUsuarioRequest(
            nome="Nome Completo",
            cargo="Dev",
            email="novo@email.com",
            papel="ADMIN",
            nova_senha="NovaSenha@123",
        )
        assert req.nome == "Nome Completo"
        assert req.papel == "ADMIN"
