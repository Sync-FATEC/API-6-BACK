"""Orquestrador: recebe pergunta do usuario e retorna resposta completa."""

import time

from asg_sistema.pln.preprocessador import PreprocessadorPLN
from asg_sistema.pln.classificador import ClassificadorIntencao
from asg_sistema.pln.buscador_semantico import BuscadorSemantico
from asg_sistema.motor.entidades import ExtratorEntidades
from asg_sistema.motor.gerador_resposta import GeradorResposta
from asg_sistema.db import repositorio
from asg_sistema.config import config


MAPA_INTENCAO_FONTE = {
    "consultar_queimadas": "queimadas",
    "consultar_desmatamento": "deter",
    "consultar_terra_indigena": "funai",
    "consultar_unidade_conservacao": "icmbio",
    "consultar_quilombola": "palmares",
    "consultar_prodes": "prodes",
    "consultar_imovel_rural": "sicar",
    "resumo_municipal": None,
}

# Intencoes que buscam em múltiplas fontes simultaneamente
MAPA_INTENCAO_FONTES_MULTIPLAS = {
    "consultar_desmatamento": ["deter", "prodes"],
}

# Palavras-chave fortes para detecção de intenções secundárias
KEYWORDS_INTENCAO = {
    "consultar_queimadas": ["queimada", "queimadas", "incendio", "incêndio", "fogo", "foco de calor"],
    "consultar_desmatamento": ["desmatamento", "desmatado", "deter", "supressão", "desflorestamento"],
    "consultar_terra_indigena": ["indígena", "indigena", "aldeia", "funai", "terra indígena"],
    "consultar_unidade_conservacao": ["conservação", "conservacao", "parque", "reserva", "apa", "icmbio"],
    "consultar_quilombola": ["quilombo", "quilombola", "palmares"],
    "consultar_prodes": ["prodes"],
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
                "resumo": "Não encontrei informações relacionadas à sua pergunta. Tente consultar sobre queimadas, desmatamento, terras indígenas, unidades de conservação ou comunidades quilombolas no Estado de São Paulo.",
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

        # Detectar intenções secundárias via keywords
        intencoes_secundarias = self._detectar_intencoes_secundarias(
            pergunta, intencao
        )

        if intencoes_secundarias:
            resposta = self._processar_intencoes_multiplas(
                pergunta, preprocessado, intencao, confianca,
                intencoes_secundarias, entidades,
            )
        else:
            resposta = self._processar_intencao_unica(
                pergunta, preprocessado, intencao, confianca, entidades,
            )

        resposta["tempo_processamento_ms"] = round((time.time() - inicio) * 1000, 1)
        resposta["preprocessamento"] = {
            "tokens_originais": preprocessado["tokens_originais"],
            "tokens_limpos": preprocessado["tokens_limpos"],
            "stems": preprocessado["stems"],
            "lemmas": preprocessado["lemmas"],
            "texto_limpo": preprocessado["texto_limpo"],
        }

        return resposta

    def _detectar_intencoes_secundarias(
        self, pergunta: str, intencao_principal: str,
    ) -> list[tuple[str, float]]:
        """Detecta intenções adicionais via keywords + probabilidade do classificador."""
        texto_lower = pergunta.lower()
        candidatos = []

        for intent_candidato, keywords in KEYWORDS_INTENCAO.items():
            if intent_candidato == intencao_principal:
                continue
            if intent_candidato not in MAPA_INTENCAO_FONTE:
                continue
            if any(kw in texto_lower for kw in keywords):
                candidatos.append(intent_candidato)

        if not candidatos:
            return []

        todas_probs = self.classificador.classificar_multiplo(pergunta, limiar=0.10)
        prob_map = {i: c for i, c in todas_probs}

        secundarias = []
        for cand in candidatos:
            prob = prob_map.get(cand, 0.0)
            if prob >= 0.10:
                secundarias.append((cand, prob))

        secundarias.sort(key=lambda x: x[1], reverse=True)
        return secundarias[:2]  # máximo 2 intenções secundárias

    def _buscar_para_intencao(self, texto_limpo, intencao, entidades, top_k, top_k_geo):
        """Executa busca para uma única intenção, retorna (resultados, resultados_geo)."""
        fontes_multiplas = MAPA_INTENCAO_FONTES_MULTIPLAS.get(intencao)
        filtros = {
            "fonte": MAPA_INTENCAO_FONTE.get(intencao) if not fontes_multiplas else None,
            "fontes": fontes_multiplas,
            "municipios": entidades.get("municipios", []),
            "periodo": entidades.get("periodo", {}),
        }

        if fontes_multiplas:
            # Busca separada por fonte para garantir representação
            metade = max(top_k // 2, 5)
            metade_geo = max(top_k_geo // 2, 100)

            filtros_deter = {**filtros, "fontes": None, "fonte": "deter"}
            filtros_prodes = {**filtros, "fontes": None, "fonte": "prodes"}

            res_deter = self.buscador.buscar(
                texto_consulta=texto_limpo, filtros=filtros_deter, top_k=metade,
            )
            res_prodes = self.buscador.buscar(
                texto_consulta=texto_limpo, filtros=filtros_prodes, top_k=metade,
            )
            ids_vistos = {r["id"] for r in res_deter}
            resultados = list(res_deter)
            for r in res_prodes:
                if r["id"] not in ids_vistos:
                    resultados.append(r)

            geo_deter = self.buscador.buscar(
                texto_consulta=texto_limpo, filtros=filtros_deter, top_k=metade_geo,
            )
            geo_prodes = self.buscador.buscar(
                texto_consulta=texto_limpo, filtros=filtros_prodes, top_k=metade_geo,
            )
            ids_vistos_geo = {r["id"] for r in geo_deter}
            resultados_geo = list(geo_deter)
            for r in geo_prodes:
                if r["id"] not in ids_vistos_geo:
                    resultados_geo.append(r)
        else:
            resultados = self.buscador.buscar(
                texto_consulta=texto_limpo, filtros=filtros, top_k=top_k,
            )
            resultados_geo = self.buscador.buscar(
                texto_consulta=texto_limpo, filtros=filtros, top_k=top_k_geo,
            )

        return resultados, resultados_geo

    def _processar_intencoes_multiplas(
        self, pergunta, preprocessado, intencao_principal, confianca,
        intencoes_secundarias, entidades,
    ) -> dict:
        """Processa múltiplas intenções e faz merge dos resultados."""
        todas_intencoes = [(intencao_principal, confianca)] + intencoes_secundarias
        top_k_por_intencao = max(self.top_k // len(todas_intencoes), 5)
        geo_por_intencao = max(500 // len(todas_intencoes), 100)

        todos_resultados = []
        todos_geo = []
        ids_vistos = set()
        ids_geo_vistos = set()

        for intent, _ in todas_intencoes:
            res, res_geo = self._buscar_para_intencao(
                preprocessado["texto_limpo"], intent, entidades,
                top_k_por_intencao, geo_por_intencao,
            )
            for r in res:
                if r["id"] not in ids_vistos:
                    ids_vistos.add(r["id"])
                    todos_resultados.append(r)
            for r in res_geo:
                if r["id"] not in ids_geo_vistos:
                    ids_geo_vistos.add(r["id"])
                    todos_geo.append(r)

        lista_intencoes = [
            {"intencao": i, "confianca": round(c, 3)} for i, c in todas_intencoes
        ]
        resposta = self.gerador.gerar(
            pergunta=pergunta,
            intencao=intencao_principal,
            confianca=confianca,
            entidades=entidades,
            resultados=todos_resultados,
            resultados_geo=todos_geo,
            intencoes_detectadas=lista_intencoes,
        )
        resposta["intencoes_detectadas"] = lista_intencoes
        return resposta

    def _processar_intencao_unica(
        self, pergunta, preprocessado, intencao, confianca, entidades,
    ) -> dict:
        """Processa uma única intenção (lógica original)."""
        fontes_multiplas = MAPA_INTENCAO_FONTES_MULTIPLAS.get(intencao)
        filtros = {
            "fonte": MAPA_INTENCAO_FONTE.get(intencao) if not fontes_multiplas else None,
            "fontes": fontes_multiplas,
            "uf_sigla": config.uf_escopo,
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
                uf_sigla=config.uf_escopo,
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
                uf_sigla=config.uf_escopo,
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

        elif fontes_multiplas:
            # Sem município: busca separada por fonte para garantir representação
            metade = max(self.top_k // 2, 5)
            metade_geo = 500

            filtros_deter = {**filtros, "fontes": None, "fonte": "deter"}
            filtros_prodes = {**filtros, "fontes": None, "fonte": "prodes"}

            resultados_deter = self.buscador.buscar(
                texto_consulta=preprocessado["texto_limpo"],
                filtros=filtros_deter,
                top_k=metade,
            )
            resultados_prodes = self.buscador.buscar(
                texto_consulta=preprocessado["texto_limpo"],
                filtros=filtros_prodes,
                top_k=metade,
            )

            ids_vistos = {r["id"] for r in resultados_deter}
            resultados = list(resultados_deter)
            for r in resultados_prodes:
                if r["id"] not in ids_vistos:
                    resultados.append(r)
            resultados = resultados[: self.top_k]

            # Geo
            geo_deter = self.buscador.buscar(
                texto_consulta=preprocessado["texto_limpo"],
                filtros=filtros_deter,
                top_k=metade_geo,
            )
            geo_prodes = self.buscador.buscar(
                texto_consulta=preprocessado["texto_limpo"],
                filtros=filtros_prodes,
                top_k=metade_geo,
            )
            ids_vistos_geo = {r["id"] for r in geo_deter}
            resultados_geo = list(geo_deter)
            for r in geo_prodes:
                if r["id"] not in ids_vistos_geo:
                    resultados_geo.append(r)

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

            # Fallback: UC com município não encontrou -> busca sem município
            if (
                intencao == "consultar_unidade_conservacao"
                and not resultados
                and filtros.get("municipios")
            ):
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

        return self.gerador.gerar(
            pergunta=pergunta,
            intencao=intencao,
            confianca=confianca,
            entidades=entidades_resumo,
            resultados=resultados,
            resultados_geo=resultados_geo,
        )
