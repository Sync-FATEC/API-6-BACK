"""Rotas REST para consulta estruturada de dados."""

from datetime import datetime
from fastapi import APIRouter, HTTPException, Query

from asg_sistema.db.conexao import executar_consulta
from asg_sistema.db import repositorio

router = APIRouter()


@router.get("/resumo")
def resumo_banco():
    """Retorna resumo das contagens por tabela com timestamp."""
    stats = repositorio.contar_por_tabela()
    return {
        "stats": stats,
        "timestamp_atualizacao": datetime.utcnow().isoformat()
    }


@router.get("/fontes")
def listar_fontes():
    return repositorio.buscar_fontes()


@router.get("/queimadas")
def listar_queimadas(
    municipio: str | None = Query(None),
    limite: int = Query(100, le=50000),
    data_inicio: str | None = Query(None),
    data_fim: str | None = Query(None),
):
    filtro = "WHERE UPPER(TRIM(estado)) IN ('SP', 'SAO PAULO', 'SÃO PAULO')"
    params: dict[str, str | int] = {}
    
    # Se houver filtro de data, aumenta o limite para pegar tudo do período
    if data_inicio or data_fim:
        params["limite"] = 50000
    else:
        params["limite"] = limite
    
    if municipio:
        filtro += " AND municipio ILIKE :mun"
        params["mun"] = f"%{municipio}%"
    if data_inicio:
        filtro += " AND data_hora >= :data_inicio"
        params["data_inicio"] = data_inicio if len(data_inicio) > 10 else f"{data_inicio} 00:00:00"
    if data_fim:
        filtro += " AND data_hora <= :data_fim"
        params["data_fim"] = data_fim if len(data_fim) > 10 else f"{data_fim} 23:59:59"

    return executar_consulta(
        f"""SELECT id, latitude, longitude, data_hora, satelite,
                   municipio, bioma, frp, risco_fogo
            FROM queimadas {filtro}
            ORDER BY data_hora DESC LIMIT :limite""",
        params,
    )


@router.get("/terras-indigenas")
def listar_terras_indigenas(municipio: str | None = Query(None)):
    filtro = "WHERE UPPER(TRIM(uf)) = 'SP'"
    params: dict[str, str | int] = {}
    if municipio:
        filtro += " AND municipio ILIKE :mun"
        params["mun"] = f"%{municipio}%"

    return executar_consulta(
        f"""SELECT id, nome, etnia, municipio, uf, area_ha, fase, modalidade
            FROM terras_indigenas {filtro} ORDER BY nome""",
        params,
    )


@router.get("/desmatamento")
def listar_desmatamento(
    municipio: str | None = Query(None),
    limite: int = Query(100, le=50000),
    data_inicio: str | None = Query(None),
    data_fim: str | None = Query(None),
):
    filtro = "WHERE UPPER(TRIM(uf)) = 'SP'"
    params: dict[str, str | int] = {}
    
    # Se houver filtro de data, aumenta o limite para pegar tudo do período
    if data_inicio or data_fim:
        params["limite"] = 50000
    else:
        params["limite"] = limite
    
    if municipio:
        filtro += " AND municipio ILIKE :mun"
        params["mun"] = f"%{municipio}%"
    if data_inicio:
        filtro += " AND data_avistamento >= :data_inicio"
        params["data_inicio"] = data_inicio if len(data_inicio) > 10 else f"{data_inicio} 00:00:00"
    if data_fim:
        filtro += " AND data_avistamento <= :data_fim"
        params["data_fim"] = data_fim if len(data_fim) > 10 else f"{data_fim} 23:59:59"

    return executar_consulta(
        f"""SELECT id, classe, municipio, data_avistamento, satelite,
                   area_total_km2, nome_uc
            FROM desmatamento_alertas {filtro}
            ORDER BY data_avistamento DESC LIMIT :limite""",
        params,
    )


@router.get("/sicar")
def listar_sicar(
    municipio: str | None = Query(None),
    limite: int = Query(100, le=1000)
):
    """Lista imóveis rurais (SICAR)."""
    filtro = "WHERE UPPER(TRIM(cod_estado)) IN ('SP', '35')"
    params: dict[str, str | int] = {"limite": limite}
    
    if municipio:
        filtro += " AND municipio ILIKE :mun"
        params["mun"] = f"%{municipio}%"

    return executar_consulta(
        f"""SELECT id, cod_imovel, nom_tema, ind_status, municipio, cod_estado, num_area
            FROM sicar_imoveis {filtro}
            ORDER BY id DESC LIMIT :limite""",
        params,
    )


@router.get("/imovel-rural/{cod_imovel:path}")
def obter_imovel_rural_por_cod(cod_imovel: str):
    """Retorna dados do imóvel rural (SICAR/CAR) pelo cod_imovel, incluindo geometria GeoJSON."""
    row = repositorio.buscar_imovel_rural_por_cod(cod_imovel)
    if not row:
        raise HTTPException(
            status_code=404,
            detail="Imóvel rural não encontrado para este código CAR / cod_imovel.",
        )
    return row


@router.get("/unidades-conservacao")
def listar_ucs(municipio: str | None = Query(None)):
    filtro = "WHERE UPPER(COALESCE(uf, '')) LIKE '%SP%'"
    params: dict[str, str | int] = {}
    if municipio:
        filtro += " AND municipio ILIKE :mun"
        params["mun"] = f"%{municipio}%"

    return executar_consulta(
        f"""SELECT id, nome, categoria, grupo, esfera, municipio, area_ha
            FROM unidades_conservacao {filtro}
            ORDER BY nome LIMIT 500""",
        params,
    )


@router.get("/quilombolas")
def listar_quilombolas(municipio: str | None = Query(None)):
    """Retorna comunidades quilombolas."""
    filtro = "WHERE UPPER(TRIM(uf)) = 'SP'"
    params: dict[str, str | int] = {}
    if municipio:
        filtro += " AND municipio ILIKE :mun"
        params["mun"] = f"%{municipio}%"

    return executar_consulta(
        f"""SELECT id, comunidade, municipio, uf, ano_certificacao
            FROM comunidades_quilombolas {filtro}
            ORDER BY comunidade""",
        params,
    )


@router.get("/prodes")
def listar_prodes(
    municipio: str | None = Query(None),
    limite: int = Query(1000, le=50000),
    data_inicio: str | None = Query(None),
    data_fim: str | None = Query(None),
):
    """Retorna dados PRODES (desmatamento anual)."""
    filtro = "WHERE UPPER(TRIM(estado)) IN ('SP', 'SAO PAULO', 'SÃO PAULO')"
    params: dict[str, str | int] = {}
    
    # Se houver filtro de data, aumenta o limite para pegar tudo do período
    if data_inicio or data_fim:
        params["limite"] = 50000
    else:
        params["limite"] = limite
    
    # if municipio:
    #     filtro += " AND municipio ILIKE :mun"
    #     params["mun"] = f"%{municipio}%"
    if data_inicio:
        filtro += " AND ano >= :data_inicio"
        params["data_inicio"] = data_inicio[:4]  # Extract year
    if data_fim:
        filtro += " AND ano <= :data_fim"
        params["data_fim"] = data_fim[:4]  # Extract year

    return executar_consulta(
        f"""SELECT id, ano, data_imagem, classe_nome, area_km, estado,
                   ST_Y(ST_Centroid(geom)) AS latitude, 
                   ST_X(ST_Centroid(geom)) AS longitude
            FROM prodes_desmatamento {filtro}
            ORDER BY ano DESC, data_imagem DESC LIMIT :limite""",
        params,
    )
