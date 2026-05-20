"""FastAPI application factory."""

import json
import asyncio
import glob
import logging
import os
import subprocess
import sys
import uuid
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import cast

from fastapi import BackgroundTasks, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from asg_sistema.api import rotas_banco, rotas_consulta, rotas_dados, rotas_fazenda, rotas_geo, rotas_pipeline, rotas_dashboard, rotas_sentinel
from asg_sistema.auth.middleware_autenticacao import MiddlewareAutenticacao
from asg_sistema.db.conexao import SessionLocal, engine
from asg_sistema.db.models import AgendamentoAtualizacao, Base
from asg_sistema.routers.agendamento_router import router as agendamento_router
from asg_sistema.routers.auth_router import router as auth_router
from asg_sistema.scheduler.gerenciador import (
    encerrar_scheduler,
    iniciar_scheduler,
    registrar_job,
)

logger = logging.getLogger("uvicorn.error")

pipeline_status = {
    "rodando": False
}


@asynccontextmanager
async def lifespan(app: FastAPI):
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

app.add_middleware(MiddlewareAutenticacao)
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
app.include_router(rotas_fazenda.router, prefix="/api/fazenda", tags=["Fazenda"])
app.include_router(rotas_pipeline.router, prefix="/api/etl", tags=["Pipeline ETL"])
app.include_router(rotas_dashboard.router, prefix="/api", tags=["Dashboard"])
app.include_router(rotas_sentinel.router, prefix="/api/dados", tags=["Sentinel-2"])
app.include_router(agendamento_router, prefix="/api/v1")
app.include_router(auth_router, prefix="/api/v1")


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


def _logs_dir() -> Path:
    caminho = Path(__file__).resolve().parent.parent.parent / "logs"
    caminho.mkdir(parents=True, exist_ok=True)
    return caminho


def _status_path_etl(execution_id: str) -> Path:
    return _logs_dir() / f"status_etl_{execution_id}.json"


def _status_etl_base(execution_id: str) -> dict:
    agora = datetime.utcnow().isoformat()
    return {
        "execution_id": execution_id,
        "pipeline": "ETL ASG-SP",
        "inicio": agora,
        "atualizado_em": agora,
        "etapa_atual": "inicializacao",
        "status_execucao": "em_andamento",
        "finalizado": False,
        "mensagem": "Execucao ETL iniciada.",
        "etapas": [],
        "erros": [],
        "fontes": [],
        "eventos": [],
    }


def _carregar_status_etl(execution_id: str) -> dict:
    caminho = _status_path_etl(execution_id)
    if not caminho.exists():
        return _status_etl_base(execution_id)

    try:
        with open(caminho, "r", encoding="utf-8") as f:
            conteudo = json.load(f)
            if isinstance(conteudo, dict):
                return conteudo
    except Exception as e:
        logger.warning("Falha ao carregar status ETL %s: %s", execution_id, e)
    return _status_etl_base(execution_id)


def _salvar_status_etl(execution_id: str, status: dict):
    caminho = _status_path_etl(execution_id)
    status["execution_id"] = execution_id
    status["pipeline"] = "ETL ASG-SP"
    status["atualizado_em"] = datetime.utcnow().isoformat()
    with open(caminho, "w", encoding="utf-8") as f:
        json.dump(status, f, ensure_ascii=False, indent=2)


def _registrar_evento_status_etl(
    execution_id: str,
    tipo: str,
    mensagem: str,
    etapa: str | None = None,
):
    status = _carregar_status_etl(execution_id)
    eventos = status.get("eventos")
    if not isinstance(eventos, list):
        eventos = []

    evento = {
        "timestamp": datetime.utcnow().isoformat(),
        "tipo": tipo,
        "mensagem": mensagem,
    }
    if etapa is not None:
        evento["etapa"] = etapa

    eventos.append(evento)
    status["eventos"] = eventos
    status["mensagem"] = mensagem
    _salvar_status_etl(execution_id, status)


def _atualizar_status_etl(execution_id: str, **campos):
    status = _carregar_status_etl(execution_id)
    status.update(campos)
    _salvar_status_etl(execution_id, status)


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


@app.get("/api/etl/status/{execution_id}")
def status_etl(execution_id: str):
    """Retorna status detalhado de uma execução do ETL."""
    status_path = _status_path_etl(execution_id)
    if not status_path.exists():
        raise HTTPException(status_code=404, detail="Execução ETL não encontrada.")

    try:
        with open(status_path, "r", encoding="utf-8") as f:
            status = json.load(f)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Falha ao ler status ETL: {e}") from e

    if not isinstance(status, dict):
        raise HTTPException(status_code=500, detail="Arquivo de status ETL inválido.")

    return status


