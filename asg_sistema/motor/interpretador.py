"""Orquestrador: recebe pergunta do usuario e retorna resposta completa."""

import re
import time

from asg_sistema.pln.preprocessador import PreprocessadorPLN
from asg_sistema.pln.classificador import ClassificadorIntencao
from asg_sistema.pln.buscador_semantico import BuscadorSemantico
from asg_sistema.motor.entidades import ExtratorEntidades
from asg_sistema.motor.gerador_resposta import GeradorResposta
from asg_sistema.motor.planner import planejar, SubConsulta
from asg_sistema.motor import executor as executor_mod
from asg_sistema.motor import agregador as agregador_mod
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

MAPA_INTENCAO_FONTES_MULTIPLAS = {
    "consultar_desmatamento": ["deter", "prodes"],
}

KEYWORDS_INTENCAO = {
    "consultar_queimadas": ["queimada", "queimadas", "incendio", "incêndio", "fogo", "foco de calor"],
    "consultar_desmatamento": ["desmatamento", "desmatado", "deter", "supressão", "desflorestamento"],
    "consultar_terra_indigena": ["indígena", "indigena", "aldeia", "funai", "terra indígena"],
    "consultar_unidade_conservacao": ["conservação", "conservacao", "parque", "reserva", "apa", "icmbio"],
    "consultar_quilombola": ["quilombo", "quilombola", "palmares"],
    "consultar_prodes": ["prodes"],
    "consultar_imovel_rural": [
        "fazenda", "fazendas", "sítio", "sitio", "chácara", "chacara",
        "imovel rural", "imóvel rural", "cadastro ambiental", "sicar",
        "codigo car", "código car", "propriedade rural",
    ],
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

    @staticmethod
    def _texto_para_classificacao(pergunta: str) -> str:
        t = pergunta
        pares = [
            (r"\bfazendas?\b", "imóvel rural"),
            (r"\bsítios?\b", "imóvel rural"),
            (r"\bsitios?\b", "imóvel rural"),
            (r"\bchácaras?\b", "imóvel rural"),
            (r"\bchacaras?\b", "imóvel rural"),
            (r"\bestâncias?\b", "imóvel rural"),
            (r"\bestancias?\b", "imóvel rural"),
            (r"\bpropriedades?\s+rurais?\b", "imóvel rural"),
        ]
        for padrao, repl in pares:
            t = re.sub(padrao, repl, t, flags=re.IGNORECASE)
        return t

    def _filtros_geograficos_entidades(self, entidades: dict) -> dict:
        return {
            "municipios": entidades.get("municipios", []),
            "periodo": entidades.get("periodo", {}),
            "cod_imovel": entidades.get("cod_imovel"),
        }

    @staticmethod
    def _exportacao_vazia(pergunta: str, intencao: str, entidades: dict) -> dict:
        return {
            "resumo": {"texto": "", "total_itens": 0},
            "nota_asg": {"valor": 0, "nivel": "sem_dados", "fatores": [], "por_dimensao": {}},
            "tabela": {
                "colunas": [
                    "fonte", "tipo_registro", "municipio", "data_referencia",
                    "similaridade", "descricao", "metadados",
                ],
                "linhas": [],
                "total_linhas": 0,
            },
            "metadados": {
                "versao_payload": "1.0",
                "pergunta_original": pergunta,
                "intencao_detectada": intencao,
                "total_resultados": 0,
                "fontes_consideradas": [],
                "fontes_detalhes": [],
                "entidades": entidades,
            },
        }

    def processar(self, pergunta: str, cod_imovel: str | None = None) -> dict:
        inicio = time.time()

        texto_clf = self._texto_para_classificacao(pergunta)
        preprocessado = self.preprocessador.preprocessar(pergunta)
        intencao, confianca = self.classificador.classificar(texto_clf)

        entidades_pre = self.extrator_entidades.extrair(pergunta)
        cod_pre = entidades_pre.get("cod_imovel") or (cod_imovel.strip() if cod_imovel else None)
        if cod_pre and (confianca < 0.3 or intencao not in MAPA_INTENCAO_FONTE):
            intencao = "consultar_imovel_rural"
            confianca = max(confianca, 0.6)

        if confianca < 0.3 or intencao not in MAPA_INTENCAO_FONTE:
            ent_prev = {}
            if cod_imovel and str(cod_imovel).strip():
                ent_prev["cod_imovel"] = str(cod_imovel).strip()
            return {
                "pergunta": pergunta,
                "intencao_detectada": "fora_do_escopo",
                "confianca": round(confianca, 3) if confianca else 0,
                "entidades": ent_prev,
                "resumo": (
                    "Não encontrei informações relacionadas à sua pergunta. Tente consultar sobre queimadas, "
                    "desmatamento, terras indígenas, unidades de conservação, comunidades quilombolas, "
                    "imóveis rurais (CAR/SICAR) ou resumo municipal no Estado de São Paulo."
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
                "exportacao_relatorio": self._exportacao_vazia(
                    pergunta, "fora_do_escopo", ent_prev
                ),
            }

        entidades = entidades_pre
        if cod_imovel and str(cod_imovel).strip():
            entidades["cod_imovel"] = str(cod_imovel).strip()

        intencoes_secundarias = self._detectar_intencoes_secundarias(
            pergunta, intencao
        )
        plano = planejar(
            intencao_principal=intencao,
            confianca_principal=confianca,
            intencoes_secundarias=intencoes_secundarias,
            entidades=entidades,
        )
        parciais = executor_mod.executar_plano(
            plano=plano,
            preprocessado=preprocessado,
            entidades_base=entidades,
            buscador_subconsulta=self._buscar_subconsulta,
        )
        resposta = agregador_mod.agregar(
            pergunta=pergunta,
            plano=plano,
            entidades_base=entidades,
            parciais=parciais,
            gerador=self.gerador,
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

        todas_probs = self.classificador.classificar_multiplo(
            self._texto_para_classificacao(pergunta), limiar=0.10
        )
        prob_map = {i: c for i, c in todas_probs}

        secundarias = []
        for cand in candidatos:
            prob = prob_map.get(cand, 0.0)
            if prob >= 0.10:
                secundarias.append((cand, prob))

        secundarias.sort(key=lambda x: x[1], reverse=True)
        return secundarias[:2]

    def _buscar_subconsulta(
        self, preprocessado: dict, sub: SubConsulta, entidades_base: dict,
    ) -> dict:
        """Executa UMA subconsulta e retorna a resposta parcial anotada.

        Branch:
        - sub.cod_imovel → caminho CAR (cruzamento espacial).
        - caso contrário → busca semântica padrão.
        """
        if sub.eh_car:
            parcial = self._parcial_car(sub)
        else:
            parcial = self._parcial_busca(preprocessado, sub, entidades_base)

        parcial["_sub"] = {
            "rotulo": sub.rotulo,
            "municipio": sub.municipio,
            "intencao": sub.intencao,
            "confianca": sub.confianca,
            "cod_imovel": sub.cod_imovel,
        }
        return parcial

    def _parcial_busca(
        self, preprocessado: dict, sub: SubConsulta, entidades_base: dict,
    ) -> dict:
        ent_sub = sub.entidades(entidades_base)
        resultados, resultados_geo, ent_efetiva = self._buscar_completo(
            preprocessado, sub.intencao, ent_sub,
        )
        parcial = self.gerador.gerar(
            pergunta="",
            intencao=sub.intencao,
            confianca=sub.confianca,
            entidades=ent_efetiva,
            resultados=resultados,
            resultados_geo=resultados_geo,
        )
        parcial["_raw_resultados"] = resultados
        parcial["_raw_resultados_geo"] = resultados_geo
        return parcial

    def _parcial_car(self, sub: SubConsulta) -> dict:
        import json

        cod = sub.cod_imovel or ""
        imovel = repositorio.buscar_imovel_por_car(cod)

        if not imovel or not imovel.get("geometry"):
            parcial = {
                "intencao_detectada": "consultar_imovel_rural",
                "confianca": round(sub.confianca, 3),
                "entidades": {"codigos_car": [cod]},
                "resumo": f"Nenhum imóvel rural com código CAR {cod} foi encontrado no banco de dados.",
                "estatisticas": {},
                "dados": [],
                "fontes": [],
                "geojson": None,
                "total_resultados": 0,
                "nota_risco": {
                    "nota": 0, "nivel": "sem_dados",
                    "fatores": [], "por_dimensao": {},
                },
                "imovel": None,
                "ameacas_encontradas": [],
                "exportacao_relatorio": self._exportacao_vazia(
                    "", "consultar_imovel_rural", {"codigos_car": [cod]},
                ),
            }
        else:
            geom_json = json.dumps(imovel["geometry"])
            municipio = imovel.get("municipio", "")
            cruzamento = repositorio.cruzamento_espacial_imovel(geom_json, municipio)
            parcial = self.gerador.gerar_resposta_car(
                pergunta="",
                imovel=imovel,
                cruzamento=cruzamento,
            )

        parcial["_raw_resultados"] = []
        parcial["_raw_resultados_geo"] = []
        return parcial

    def _buscar_completo(
        self, preprocessado: dict, intencao: str, entidades: dict,
    ) -> tuple[list, list, dict]:
        """Executa o pipeline de busca para uma intenção + entidades.

        Retorna (resultados, resultados_geo, entidades_efetivas). `entidades_efetivas`
        pode diferir de `entidades` quando um fallback (ex.: remover filtro municipal)
        é acionado.
        """
        fontes_multiplas = MAPA_INTENCAO_FONTES_MULTIPLAS.get(intencao)
        filtros = {
            "fonte": MAPA_INTENCAO_FONTE.get(intencao) if not fontes_multiplas else None,
            "fontes": fontes_multiplas,
            "uf_sigla": config.uf_escopo,
            **self._filtros_geograficos_entidades(entidades),
        }

        entidades_resumo = entidades

        # Desmatamento com município: DETER textual + PRODES espacial por proximidade
        if fontes_multiplas and filtros.get("municipios"):
            municipio = filtros["municipios"][0]
            embedding = self.buscador.extrator.embedding_unico(preprocessado["texto_limpo"])
            embedding_str = "[" + ",".join(str(float(v)) for v in embedding) + "]"

            filtros_deter = {**filtros, "fontes": None, "fonte": "deter"}
            resultados_deter = self.buscador.buscar(
                texto_consulta=preprocessado["texto_limpo"],
                filtros=filtros_deter, top_k=self.top_k,
            )

            uids_prodes = repositorio.buscar_uids_prodes_por_municipio(municipio)
            resultados_prodes = repositorio.busca_vetorial_prodes_uids(
                embedding_str=embedding_str,
                uids=uids_prodes,
                uf_sigla=config.uf_escopo,
                limite=self.top_k,
            )

            ids_vistos = {r["id"] for r in resultados_deter}
            resultados = list(resultados_deter)
            for r in resultados_prodes:
                if r["id"] not in ids_vistos:
                    resultados.append(r)
            resultados = resultados[: self.top_k]

            resultados_geo_deter = self.buscador.buscar(
                texto_consulta=preprocessado["texto_limpo"],
                filtros=filtros_deter, top_k=1000,
            )
            resultados_geo_prodes = repositorio.busca_vetorial_prodes_uids(
                embedding_str=embedding_str,
                uids=uids_prodes,
                uf_sigla=config.uf_escopo,
                limite=1000,
            )
            ids_vistos_geo = {r["id"] for r in resultados_geo_deter}
            resultados_geo = list(resultados_geo_deter)
            for r in resultados_geo_prodes:
                if r["id"] not in ids_vistos_geo:
                    resultados_geo.append(r)

            if not resultados:
                filtros_sem_mun = {**filtros, "municipios": []}
                resultados = self.buscador.buscar(
                    texto_consulta=preprocessado["texto_limpo"],
                    filtros=filtros_sem_mun, top_k=self.top_k,
                )
                resultados_geo = self.buscador.buscar(
                    texto_consulta=preprocessado["texto_limpo"],
                    filtros=filtros_sem_mun, top_k=1000,
                )
                entidades_resumo = {**entidades, "municipios": []}

        elif fontes_multiplas:
            metade = max(self.top_k // 2, 5)
            metade_geo = 500

            filtros_deter = {**filtros, "fontes": None, "fonte": "deter"}
            filtros_prodes = {**filtros, "fontes": None, "fonte": "prodes"}

            resultados_deter = self.buscador.buscar(
                texto_consulta=preprocessado["texto_limpo"],
                filtros=filtros_deter, top_k=metade,
            )
            resultados_prodes = self.buscador.buscar(
                texto_consulta=preprocessado["texto_limpo"],
                filtros=filtros_prodes, top_k=metade,
            )

            ids_vistos = {r["id"] for r in resultados_deter}
            resultados = list(resultados_deter)
            for r in resultados_prodes:
                if r["id"] not in ids_vistos:
                    resultados.append(r)
            resultados = resultados[: self.top_k]

            geo_deter = self.buscador.buscar(
                texto_consulta=preprocessado["texto_limpo"],
                filtros=filtros_deter, top_k=metade_geo,
            )
            geo_prodes = self.buscador.buscar(
                texto_consulta=preprocessado["texto_limpo"],
                filtros=filtros_prodes, top_k=metade_geo,
            )
            ids_vistos_geo = {r["id"] for r in geo_deter}
            resultados_geo = list(geo_deter)
            for r in geo_prodes:
                if r["id"] not in ids_vistos_geo:
                    resultados_geo.append(r)

        else:
            resultados = self.buscador.buscar(
                texto_consulta=preprocessado["texto_limpo"],
                filtros=filtros, top_k=self.top_k,
            )
            resultados_geo = self.buscador.buscar(
                texto_consulta=preprocessado["texto_limpo"],
                filtros=filtros, top_k=1000,
            )

            if (
                intencao == "consultar_unidade_conservacao"
                and not resultados
                and filtros.get("municipios")
            ):
                filtros_sem_mun = {**filtros, "municipios": []}
                resultados = self.buscador.buscar(
                    texto_consulta=preprocessado["texto_limpo"],
                    filtros=filtros_sem_mun, top_k=self.top_k,
                )
                resultados_geo = self.buscador.buscar(
                    texto_consulta=preprocessado["texto_limpo"],
                    filtros=filtros_sem_mun, top_k=1000,
                )

        return resultados, resultados_geo, entidades_resumo
