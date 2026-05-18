"""Configuração compartilhada de fixtures para os testes do ASG Sistema.

IMPORTANTE: As variáveis de ambiente precisam ser definidas ANTES de qualquer
importação dos módulos da aplicação, pois config.py é avaliado no nível do
módulo.
"""

import os

# Configura variáveis de ambiente para testes ANTES de importar qualquer módulo da app.
os.environ.setdefault("ASG_JWT_SEGREDO", "chave-secreta-de-testes-nao-usar-em-producao")
os.environ.setdefault("ASG_JWT_ALGORITMO", "HS256")
os.environ.setdefault("ASG_JWT_EXPIRACAO_MINUTOS", "60")
os.environ.setdefault("ASG_DB_HOST", "localhost")
os.environ.setdefault("ASG_DB_PORT", "5433")
os.environ.setdefault("ASG_DB_NOME", "asg_test")
os.environ.setdefault("ASG_DB_USUARIO", "asg_user")
os.environ.setdefault("ASG_DB_SENHA", "asg_pass")
os.environ.setdefault("ASG_ENV", "test")

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from asg_sistema.db.models import Base, Usuario
from asg_sistema.auth import senha as senha_util
from asg_sistema.auth import jwt_tokens

# ──────────────────────────────────────────────────────────────────────────────
# Banco de dados em memória para testes
# ──────────────────────────────────────────────────────────────────────────────

SQLALCHEMY_DATABASE_URL = "sqlite:///:memory:"


@pytest.fixture(scope="session")
def engine_teste():
    """Engine SQLite em memória para toda a sessão de testes."""
    engine = create_engine(
        SQLALCHEMY_DATABASE_URL,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    yield engine
    Base.metadata.drop_all(bind=engine)


@pytest.fixture(scope="function")
def db_sessao(engine_teste):
    """Sessão de banco de dados isolada por teste (rollback após cada teste)."""
    connection = engine_teste.connect()
    transaction = connection.begin()
    SessionTest = sessionmaker(bind=connection)
    session = SessionTest()

    yield session

    session.close()
    transaction.rollback()
    connection.close()


# ──────────────────────────────────────────────────────────────────────────────
# Usuários para testes
# ──────────────────────────────────────────────────────────────────────────────

SENHA_PADRAO = "senha@Teste123"


@pytest.fixture
def usuario_admin(db_sessao):
    """Cria um usuário ADMIN no banco de testes."""
    usuario = Usuario(
        nome="Admin Teste",
        cargo="Administrador",
        email="admin@teste.com",
        senha_hash=senha_util.hash_senha(SENHA_PADRAO),
        papel="ADMIN",
    )
    db_sessao.add(usuario)
    db_sessao.commit()
    db_sessao.refresh(usuario)
    return usuario


@pytest.fixture
def usuario_comum(db_sessao):
    """Cria um usuário USER no banco de testes."""
    usuario = Usuario(
        nome="Usuário Comum",
        cargo="Analista",
        email="usuario@teste.com",
        senha_hash=senha_util.hash_senha(SENHA_PADRAO),
        papel="USER",
    )
    db_sessao.add(usuario)
    db_sessao.commit()
    db_sessao.refresh(usuario)
    return usuario


# ──────────────────────────────────────────────────────────────────────────────
# Tokens JWT para testes
# ──────────────────────────────────────────────────────────────────────────────


@pytest.fixture
def token_admin(usuario_admin):
    """Gera token JWT válido para o usuário admin."""
    return jwt_tokens.criar_token_acesso(
        usuario_id=usuario_admin.id,
        email=usuario_admin.email,
        papel=usuario_admin.papel,
    )


@pytest.fixture
def token_usuario(usuario_comum):
    """Gera token JWT válido para o usuário comum."""
    return jwt_tokens.criar_token_acesso(
        usuario_id=usuario_comum.id,
        email=usuario_comum.email,
        papel=usuario_comum.papel,
    )


# ──────────────────────────────────────────────────────────────────────────────
# TestClient FastAPI com override de DB
# ──────────────────────────────────────────────────────────────────────────────


@pytest.fixture
def client(db_sessao):
    """TestClient com override da sessão de banco para SQLite em memória."""
    # Importações tardias para evitar problemas com config
    from asg_sistema.api.app import app
    from asg_sistema.db.conexao import obter_sessao

    def _override_sessao():
        try:
            yield db_sessao
        finally:
            pass

    app.dependency_overrides[obter_sessao] = _override_sessao
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c
    app.dependency_overrides.clear()