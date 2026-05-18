"""Testes unitários para mudanças em asg_sistema/config.py.

Escopo do PR: validator jwt_segredo_nao_vazio e novos campos JWT.
"""

import os
import pytest

# Garante que o segredo está definido para importações do módulo
os.environ.setdefault("ASG_JWT_SEGREDO", "chave-secreta-de-testes-nao-usar-em-producao")

from pydantic import ValidationError
from pydantic_settings import BaseSettings


# ──────────────────────────────────────────────────────────────────────────────
# Helpers para criar instâncias de Configuracao com variáveis customizadas
# ──────────────────────────────────────────────────────────────────────────────

def _criar_config(**overrides):
    """Cria uma instância de Configuracao com env vars customizadas."""
    from asg_sistema.config import Configuracao

    env_vars = {
        "ASG_JWT_SEGREDO": "segredo-valido-para-teste",
        "ASG_DB_HOST": "localhost",
        "ASG_DB_PORT": "5433",
        "ASG_DB_NOME": "asg_test",
        "ASG_DB_USUARIO": "user",
        "ASG_DB_SENHA": "pass",
    }
    env_vars.update({f"ASG_{k.upper()}": str(v) for k, v in overrides.items()})

    # Cria subclasse que ignora o arquivo .env
    class ConfiguracaoTeste(Configuracao):
        class Config:
            env_prefix = "ASG_"
            env_file = None

    old_env = {}
    for k, v in env_vars.items():
        old_env[k] = os.environ.get(k)
        os.environ[k] = v

    try:
        return ConfiguracaoTeste()
    finally:
        for k, old_v in old_env.items():
            if old_v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = old_v


class TestJwtSegredoValidator:
    """Testes para o validator jwt_segredo_nao_vazio."""

    def test_segredo_valido_aceito(self):
        cfg = _criar_config(jwt_segredo="minha-chave-secreta-valida")
        assert cfg.jwt_segredo == "minha-chave-secreta-valida"

    def test_segredo_vazio_levanta_validation_error(self):
        with pytest.raises((ValidationError, ValueError)):
            _criar_config(jwt_segredo="")

    def test_segredo_somente_espacos_levanta_validation_error(self):
        with pytest.raises((ValidationError, ValueError)):
            _criar_config(jwt_segredo="   ")

    def test_segredo_com_espacos_nas_bordas_limpo(self):
        """Segredo com espaços nas bordas deve ser limpo (strip)."""
        cfg = _criar_config(jwt_segredo=" chave-valida ")
        assert cfg.jwt_segredo == "chave-valida"


class TestCamposJwt:
    """Testes para os novos campos JWT em Configuracao."""

    def test_jwt_algoritmo_padrao_hs256(self):
        cfg = _criar_config()
        assert cfg.jwt_algoritmo == "HS256"

    def test_jwt_algoritmo_customizavel(self):
        cfg = _criar_config(jwt_algoritmo="HS512")
        assert cfg.jwt_algoritmo == "HS512"

    def test_jwt_expiracao_padrao(self):
        """Padrão é 60 * 24 = 1440 minutos."""
        cfg = _criar_config()
        assert cfg.jwt_expiracao_minutos == 60 * 24

    def test_jwt_expiracao_customizavel(self):
        cfg = _criar_config(jwt_expiracao_minutos="30")
        assert cfg.jwt_expiracao_minutos == 30

    def test_campos_jwt_presentes(self):
        cfg = _criar_config()
        assert hasattr(cfg, "jwt_segredo")
        assert hasattr(cfg, "jwt_algoritmo")
        assert hasattr(cfg, "jwt_expiracao_minutos")


class TestConfiguracaoAtual:
    """Testa a instância config já criada no módulo."""

    def test_config_importavel(self):
        from asg_sistema.config import config
        assert config is not None

    def test_config_tem_jwt_segredo(self):
        from asg_sistema.config import config
        assert config.jwt_segredo
        assert len(config.jwt_segredo) > 0

    def test_config_tem_jwt_algoritmo(self):
        from asg_sistema.config import config
        assert config.jwt_algoritmo in ("HS256", "HS384", "HS512", "RS256")

    def test_config_jwt_expiracao_positiva(self):
        from asg_sistema.config import config
        assert config.jwt_expiracao_minutos > 0