"""Etapa 4 da pipeline PLN: Treinamento de modelo de IA.
Classificador de intencao usando Naive Bayes + TF-IDF.
"""

import json
from pathlib import Path

import joblib
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.naive_bayes import MultinomialNB
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import LabelEncoder

from asg_sistema.pln.preprocessador import PreprocessadorPLN


class ClassificadorIntencao:
    def __init__(self, preprocessador: PreprocessadorPLN):
        self.preprocessador = preprocessador
        self.label_encoder = LabelEncoder()
        self.pipeline = Pipeline([
            ("tfidf", TfidfVectorizer(max_features=3000, ngram_range=(1, 2))),
            ("clf", MultinomialNB(alpha=0.1)),
        ])

    def treinar(self, textos: list[str], intencoes: list[str]):
        textos_processados = [
            self.preprocessador.preprocessar(t)["texto_limpo"] for t in textos
        ]
        self.label_encoder.fit(intencoes)
        y = self.label_encoder.transform(intencoes)
        self.pipeline.fit(textos_processados, y)

    def treinar_de_arquivo(self, caminho: Path):
        with open(caminho, "r", encoding="utf-8") as f:
            dados = json.load(f)
        textos = [d["texto"] for d in dados]
        intencoes = [d["intencao"] for d in dados]
        self.treinar(textos, intencoes)

    def classificar(self, texto: str) -> tuple[str, float]:
        texto_limpo = self.preprocessador.preprocessar(texto)["texto_limpo"]
        proba = self.pipeline.predict_proba([texto_limpo])[0]
        idx = proba.argmax()
        intencao = self.label_encoder.inverse_transform([idx])[0]
        confianca = float(proba[idx])
        return intencao, confianca

    def classificar_multiplo(self, texto: str, limiar: float = 0.10) -> list[tuple[str, float]]:
        """Retorna todas as intenções com probabilidade acima do limiar, ordenadas."""
        texto_limpo = self.preprocessador.preprocessar(texto)["texto_limpo"]
        proba = self.pipeline.predict_proba([texto_limpo])[0]
        resultados = []
        for idx, p in enumerate(proba):
            if p >= limiar:
                intencao = self.label_encoder.inverse_transform([idx])[0]
                resultados.append((intencao, float(p)))
        resultados.sort(key=lambda x: x[1], reverse=True)
        return resultados

    def salvar(self, diretorio: Path):
        diretorio.mkdir(parents=True, exist_ok=True)
        joblib.dump(self.pipeline, diretorio / "classificador_intencao.pkl")
        joblib.dump(self.label_encoder, diretorio / "label_encoder.pkl")

    def carregar(self, diretorio: Path):
        self.pipeline = joblib.load(diretorio / "classificador_intencao.pkl")
        self.label_encoder = joblib.load(diretorio / "label_encoder.pkl")
