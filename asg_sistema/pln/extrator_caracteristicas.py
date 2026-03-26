"""Etapa 2 da pipeline PLN: Extracao de caracteristicas.
Bag of Words, TF-IDF e embeddings semanticos.
"""

import numpy as np
from sklearn.feature_extraction.text import CountVectorizer, TfidfVectorizer


class ExtratorCaracteristicas:
    def __init__(self, modelo_embeddings: str = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"):
        self.count_vectorizer = CountVectorizer(max_features=5000, ngram_range=(1, 2))
        self.tfidf_vectorizer = TfidfVectorizer(max_features=5000, ngram_range=(1, 2), sublinear_tf=True)
        self._modelo_embeddings_nome = modelo_embeddings
        self._sentence_model = None

    @property
    def sentence_model(self):
        if self._sentence_model is None:
            from sentence_transformers import SentenceTransformer
            self._sentence_model = SentenceTransformer(self._modelo_embeddings_nome)
        return self._sentence_model

    def bow(self, corpus: list[str]):
        return self.count_vectorizer.fit_transform(corpus)

    def tfidf_fit(self, corpus: list[str]):
        return self.tfidf_vectorizer.fit_transform(corpus)

    def tfidf_transform(self, textos: list[str]):
        return self.tfidf_vectorizer.transform(textos)

    def embeddings(self, textos: list[str]) -> np.ndarray:
        return self.sentence_model.encode(textos, show_progress_bar=False, batch_size=64)

    def embedding_unico(self, texto: str) -> np.ndarray:
        return self.sentence_model.encode([texto])[0]
