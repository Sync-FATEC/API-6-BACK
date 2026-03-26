"""Etapa 3 da pipeline PLN: Modelo de linguagem.
Representacao numerico-matematica do corpus ASG.
"""

import numpy as np

from asg_sistema.pln.extrator_caracteristicas import ExtratorCaracteristicas


class ModeloLinguagem:
    def __init__(self, extrator: ExtratorCaracteristicas):
        self.extrator = extrator
        self.tfidf_matrix = None
        self.embedding_matrix = None
        self.corpus_ids: list[int] = []
        self.corpus_textos: list[str] = []

    def construir(self, textos: list[str], ids: list[int]):
        self.corpus_textos = textos
        self.corpus_ids = ids
        self.tfidf_matrix = self.extrator.tfidf_fit(textos)
        self.embedding_matrix = self.extrator.embeddings(textos)

    def representar_consulta_tfidf(self, texto_limpo: str):
        return self.extrator.tfidf_transform([texto_limpo])

    def representar_consulta_embedding(self, texto: str) -> np.ndarray:
        return self.extrator.embedding_unico(texto)