@app.post("/api/etl/executar")
def executar_etl_api(
    background_tasks: BackgroundTasks, 
    etapa: str = "full", 
    skip_sicar: bool = False
):
    """Dispara execucao do pipeline ETL via API."""
    
    from asg_sistema.api.etl_cooldown import (
        assegurar_cooldown_disparo_etl_api,
        registrar_disparo_etl_api,
    )

    assegurar_cooldown_disparo_etl_api()

    execution_id = uuid.uuid4().hex
    
    repo_root = Path(__file__).resolve().parent.parent.parent
    script_etl = repo_root / "scripts" / "etl_pipeline.py"
    script_sicar = repo_root / "scripts" / "coletar_sicar.py"

    if not script_etl.exists():
        raise HTTPException(status_code=500, detail=f"Script ETL não encontrado em: {script_etl}")

    status = _status_etl_base(execution_id)
    status["mensagem"] = "Execução ETL agendada e aguardando processamento."
    status["etapa_atual"] = "fila"
    status["etapa_solicitada"] = etapa
    status["skip_sicar"] = skip_sicar
    _salvar_status_etl(execution_id, status)
    _registrar_evento_status_etl(
        execution_id,
        "execucao_agendada",
        f"Execução ETL agendada (etapa={etapa}, skip_sicar={skip_sicar}).",
        etapa="fila",
    )

    def _rodar_pipeline():
        def _finalizar_com_falha(etapa_falha: str, detalhe: str):
            status_atual = _carregar_status_etl(execution_id)
            erros = status_atual.get("erros")
            if not isinstance(erros, list):
                erros = []
            erros.append({
                "etapa": etapa_falha,
                "erro": detalhe,
                "timestamp": datetime.utcnow().isoformat(),
            })
            _atualizar_status_etl(
                execution_id,
                etapa_atual=etapa_falha,
                status_execucao="falha",
                finalizado=True,
                mensagem=detalhe,
                fim=datetime.utcnow().isoformat(),
                erros=erros,
            )

        try:
            if not skip_sicar:
                _atualizar_status_etl(
                    execution_id,
                    etapa_atual="coleta_sicar",
                    mensagem="Executando coleta SICAR antes do pipeline.",
                    status_execucao="em_andamento",
                )
                _registrar_evento_status_etl(
                    execution_id,
                    "sicar_iniciado",
                    "Iniciando coleta SICAR.",
                    etapa="coleta_sicar",
                )
                print(f"[INFO] Iniciando coleta SICAR: {script_sicar}")
                subprocess.run(
                    [sys.executable, str(script_sicar)],
                    cwd=str(repo_root),
                    check=True
                )
                _registrar_evento_status_etl(
                    execution_id,
                    "sicar_concluido",
                    "Coleta SICAR concluída com sucesso.",
                    etapa="coleta_sicar",
                )
            else:
                print("[INFO] Pulando a coleta do SICAR (skip_sicar=True).")
                _registrar_evento_status_etl(
                    execution_id,
                    "sicar_pulado",
                    "Coleta SICAR pulada por configuração (skip_sicar=True).",
                    etapa="coleta_sicar",
                )

            _atualizar_status_etl(
                execution_id,
                etapa_atual="pipeline",
                mensagem=f"Iniciando pipeline ETL (etapa: {etapa}).",
                status_execucao="em_andamento",
            )
            _registrar_evento_status_etl(
                execution_id,
                "pipeline_iniciado",
                f"Iniciando subprocesso ETL (etapa: {etapa}).",
                etapa="pipeline",
            )
            
            print(f"[INFO] Iniciando pipeline ETL (etapa: {etapa}): {script_etl}")
            subprocess.run(
                [
                    sys.executable,
                    str(script_etl),
                    "--etapa",
                    etapa,
                    "--execution-id",
                    execution_id,
                ],
                cwd=str(repo_root),
                check=True
            )
            script_treino = repo_root / "scripts" / "treinar_classificador.py"

            if script_treino.exists():
                subprocess.run(
                    [sys.executable, str(script_treino)],
                    cwd=str(repo_root),
                    check=True
                )
            _registrar_evento_status_etl(
                execution_id,
                "pipeline_subprocess_concluido",
                "Subprocesso ETL finalizado.",
                etapa="pipeline",
            )
            print("[INFO] Pipeline ETL finalizado com sucesso pela API.")
            
            
        except subprocess.CalledProcessError as e:
            detalhe = f"O subprocesso falhou com código {e.returncode}. Comando: {e.cmd}"
            print(f"[ERRO] {detalhe}")
            _registrar_evento_status_etl(
                execution_id,
                "pipeline_subprocess_erro",
                detalhe,
                etapa="pipeline",
            )
            _finalizar_com_falha("pipeline", detalhe)
        except Exception as e:
            detalhe = f"Falha inesperada no worker do ETL: {e}"
            print(f"[ERRO] {detalhe}")
            _registrar_evento_status_etl(
                execution_id,
                "pipeline_worker_erro",
                detalhe,
                etapa="pipeline",
            )
            _finalizar_com_falha("pipeline", detalhe)

    background_tasks.add_task(_rodar_pipeline)
    
    registrar_disparo_etl_api()
    
    return {
        "status": "iniciado", 
        "etapa": etapa, 
        "skip_sicar": skip_sicar,
        "execution_id": execution_id,
    }