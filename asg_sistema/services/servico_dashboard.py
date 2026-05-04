from datetime import datetime
from asg_sistema.db.conexao import executar_consulta
from asg_sistema.schemas.dashboard import (
    DashboardMetrics,
    DashboardPorMunicipio,
    DashboardPorAno,
    DashboardResponse,
)


def calcular_metricas() -> DashboardMetrics:
    """Calcula as métricas consolidadas do dashboard."""
    
    # Total de propriedades no SICAR
    res_sicar = executar_consulta(
        "SELECT COUNT(*) as total, COALESCE(SUM(num_area), 0) as area_total FROM sicar_imoveis"
    )
    total_propriedades = res_sicar[0]["total"] if res_sicar else 0
    area_propriedades = float(res_sicar[0]["area_total"] or 0)
    
    # Métricas de queimadas
    res_queimadas = executar_consulta(
        "SELECT COUNT(*) as total, COALESCE(AVG(risco_fogo), 0) as media_risco FROM queimadas"
    )
    total_queimadas = res_queimadas[0]["total"] if res_queimadas else 0
    media_risco_fogo = float(res_queimadas[0]["media_risco"] or 0)
    
    # Total de alertas de desmatamento
    res_desmatamento = executar_consulta(
        "SELECT COUNT(*) as total, COALESCE(SUM(area_total_km2), 0) as area_total FROM desmatamento_alertas"
    )
    total_desmatamento = res_desmatamento[0]["total"] if res_desmatamento else 0
    area_desmatamento = float(res_desmatamento[0]["area_total"] or 0)
    
    # Total de unidades de conservação
    res_uc = executar_consulta("SELECT COUNT(*) as total FROM unidades_conservacao")
    total_unidades_conservacao = res_uc[0]["total"] if res_uc else 0
    
    # Total de terras indígenas
    res_ti = executar_consulta("SELECT COUNT(*) as total FROM terras_indigenas")
    total_terras_indigenas = res_ti[0]["total"] if res_ti else 0
    
    # Total de comunidades quilombolas
    res_quilombo = executar_consulta("SELECT COUNT(*) as total FROM comunidades_quilombolas")
    total_comunidades_quilombolas = res_quilombo[0]["total"] if res_quilombo else 0
    
    # Última atualização
    res_data = executar_consulta(
        "SELECT MAX(dat_atualizacao) as ultima FROM sicar_imoveis WHERE dat_atualizacao IS NOT NULL"
    )
    ultima_atualizacao = res_data[0]["ultima"] if res_data and res_data[0]["ultima"] else None
    
    return DashboardMetrics(
        total_propriedades=total_propriedades,
        media_risco_fogo=round(media_risco_fogo, 2),
        total_queimadas=total_queimadas,
        total_desmatamento=total_desmatamento,
        total_unidades_conservacao=total_unidades_conservacao,
        total_terras_indigenas=total_terras_indigenas,
        total_comunidades_quilombolas=total_comunidades_quilombolas,
        area_total_propriedades_ha=round(area_propriedades, 2),
        area_total_desmatamento_km2=round(area_desmatamento, 2),
        ultima_atualizacao=ultima_atualizacao,
    )


