"""
Ponto de entrada do backend ASG.

Para rodar:
    python -m uvicorn main:app --reload --port 8001
"""

from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from asg_sistema.config import config
from asg_sistema.db.conexao import engine, SessionLocal
from asg_sistema.db.models import Base, AgendamentoAtualizacao
from asg_sistema.scheduler.gerenciador import (
    iniciar_scheduler,
    encerrar_scheduler,
    registrar_job,
)
from asg_sistema.routers.agendamento_router import router as agendamento_router
from asg_sistema.routers.auth_router import router as auth_router
from asg_sistema.routers.conversa_router import router_conversas, router_mensagens
from asg_sistema.api.rotas_consulta import router as consulta_router
from asg_sistema.api import rotas_banco, rotas_dados, rotas_fazenda, rotas_geo, rotas_historico, rotas_pipeline, rotas_dashboard, rotas_sentinel

# Cria todas as tabelas (modelos SQLAlchemy) se ainda não existirem
Base.metadata.create_all(bind=engine)


@asynccontextmanager
async def lifespan(app: FastAPI):
    iniciar_scheduler()

    db = SessionLocal()
    try:
        agendamentos_ativos = (
            db.query(AgendamentoAtualizacao)
            .filter(AgendamentoAtualizacao.ativo == True)
            .all()
        )
        for ag in agendamentos_ativos:
            registrar_job(ag.id, ag.cron_expressao)
    finally:
        db.close()

    yield

    encerrar_scheduler()


app = FastAPI(
    title="ASG SP - Backend",
    description="Backend de agendamento, consulta e histórico de conversas do sistema ASG.",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(agendamento_router, prefix="/api/v1")
app.include_router(auth_router, prefix="/api/v1")
app.include_router(consulta_router, prefix="/api/v1")
app.include_router(router_conversas, prefix="/api/v1")
app.include_router(router_mensagens, prefix="/api/v1")
app.include_router(rotas_historico.router, prefix="/api", tags=["Histórico"])
app.include_router(rotas_banco.router, prefix="/api", tags=["Banco de dados"])
app.include_router(rotas_dados.router, prefix="/api/dados", tags=["Dados"])
app.include_router(rotas_geo.router, prefix="/api/geo", tags=["GeoJSON"])
app.include_router(rotas_fazenda.router, prefix="/api/fazenda", tags=["Fazenda"])
app.include_router(rotas_pipeline.router, prefix="/api/etl", tags=["Pipeline ETL"])
app.include_router(rotas_dashboard.router, prefix="/api", tags=["Dashboard"])
app.include_router(rotas_sentinel.router, prefix="/api/dados", tags=["Sentinel-2"])


@app.get("/api/saude")
def saude():
    return {"status": "ok", "servico": "backend-asg"}


if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host=config.api_host,
        port=config.api_porta,
        reload=True,
    )
