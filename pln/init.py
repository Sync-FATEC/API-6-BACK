"""Pacote de utilitários de PLN (processamento de linguagem natural)."""

from pln.preprocessador import (
    ModoReducaoLexical,
    Preprocessador,
    ResultadoPreprocessamento,
    limpar_texto,
    normalizar_unicode,
    preprocessar_texto,
    remover_acentos,
    tokens_para_vetorizacao,
)

__all__ = [
    "ModoReducaoLexical",
    "Preprocessador",
    "ResultadoPreprocessamento",
    "limpar_texto",
    "normalizar_unicode",
    "preprocessar_texto",
    "remover_acentos",
    "tokens_para_vetorizacao",
]
