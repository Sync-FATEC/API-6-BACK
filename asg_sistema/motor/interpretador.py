"""Orquestrador: recebe pergunta do usuario e retorna resposta completa."""

import time

from asg_sistema.pln.preprocessador import PreprocessadorPLN
from asg_sistema.pln.classificador import ClassificadorIntencao
from asg_sistema.pln.buscador_semantico import BuscadorSemantico
from asg_sistema.motor.entidades import ExtratorEntidades
from asg_sistema.motor.gerador_resposta import GeradorResposta
from asg_sistema.db import repositorio


MAPA_INTENCAO_FONTE = {
    "consultar_queimadas": "queimadas",
    "consultar_desmatamento": "deter",
    "consultar_terra_indigena": "funai",
    "consultar_unidade_conservacao": "icmbio",
    "consultar_quilombola": "palmares",
    "consultar_prodes": "prodes",
    "resumo_municipal": None,
}

# Intencoes que buscam em múltiplas fontes simultaneamente
MAPA_INTENCAO_FONTES_MULTIPLAS = {
    "consultar_desmatamento": ["deter", "prodes"],
}


class InterpretadorConsulta:
    def __init__(
        self,
        preprocessador: PreprocessadorPLN,
        classificador: ClassificadorIntencao,
        extrator_entidades: ExtratorEntidades,
        buscador: BuscadorSemantico,
        gerador: GeradorResposta,
        top_k: int = 15,
    ):
        self.preprocessador = preprocessador
        self.classificador = classificador
        self.extrator_entidades = extrator_entidades
        self.buscador = buscador
        self.gerador = gerador
        self.top_k = top_k

    def processar(self, pergunta: str) -> dict:
        inicio = time.time()

        preprocessado = self.preprocessador.preprocessar(pergunta)
        intencao, confianca = self.classificador.classificar(pergunta)

        if confianca < 0.3 or intencao not in MAPA_INTENCAO_FONTE:
            return {
                "pergunta": pergunta,
                "intencao_detectada": "fora_do_escopo",
                "confianca": round(confianca, 3) if confianca else 0,
                "entidades": {},
                "resumo": (
                    "Desculpe, não entendi sua pergunta. "
                    "Sou um assistente especializado em dados ambientais, sociais e de governança (ASG) "
                    "do Estado de São Paulo. Tente perguntar sobre:\n"
                    "- Focos de queimada (ex: 'Houve queimadas em Avaí?')\n"
                    "- Terras indígenas (ex: 'Quais terras indígenas existem em Ubatuba?')\n"
                    "- Desmatamento (ex: 'Alertas de desmatamento no Cerrado')\n"
                    "- Unidades de conservação (ex: 'Unidades de conservação em Bertioga')\n"
                    "- Comunidades quilombolas (ex: 'Quilombolas no Vale do Ribeira')\n"
                    "- Desmatamento histórico PRODES (ex: 'Desmatamento anual na Mata Atlântica')\n"
                    "- Resumo municipal (ex: 'Qual a situação ambiental de Campinas?')"
                ),
                "estatisticas": {},
                "dados": [],
                "fontes": [],
                "geojson": None,
                "total_resultados": 0,
                "tempo_processamento_ms": round((time.time() - inicio) * 1000, 1),
                "preprocessamento": {
                    "tokens_limpos": preprocessado["tokens_limpos"],
                    "stems": preprocessado["stems"],
                },
            }

        entidades = self.extrator_entidades.extrair(pergunta)

        fontes_multiplas = MAPA_INTENCAO_FONTES_MULTIPLAS.get(intencao)
        filtros = {
            "fonte": MAPA_INTENCAO_FONTE.get(intencao) if not fontes_multiplas else None,
            "fontes": fontes_multiplas,
            "municipios": entidades.get("municipios", []),
            "periodo": entidades.get("periodo", {}),
        }

        entidades_resumo = entidades

        # Para consultar_desmatamento com município: combina DETER (filtro textual)
        # + PRODES (filtro espacial por proximidade geográfica)
        if fontes_multiplas and filtros.get("municipios"):
            municipio = filtros["municipios"][0]
            embedding_str = self.buscador.extrator.embedding_unico(preprocessado["texto_limpo"])
            embedding_str = "[" + ",".join(str(float(v)) for v in embedding_str) + "]"

            # DETER: busca por município textual
            filtros_deter = {**filtros, "fontes": None, "fonte": "deter"}
            resultados_deter = self.buscador.buscar(
                texto_consulta=preprocessado["texto_limpo"],
                filtros=filtros_deter,
                top_k=self.top_k,
            )

            # PRODES: busca espacial por proximidade do município
            uids_prodes = repositorio.buscar_uids_prodes_por_municipio(municipio)
            resultados_prodes = repositorio.busca_vetorial_prodes_uids(
                embedding_str=embedding_str,
                uids=uids_prodes,
                limite=self.top_k,
            )

            # Merge: DETER primeiro (mais recente/específico), depois PRODES
            ids_vistos = {r["id"] for r in resultados_deter}
            resultados = list(resultados_deter)
            for r in resultados_prodes:
                if r["id"] not in ids_vistos:
                    resultados.append(r)
            resultados = resultados[: self.top_k]

            # Geo: mesma lógica mas com limite maior
            resultados_geo_deter = self.buscador.buscar(
                texto_consulta=preprocessado["texto_limpo"],
                filtros=filtros_deter,
                top_k=1000,
            )
            uids_prodes_geo = uids_prodes  # já calculados
            resultados_geo_prodes = repositorio.busca_vetorial_prodes_uids(
                embedding_str=embedding_str,
                uids=uids_prodes_geo,
                limite=1000,
            )
            ids_vistos_geo = {r["id"] for r in resultados_geo_deter}
            resultados_geo = list(resultados_geo_deter)
            for r in resultados_geo_prodes:
                if r["id"] not in ids_vistos_geo:
                    resultados_geo.append(r)

            # Se ainda não achou nada, fallback para estado inteiro
            if not resultados:
                filtros_sem_mun = {**filtros, "municipios": []}
                resultados = self.buscador.buscar(
                    texto_consulta=preprocessado["texto_limpo"],
                    filtros=filtros_sem_mun,
                    top_k=self.top_k,
                )
                resultados_geo = self.buscador.buscar(
                    texto_consulta=preprocessado["texto_limpo"],
                    filtros=filtros_sem_mun,
                    top_k=1000,
                )
                entidades_resumo = {**entidades, "municipios": []}
        else:
            resultados = self.buscador.buscar(
                texto_consulta=preprocessado["texto_limpo"],
                filtros=filtros,
                top_k=self.top_k,
            )
            resultados_geo = self.buscador.buscar(
                texto_consulta=preprocessado["texto_limpo"],
                filtros=filtros,
                top_k=1000,
            )

        resposta = self.gerador.gerar(
            pergunta=pergunta,
            intencao=intencao,
            confianca=confianca,
            entidades=entidades_resumo,
            resultados=resultados,
            resultados_geo=resultados_geo,
        )

        resposta["tempo_processamento_ms"] = round((time.time() - inicio) * 1000, 1)
        resposta["preprocessamento"] = {
            "tokens_limpos": preprocessado["tokens_limpos"],
            "stems": preprocessado["stems"],
        }

        return resposta
