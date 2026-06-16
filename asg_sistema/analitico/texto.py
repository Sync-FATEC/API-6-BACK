"""Normalização e fuzzy matching (RapidFuzz + Unidecode) p/ value linking.

Tolerante a acento e erro ortográfico. Usado no slot extraction e no
ExtratorEntidades (substitui o difflib).
"""

from rapidfuzz import fuzz, process
from unidecode import unidecode


def normalizar(texto: str) -> str:
    """Minúsculas, sem acento, sem espaços nas pontas."""
    return unidecode((texto or "").lower().strip())


def melhor_match(termo: str, candidatos: list[str]) -> tuple[str | None, float]:
    """Retorna (candidato_original, score 0..100) comparando sem acento.

    Usa WRatio (robusto a ordem/substring). Score 0 quando não há candidato.
    """
    if not termo or not candidatos:
        return None, 0.0
    mapa = {normalizar(c): c for c in candidatos}
    achado = process.extractOne(normalizar(termo), list(mapa.keys()), scorer=fuzz.WRatio)
    if not achado:
        return None, 0.0
    chave, score, _ = achado
    return mapa[chave], float(score)
