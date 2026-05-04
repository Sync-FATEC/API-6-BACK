"""Extracao de entidades: municipios, periodos temporais e codigo CAR (SICAR)."""

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
        out: dict = {"municipios": municipios, "periodo": periodo}
        # Extração do outro dev (cod_imovel único)
        cod = extrair_cod_imovel_do_texto(texto)
        if cod:
            out["cod_imovel"] = cod
        # Extração adicional para cruzamento espacial (lista de códigos)
        codigos_car = self._extrair_codigos_car(texto)
        if codigos_car:
            out["codigos_car"] = codigos_car
            if not out.get("cod_imovel"):
                out["cod_imovel"] = codigos_car[0]
        return out

    def _extrair_municipios(self, texto: str) -> list[str]:
        texto_lower = texto.lower()
        encontrados = []
        for chave, nome_original in self.municipios_norm.items():
            if len(chave) >= 4 and chave in texto_lower:
                if nome_original not in encontrados:
                    encontrados.append(nome_original)
        return encontrados

    def _extrair_codigos_car(self, texto: str) -> list[str]:
        """Extrai códigos CAR no padrão UF-IBGE-SEQUENCIAL (ex: SP-3524808-123456789ABC)."""
        padrao = r'\b([A-Z]{2}[-.]?\d{7}[-.]?\w{12,})\b'
        matches = re.findall(padrao, texto, re.IGNORECASE)
        return [m.upper().replace(".", "-") for m in matches]

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


_PADROES_COD_IMOVEL = [
    re.compile(
        r"(?i)(?:c(?:ó|o)digo\s*)?(?:do\s+)?(?:\bcar\b|\bsicar\b)\s*[:#]?\s*([A-Z0-9.\-_]{12,})",
    ),
    re.compile(
        r"\b((?:BR[\-_./]?(?:[A-Z]{2})[\-_./]?)?[A-Z]{2}[\-_]\d{4,}(?:[.\-_0-9A-Za-z]{8,}))\b",
    ),
]


def extrair_cod_imovel_do_texto(texto: str) -> str | None:
    """Extrai cod_imovel (CAR) mencionado na pergunta."""
    if not texto or not texto.strip():
        return None
    t = texto.strip()
    for rx in _PADROES_COD_IMOVEL:
        m = rx.search(t)
        if m:
            cod = m.group(1).strip(" .,:;")
            if len(cod) >= 12:
                return cod
    return None
