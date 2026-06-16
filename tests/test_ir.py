"""Representação intermediária ConsultaAnalitica."""

from asg_sistema.analitico.ir import ConsultaAnalitica, Metrica, Ordem


def test_ir_basica():
    ir = ConsultaAnalitica(
        tabela="desmatamento_alertas",
        metrica=Metrica(agg="SUM", coluna="area_total_km2", alias="area_km2"),
        dimensoes=["municipio"],
        filtros={}, ordem=Ordem(por="area_km2", desc=True), limite=3, confianca=0.8,
    )
    assert ir.tabela == "desmatamento_alertas"
    assert ir.metrica.agg == "SUM"
    assert ir.completa() is True


def test_ir_incompleta_sem_tabela():
    ir = ConsultaAnalitica(tabela=None, metrica=None, dimensoes=[], filtros={},
                           ordem=None, limite=100, confianca=0.1)
    assert ir.completa() is False
