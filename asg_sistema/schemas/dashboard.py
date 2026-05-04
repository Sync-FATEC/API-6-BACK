from datetime import datetime
from pydantic import BaseModel, Field


class DashboardMetrics(BaseModel):
    total_propriedades: int = Field(description="Total de propriedades no SICAR")
    media_risco_fogo: float = Field(description="Média de risco de fogo das queimadas")
    total_queimadas: int = Field(description="Total de registros de queimadas")
    total_desmatamento: int = Field(description="Total de alertas de desmatamento")
    total_unidades_conservacao: int = Field(description="Total de unidades de conservação")
    total_terras_indigenas: int = Field(description="Total de terras indígenas")
    total_comunidades_quilombolas: int = Field(description="Total de comunidades quilombolas")
    area_total_propriedades_ha: float = Field(description="Área total das propriedades (ha)")
    area_total_desmatamento_km2: float = Field(description="Área total de desmatamento (km²)")
    ultima_atualizacao: str | None = Field(description="Data da última atualização dos dados")


class DashboardPorMunicipio(BaseModel):
    municipio: str
    total_propriedades: int
    total_queimadas: int
    total_desmatamento: int
    media_risco_fogo: float | None
    area_total_ha: float


class DashboardPorAno(BaseModel):
    ano: int
    total_queimadas: int
    total_desmatamento_km2: float
    area_desmatada_km2: float


class DashboardResponse(BaseModel):
    metricas: DashboardMetrics
    por_municipio: list[DashboardPorMunicipio]
    por_ano: list[DashboardPorAno]
    timestamp: datetime
