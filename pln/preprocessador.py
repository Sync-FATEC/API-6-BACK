"""
Pré-processamento de texto em português para PLN.

Inclui normalização Unicode, limpeza (URLs, e-mails, ruído), tokenização com
spaCy, remoção opcional de stopwords, lemmatização (spaCy) ou stemming (NLTK
Snowball, português) e saída pronta para vetorização (TF-IDF, CountVectorizer).
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from enum import Enum
from functools import lru_cache
from typing import Any, Optional

# Padrões de limpeza
_RE_URL = re.compile(r"https?://\S+|www\.\S+", re.IGNORECASE)
_RE_EMAIL = re.compile(r"\S+@\S+")
_RE_ESPACOS = re.compile(r"\s+")


class ModoReducaoLexical(Enum):
    """Como reduzir flexões após a tokenização."""

    NENHUM = "nenhum"
    LEMMA = "lemma"
    STEM = "stem"


@dataclass(frozen=True)
class ResultadoPreprocessamento:
    """Resultado do pipeline de pré-processamento."""

    texto_limpo: str
    tokens: list[str]
    texto_para_vetorizacao: str


def normalizar_unicode(texto: str, forma: str = "NFKC") -> str:
    """Normaliza o texto com unicodedata (padrão NFKC)."""
    return unicodedata.normalize(forma, texto)


def remover_acentos(texto: str) -> str:
    """Remove marcas diacríticas (NFD + filtro de combining)."""
    nfd = unicodedata.normalize("NFD", texto)
    return "".join(c for c in nfd if unicodedata.category(c) != "Mn")


def limpar_texto(
    texto: str,
    *,
    minusculas: bool = True,
    remover_urls: bool = True,
    remover_emails: bool = True,
    remover_numeros: bool = False,
    forma_unicode: str = "NFKC",
    sem_acentos: bool = False,
) -> str:
    """
    Limpeza superficial antes da tokenização spaCy.

    Não substitui o tokenizador; remove ruído comum e uniformiza caixa/Unicode.
    """
    if not texto:
        return ""
    t = texto.strip()
    t = normalizar_unicode(t, forma_unicode)
    if sem_acentos:
        t = remover_acentos(t)
    if remover_urls:
        t = _RE_URL.sub(" ", t)
    if remover_emails:
        t = _RE_EMAIL.sub(" ", t)
    if remover_numeros:
        t = re.sub(r"\d+", " ", t)
    if minusculas:
        t = t.lower()
    t = _RE_ESPACOS.sub(" ", t).strip()
    return t


def tokens_para_vetorizacao(tokens: list[str]) -> str:
    """Junta tokens com espaço, formato usual para CountVectorizer / TfidfVectorizer."""
    return " ".join(tokens)


@lru_cache(maxsize=1)
def _stemmer_portugues():
    from nltk.stem import SnowballStemmer

    return SnowballStemmer("portuguese")


_nlp_por_modelo: dict[str, Any] = {}


def _carregar_spacy(nome_modelo: str):
    if nome_modelo not in _nlp_por_modelo:
        try:
            import spacy
        except ImportError as e:
            raise ImportError(
                "Instale spaCy e o modelo em português, por exemplo: "
                "pip install spacy && python -m spacy download pt_core_news_sm"
            ) from e
        try:
            _nlp_por_modelo[nome_modelo] = spacy.load(nome_modelo)
        except OSError as e:
            raise OSError(
                f'Modelo spaCy "{nome_modelo}" não encontrado. '
                f"Execute: python -m spacy download {nome_modelo}"
            ) from e
    return _nlp_por_modelo[nome_modelo]


def _reduzir_lexema(palavra: str, modo: ModoReducaoLexical) -> str:
    if modo == ModoReducaoLexical.NENHUM:
        return palavra
    if modo == ModoReducaoLexical.STEM:
        return _stemmer_portugues().stem(palavra)
    return palavra


class Preprocessador:
    """
    Pipeline configurável: limpeza → spaCy → stopwords → lemma/stem → string para vetores.
    """

    def __init__(
        self,
        *,
        modelo_spacy: str = "pt_core_news_sm",
        modo_reducao: ModoReducaoLexical = ModoReducaoLexical.LEMMA,
        remover_stopwords: bool = True,
        apenas_alfabetico: bool = True,
        minusculas: bool = True,
        remover_urls: bool = True,
        remover_emails: bool = True,
        remover_numeros: bool = False,
        sem_acentos: bool = False,
    ) -> None:
        self.modelo_spacy = modelo_spacy
        self.modo_reducao = modo_reducao
        self.remover_stopwords = remover_stopwords
        self.apenas_alfabetico = apenas_alfabetico
        self.minusculas = minusculas
        self.remover_urls = remover_urls
        self.remover_emails = remover_emails
        self.remover_numeros = remover_numeros
        self.sem_acentos = sem_acentos

    def preprocessar(self, texto: str) -> ResultadoPreprocessamento:
        texto_limpo = limpar_texto(
            texto,
            minusculas=self.minusculas,
            remover_urls=self.remover_urls,
            remover_emails=self.remover_emails,
            remover_numeros=self.remover_numeros,
            sem_acentos=self.sem_acentos,
        )
        if not texto_limpo:
            return ResultadoPreprocessamento(texto_limpo="", tokens=[], texto_para_vetorizacao="")

        nlp = _carregar_spacy(self.modelo_spacy)
        doc = nlp(texto_limpo)
        tokens: list[str] = []

        for token in doc:
            if token.is_space:
                continue
            if self.apenas_alfabetico and not token.is_alpha:
                continue
            if self.remover_stopwords and token.is_stop:
                continue
            if self.modo_reducao == ModoReducaoLexical.LEMMA:
                lemma = (token.lemma_ or "").strip()
                if lemma.lower() in ("-pron-", ""):
                    lex = token.text.strip()
                else:
                    lex = lemma
            else:
                lex = token.text.strip()
            if self.minusculas:
                lex = lex.lower()
            if not lex:
                continue
            if self.modo_reducao in (ModoReducaoLexical.STEM, ModoReducaoLexical.NENHUM):
                lex = _reduzir_lexema(lex, self.modo_reducao)
            tokens.append(lex)

        return ResultadoPreprocessamento(
            texto_limpo=texto_limpo,
            tokens=tokens,
            texto_para_vetorizacao=tokens_para_vetorizacao(tokens),
        )


def preprocessar_texto(
    texto: str,
    *,
    modelo_spacy: str = "pt_core_news_sm",
    modo_reducao: ModoReducaoLexical = ModoReducaoLexical.LEMMA,
    remover_stopwords: bool = True,
    apenas_alfabetico: bool = True,
    minusculas: bool = True,
    remover_urls: bool = True,
    remover_emails: bool = True,
    remover_numeros: bool = False,
    sem_acentos: bool = False,
    preprocessador: Optional[Preprocessador] = None,
) -> ResultadoPreprocessamento:
    """
    Atalho funcional. Reutilize uma instância de ``Preprocessador`` em lote
    (parâmetro ``preprocessador``) para não recarregar opções a cada chamada.
    """
    proc = preprocessador or Preprocessador(
        modelo_spacy=modelo_spacy,
        modo_reducao=modo_reducao,
        remover_stopwords=remover_stopwords,
        apenas_alfabetico=apenas_alfabetico,
        minusculas=minusculas,
        remover_urls=remover_urls,
        remover_emails=remover_emails,
        remover_numeros=remover_numeros,
        sem_acentos=sem_acentos,
    )
    return proc.preprocessar(texto)
