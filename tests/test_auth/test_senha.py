"""Testes unitários para asg_sistema/auth/senha.py."""

import os

os.environ.setdefault("ASG_JWT_SEGREDO", "chave-secreta-de-testes-nao-usar-em-producao")

import pytest

from asg_sistema.auth.senha import hash_senha, verificar_senha


class TestHashSenha:
    """Testes para hash_senha."""

    def test_hash_retorna_string(self):
        resultado = hash_senha("minha_senha")
        assert isinstance(resultado, str)

    def test_hash_nao_igual_senha_plana(self):
        senha = "senha_secreta"
        assert hash_senha(senha) != senha

    def test_hash_bcrypt_formato(self):
        """Hash bcrypt começa com $2b$ ou $2a$."""
        resultado = hash_senha("qualquer")
        assert resultado.startswith("$2")

    def test_hash_diferente_para_mesma_senha(self):
        """bcrypt usa salt aleatório: dois hashes da mesma senha devem diferir."""
        senha = "mesma_senha_123"
        hash1 = hash_senha(senha)
        hash2 = hash_senha(senha)
        assert hash1 != hash2

    def test_hash_senha_longa(self):
        senha_longa = "A" * 200
        resultado = hash_senha(senha_longa)
        assert isinstance(resultado, str)
        assert len(resultado) > 0

    def test_hash_senha_especial(self):
        senha = "!@#$%^&*()_+-=[]{}|;':\",./<>?"
        resultado = hash_senha(senha)
        assert isinstance(resultado, str)


class TestVerificarSenha:
    """Testes para verificar_senha."""

    def test_verificar_senha_correta_retorna_true(self):
        senha = "senha_correta_123"
        h = hash_senha(senha)
        assert verificar_senha(senha, h) is True

    def test_verificar_senha_incorreta_retorna_false(self):
        h = hash_senha("senha_correta")
        assert verificar_senha("senha_errada", h) is False

    def test_verificar_senha_vazia_incorreta(self):
        h = hash_senha("senha_correta")
        assert verificar_senha("", h) is False

    def test_verificar_senha_case_sensitive(self):
        h = hash_senha("SenhaComMaiuscula")
        assert verificar_senha("senhacommaiuscula", h) is False

    def test_verificar_hash_invalido_retorna_false_ou_levanta(self):
        """Senhas com hash inválido não devem retornar True."""
        # passlib retorna False para hashes malformados
        resultado = verificar_senha("qualquer", "hash-invalido")
        assert resultado is False

    def test_verificar_senha_com_caracteres_especiais(self):
        senha = "p@ssw0rd!#$"
        h = hash_senha(senha)
        assert verificar_senha(senha, h) is True
        assert verificar_senha("p@ssw0rd", h) is False

    def test_hash_e_verificar_roundtrip(self):
        """Ciclo completo: hash → verificação positiva → verificação negativa."""
        senha = "roundtrip_test_senha"
        h = hash_senha(senha)
        assert verificar_senha(senha, h) is True
        assert verificar_senha(senha + "x", h) is False