def calcular_por_municipio(limite: int = 20) -> list[DashboardPorMunicipio]:
    """Calcula agregações por município."""
    
    sql = """
        WITH dados_mun AS (
            SELECT 
                s.municipio,
                COUNT(DISTINCT s.id) as total_propriedades,
                COALESCE(SUM(s.num_area), 0) as area_total
            FROM sicar_imoveis s
            WHERE s.municipio IS NOT NULL
            GROUP BY s.municipio
            
            UNION ALL
            
            SELECT 
                q.municipio,
                0 as total_propriedades,
                0 as area_total
            FROM queimadas q
            WHERE q.municipio IS NOT NULL
            
            UNION ALL
            
            SELECT 
                d.municipio,
                0 as total_propriedades,
                0 as area_total  
            FROM desmatamento_alertas d
            WHERE d.municipio IS NOT NULL
        )
        SELECT 
            municipio as municipio,
            SUM(CASE WHEN total_propriedades > 0 THEN total_propriedades ELSE 0 END) as total_propriedades,
            SUM(CASE WHEN area_total > 0 THEN area_total ELSE 0 END) as area_total_ha
        FROM dados_mun
        GROUP BY municipio
        ORDER BY total_propriedades DESC
        LIMIT :limite
    """
    rows = executar_consulta(sql, {"limite": limite})
    
    resultado = []
    for r in rows:
        mun = r.get("municipio")
        if not mun:
            continue
        
        # Buscar total de queimadas e desmatamento por município
        res_q = executar_consulta(
            "SELECT COUNT(*) as total FROM queimadas WHERE municipio ILIKE :mun",
            {"mun": f"%{mun}%"}
        )
        total_q = res_q[0]["total"] if res_q else 0
        
        res_d = executar_consulta(
            "SELECT COUNT(*) as total FROM desmatamento_alertas WHERE municipio ILIKE :mun",
            {"mun": f"%{mun}%"}
        )
        total_d = res_d[0]["total"] if res_d else 0
        
        res_r = executar_consulta(
            "SELECT COALESCE(AVG(risco_fogo), 0) as media FROM queimadas WHERE municipio ILIKE :mun",
            {"mun": f"%{mun}%"}
        )
        media_risco = res_r[0]["media"] if res_r and res_r[0]["media"] else None
        
        resultado.append(DashboardPorMunicipio(
            municipio=mun,
            total_propriedades=r.get("total_propriedades", 0),
            total_queimadas=total_q,
            total_desmatamento=total_d,
            media_risco_fogo=float(media_risco) if media_risco else None,
            area_total_ha=float(r.get("area_total_ha") or 0),
        ))
    
    return resultado


def calcular_por_ano() -> list[DashboardPorAno]:
    """Calcula agregações por ano (queimadas e desmatamento)."""
    
    # Queimadas por ano
    sql_queimadas = """
        SELECT 
            EXTRACT(YEAR FROM data_hora) as ano,
            COUNT(*) as total
        FROM queimadas
        WHERE data_hora IS NOT NULL
        GROUP BY EXTRACT(YEAR FROM data_hora)
        ORDER BY ano
    """
    rows_q = executar_consulta(sql_queimadas)
    
    # Desmatamento por ano
    sql_desmatamento = """
        SELECT 
            EXTRACT(YEAR FROM data_avistamento) as ano,
            COALESCE(SUM(area_total_km2), 0) as area
        FROM desmatamento_alertas
        WHERE data_avistamento IS NOT NULL
        GROUP BY EXTRACT(YEAR FROM data_avistamento)
        ORDER BY ano
    """
    rows_d = executar_consulta(sql_desmatamento)
    
    # Unir resultados
    resultados_por_ano = {}
    
    for r in rows_q:
        ano = int(r.get("ano", 0))
        if ano > 0:
            resultados_por_ano[ano] = {
                "ano": ano,
                "total_queimadas": r.get("total", 0),
                "area_desmatada_km2": 0.0,
            }
    
    for r in rows_d:
        ano = int(r.get("ano", 0))
        if ano > 0:
            if ano in resultados_por_ano:
                resultados_por_ano[ano]["area_desmatada_km2"] = float(r.get("area") or 0)
            else:
                resultados_por_ano[ano] = {
                    "ano": ano,
                    "total_queimadas": 0,
                    "area_desmatada_km2": float(r.get("area") or 0),
                }
    
    return [
        DashboardPorAno(
            ano=d["ano"],
            total_queimadas=d["total_queimadas"],
            total_desmatamento_km2=0.0,
            area_desmatada_km2=round(d["area_desmatada_km2"], 2),
        )
        for d in sorted(resultados_por_ano.values(), key=lambda x: x["ano"])
    ]


def obter_dashboard_completo() -> DashboardResponse:
    """Retorna o dashboard completo com todas as agregações."""
    
    metricas = calcular_metricas()
    por_municipio = calcular_por_municipio()
    por_ano = calcular_por_ano()
    
    return DashboardResponse(
        metricas=metricas,
        por_municipio=por_municipio,
        por_ano=por_ano,
        timestamp=datetime.utcnow(),
    )