"""Rotas para análise de fazenda — download de relatório ASG em PDF."""

import io
import json
import os
import tempfile
from datetime import datetime
from pathlib import Path

import contextily as ctx
import geopandas as gpd
import matplotlib.pyplot as plt
from matplotlib.patches import Patch

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse
from jinja2 import Environment, FileSystemLoader
from weasyprint import CSS, HTML

from asg_sistema.db import repositorio
from asg_sistema.motor.calculadora_risco import calcular_score_ahp

router = APIRouter()

BASE_DIR = Path(__file__).resolve().parent.parent.parent
TEMPLATES_DIR = BASE_DIR / "templates"
STATIC_DIR = BASE_DIR / "static"
IMAGES_DIR = STATIC_DIR / "images"

_STATUS_MAP = {"AT": "ATIVO", "PE": "PENDENTE", "SU": "SUSPENSO", "CA": "CANCELADO"}
_TIPO_MAP = {"IRU": "IMÓVEL RURAL", "REC": "RESERVA LEGAL", "APP": "APP"}


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------


@router.get("/relatorio-asg")
def relatorio_asg(
    car: str = Query(..., description="Código CAR do imóvel rural"),
):
    """Gera e retorna o relatório ASG do imóvel em PDF."""
    imovel = repositorio.buscar_imovel_por_car(car)
    if not imovel or not imovel.get("geometry"):
        raise HTTPException(status_code=404, detail=f"Imóvel '{car}' não encontrado.")

    geom_json = json.dumps(imovel["geometry"])
    municipio = imovel.get("municipio", "")
    cruzamento = repositorio.cruzamento_espacial_imovel(geom_json, municipio)

    area_ha = float(imovel.get("area_ha_calc") or imovel.get("num_area") or 1)
    area_km2 = max(area_ha / 100, 0.01)
    nota_risco = calcular_score_ahp(cruzamento, area_km2)

    dados = _montar_dados_template(imovel, cruzamento, nota_risco, area_ha)
    geojson = _montar_geojson(imovel, cruzamento)

    pdf_bytes = _gerar_pdf(car, dados, geojson)
    return StreamingResponse(
        io.BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="relatorio_{car[:20]}.pdf"'},
    )


# ---------------------------------------------------------------------------
# Montagem dos dados para o template
# ---------------------------------------------------------------------------


def _montar_dados_template(
    imovel: dict, cruzamento: dict, nota_risco: dict, area_ha: float
) -> dict:
    sub = nota_risco.get("sub_scores", {})
    return {
        "indice_risco": nota_risco.get("nota", 0),
        "lista_riscos": _montar_lista_riscos(cruzamento, sub),
        "municipio": (imovel.get("municipio") or "").upper(),
        "categoria": _TIPO_MAP.get(imovel.get("ind_tipo", ""), "IMÓVEL RURAL"),
        "status": _STATUS_MAP.get(imovel.get("ind_status", ""), imovel.get("ind_status", "")),
        "condicao": (imovel.get("des_condic") or "").upper(),
        "area": f"{area_ha:,.1f} HECTARES",
        "mod_fiscais": str(imovel.get("mod_fiscal") or "-"),
        "fonte": "SICAR",
        "data_fonte": _formatar_data(imovel.get("dat_atualizacao") or imovel.get("dat_criacao")),
    }


def _montar_lista_riscos(cruzamento: dict, sub_scores: dict) -> list:
    q  = cruzamento.get("queimadas", {})
    d  = cruzamento.get("deter", {})
    p  = cruzamento.get("prodes", {})
    ti = cruzamento.get("terras_indigenas", {})
    ql = cruzamento.get("quilombolas", {})
    uc = cruzamento.get("unidades_conservacao", {})

    # Distância mínima de desmatamento (deter ou prodes)
    dist_demat = min(
        float(d.get("distancia_min_km") or 999),
        float(p.get("distancia_min_km") or 999),
    )
    if dist_demat == 999:
        dist_demat = 0.0

    # Distância terra indígena
    proximas_ti = ti.get("proximas_10km") or []
    if ti.get("sobrepoe"):
        dist_ti = 0.0
    elif proximas_ti:
        dists = [float(t.get("distancia_km", 0)) for t in proximas_ti if isinstance(t, dict)]
        dist_ti = min(dists) if dists else 0.0
    else:
        dist_ti = 0.0

    # Converte sub_scores (0-100) para escala do template (0-20)
    def _para_20(chave: str) -> int:
        return min(20, round(float(sub_scores.get(chave, 0)) / 5))

    demat_val = min(20, round(max(
        float(sub_scores.get("desmatamento_deter", 0)),
        float(sub_scores.get("desmatamento_prodes", 0)),
    ) / 5))

    # UC e quilombola compõem contexto_municipal — separa proporcionalmente
    total_uc = int(uc.get("total") or 0)
    total_ql = int(ql.get("total") or 0)
    contexto_raw = float(sub_scores.get("contexto_municipal", 0))
    if total_uc + total_ql > 0:
        peso_uc = total_uc / (total_uc + total_ql)
        peso_ql = 1 - peso_uc
    else:
        peso_uc = peso_ql = 0.5

    uc_val = min(20, round(contexto_raw * peso_uc / 5))
    ql_val = min(20, round(contexto_raw * peso_ql / 5))

    return [
        {
            "nome": "Desmatamento",
            "valor": demat_val,
            "distancia": f"{dist_demat:.1f}km",
        },
        {
            "nome": "Queimada",
            "valor": _para_20("queimadas"),
            "distancia": f"{float(q.get('distancia_min_km') or 0):.1f}km",
        },
        {
            "nome": "Terra Indígena",
            "valor": _para_20("terras_indigenas"),
            "distancia": f"{dist_ti:.1f}km",
        },
        {
            "nome": "Terra Quilombola",
            "valor": ql_val,
            "distancia": "0.0km" if total_ql > 0 else "-",
        },
        {
            "nome": "Unid. Conservação",
            "valor": uc_val,
            "distancia": "0.0km" if total_uc > 0 else "-",
        },
    ]


