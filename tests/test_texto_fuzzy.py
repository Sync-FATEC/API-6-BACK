"""Normalização e fuzzy matching (RapidFuzz + Unidecode) p/ value linking."""

from asg_sistema.analitico.texto import normalizar, melhor_match


class TestNormalizar:
    def test_remove_acento_e_caixa(self):
        assert normalizar("São Paulo") == "sao paulo"


class TestMelhorMatch:
    def test_match_exato(self):
        nome, score = melhor_match("campinas", ["São Paulo", "Bauru", "Campinas"])
        assert nome == "Campinas" and score >= 95

    def test_match_com_erro_ortografico(self):
        nome, score = melhor_match("ribeirao pretoo", ["São Paulo", "Bauru", "Ribeirão Preto"])
        assert nome == "Ribeirão Preto" and score >= 85

    def test_sem_match_bom(self):
        nome, score = melhor_match("xyzzy", ["Bauru"])
        assert score < 85
