"""Catálogo analítico: allowlist coerente, internas escondidas, âncoras semânticas."""

from asg_sistema.analitico import catalogo


class TestAllowlist:
    def test_tabelas_e_internas(self):
        for t in ("queimadas", "desmatamento_alertas", "prodes_desmatamento", "sicar_imoveis"):
            assert t in catalogo.TABELAS_PERMITIDAS
        for p in ("corpus_asg", "usuarios", "conversas", "mensagens"):
            assert p not in catalogo.TABELAS_PERMITIDAS and p not in catalogo.VIEWS_PERMITIDAS

    def test_colunas(self):
        assert "data_hora" in catalogo.TABELAS_PERMITIDAS["queimadas"]
        assert "area_total_km2" in catalogo.TABELAS_PERMITIDAS["desmatamento_alertas"]
        assert "area_km" in catalogo.TABELAS_PERMITIDAS["prodes_desmatamento"]
        assert "ind_status" in catalogo.TABELAS_PERMITIDAS["sicar_imoveis"]

    def test_nomes_permitidos(self):
        n = catalogo.nomes_permitidos()
        assert "queimadas" in n and "vw_prodes_ano" in n

    def test_todas_as_colunas(self):
        c = catalogo.todas_as_colunas()
        assert "municipio" in c and "area_km" in c


class TestCatalogoSemantico:
    def test_estrutura(self):
        ancoras = catalogo.CATALOGO_SEMANTICO
        assert any(a["tipo"] == "tabela" and a["alvo"] == "queimadas" for a in ancoras)
        assert any(a["tipo"] == "metrica" for a in ancoras)
        assert all({"frase", "tipo", "alvo"} <= set(a) for a in ancoras)

    def test_metricas_e_dimensoes(self):
        assert catalogo.METRICAS["queimadas"]["focos"] == ("COUNT", None)
        assert "municipio" in catalogo.DIMENSOES["queimadas"]
