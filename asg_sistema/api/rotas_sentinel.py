"""
Endpoint para geração de imagem de satélite Sentinel-2
de um ponto de queimada.

Rota: GET /api/dados/queimadas/{id}/imagem-satelite

Funcionalidade:
  1. Busca lat/lon/data_hora no banco pelo id.
  2. Verifica se já existe cache em static/sentinel_cache/.
  3. Se não, busca no Planetary Computer (Sentinel-2-L2A), recorta a região,
     normaliza e salva PNG no cache.
  4. Retorna StreamingResponse com a imagem PNG.
"""

import io
import logging
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse
from PIL import Image

from asg_sistema.db.conexao import executar_consulta

logger = logging.getLogger("uvicorn.error")

router = APIRouter()

# Pasta de cache (criada automaticamente se não existir)
CACHE_DIR = Path(__file__).resolve().parent.parent.parent / "static" / "sentinel_cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

# Margem em graus ao redor do ponto (aprox. ~3 km)
MARGEM = 0.03


def _chave_cache(lat: float, lon: float, data: str) -> str:
    """Gera um nome de arquivo único para o cache."""
    lat_s = f"{lat:.5f}".replace("-", "m").replace(".", "_")
    lon_s = f"{lon:.5f}".replace("-", "m").replace(".", "_")
    data_s = data[:10].replace("-", "")
    return f"{lat_s}_{lon_s}_{data_s}.png"


def _gerar_imagem_sentinel(lat: float, lon: float, data_hora: datetime) -> bytes:
    """
    Busca imagem Sentinel-2 no Planetary Computer,
    recorta a região e retorna bytes PNG.
    Levanta ValueError se nenhuma imagem for encontrada.
    """
    try:
        import planetary_computer
        from pystac_client import Client
        import rasterio
        from rasterio.warp import transform_bounds
        from rasterio.windows import from_bounds
    except ImportError as exc:
        raise RuntimeError(
            "Dependências de imagem satélite não instaladas: "
            "pystac-client, planetary-computer, rasterio"
        ) from exc

    bbox = [
        lon - MARGEM,
        lat - MARGEM,
        lon + MARGEM,
        lat + MARGEM,
    ]

    inicio = (data_hora - timedelta(days=10)).strftime("%Y-%m-%d")
    fim = (data_hora + timedelta(days=10)).strftime("%Y-%m-%d")
    intervalo = f"{inicio}/{fim}"

    logger.info(
        "Buscando Sentinel-2: bbox=%s intervalo=%s",
        bbox,
        intervalo,
    )

    catalog = Client.open(
        "https://planetarycomputer.microsoft.com/api/stac/v1"
    )

    search = catalog.search(
        collections=["sentinel-2-l2a"],
        bbox=bbox,
        datetime=intervalo,
        query={"eo:cloud_cover": {"lt": 80}},
        limit=20,
    )

    items = list(search.items())

    if not items:
        raise ValueError(
            f"Nenhuma imagem Sentinel-2 encontrada para "
            f"lat={lat}, lon={lon}, período={intervalo}."
        )

    # Escolhe a imagem com menos nuvens
    items.sort(key=lambda i: i.properties.get("eo:cloud_cover", 999))
    item = planetary_computer.sign(items[0])

    logger.info(
        "Imagem escolhida: id=%s cobertura_nuvem=%.1f%%",
        item.id,
        item.properties.get("eo:cloud_cover", -1),
    )

    url_tif = item.assets["visual"].href

    with rasterio.open(url_tif) as src:
        bbox_raster = transform_bounds(
            "EPSG:4326",
            src.crs,
            bbox[0],
            bbox[1],
            bbox[2],
            bbox[3],
            densify_pts=21,
        )
        window = from_bounds(*bbox_raster, transform=src.transform)
        img = src.read([1, 2, 3], window=window)

    # (bandas, h, w) → (h, w, bandas)
    img = np.transpose(img, (1, 2, 0))
    img = np.nan_to_num(img)

    img_min = img.min()
    img_max = img.max()
    if img_max > img_min:
        img = ((img - img_min) / (img_max - img_min) * 255).astype(np.uint8)
    else:
        img = img.astype(np.uint8)

    buf = io.BytesIO()
    Image.fromarray(img).save(buf, format="PNG")
    buf.seek(0)
    return buf.read()


@router.get(
    "/queimadas/{queimada_id}/imagem-satelite",
    summary="Imagem Sentinel-2 de uma queimada",
    description=(
        "Retorna uma imagem PNG recortada do satélite Sentinel-2 "
        "centrada na localização da queimada. "
        "Usa cache em disco para evitar downloads repetidos."
    ),
    response_class=StreamingResponse,
    tags=["Sentinel-2"],
)
def imagem_satelite_queimada(
    queimada_id: int,
    lat: float | None = Query(None, description="Latitude (sobrescreve banco)"),
    lon: float | None = Query(None, description="Longitude (sobrescreve banco)"),
    data: str | None = Query(None, description="Data ISO-8601 (sobrescreve banco)"),
):
    """
    Retorna imagem PNG do Sentinel-2 para o ponto de queimada.

    - Busca coordenadas e data no banco pelo id.
    - Aceita lat/lon/data opcionais como query params para sobrescrever.
    - Usa cache em disco; gera somente se não existir.
    """
    # ── 1. Resolver lat / lon / data_hora ────────────────────────────────────
    # Se lat e lon já foram passados como query params, não precisa consultar o banco
    if lat is not None and lon is not None:
        # data pode vir como query param ou ser ignorada (usa data atual como referência)
        data = data or ""
    else:
        # Busca no banco pelo id
        rows = executar_consulta(
            "SELECT latitude, longitude, data_hora FROM queimadas WHERE id = :id",
            {"id": queimada_id},
        )
        if not rows:
            raise HTTPException(
                status_code=404,
                detail=f"Queimada id={queimada_id} não encontrada.",
            )
        row = rows[0]
        lat = float(row["latitude"])
        lon = float(row["longitude"])
        data = data or str(row["data_hora"])

    # Parseia data_hora (aceita vários formatos)
    data_hora: datetime
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            data_hora = datetime.strptime(data[:19], fmt[:len(data[:19])])
            break
        except ValueError:
            continue
    else:
        # Fallback: só a data
        try:
            data_hora = datetime.strptime(data[:10], "%Y-%m-%d")
        except ValueError:
            raise HTTPException(
                status_code=422,
                detail=f"Formato de data inválido: {data!r}",
            )

    # ── 2. Verificar cache ────────────────────────────────────────────────────
    chave = _chave_cache(lat, lon, data_hora.strftime("%Y-%m-%d"))
    cache_path = CACHE_DIR / chave

    if cache_path.exists():
        logger.info("Cache hit Sentinel-2: %s", chave)
        return StreamingResponse(
            cache_path.open("rb"),
            media_type="image/png",
            headers={
                "X-Cache": "HIT",
                "Cache-Control": "public, max-age=86400",
            },
        )

    # ── 3. Gerar imagem ───────────────────────────────────────────────────────
    try:
        png_bytes = _gerar_imagem_sentinel(lat, lon, data_hora)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Erro ao gerar imagem Sentinel-2: %s", exc)
        raise HTTPException(
            status_code=500,
            detail=f"Erro interno ao gerar imagem: {exc}",
        ) from exc

    # Salva no cache
    cache_path.write_bytes(png_bytes)
    logger.info("Cache MISS → salvo: %s", chave)

    return StreamingResponse(
        io.BytesIO(png_bytes),
        media_type="image/png",
        headers={
            "X-Cache": "MISS",
            "Cache-Control": "public, max-age=86400",
        },
    )
