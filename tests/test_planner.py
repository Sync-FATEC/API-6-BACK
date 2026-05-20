"""Testes unitarios para asg_sistema.motor.planner.planejar.

Regras de negocio cobertas:
1. resumo_municipal + municipio -> expande em N subconsultas tematicas.
2. resumo_municipal sem municipio -> mantem subconsulta unica (sem fanout).
3. resumo_municipal + CAR -> nao expande; CAR absorve o tema.
4. Intencao normal nao e afetada pelo fanout.
5. intencoes_detectadas refletem os temas quando ha fanout.
"""

from asg_sistema.motor.planner import planejar


_TEMAS_RESUMO = {
    "consultar_queimadas",
    "consultar_desmatamento",
    "consultar_terra_indigena",
    "consultar_unidade_conservacao",
    "consultar_quilombola",
    "consultar_imovel_rural",
}


class TestResumoMunicipalFanout:
    def test_deve_expandir_em_todos_os_temas_quando_ha_municipio(self):
        plano = planejar(
            intencao_principal="resumo_municipal",
            confianca_principal=0.9,
            intencoes_secundarias=[],
            entidades={"municipios": ["Caçapava"]},
        )

        intencoes_subs = {s.intencao for s in plano.subconsultas}
        assert intencoes_subs == _TEMAS_RESUMO
        assert all(s.municipio == "Caçapava" for s in plano.subconsultas)
        assert plano.eixo_agrupamento == "intencao"

    def test_deve_preservar_intencao_principal_no_plano(self):
        plano = planejar(
            intencao_principal="resumo_municipal",
            confianca_principal=0.9,
            intencoes_secundarias=[],
            entidades={"municipios": ["Caçapava"]},
        )
        assert plano.intencao_principal == "resumo_municipal"

    def test_intencoes_detectadas_devem_refletir_temas_expandidos(self):
        plano = planejar(
            intencao_principal="resumo_municipal",
            confianca_principal=0.9,
            intencoes_secundarias=[],
            entidades={"municipios": ["Caçapava"]},
        )

        intencoes_detectadas = {d["intencao"] for d in plano.intencoes_detectadas}
        assert intencoes_detectadas == _TEMAS_RESUMO
        assert "resumo_municipal" not in intencoes_detectadas


class TestResumoMunicipalSemFanout:
    def test_deve_manter_subconsulta_unica_quando_nao_ha_municipio(self):
        plano = planejar(
            intencao_principal="resumo_municipal",
            confianca_principal=0.9,
            intencoes_secundarias=[],
            entidades={},
        )

        assert len(plano.subconsultas) == 1
        assert plano.subconsultas[0].intencao == "resumo_municipal"
        assert plano.eixo_agrupamento == "unico"

    def test_deve_nao_expandir_quando_ha_cod_imovel(self):
        # CAR domina; resumo_municipal vira complemento sob o CAR, sem fanout.
        plano = planejar(
            intencao_principal="resumo_municipal",
            confianca_principal=0.9,
            intencoes_secundarias=[],
            entidades={"municipios": ["Caçapava"], "cod_imovel": "SP-123"},
        )

        intencoes_subs = [s.intencao for s in plano.subconsultas]
        # 1 subconsulta CAR + 1 subconsulta resumo_municipal (não expandida).
        assert "consultar_imovel_rural" in intencoes_subs
        assert intencoes_subs.count("consultar_queimadas") == 0
        assert any(i == "resumo_municipal" for i in intencoes_subs)


class TestIntencaoNormalNaoAfetada:
    def test_consultar_desmatamento_deve_continuar_com_uma_subconsulta(self):
        plano = planejar(
            intencao_principal="consultar_desmatamento",
            confianca_principal=0.9,
            intencoes_secundarias=[],
            entidades={"municipios": ["Caçapava"]},
        )

        assert len(plano.subconsultas) == 1
        assert plano.subconsultas[0].intencao == "consultar_desmatamento"
