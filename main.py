"""
Ponto de entrada do backend ASG.
Responsável pelo agendamento de atualização da base de dados.

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

# Cria a tabela de agendamentos se ainda não existir
Base.metadata.create_all(bind=engine)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Inicia o scheduler
    iniciar_scheduler()

    # Recarrega agendamentos ativos após reinício
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
    description="Backend de agendamento e atualização da base de dados ASG.",
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