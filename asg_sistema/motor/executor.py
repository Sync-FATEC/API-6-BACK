"""Executa um ExecutionPlan rodando cada SubConsulta em paralelo.

O DB é o gargalo (IO-bound), então ThreadPoolExecutor entrega ganho real
mesmo com GIL. O callable injetado (`buscador_subconsulta`) é o método do
InterpretadorConsulta que isola o pipeline de busca + geração parcial.
"""

from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable

from asg_sistema.motor.planner import ExecutionPlan, SubConsulta


def executar_plano(
    plano: ExecutionPlan,
    preprocessado: dict,
    entidades_base: dict,
    buscador_subconsulta: Callable[[dict, SubConsulta, dict], dict],
    max_workers: int = 6,
) -> list[dict]:
    """Executa cada SubConsulta em paralelo, preservando a ordem do plano."""
    subs = plano.subconsultas
    if not subs:
        return []

    workers = min(max_workers, len(subs)) or 1

    resultados: list[dict | None] = [None] * len(subs)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futuros = {
            pool.submit(buscador_subconsulta, preprocessado, sub, entidades_base): idx
            for idx, sub in enumerate(subs)
        }
        for fut in as_completed(futuros):
            idx = futuros[fut]
            try:
                resultados[idx] = fut.result()
            except Exception as e:
                sub = subs[idx]
                resultados[idx] = {
                    "_sub": {
                        "rotulo": sub.rotulo,
                        "municipio": sub.municipio,
                        "intencao": sub.intencao,
                        "confianca": sub.confianca,
                    },
                    "_erro": str(e),
                    "_raw_resultados": [],
                    "_raw_resultados_geo": [],
                    "resumo": f"Erro ao processar {sub.rotulo}: {e}",
                    "estatisticas": {},
                    "dados": [],
                    "fontes": [],
                    "geojson": None,
                    "total_resultados": 0,
                    "nota_risco": {"nota": 0, "nivel": "sem_dados", "fatores": [], "por_dimensao": {}},
                }

    return [r for r in resultados if r is not None]
