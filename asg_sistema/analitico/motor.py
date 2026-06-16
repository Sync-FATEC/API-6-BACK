"""Orquestrador do caminho analítico: slots -> SQL -> validação -> execução -> render.

Dependências injetadas (executor, explain, gerador) -> testável sem DB/modelo.
Degradação graciosa: em qualquer falha devolve uma resposta com `erro` preenchido,
que o interpretador usa para cair no fluxo atual.
"""

import logging
import time

from asg_sistema.config import config
from asg_sistema.analitico.construtor_sql import construir
from asg_sistema.analitico.renderizador import renderizar
from asg_sistema.analitico.validador_sql import validar_sql

logger = logging.getLogger("asg.analitico")


def _resposta_fallback(pergunta: str, motivo: str) -> dict:
    return {
        "pergunta": pergunta,
        "intencao_detectada": "consulta_analitica",
        "confianca": 0.0,
        "entidades": {},
        "resumo": (
            "Não consegui interpretar essa pergunta com confiança. Posso responder, por exemplo: "
            "rankings e contagens (\"top municípios com mais queimadas\"), comparações "
            "(\"Bauru vs Sorocaba\", \"2023 vs 2024\"), distribuições/percentuais, filtros "
            "numéricos (\"imóveis com área entre 100 e 500 ha\"), risco de propriedades e "
            "listagens. Tente reformular com um destes formatos."
        ),
        "estatisticas": {"erro": motivo},
        "dados": [],
        "fontes": [],
        "geojson": None,
        "nota_risco": None,
        "grupos": None,
        "total_resultados": 0,
        "erro": motivo,
    }


class MotorAnalitico:
    def __init__(self, extrator_slots, executor, explain, gerador_local=None):
        self.slots = extrator_slots
        self.executor = executor
        self.explain = explain
        self.gerador_local = gerador_local  # opcional (fallback generativo)

    def consultar(self, pergunta: str, rota: str = "ANALITICA", contexto: dict | None = None) -> dict:
        inicio = time.time()
        ir = self.slots.extrair(pergunta, rota=rota, contexto=contexto)

        sql, params = None, {}
        if ir.completa() and ir.confianca >= config.analitico_confianca_minima:
            try:
                sql, params = construir(ir, max_limit=config.sql_max_limit)
            except Exception as e:  # noqa: BLE001
                logger.info("construtor_falhou", extra={"erro": str(e)})
                sql = None

        if sql is None and self.gerador_local is not None:
            try:
                sql = self.gerador_local.gerar(pergunta)
                params = {}
            except Exception as e:  # noqa: BLE001
                logger.info("gerador_local_falhou", extra={"erro": str(e)})
                sql = None

        if sql is None:
            return self._log(_resposta_fallback(pergunta, "confiança insuficiente / IR incompleta"), inicio)

        val = validar_sql(sql, max_limit=config.sql_max_limit)
        if not val.valido:
            return self._log(_resposta_fallback(pergunta, f"SQL rejeitado: {val.erro}"), inicio)

        erro_explain = self.explain(val.sql_final, params)
        if erro_explain:
            return self._log(_resposta_fallback(pergunta, f"EXPLAIN falhou: {erro_explain}"), inicio)

        try:
            linhas = self.executor(val.sql_final, params, timeout_ms=config.sql_timeout_ms)
        except Exception as e:  # noqa: BLE001
            return self._log(_resposta_fallback(pergunta, f"execução falhou: {e}"), inicio)

        out = renderizar(pergunta, ir, linhas, sql=val.sql_final)
        out["erro"] = None
        return self._log(out, inicio)

    def _log(self, out: dict, inicio: float) -> dict:
        out["tempo_processamento_ms"] = round((time.time() - inicio) * 1000, 1)
        logger.info(
            "consulta_analitica",
            extra={
                "sql": (out.get("estatisticas") or {}).get("sql"),
                "n_linhas": out.get("total_resultados", 0),
                "status": "erro" if out.get("erro") else "ok",
                "ms": out["tempo_processamento_ms"],
            },
        )
        return out
