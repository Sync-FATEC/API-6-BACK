"""Testes de integração para asg_sistema/routers/auth_router.py.

Usa SQLite em memória e override da dependência de sessão.
"""

import os

os.environ.setdefault("ASG_JWT_SEGREDO", "chave-secreta-de-testes-nao-usar-em-producao")

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from asg_sistema.db.models import Base, Usuario
from asg_sistema.db.conexao import obter_sessao
from asg_sistema.auth import senha as senha_util
from asg_sistema.auth.jwt_tokens import criar_token_acesso
from asg_sistema.routers.auth_router import router as auth_router
from asg_sistema.auth.middleware_autenticacao import MiddlewareAutenticacao


# ──────────────────────────────────────────────────────────────────────────────
# Setup do banco de testes e app
# ──────────────────────────────────────────────────────────────────────────────

SQLITE_URL = "sqlite:///:memory:"

_engine = create_engine(
    SQLITE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
Base.metadata.create_all(bind=_engine)
_TestingSession = sessionmaker(bind=_engine)


def _get_test_session():
    db = _TestingSession()
    try:
        yield db
    finally:
        db.close()


def _criar_app_auth():
    app = FastAPI()
    app.add_middleware(MiddlewareAutenticacao)
    app.include_router(auth_router, prefix="/api/v1")
    app.dependency_overrides[obter_sessao] = _get_test_session
    return app


@pytest.fixture(autouse=True)
def limpar_banco():
    """Limpa a tabela de usuários antes de cada teste."""
    with _engine.connect() as conn:
        conn.execute(Usuario.__table__.delete())
        conn.commit()
    yield


@pytest.fixture
def app():
    return _criar_app_auth()


@pytest.fixture
def client(app):
    return TestClient(app, raise_server_exceptions=False)


CADASTRO_VALIDO = {
    "nome": "João Silva",
    "cargo": "Analista",
    "email": "joao@example.com",
    "senha": "senha@Segura123",
    "papel": "USER",
}


# ──────────────────────────────────────────────────────────────────────────────
# POST /api/v1/auth/cadastro
# ──────────────────────────────────────────────────────────────────────────────


class TestCadastro:
    def test_cadastro_usuario_user_retorna_201(self, client):
        resp = client.post("/api/v1/auth/cadastro", json=CADASTRO_VALIDO)
        assert resp.status_code == 201

    def test_cadastro_retorna_access_token(self, client):
        resp = client.post("/api/v1/auth/cadastro", json=CADASTRO_VALIDO)
        data = resp.json()
        assert "access_token" in data
        assert len(data["access_token"]) > 0

    def test_cadastro_retorna_token_type_bearer(self, client):
        resp = client.post("/api/v1/auth/cadastro", json=CADASTRO_VALIDO)
        assert resp.json()["token_type"] == "bearer"

    def test_cadastro_retorna_dados_usuario(self, client):
        resp = client.post("/api/v1/auth/cadastro", json=CADASTRO_VALIDO)
        usuario = resp.json()["usuario"]
        assert usuario["email"] == "joao@example.com"
        assert usuario["nome"] == "João Silva"
        assert usuario["papel"] == "USER"

    def test_cadastro_nao_retorna_senha(self, client):
        resp = client.post("/api/v1/auth/cadastro", json=CADASTRO_VALIDO)
        assert "senha" not in resp.json()
        assert "senha_hash" not in str(resp.json())

    def test_cadastro_email_duplicado_retorna_409(self, client):
        client.post("/api/v1/auth/cadastro", json=CADASTRO_VALIDO)
        resp = client.post("/api/v1/auth/cadastro", json=CADASTRO_VALIDO)
        assert resp.status_code == 409

    def test_cadastro_primeiro_admin_permitido(self, client):
        payload = {**CADASTRO_VALIDO, "papel": "ADMIN"}
        resp = client.post("/api/v1/auth/cadastro", json=payload)
        assert resp.status_code == 201
        assert resp.json()["usuario"]["papel"] == "ADMIN"

    def test_cadastro_segundo_admin_bloqueado(self, client):
        """Segundo cadastro como ADMIN deve ser rejeitado se já existir usuário."""
        # Cria primeiro usuário (qualquer papel)
        client.post("/api/v1/auth/cadastro", json=CADASTRO_VALIDO)
        # Tenta criar segundo como ADMIN
        payload = {
            "nome": "Admin2",
            "cargo": "Dir",
            "email": "admin2@ex.com",
            "senha": "outraSenha@123",
            "papel": "ADMIN",
        }
        resp = client.post("/api/v1/auth/cadastro", json=payload)
        assert resp.status_code == 403

    def test_cadastro_senha_curta_retorna_422(self, client):
        payload = {**CADASTRO_VALIDO, "senha": "curta"}
        resp = client.post("/api/v1/auth/cadastro", json=payload)
        assert resp.status_code == 422

    def test_cadastro_email_invalido_retorna_422(self, client):
        payload = {**CADASTRO_VALIDO, "email": "nao-e-email"}
        resp = client.post("/api/v1/auth/cadastro", json=payload)
        assert resp.status_code == 422

    def test_cadastro_nome_vazio_retorna_422(self, client):
        payload = {**CADASTRO_VALIDO, "nome": ""}
        resp = client.post("/api/v1/auth/cadastro", json=payload)
        assert resp.status_code == 422


# ──────────────────────────────────────────────────────────────────────────────
# POST /api/v1/auth/login
# ──────────────────────────────────────────────────────────────────────────────


class TestLogin:
    @pytest.fixture(autouse=True)
    def _criar_usuario(self, client):
        client.post("/api/v1/auth/cadastro", json=CADASTRO_VALIDO)

    def test_login_valido_retorna_200(self, client):
        resp = client.post(
            "/api/v1/auth/login",
            json={"email": "joao@example.com", "senha": "senha@Segura123"},
        )
        assert resp.status_code == 200

    def test_login_retorna_access_token(self, client):
        resp = client.post(
            "/api/v1/auth/login",
            json={"email": "joao@example.com", "senha": "senha@Segura123"},
        )
        data = resp.json()
        assert "access_token" in data

    def test_login_senha_incorreta_retorna_401(self, client):
        resp = client.post(
            "/api/v1/auth/login",
            json={"email": "joao@example.com", "senha": "senha-errada"},
        )
        assert resp.status_code == 401

    def test_login_email_inexistente_retorna_401(self, client):
        resp = client.post(
            "/api/v1/auth/login",
            json={"email": "nao@existe.com", "senha": "qualquer"},
        )
        assert resp.status_code == 401

    def test_login_email_case_insensitive(self, client):
        """Login com e-mail em maiúsculas deve funcionar."""
        resp = client.post(
            "/api/v1/auth/login",
            json={"email": "JOAO@EXAMPLE.COM", "senha": "senha@Segura123"},
        )
        assert resp.status_code == 200

    def test_login_retorna_dados_usuario(self, client):
        resp = client.post(
            "/api/v1/auth/login",
            json={"email": "joao@example.com", "senha": "senha@Segura123"},
        )
        usuario = resp.json()["usuario"]
        assert usuario["email"] == "joao@example.com"

    def test_login_payload_invalido_retorna_422(self, client):
        resp = client.post("/api/v1/auth/login", json={"email": "nao-e-email"})
        assert resp.status_code == 422


# ──────────────────────────────────────────────────────────────────────────────
# POST /api/v1/auth/alterar-senha
# ──────────────────────────────────────────────────────────────────────────────


class TestAlterarSenha:
    @pytest.fixture(autouse=True)
    def _criar_e_logar(self, client):
        client.post("/api/v1/auth/cadastro", json=CADASTRO_VALIDO)
        login_resp = client.post(
            "/api/v1/auth/login",
            json={"email": "joao@example.com", "senha": "senha@Segura123"},
        )
        self.token = login_resp.json()["access_token"]

    def test_alterar_senha_valida_retorna_200(self, client):
        resp = client.post(
            "/api/v1/auth/alterar-senha",
            json={"senha_atual": "senha@Segura123", "nova_senha": "novaSenha@456"},
            headers={"Authorization": f"Bearer {self.token}"},
        )
        assert resp.status_code == 200

    def test_alterar_senha_retorna_mensagem(self, client):
        resp = client.post(
            "/api/v1/auth/alterar-senha",
            json={"senha_atual": "senha@Segura123", "nova_senha": "novaSenha@456"},
            headers={"Authorization": f"Bearer {self.token}"},
        )
        assert "mensagem" in resp.json()

    def test_alterar_senha_atual_incorreta_retorna_400(self, client):
        resp = client.post(
            "/api/v1/auth/alterar-senha",
            json={"senha_atual": "senha-errada", "nova_senha": "novaSenha@456"},
            headers={"Authorization": f"Bearer {self.token}"},
        )
        assert resp.status_code == 400

    def test_alterar_senha_igual_retorna_400(self, client):
        """Nova senha igual à atual deve ser rejeitada."""
        resp = client.post(
            "/api/v1/auth/alterar-senha",
            json={"senha_atual": "senha@Segura123", "nova_senha": "senha@Segura123"},
            headers={"Authorization": f"Bearer {self.token}"},
        )
        assert resp.status_code == 400

    def test_alterar_senha_sem_token_retorna_401(self, client):
        resp = client.post(
            "/api/v1/auth/alterar-senha",
            json={"senha_atual": "senha@Segura123", "nova_senha": "novaSenha@456"},
        )
        assert resp.status_code == 401

    def test_alterar_senha_nova_curta_retorna_422(self, client):
        resp = client.post(
            "/api/v1/auth/alterar-senha",
            json={"senha_atual": "senha@Segura123", "nova_senha": "curta"},
            headers={"Authorization": f"Bearer {self.token}"},
        )
        assert resp.status_code == 422

    def test_nova_senha_funciona_no_login_subsequente(self, client):
        """Após alterar senha, novo login com nova senha deve funcionar."""
        client.post(
            "/api/v1/auth/alterar-senha",
            json={"senha_atual": "senha@Segura123", "nova_senha": "novaSenha@456"},
            headers={"Authorization": f"Bearer {self.token}"},
        )
        resp_login = client.post(
            "/api/v1/auth/login",
            json={"email": "joao@example.com", "senha": "novaSenha@456"},
        )
        assert resp_login.status_code == 200


# ──────────────────────────────────────────────────────────────────────────────
# PUT /api/v1/auth/usuarios/{usuario_id}
# ──────────────────────────────────────────────────────────────────────────────


class TestEditarUsuario:
    @pytest.fixture(autouse=True)
    def _setup(self, client):
        # Cria admin
        admin_payload = {**CADASTRO_VALIDO, "email": "admin@ex.com", "papel": "ADMIN"}
        resp_admin = client.post("/api/v1/auth/cadastro", json=admin_payload)
        login_admin = client.post(
            "/api/v1/auth/login",
            json={"email": "admin@ex.com", "senha": "senha@Segura123"},
        )
        self.token_admin = login_admin.json()["access_token"]

        # Cria usuário comum
        user_payload = {**CADASTRO_VALIDO, "email": "user@ex.com", "papel": "USER"}
        resp_user = client.post("/api/v1/auth/cadastro", json=user_payload)
        self.usuario_id = resp_user.json()["usuario"].get("id") if "usuario" in resp_user.json() else None
        login_user = client.post(
            "/api/v1/auth/login",
            json={"email": "user@ex.com", "senha": "senha@Segura123"},
        )
        self.token_user = login_user.json()["access_token"]

        # Obtemos os ids via banco (SQLite)
        with _TestingSession() as db:
            admin = db.query(Usuario).filter(Usuario.email == "admin@ex.com").first()
            user = db.query(Usuario).filter(Usuario.email == "user@ex.com").first()
            self.admin_id = admin.id if admin else None
            self.user_id = user.id if user else None

    def test_admin_pode_editar_qualquer_usuario(self, client):
        if self.user_id is None:
            pytest.skip("user_id não disponível")
        resp = client.put(
            f"/api/v1/auth/usuarios/{self.user_id}",
            json={"nome": "Novo Nome"},
            headers={"Authorization": f"Bearer {self.token_admin}"},
        )
        assert resp.status_code == 200

    def test_usuario_pode_editar_proprio_perfil(self, client):
        if self.user_id is None:
            pytest.skip("user_id não disponível")
        resp = client.put(
            f"/api/v1/auth/usuarios/{self.user_id}",
            json={"nome": "Nome Atualizado"},
            headers={"Authorization": f"Bearer {self.token_user}"},
        )
        assert resp.status_code == 200

    def test_usuario_nao_pode_editar_outro(self, client):
        if self.admin_id is None:
            pytest.skip("admin_id não disponível")
        resp = client.put(
            f"/api/v1/auth/usuarios/{self.admin_id}",
            json={"nome": "Invasão"},
            headers={"Authorization": f"Bearer {self.token_user}"},
        )
        assert resp.status_code == 403

    def test_usuario_inexistente_retorna_404(self, client):
        resp = client.put(
            "/api/v1/auth/usuarios/99999",
            json={"nome": "Fantasma"},
            headers={"Authorization": f"Bearer {self.token_admin}"},
        )
        assert resp.status_code == 404

    def test_usuario_nao_admin_nao_pode_definir_papel_admin(self, client):
        if self.user_id is None:
            pytest.skip("user_id não disponível")
        resp = client.put(
            f"/api/v1/auth/usuarios/{self.user_id}",
            json={"papel": "ADMIN"},
            headers={"Authorization": f"Bearer {self.token_user}"},
        )
        assert resp.status_code == 403

    def test_editar_sem_token_retorna_401(self, client):
        resp = client.put("/api/v1/auth/usuarios/1", json={"nome": "X"})
        assert resp.status_code == 401

    def test_editar_email_duplicado_retorna_409(self, client):
        """Tentativa de alterar email para um já em uso deve retornar 409."""
        if self.user_id is None:
            pytest.skip("user_id não disponível")
        resp = client.put(
            f"/api/v1/auth/usuarios/{self.user_id}",
            json={"email": "admin@ex.com"},
            headers={"Authorization": f"Bearer {self.token_admin}"},
        )
        assert resp.status_code == 409