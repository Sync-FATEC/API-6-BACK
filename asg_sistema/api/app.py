"""FastAPI application factory."""

import logging
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from asg_sistema.api import rotas_consulta, rotas_dados, rotas_geo

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"

logger = logging.getLogger("uvicorn.error")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Pré-carregando modelo NLP...")
    rotas_consulta.obter_interpretador()
    logger.info("Modelo NLP pronto. Primeira requisição será rápida.")
    yield


app = FastAPI(
    title="ASG SP - Análise Ambiental, Social e Governança",
    description="Sistema de consulta por linguagem natural a dados ASG do Estado de São Paulo",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(rotas_consulta.router, prefix="/api", tags=["Consulta"])
app.include_router(rotas_dados.router, prefix="/api/dados", tags=["Dados"])
app.include_router(rotas_geo.router, prefix="/api/geo", tags=["GeoJSON"])

app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR / "static")), name="static")
templates = Jinja2Templates(directory=str(FRONTEND_DIR / "templates"))


@app.get("/", response_class=HTMLResponse)
def pagina_inicial(request: Request):
    return templates.TemplateResponse(request, "index.html")


@app.get("/api/saude")
def saude():
    from asg_sistema.db import repositorio
    try:
        contagens = repositorio.contar_por_tabela()
        return {"status": "ok", "contagens": contagens}
    except Exception as e:
        return {"status": "erro", "detalhe": str(e)}


@app.get("/api/etl/historico")
def historico_etl():
    """Retorna historico das execucoes do pipeline ETL."""
    import json as _json
    log_path = Path(__file__).resolve().parent.parent.parent / "logs" / "historico_etl.jsonl"
    if not log_path.exists():
        return {"execucoes": [], "total": 0}
    execucoes = []
    with open(log_path, "r", encoding="utf-8") as f:
        for linha in f:
            linha = linha.strip()
            if linha:
                execucoes.append(_json.loads(linha))
    execucoes.reverse()
    return {"execucoes": execucoes[:20], "total": len(execucoes)}


@app.post("/api/etl/executar")
def executar_etl_api(etapa: str = "full"):
    """Dispara execucao do pipeline ETL via API."""
    import subprocess
    script = Path(__file__).resolve().parent.parent.parent / "scripts" / "etl_pipeline.py"
    try:
        proc = subprocess.Popen(
            [sys.executable, str(script), "--etapa", etapa],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        return {"status": "iniciado", "pid": proc.pid, "etapa": etapa}
    except Exception as e:
        return {"status": "erro", "detalhe": str(e)}
