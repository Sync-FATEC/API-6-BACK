"""Rotas de operação no banco de dados (DDL e orquestração com ETL)."""

import subprocess
import sys
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from asg_sistema.db.schema_setup import aplicar_schema

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_ETL_SCRIPT = _REPO_ROOT / "scripts" / "etl_pipeline.py"

router = APIRouter(prefix="/bd")


class AtualizacaoBancoResposta(BaseModel):
    mensagem: str
    schema_aplicado: bool = False
    pipeline_iniciado: bool = False
    pid: int | None = Field(default=None, description="PID do processo ETL, se iniciado.")


@router.post("/atualizar", response_model=AtualizacaoBancoResposta)
def atualizar_base_dados(
    aplicar_ddl: bool = True,
    disparar_pipeline: bool = False,
    etapa: str = "full",
):
    """
    Atualiza o banco de dados.

    - Com `aplicar_ddl=true` (padrão), reaplica `schema.sql` (idempotente).
    - Com `disparar_pipeline=true`, inicia `scripts/etl_pipeline.py` em segundo plano
      (coleta, carga, embeddings — mesmo fluxo de `POST /api/etl/executar`).
    """
    partes: list[str] = []
    schema_ok = False

    if aplicar_ddl:
        try:
            aplicar_schema()
            schema_ok = True
            partes.append("Schema aplicado.")
        except Exception as e:
            raise HTTPException(
                status_code=500,
                detail=f"Falha ao aplicar schema: {e}",
            ) from e

    pid: int | None = None
    pipeline_ok = False
    if disparar_pipeline:
        if not _ETL_SCRIPT.is_file():
            raise HTTPException(
                status_code=500,
                detail=f"Script ETL não encontrado: {_ETL_SCRIPT}",
            )
        try:
            proc = subprocess.Popen(
                [sys.executable, str(_ETL_SCRIPT), "--etapa", etapa],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=str(_REPO_ROOT),
            )
            pid = proc.pid
            pipeline_ok = True
            partes.append(f"Pipeline ETL iniciado (PID {pid}, etapa={etapa}).")
        except Exception as e:
            raise HTTPException(
                status_code=500,
                detail=f"Falha ao iniciar ETL: {e}",
            ) from e

    if not aplicar_ddl and not disparar_pipeline:
        raise HTTPException(
            status_code=400,
            detail="Use aplicar_ddl=true e/ou disparar_pipeline=true.",
        )

    return AtualizacaoBancoResposta(
        mensagem=" ".join(partes),
        schema_aplicado=schema_ok,
        pipeline_iniciado=pipeline_ok,
        pid=pid,
    )
