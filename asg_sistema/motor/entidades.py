"""Extracao de entidades: municipios e periodos temporais."""

import re
from datetime import datetime, timedelta


MAPA_PERIODOS = {
    "hoje": 1,
    "ontem": 2,
    "semana": 7,
    "mês": 30,
    "mes": 30,
    "último mês": 30,
    "ultimo mes": 30,
    "últimos meses": 90,
    "ultimos meses": 90,
    "trimestre": 90,
    "semestre": 180,
    "ano": 365,
    "último ano": 365,
    "ultimo ano": 365,
}


class ExtratorEntidades:
    def __init__(self, municipios: list[str]):
        self.municipios_norm = {}
        for m in municipios:
            self.municipios_norm[m.lower().strip()] = m
            sem_acento = _remover_acentos(m.lower().strip())
            self.municipios_norm[sem_acento] = m

    def extrair(self, texto: str) -> dict:
        municipios = self._extrair_municipios(texto)
        periodo = self._extrair_periodo(texto)
        return {"municipios": municipios, "periodo": periodo}

    def _extrair_municipios(self, texto: str) -> list[str]:
        texto_lower = texto.lower()
        encontrados = []
        for chave, nome_original in self.municipios_norm.items():
            if len(chave) >= 4 and chave in texto_lower:
                if nome_original not in encontrados:
                    encontrados.append(nome_original)
        return encontrados

    def _extrair_periodo(self, texto: str) -> dict:
        texto_lower = texto.lower()
        for padrao, dias in MAPA_PERIODOS.items():
            if padrao in texto_lower:
                fim = datetime.now()
                inicio = fim - timedelta(days=dias)
                return {
                    "inicio": inicio.strftime("%Y-%m-%d"),
                    "fim": fim.strftime("%Y-%m-%d"),
                }

        match = re.search(r"(\d{1,2})\s*(?:últimos|ultimos)\s*(?:meses|dias)", texto_lower)
        if match:
            num = int(match.group(1))
            if "dias" in texto_lower:
                dias = num
            else:
                dias = num * 30
            fim = datetime.now()
            inicio = fim - timedelta(days=dias)
            return {
                "inicio": inicio.strftime("%Y-%m-%d"),
                "fim": fim.strftime("%Y-%m-%d"),
            }

        return {}


def _remover_acentos(texto: str) -> str:
    import unicodedata
    nfkd = unicodedata.normalize("NFKD", texto)
    return "".join(c for c in nfkd if not unicodedata.combining(c))
