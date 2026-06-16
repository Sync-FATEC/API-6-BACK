"""Regressão offline do motor genérico: pergunta -> rota -> IR -> SQL válido.

Não usa banco nem o modelo de embeddings (FakeLinker keyword->tabela), então roda
em qualquer ambiente e garante que os arquétipos suportados continuam gerando SQL
correto e seguro enquanto o banco é preparado.
"""

import os

os.environ.setdefault("ASG_JWT_SEGREDO", "test-secret")

import pytest

from asg_sistema.motor.entidades import ExtratorEntidades
from asg_sistema.analitico.slots import ExtratorSlots
from asg_sistema.analitico.construtor_sql import construir
from asg_sistema.analitico.validador_sql import validar_sql
from asg_sistema.analitico.roteador import rotear
from asg_sistema.analitico.linker import ResultadoLink

_MUNICIPIOS = ["Bauru", "Sorocaba", "Campinas", "Araçatuba", "Marília", "Ubatuba"]


class _FakeLinker:
    """Linker determinístico por palavra-chave (substitui MiniLM nos testes)."""

    def ligar(self, p: str) -> ResultadoLink:
        pl = p.lower()
        r = ResultadoLink()
        if "desmatamento" in pl or "alerta" in pl:
            r.tabela, r.metrica_agg = "desmatamento_alertas", "SUM"
        elif "propriedade" in pl or "imóve" in pl or "imove" in pl or "fazenda" in pl:
            r.tabela, r.metrica_agg = "sicar_imoveis", "COUNT"
        else:
            r.tabela, r.metrica_agg = "queimadas", "COUNT"
        r.confianca = 0.7
        r.tabelas = [(r.tabela, 0.7), ("desmatamento_alertas", 0.5)]
        return r


def _slots():
    return ExtratorSlots(_FakeLinker(), ExtratorEntidades(_MUNICIPIOS))


# (pergunta, rota_esperada, fragmento_esperado_no_sql)
CASOS = [
    ("top 3 cidades com mais desmatamento", "ANALITICA", "GROUP BY municipio"),
    ("quantas queimadas por município", "ANALITICA", "COUNT(*)"),
    ("média de frp por bioma", "ANALITICA", "AVG"),
    ("Compare queimadas em Bauru e Sorocaba", "ANALITICA", "or municipio ilike"),
    ("quantos focos por município em 2023 e 2024", "ANALITICA", "EXTRACT(YEAR"),
    ("municípios com mais de 100 focos", "ANALITICA", "HAVING"),
    ("liste as terras indígenas em Bauru", "LISTAGEM", "FROM terras_indigenas"),
    ("liste unidades de conservação federais", "LISTAGEM", "FROM unidades_conservacao"),
    ("imóveis com área entre 100 e 500 hectares em Campinas", "LISTAGEM", "BETWEEN"),
    ("quais propriedades têm maior risco ambiental", "PROPRIEDADE", "nota_risco"),
    ("propriedades com queimadas após alertas de desmatamento", "PROPRIEDADE", "fogo_apos_alerta"),
]


@pytest.mark.parametrize("pergunta,rota_esp,frag", CASOS, ids=[c[0][:30] for c in CASOS])
def test_pergunta_gera_sql_valido(pergunta, rota_esp, frag):
    rota = rotear(pergunta)
    assert rota == rota_esp, f"rota {rota} != {rota_esp}"
    ir = _slots().extrair(pergunta, rota=rota)
    assert ir.completa(), "IR incompleta"
    sql, _params = construir(ir)
    assert validar_sql(sql).valido, f"SQL inválido: {sql}"
    assert frag.lower() in " ".join(sql.split()).lower(), f"esperado '{frag}' em: {sql}"


def test_followup_herda_contexto():
    ctx = {
        "tabela": "queimadas", "modo": "agregacao",
        "filtros": {"municipio": "Bauru"}, "dimensoes": ["municipio"],
        "coluna_ordem": None, "ordem_desc": True, "limite": 10,
        "metrica_agg": "COUNT", "metrica_coluna": None, "metrica_alias": "focos",
    }
    ir = _slots().extrair("E em Sorocaba?", rota="ANALITICA", contexto=ctx)
    assert ir.tabela == "queimadas"
    assert "Sorocaba" in str(ir.filtros.get("municipio"))
    sql, _ = construir(ir)
    assert validar_sql(sql).valido


ATAQUES = [
    "DROP TABLE fato_propriedade_ambiental",
    "DELETE FROM queimadas",
    "UPDATE sicar_imoveis SET ind_status='CA'",
    "SELECT * FROM usuarios LIMIT 5",
    "SELECT senha_hash FROM usuarios LIMIT 5",
    "SELECT pg_sleep(5) FROM queimadas LIMIT 1",
    "SELECT 1 FROM queimadas LIMIT 1; DROP TABLE queimadas",
]


@pytest.mark.parametrize("ataque", ATAQUES)
def test_seguranca_bloqueia_ataques(ataque):
    assert validar_sql(ataque).valido is False