def _formatar_data(valor) -> str:
    if not valor:
        return "-"
    try:
        dt = datetime.fromisoformat(str(valor)[:10])
        return dt.strftime("%d/%m/%Y")
    except Exception:
        return str(valor)


# ---------------------------------------------------------------------------
# GeoJSON para o mapa
# ---------------------------------------------------------------------------


def _montar_geojson(imovel: dict, cruzamento: dict) -> dict:
    features = []

    if imovel.get("geometry"):
        features.append({
            "type": "Feature",
            "geometry": imovel["geometry"],
            "properties": {"tipo": "fazenda"},
        })

    for item in (cruzamento.get("prodes", {}).get("geo") or []):
        geom = item.get("geometry") if isinstance(item, dict) else None
        if geom:
            features.append({
                "type": "Feature",
                "geometry": geom,
                "properties": {"tipo": "prodes"},
            })

    return {"type": "FeatureCollection", "features": features}


# ---------------------------------------------------------------------------
# Mapa satélite
# ---------------------------------------------------------------------------


def _gerar_mapa(geojson_data: dict, output_path: str) -> bool:
    try:
        features = geojson_data.get("features", [])
        if not features:
            return False

        df = gpd.GeoDataFrame.from_features(features)
        df.set_crs(epsg=4326, inplace=True)
        df = df.to_crs(epsg=3857)

        fig, ax = plt.subplots(figsize=(8, 16))

        fazenda = df[df["tipo"] == "fazenda"]
        prodes  = df[df["tipo"] == "prodes"]

        if not fazenda.empty:
            fazenda.plot(ax=ax, facecolor="#1682f0", alpha=0.3, edgecolor="#1682f0", linewidth=1, zorder=1)
        if not prodes.empty:
            prodes.plot(ax=ax, facecolor="#F61247", alpha=0.3, edgecolor="#F61247", linewidth=1, zorder=2)

        legend_elements = [
            Patch(facecolor="#1682f0", edgecolor="#1682f0", alpha=0.3, label="Fazenda"),
            Patch(facecolor="#F61247", edgecolor="#F61247", alpha=0.3, label="Desmatamento (PRODES)"),
        ]
        ax.legend(handles=legend_elements, loc="lower left", fontsize=8, frameon=True)

        minx, miny, maxx, maxy = df.total_bounds
        margin = 0.1
        dx, dy = maxx - minx, maxy - miny
        ax.set_xlim(minx - dx * margin, maxx + dx * margin)
        ax.set_ylim(miny - dy * margin, maxy + dy * margin)

        ctx.add_basemap(ax, source=ctx.providers.OpenStreetMap.Mapnik, attribution=False)
        ax.set_axis_off()

        plt.savefig(output_path, bbox_inches="tight", pad_inches=0, dpi=200, transparent=True)
        plt.close()
        return True
    except Exception as e:
        print(f"[ERRO] Falha ao gerar mapa: {e}")
        return False


# ---------------------------------------------------------------------------
# Geração do PDF
# ---------------------------------------------------------------------------


def _gerar_pdf(car: str, dados: dict, geojson: dict) -> bytes:
    env = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)))
    template = env.get_template("relatorio.html")

    logo_url        = "file://" + str(IMAGES_DIR / "visiona_logo.svg").replace("\\", "/")
    header_deco_url = "file://" + str(IMAGES_DIR / "header_deco.svg").replace("\\", "/")

    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
        tmp_path = tmp.name

    try:
        mapa_url = ""
        if _gerar_mapa(geojson, tmp_path):
            mapa_url = "file://" + tmp_path.replace("\\", "/")

        context = {
            "data_relatorio": datetime.now().strftime("%d/%m/%Y %H:%M"),
            "logo_url": logo_url,
            "header_deco_url": header_deco_url,
            "mapa_url": mapa_url,
            "codigo_imovel": car,
            **dados,
        }

        html_content = template.render(context)
        css_path = STATIC_DIR / "relatorio.css"
        stylesheets = [CSS(filename=str(css_path))] if css_path.exists() else []

        pdf_bytes = HTML(string=html_content).write_pdf(stylesheets=stylesheets)
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)

    return pdf_bytes
