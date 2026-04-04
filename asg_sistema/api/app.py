"""FastAPI application factory."""

import logging
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from asg_sistema.api import rotas_banco, rotas_consulta, rotas_dados, rotas_geo

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
app.include_router(rotas_banco.router, prefix="/api", tags=["Banco de dados"])
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


def _entrada_historico_etl_valida(reg: dict) -> bool:
    """Descarta duplicata antiga: registro vazio com sucesso=true (bug do main() + salvar extra)."""
    etapas = reg.get("etapas") or []
    erros = reg.get("erros") or []
    if not etapas and not erros and reg.get("sucesso") is True:
        return False
    return True


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
            if not linha:
                continue
            reg = _json.loads(linha)
            if _entrada_historico_etl_valida(reg):
                execucoes.append(reg)
    execucoes.reverse()
    return {"execucoes": execucoes[:20], "total": len(execucoes)}


@app.post("/api/etl/executar")
def executar_etl_api(etapa: str = "full"):
    """Dispara execucao do pipeline ETL via API (cooldown: 1h se ENV=production, 5s caso contrário)."""
    import subprocess

    from asg_sistema.api.etl_cooldown import (
        assegurar_cooldown_disparo_etl_api,
        registrar_disparo_etl_api,
    )

    assegurar_cooldown_disparo_etl_api()
    repo_root = Path(__file__).resolve().parent.parent.parent
    script_etl = repo_root / "scripts" / "etl_pipeline.py"
    script_sicar = repo_root / "scripts" / "sicar" / "coletar_sicar.py"

    def _rodar_pipeline():
        subprocess.run(
            [sys.executable, str(script_sicar)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            cwd=str(repo_root),
        )
        subprocess.run(
            [sys.executable, str(script_etl), "--etapa", etapa],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            cwd=str(repo_root),
        )

    import threading
    try:
        t = threading.Thread(target=_rodar_pipeline, daemon=True)
        t.start()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Falha ao iniciar ETL: {e}") from e
    registrar_disparo_etl_api()
    return {"status": "iniciado", "etapa": etapa}
