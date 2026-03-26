"""Etapa 5 da pipeline PLN: Busca semantica.
Combina similaridade vetorial (pgvector) com filtros estruturados.
"""

from asg_sistema.db import repositorio
from asg_sistema.pln.extrator_caracteristicas import ExtratorCaracteristicas


class BuscadorSemantico:
    def __init__(self, extrator: ExtratorCaracteristicas):
        self.extrator = extrator

    def buscar(self, texto_consulta: str, filtros: dict, top_k: int = 15) -> list[dict]:
        embedding = self.extrator.embedding_unico(texto_consulta)
        embedding_str = "[" + ",".join(str(float(v)) for v in embedding) + "]"

        municipios = filtros.get("municipios", [])
        periodo = filtros.get("periodo", {})

        resultados = repositorio.busca_vetorial(
            embedding_str=embedding_str,
            fonte=filtros.get("fonte"),
            fontes=filtros.get("fontes"),
            municipio=municipios[0] if municipios else None,
            data_inicio=periodo.get("inicio"),
            data_fim=periodo.get("fim"),
            limite=top_k,
        )
        return resultados
