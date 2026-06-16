"""Schema linking por embeddings: pergunta -> tabela/métrica/dimensões via cosseno.

Reusa o ExtratorCaracteristicas (sentence-transformers MiniLM multilíngue). As
frases-âncora do catálogo são embedadas uma única vez e ficam em memória.
"""

from dataclasses import dataclass, field

import numpy as np
from sklearn.metrics.pairwise import cosine_similarity

from asg_sistema.analitico.catalogo import CATALOGO_SEMANTICO
from asg_sistema.pln.extrator_caracteristicas import ExtratorCaracteristicas


@dataclass
class ResultadoLink:
    tabela: str | None = None
    metrica_agg: str | None = None
    dimensoes: list[str] = field(default_factory=list)
    confianca: float = 0.0
    scores: dict = field(default_factory=dict)
    # Todas as tabelas candidatas (alvo -> melhor score), ordenadas desc.
    tabelas: list[tuple[str, float]] = field(default_factory=list)


class SchemaLinker:
    def __init__(self, extrator: ExtratorCaracteristicas | None = None, limiar: float = 0.35):
        self.extrator = extrator or ExtratorCaracteristicas()
        self.limiar = limiar
        self._ancoras = CATALOGO_SEMANTICO
        frases = [a["frase"] for a in self._ancoras]
        self._emb_ancoras = np.asarray(self.extrator.embeddings(frases))

    def ligar(self, pergunta: str) -> ResultadoLink:
        emb = np.asarray(self.extrator.embedding_unico(pergunta)).reshape(1, -1)
        sims = cosine_similarity(emb, self._emb_ancoras)[0]

        melhor_por_tipo: dict[str, tuple[str, float]] = {}
        dims: list[tuple[str, float]] = []
        tabela_scores: dict[str, float] = {}  # alvo -> melhor score (todas as tabelas)
        for ancora, s in zip(self._ancoras, sims):
            tipo, alvo = ancora["tipo"], ancora["alvo"]
            if tipo == "dimensao":
                if s >= self.limiar:
                    dims.append((alvo, float(s)))
            else:
                if tipo == "tabela":
                    if alvo not in tabela_scores or s > tabela_scores[alvo]:
                        tabela_scores[alvo] = float(s)
                atual = melhor_por_tipo.get(tipo)
                if atual is None or s > atual[1]:
                    melhor_por_tipo[tipo] = (alvo, float(s))

        res = ResultadoLink()
        if "tabela" in melhor_por_tipo and melhor_por_tipo["tabela"][1] >= self.limiar:
            res.tabela = melhor_por_tipo["tabela"][0]
        if "metrica" in melhor_por_tipo and melhor_por_tipo["metrica"][1] >= self.limiar:
            res.metrica_agg = melhor_por_tipo["metrica"][0]

        vistos: set[str] = set()
        for alvo, _s in sorted(dims, key=lambda x: -x[1]):
            if alvo not in vistos:
                res.dimensoes.append(alvo)
                vistos.add(alvo)

        res.scores = {k: round(v[1], 3) for k, v in melhor_por_tipo.items()}
        res.tabelas = sorted(tabela_scores.items(), key=lambda x: -x[1])
        # Confiança é guiada pela ligação da TABELA (decisão crítica). A métrica
        # tem default seguro (COUNT), então não deve derrubar a confiança.
        res.confianca = float(melhor_por_tipo["tabela"][1]) if "tabela" in melhor_por_tipo else 0.0
        return res
