"""Etapa 1 da pipeline PLN: Pre-processamento.
Tokenizacao, remocao de stopwords, stemming e lematizacao.
"""

import nltk
from nltk.corpus import stopwords
from nltk.stem import RSLPStemmer
from nltk.tokenize import word_tokenize

nltk.download("punkt", quiet=True)
nltk.download("punkt_tab", quiet=True)
nltk.download("stopwords", quiet=True)
nltk.download("rslp", quiet=True)


class PreprocessadorPLN:
    def __init__(self):
        self.stemmer = RSLPStemmer()
        self.stopwords_pt = set(stopwords.words("portuguese"))
        self.stopwords_pt.update({
            "favor", "gostaria", "saber", "pode", "poderia",
            "quero", "preciso", "sobre", "qual", "quais",
        })
        self._nlp = None

    @property
    def nlp(self):
        if self._nlp is None:
            import spacy
            self._nlp = spacy.load("pt_core_news_sm")
        return self._nlp

    def tokenizar(self, texto: str) -> list[str]:
        return word_tokenize(texto.lower(), language="portuguese")

    def remover_stopwords(self, tokens: list[str]) -> list[str]:
        return [t for t in tokens if t not in self.stopwords_pt and t.isalpha()]

    def aplicar_stemming(self, tokens: list[str]) -> list[str]:
        return [self.stemmer.stem(t) for t in tokens]

    def aplicar_lematizacao(self, texto: str) -> list[str]:
        doc = self.nlp(texto.lower())
        return [token.lemma_ for token in doc if not token.is_stop and token.is_alpha]

    def preprocessar(self, texto: str) -> dict:
        tokens = self.tokenizar(texto)
        tokens_limpos = self.remover_stopwords(tokens)
        stems = self.aplicar_stemming(tokens_limpos)
        lemmas = self.aplicar_lematizacao(texto)
        texto_limpo = " ".join(tokens_limpos)
        return {
            "tokens_originais": tokens,
            "tokens_limpos": tokens_limpos,
            "stems": stems,
            "lemmas": lemmas,
            "texto_limpo": texto_limpo,
        }
