from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

from asg_sistema.services.servico_dashboard import (
    calcular_metricas,
    calcular_por_municipio,
    calcular_por_ano,
    obter_dashboard_completo,
)

router = APIRouter()


@router.get("/dashboard/metricas")
def get_metricas():
    """
    Retorna as métricas consolidadas do dashboard.
    
    Calcula:
    - Total de propriedades no SICAR
    - Média de risco de fogo das queimadas
    - Totais de eventos ambientais (queimadas, desmatamento, etc.)
    - Áreas totais
    """
    metricas = calcular_metricas()
    return JSONResponse(
        content={
            "total_propriedades": metricas.total_propriedades,
            "media_risco_fogo": metricas.media_risco_fogo,
            "total_queimadas": metricas.total_queimadas,
            "total_desmatamento": metricas.total_desmatamento,
            "total_unidades_conservacao": metricas.total_unidades_conservacao,
            "total_terras_indigenas": metricas.total_terras_indigenas,
            "total_comunidades_quilombolas": metricas.total_comunidades_quilombolas,
            "area_total_propriedades_ha": metricas.area_total_propriedades_ha,
            "area_total_desmatamento_km2": metricas.area_total_desmatamento_km2,
            "ultima_atualizacao": metricas.ultima_atualizacao,
        }
    )


@router.get("/dashboard/municipios")
def get_por_municipio(limite: int = Query(default=20, ge=1, le=100)):
    """
    Retorna dados agregados por município.
    
    Args:
        limite: Número máximo de municípios a retornar (padrão: 20)
    """
    dados = calcular_por_municipio(limite)
    return JSONResponse(
        content=[
            {
                "municipio": d.municipio,
                "total_propriedades": d.total_propriedades,
                "total_queimadas": d.total_queimadas,
                "total_desmatamento": d.total_desmatamento,
                "media_risco_fogo": d.media_risco_fogo,
                "area_total_ha": d.area_total_ha,
            }
            for d in dados
        ]
    )


@router.get("/dashboard/anos")
def get_por_ano():
    """
    Retorna dados agregados por ano.
    
    Inclui total de queimadas e área desmatada por ano.
    """
    dados = calcular_por_ano()
    return JSONResponse(
        content=[
            {
                "ano": d.ano,
                "total_queimadas": d.total_queimadas,
                "area_desmatada_km2": d.area_desmatada_km2,
            }
            for d in dados
        ]
    )


@router.get("/dashboard")
def get_dashboard_completo():
    """
    Retorna o dashboard completo com todas as métricas e agregações.
    
    Endpoint unificado que retorna:
    - Métricas gerais
    - Dados por município
    - Dados por ano
    """
    dashboard = obter_dashboard_completo()
    return JSONResponse(
        content={
            "metricas": {
                "total_propriedades": dashboard.metricas.total_propriedades,
                "media_risco_fogo": dashboard.metricas.media_risco_fogo,
                "total_queimadas": dashboard.metricas.total_queimadas,
                "total_desmatamento": dashboard.metricas.total_desmatamento,
                "total_unidades_conservacao": dashboard.metricas.total_unidades_conservacao,
                "total_terras_indigenas": dashboard.metricas.total_terras_indigenas,
                "total_comunidades_quilombolas": dashboard.metricas.total_comunidades_quilombolas,
                "area_total_propriedades_ha": dashboard.metricas.area_total_propriedades_ha,
                "area_total_desmatamento_km2": dashboard.metricas.area_total_desmatamento_km2,
                "ultima_atualizacao": dashboard.metricas.ultima_atualizacao,
            },
            "por_municipio": [
                {
                    "municipio": d.municipio,
                    "total_propriedades": d.total_propriedades,
                    "total_queimadas": d.total_queimadas,
                    "total_desmatamento": d.total_desmatamento,
                    "media_risco_fogo": d.media_risco_fogo,
                    "area_total_ha": d.area_total_ha,
                }
                for d in dashboard.por_municipio
            ],
            "por_ano": [
                {
                    "ano": d.ano,
                    "total_queimadas": d.total_queimadas,
                    "area_desmatada_km2": d.area_desmatada_km2,
                }
                for d in dashboard.por_ano
            ],
            "timestamp": dashboard.timestamp.isoformat(),
        }
    )