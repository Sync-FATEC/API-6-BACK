"""Schemas Pydantic para request/response da API."""

from pydantic import BaseModel, Field


class ConsultaRequest(BaseModel):
    pergunta: str = Field(..., min_length=1, max_length=500)
    cod_imovel: str | None = Field(
        default=None,
        max_length=260,
        description="Código CAR / cod_imovel (SICAR) do imóvel rural para contextualizar a consulta.",
    )
    conversa_id: int | None = Field(
        default=None,
        description="ID da conversa existente. Se não informado e houver autenticação, uma nova conversa é criada.",
    )


class GrupoResposta(BaseModel):
    rotulo: str
    filtros: dict
    resumo: str
    estatisticas: dict
    total_resultados: int
    nota_risco: dict | None = None
    fontes: list[dict] = []


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
    nota_risco: dict | None = None
    exportacao_relatorio: dict | None = None
    grupos: list[GrupoResposta] | None = None
    eixo_agrupamento: str | None = None
    intencoes_detectadas: list[dict] | None = None
    conversa_id: int | None = None
    mensagem_id: int | None = None
