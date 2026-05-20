"""Normalizacao tolerante a erros de digitacao e abreviacoes comuns.

Aplicada ANTES do classificador para reduzir dependencia da grafia exata.
"""

from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher


# Apelidos populares -> nome oficial do municipio
APELIDOS_MUNICIPIO: dict[str, str] = {
    "caragua": "Caraguatatuba",
    "sjc": "São José dos Campos",
    "sjcampos": "São José dos Campos",
    "sj campos": "São José dos Campos",
    "rio preto": "São José do Rio Preto",
    "sjrp": "São José do Rio Preto",
    "campos do jordao": "Campos do Jordão",
    "abc": "Santo André",
    "vix": "Vitória",
    "rib preto": "Ribeirão Preto",
    "rp": "Ribeirão Preto",
    "presidente prudente": "Presidente Prudente",
    "barretos": "Barretos",
    "sao seba": "São Sebastião",
    "sao sebas": "São Sebastião",
    "saosebastiao": "São Sebastião",
}

# Typos comuns / palavras sem acento que mudam a intencao
TYPOS_PALAVRAS: dict[str, str] = {
    "situasao": "situação",
    "situacao": "situação",
    "situaçao": "situação",
    "situaçãi": "situação",
    "indegena": "indígena",
    "indegenas": "indígenas",
    "indigenas": "indígenas",
    "conservasao": "conservação",
    "conservacao": "conservação",
    "ambiental": "ambiental",
    "anbiental": "ambiental",
    "quimada": "queimada",
    "quimadas": "queimadas",
    "kueimadas": "queimadas",
    "desmatamemto": "desmatamento",
    "desmate": "desmatamento",
    "quilombo": "quilombola",
    "quilombolasque": "quilombolas",
    "imobel": "imóvel",
    "imovel": "imóvel",
    "imoveis": "imóveis",
    "imobeis": "imóveis",
    "fazendas": "fazendas",
    "fasenda": "fazenda",
    "fasendas": "fazendas",
    "panorama": "situação",
    "como esta": "situação de",
    "como está": "situação de",
}


def _remover_acentos(texto: str) -> str:
    nfkd = unicodedata.normalize("NFKD", texto)
    return "".join(c for c in nfkd if not unicodedata.combining(c))


# Palavras-chave canonicas usadas para fuzzy match (similaridade >= 0.75)
# em palavras com >= 5 caracteres. Cobertura: termos que disparam intent.
PALAVRAS_CANONICAS: list[str] = [
    "situação",
    "resumo",
    "panorama",
    "queimadas", "queimada",
    "desmatamento", "desmate",
    "indígenas", "indígena",
    "conservação",
    "quilombolas", "quilombola",
    "ambiental",
    "imóvel", "imóveis",
    "fazenda", "fazendas",
    "cadastro",
    "rural", "rurais",
]


def _similaridade(a: str, b: str) -> float:
    return SequenceMatcher(None, a, b).ratio()


def _corrigir_typo_fuzzy(palavra: str) -> str | None:
    """Se `palavra` (sem acento, lower) eh suficientemente proxima de uma
    palavra canonica, retorna a forma canonica. Caso contrario, None.
    """
    p = _remover_acentos(palavra.lower())
    if len(p) < 5:
        return None

    melhor_palavra: str | None = None
    melhor_score = 0.0
    for canonica in PALAVRAS_CANONICAS:
        c = _remover_acentos(canonica.lower())
        if abs(len(p) - len(c)) > 3:
            continue  # diferenca de tamanho grande, nao eh typo
        score = _similaridade(p, c)
        if score > melhor_score:
            melhor_score = score
            melhor_palavra = canonica

    if melhor_palavra is not None and melhor_score >= 0.78:
        # Se ja eh exatamente a palavra canonica (sem acento), retorna ela
        # pra preservar acentuacao correta.
        return melhor_palavra
    return None


def normalizar_pergunta(pergunta: str) -> str:
    """Normaliza a pergunta corrigindo typos comuns e expandindo apelidos.

    Sempre preserva o texto original quando possivel — apenas substitui
    palavras conhecidas no dicionario.
    """
    if not pergunta:
        return pergunta

    texto = pergunta

    # 1) Expande apelidos de municipio (maior precedencia — match por substring).
    texto_lower = texto.lower()
    texto_sem_acento = _remover_acentos(texto_lower)
    for apelido, nome_oficial in APELIDOS_MUNICIPIO.items():
        ap_norm = _remover_acentos(apelido.lower())
        if re.search(rf"\b{re.escape(ap_norm)}\b", texto_sem_acento):
            # Substitui no texto original, case-insensitive
            texto = re.sub(
                rf"\b{re.escape(apelido)}\b", nome_oficial, texto, flags=re.IGNORECASE,
            )
            # Tambem tenta com versao sem acentos (para entrada "sao seba")
            apelido_sem_acento = _remover_acentos(apelido)
            if apelido_sem_acento != apelido:
                texto = re.sub(
                    rf"\b{re.escape(apelido_sem_acento)}\b",
                    nome_oficial,
                    texto,
                    flags=re.IGNORECASE,
                )

    # 2) Corrige typos palavra por palavra: dicionario fixo primeiro,
    #    depois fuzzy match (Levenshtein) contra palavras canonicas.
    def _substituir(match: re.Match) -> str:
        palavra = match.group(0)
        chave = _remover_acentos(palavra.lower())
        if chave in TYPOS_PALAVRAS:
            return TYPOS_PALAVRAS[chave]
        fuzzy = _corrigir_typo_fuzzy(palavra)
        if fuzzy is not None:
            return fuzzy
        return palavra

    texto = re.sub(r"\b[\wÀ-ÿ]+\b", _substituir, texto)

    return texto
