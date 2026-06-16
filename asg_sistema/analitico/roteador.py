"""Roteador híbrido: heurística + (opcional) embedding.

Classes: ESPACIAL (CAR único) | PROPRIEDADE (risco/evento/espacial de imóveis) |
LISTAGEM (listar registros de uma tabela base) | ANALITICA (agregação/ranking/
tendência/comparação) | DESCRITIVA (conceitual; default seguro).
"""

import re

from asg_sistema.motor.entidades import extrair_cod_imovel_do_texto

# Agregação/ranking/comparação (note: "maior"/"menor" singular contam).
_RE_ANALITICA = re.compile(
    r"\b(top|maior(?:es)?|menor(?:es)?|ranking|quantos?|quantas?|total|soma|somat[óo]rio|"
    r"m[ée]dia|contagem|n[úu]mero de|mais|menos|crescimento|aumento|percentual|"
    r"propor[çc][ãa]o|porcentagem|distribui[çc][ãa]o|compare|compara\w*|versus|\bvs\b)\b"
    r"|\bpor\s+(munic[íi]pio|cidade|ano|m[êe]s|bioma|classe|estado|sat[ée]lite)\b",
    re.IGNORECASE,
)

# Palavras de agregação "fortes" (forçam ANALITICA mesmo em alvo base).
# Inclui plural "municípios/cidades" e "quais <dimensão-plural>" (sinal de agrupamento).
_RE_AGG_FORTE = re.compile(
    r"\b(quantos?|quantas?|total|soma|m[ée]dia|contagem|ranking|top|crescimento|"
    r"percentual|porcentagem|propor[çc][ãa]o|distribui[çc][ãa]o|munic[íi]pios|cidades)\b"
    r"|\bpor\s+\w+"
    r"|\bquais\s+(meses|anos|biomas|sat[ée]lites|classes|munic[íi]pios|cidades)\b",
    re.IGNORECASE,
)
_RE_ANO = re.compile(r"\b(?:19|20)\d{2}\b")

# Alvo = propriedade/imóvel.
_RE_PROP_ALVO = re.compile(
    r"\b(propriedades?|im[óo]ve(?:l|is)|fazendas?|s[íi]tios?|ch[áa]caras?)\b",
    re.IGNORECASE,
)
# Sinal de propriedade = risco/evento/espacial (NÃO inclui "mais/maior" genérico).
_RE_PROP_SINAL = re.compile(
    r"\brisco\b|\bfator(?:es)?\b|[áa]rea impactada|impactad[oa]|pr[óo]xim|recorrent|"
    r"ap[óo]s|depois|sobrep[õo]e|\balertas?\b|\bfocos?\b|\bqueimadas?\b|inc[êe]ndio",
    re.IGNORECASE,
)

# Listagem: verbo de listar / "quais ... <entidade>".
_RE_LISTAR = re.compile(r"\bliste\b|\blistar\b|\bmostre\b|\bquais\b|\bquero ver\b", re.IGNORECASE)
# filtro numérico explícito (entre X e Y, maior/menor que N, mais/menos de N)
_RE_NUMFILTRO = re.compile(
    r"\bentre\s+[\d.]+\s+e\s+[\d.]+|\b(?:maior|menor|acima|abaixo|superior|inferior|mais|menos)\s+(?:que|de|do que|a)?\s*[\d.]+",
    re.IGNORECASE,
)
_RE_ALVO_BASE = re.compile(
    r"terras?\s+ind[íi]gen|unidades?\s+de\s+conserva|\bUCs?\b|quilombol|"
    r"im[óo]ve(?:l|is)|propriedades?|fazendas?|queimadas?|focos?|alertas?|desmatamento",
    re.IGNORECASE,
)


def rotear(pergunta: str, cod_imovel: str | None = None, linker=None) -> str:
    pergunta = pergunta or ""

    if cod_imovel and str(cod_imovel).strip():
        return "ESPACIAL"
    if extrair_cod_imovel_do_texto(pergunta):
        return "ESPACIAL"

    # PROPRIEDADE: imóvel + sinal de risco/evento/espacial.
    if _RE_PROP_ALVO.search(pergunta) and _RE_PROP_SINAL.search(pergunta):
        return "PROPRIEDADE"

    # LISTAGEM: (listar/quais OU filtro numérico) + entidade base, sem agregação forte.
    # Exclui perguntas com ano (ex.: "entre 2023 e 2024") e "compare" -> são ANALITICA.
    if (_RE_ALVO_BASE.search(pergunta) and not _RE_AGG_FORTE.search(pergunta)
            and not _RE_ANO.search(pergunta) and "compar" not in pergunta.lower()
            and (_RE_LISTAR.search(pergunta) or _RE_NUMFILTRO.search(pergunta))):
        return "LISTAGEM"

    # ANALITICA: agregação/ranking/comparação/tendência.
    if _RE_ANALITICA.search(pergunta):
        return "ANALITICA"

    # Desempate opcional por embedding.
    if linker is not None:
        try:
            r = linker.ligar(pergunta)
            if r.tabela and r.metrica_agg and r.confianca >= 0.5:
                return "ANALITICA"
        except Exception:
            pass
    return "DESCRITIVA"
