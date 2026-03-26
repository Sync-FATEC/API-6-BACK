"""Schemas Pydantic para request/response da API."""

from pydantic import BaseModel, Field


class ConsultaRequest(BaseModel):
    pergunta: str = Field(..., min_length=3, max_length=500)


class ConsultaResponse(BaseModel):
    pergunta: str
    intencao_detectada: str
    confianca: float
    entidades: dict
    resumo: str
    estatisticas: dict
    dados: list[dict]
    fontes: list[dict]
    geojson: dict | None = None
    total_resultados: int
    tempo_processamento_ms: float
    preprocessamento: dict | None = None
