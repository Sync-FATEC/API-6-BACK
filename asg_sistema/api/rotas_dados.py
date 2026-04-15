"""Rotas REST para consulta estruturada de dados."""

from fastapi import APIRouter, HTTPException, Query

from asg_sistema.db.conexao import executar_consulta
from asg_sistema.db import repositorio

router = APIRouter()


@router.get("/resumo")
def resumo_banco():
    return repositorio.contar_por_tabela()


@router.get("/fontes")
def listar_fontes():
    return repositorio.buscar_fontes()


@router.get("/queimadas")
def listar_queimadas(
    municipio: str | None = Query(None),
    limite: int = Query(100, le=5000),
):
    filtro = "WHERE UPPER(TRIM(estado)) IN ('SP', 'SAO PAULO', 'SÃO PAULO')"
    params = {"limite": limite}
    if municipio:
        filtro += " AND municipio ILIKE :mun"
        params["mun"] = f"%{municipio}%"

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
    params = {}
    if municipio:
        filtro += " AND municipio ILIKE :mun"
        params["mun"] = f"%{municipio}%"

    return executar_consulta(
        f"""SELECT id, nome, etnia, municipio, uf, area_ha, fase, modalidade
            FROM terras_indigenas {filtro} ORDER BY nome""",
        params,
    )


@router.get("/desmatamento")
def listar_desmatamento(municipio: str | None = Query(None)):
    filtro = "WHERE UPPER(TRIM(uf)) = 'SP'"
    params = {}
    if municipio:
        filtro += " AND municipio ILIKE :mun"
        params["mun"] = f"%{municipio}%"

    return executar_consulta(
        f"""SELECT id, classe, municipio, data_avistamento, satelite,
                   area_total_km2, nome_uc
            FROM desmatamento_alertas {filtro}
            ORDER BY data_avistamento DESC""",
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
    params = {}
    if municipio:
        filtro += " AND municipio ILIKE :mun"
        params["mun"] = f"%{municipio}%"

    return executar_consulta(
        f"""SELECT id, nome, categoria, grupo, esfera, municipio, area_ha
            FROM unidades_conservacao {filtro}
            ORDER BY nome LIMIT 500""",
        params,
    )
