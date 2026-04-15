"""Schemas Pydantic para request/response da API."""

from pydantic import BaseModel, Field


class ConsultaRequest(BaseModel):
    pergunta: str = Field(..., min_length=1, max_length=500)
    cod_imovel: str | None = Field(
        default=None,
        max_length=260,
        description="Código CAR / cod_imovel (SICAR) do imóvel rural para contextualizar a consulta.",
    )


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
