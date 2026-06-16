"""Schema linking por embeddings (MiniLM). Usa o modelo em cache local."""

import pytest

linker = None
try:
    from asg_sistema.analitico.linker import SchemaLinker
    linker = SchemaLinker()
except Exception:  # modelo indisponível no ambiente
    linker = None

pytestmark = pytest.mark.skipif(linker is None, reason="modelo MiniLM indisponível")


class TestLinker:
    def test_liga_tabela_queimadas(self):
        assert linker.ligar("quantos focos de incêndio por cidade").tabela == "queimadas"

    def test_liga_tabela_desmatamento(self):
        r = linker.ligar("top 3 cidades com mais desmatamento")
        assert r.tabela in ("desmatamento_alertas", "prodes_desmatamento")

    def test_liga_dimensao_municipio(self):
        assert "municipio" in linker.ligar("por município").dimensoes

    def test_confianca_no_intervalo(self):
        assert 0.0 <= linker.ligar("top 3 cidades com mais desmatamento").confianca <= 1.0
