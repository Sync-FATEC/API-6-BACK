"""FastAPI application factory."""

import asyncio
import glob
import logging
import os
import subprocess
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import cast

from fastapi import BackgroundTasks, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from asg_sistema.api import rotas_banco, rotas_consulta, rotas_dados, rotas_geo, rotas_pipeline, rotas_dashboard
from asg_sistema.db.conexao import SessionLocal, engine
from asg_sistema.db.models import AgendamentoAtualizacao, Base
from asg_sistema.routers.agendamento_router import router as agendamento_router
from asg_sistema.scheduler.gerenciador import (
    encerrar_scheduler,
    iniciar_scheduler,
    registrar_job,
)

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"

logger = logging.getLogger("uvicorn.error")

pipeline_status = {
    "rodando": False
}


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Pré-carregando modelo NLP...")
    rotas_consulta.obter_interpretador()
    logger.info("Modelo NLP pronto. Primeira requisição será rápida.")

    Base.metadata.create_all(bind=engine)
    iniciar_scheduler()

    db = SessionLocal()
    try:
        agendamentos_ativos = (
            db.query(AgendamentoAtualizacao)
            .filter(AgendamentoAtualizacao.ativo)
            .all()
        )
        for ag in agendamentos_ativos:
            registrar_job(cast(int, ag.id), cast(str, ag.cron_expressao))
    finally:
        db.close()

    yield
    encerrar_scheduler()


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
app.include_router(rotas_pipeline.router, prefix="/api/etl", tags=["Pipeline ETL"])
app.include_router(rotas_dashboard.router, prefix="/api", tags=["Dashboard"])
app.include_router(agendamento_router, prefix="/api/v1")

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