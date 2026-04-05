"""
Serviço de atualização da base ASG.

Agendamento dispara POST /api/etl/executar para reutilizar a lógica já existente.
"""

import asyncio
import logging
import httpx
from datetime import datetime
from pathlib import Path

from sqlalchemy.orm import Session

from asg_sistema.db.conexao import SessionLocal
from asg_sistema.db.models import AgendamentoAtualizacao

logger = logging.getLogger(__name__)


async def executar_atualizacao_completa(agendamento_id: int):
    """
    Executa POST /api/etl/executar para reutilizar a lógica já existente.
    Chamada pelo APScheduler em background.
    """
    db: Session = SessionLocal()

    try:
        agendamento = db.get(AgendamentoAtualizacao, agendamento_id)
        if not agendamento:
            logger.warning("Agendamento id=%d não encontrado.", agendamento_id)
            return

        # Marca como "executando"
        agendamento.ultima_execucao_em = datetime.utcnow()
        agendamento.ultimo_status = "executando"
        agendamento.ultima_mensagem = "Pipeline em andamento..."
        db.commit()

        logger.info("=== Agendamento id=%d iniciado ===", agendamento_id)

        # Dispara POST /api/etl/executar (skip_sicar=True para evitar travamentos)
        try:
            async with httpx.AsyncClient(timeout=3600) as client:
                response = await client.post(
                    "http://localhost:8000/api/etl/executar",
                    params={"skip_sicar": True},
                )
                response.raise_for_status()
                resultado = response.json()
                logger.info("[ETL] Resposta da API: %s", resultado)

        except Exception as e:
            logger.error("[ETL] Erro ao disparar POST /api/etl/executar: %s", e)
            raise

        # Se chegou aqui, sucesso!
        agendamento.ultimo_status = "sucesso"
        agendamento.ultima_mensagem = "Pipeline executado com sucesso"
        db.commit()
        logger.info("=== Agendamento id=%d finalizado: SUCESSO ===", agendamento_id)

    except Exception as e:
        logger.exception("Falha no agendamento id=%d: %s", agendamento_id, e)
        if db:
            try:
                agendamento = db.get(AgendamentoAtualizacao, agendamento_id)
                if agendamento:
                    agendamento.ultimo_status = "erro"
                    agendamento.ultima_mensagem = f"Erro: {str(e)[:200]}"
                    db.commit()
            except Exception as db_error:
                logger.error("Erro ao atualizar status do agendamento: %s", db_error)
    finally:
        if db:
            db.close()