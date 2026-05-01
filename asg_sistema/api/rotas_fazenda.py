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
    def calc_valor(chave: str, max_valor: float):
        score_raw = float(sub_scores.get(chave, 0))
        val = round((score_raw / 100.0) * max_valor, 1)
        return int(val) if val.is_integer() else val

    return [
        {
            "nome": "Queimadas",
            "valor": calc_valor("queimadas", 28),
            "max_valor": 28,
        },
        {
            "nome": "Desmatamento DETER",
            "valor": calc_valor("desmatamento_deter", 28),
            "max_valor": 28,
        },
        {
            "nome": "Terras Indígenas",
            "valor": calc_valor("terras_indigenas", 18),
            "max_valor": 18,
        },
        {
            "nome": "Terras Quilombolas",
            "valor": calc_valor("terras_quilombolas", 14),
            "max_valor": 14,
        },
        {
            "nome": "Desmatamento PRODES",
            "valor": calc_valor("desmatamento_prodes", 9),
            "max_valor": 9,
        },
        {
            "nome": "Contexto Municipal",
            "valor": calc_valor("contexto_municipal", 4),
            "max_valor": 4,
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

    def extrair_geometrias(chave_cruzamento: str, tipo_nome: str):
        dados_risco = cruzamento.get(chave_cruzamento, {})
        
        listas_busca = [
            dados_risco.get("geo") or [],
            dados_risco.get("proximas_10km") or [],
            dados_risco.get("proximas_3km") or [],
            dados_risco.get("sobreposicoes") or []
        ]
        
        for lista in listas_busca:
            for item in lista:
                geom = item.get("geometry") if isinstance(item, dict) else None
                if geom:
                    features.append({
                        "type": "Feature",
                        "geometry": geom,
                        "properties": {"tipo": tipo_nome},
                    })

    extrair_geometrias("prodes", "desmatamento")
    extrair_geometrias("deter", "desmatamento")
    extrair_geometrias("queimadas", "queimadas")
    extrair_geometrias("terras_indigenas", "terras_indigenas")
    extrair_geometrias("quilombolas", "quilombolas")
    extrair_geometrias("unidades_conservacao", "unidades_conservacao")

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

        estilos = {
            "fazenda": {"color": "#16acf7", "label": "Fazenda"},
            "desmatamento": {"color": "#f77f00", "label": "Desmatamento (PRODES/DETER)"},
            "queimadas": {"color": "#ff4444", "label": "Queimadas"},
            "terras_indigenas": {"color": "#55a630", "label": "Terra Indígena"},
            "quilombolas": {"color": "#7A360F", "label": "Terra Quilombola"},
            "unidades_conservacao": {"color": "#9d4edd", "label": "Unid. Conservação"}
        }

        legend_elements = []

        for tipo, config in estilos.items():
            df_tipo = df[df["tipo"] == tipo]
            
            if not df_tipo.empty:
                z = 1 if tipo == "fazenda" else 2
                
                df_tipo.plot(
                    ax=ax, 
                    facecolor=config["color"], 
                    alpha=0.3, 
                    edgecolor=config["color"], 
                    linewidth=1, 
                    zorder=z
                )
                
                legend_elements.append(
                    Patch(facecolor=config["color"], edgecolor=config["color"], alpha=0.3, label=config["label"])
                )

        if legend_elements:
            ax.legend(handles=legend_elements, loc="lower left", fontsize=8, frameon=True)

        minx, miny, maxx, maxy = df.total_bounds
        margin = 0.1
        dx, dy = maxx - minx, maxy - miny
        ax.set_xlim(minx - dx * margin, maxx + dx * margin)
        ax.set_ylim(miny - dy * margin, maxy + dy * margin)

        ctx.add_basemap(ax, source=ctx.providers.CartoDB.Positron, attribution=False)
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
