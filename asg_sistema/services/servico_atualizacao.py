"""
Serviço de atualização da base ASG.

Agendamento dispara POST /api/etl/executar para reutilizar a lógica já existente.
"""

import asyncio
import logging
import httpx
from datetime import datetime

from sqlalchemy.orm import Session

from asg_sistema.config import config
from asg_sistema.db.conexao import SessionLocal
from asg_sistema.db.models import AgendamentoAtualizacao

logger = logging.getLogger(__name__)
MAX_TENTATIVAS_RETRY = max(1, int(config.etl_retry_max_tentativas))
INTERVALO_RETRY = max(1, int(config.etl_retry_intervalo_erro_api_segundos))
API_URL_ETL_EXECUTAR = "http://localhost:8000/api/etl/executar"

def _atualizar_status_agendamento(
    agendamento: AgendamentoAtualizacao,
    *,
    ultimo_status: str,
    ultima_mensagem: str,
    atualizar_execucao: bool = False,
) -> None:
    if atualizar_execucao:
        setattr(agendamento, "ultima_execucao_em", datetime.utcnow())
    setattr(agendamento, "ultimo_status", ultimo_status)
    setattr(agendamento, "ultima_mensagem", ultima_mensagem)


async def _disparar_etl(etapa: str = "full") -> dict:
    """Dispara uma única tentativa de POST /api/etl/executar."""
    async with httpx.AsyncClient(timeout=3600) as client:
        response = await client.post(
            API_URL_ETL_EXECUTAR,
            params={"skip_sicar": True, "etapa": etapa},
        )
        response.raise_for_status()
        return response.json()


def _agendar_nova_tentativa_async(agendamento_id: int, proxima_tentativa: int, intervalo_segundos: int) -> None:
    """Agenda nova tentativa sem bloquear a execução atual."""
    loop = asyncio.get_running_loop()
    loop.call_later(
        intervalo_segundos,
        lambda: asyncio.create_task(
            executar_atualizacao_completa(
                agendamento_id=agendamento_id,
                tentativa_atual=proxima_tentativa,
            )
        ),
    )


async def executar_atualizacao_completa(agendamento_id: int, tentativa_atual: int = 1):
    """
    Executa POST /api/etl/executar para reutilizar a lógica já existente.
    Chamada pelo APScheduler em background.
    """
    db: Session = SessionLocal()
    max_tentativas_retry = MAX_TENTATIVAS_RETRY
    intervalo = INTERVALO_RETRY

    try:
        agendamento = db.get(AgendamentoAtualizacao, agendamento_id)
        if not agendamento:
            logger.warning("Agendamento id=%d não encontrado.", agendamento_id)
            return

        db.commit()

        logger.info(
            "=== Agendamento id=%d iniciado (tentativa %d/%d, etapa=%s) ===",
            agendamento_id,
            tentativa_atual,
            max_tentativas_retry,
            agendamento.etapa,
        )

        # Dispara POST /api/etl/executar com a etapa do agendamento
        resultado = await _disparar_etl(etapa=agendamento.etapa)
        logger.info("[ETL] Resposta da API: %s", resultado)

        # Se chegou aqui, sucesso!
        _atualizar_status_agendamento(
            agendamento,
            ultimo_status="sucesso",
            ultima_mensagem="Pipeline executado com sucesso",
        )
        db.commit()
        logger.info("=== Agendamento id=%d finalizado: SUCESSO ===", agendamento_id)

    except Exception as e:
        if tentativa_atual < max_tentativas_retry:
            proxima_tentativa = tentativa_atual + 1
    
            _agendar_nova_tentativa_async(
                agendamento_id=agendamento_id,
                proxima_tentativa=proxima_tentativa,
                intervalo_segundos=intervalo,
            )

            logger.warning(
                "[ETL] Tentativa %d/%d falhou para agendamento id=%d. "
                "Nova tentativa assíncrona em %ds. Erro: %s",
                tentativa_atual,
                max_tentativas_retry,
                agendamento_id,
                intervalo,
                str(e)[:200],
            )

            try:
                agendamento = db.get(AgendamentoAtualizacao, agendamento_id)
                if agendamento:
                    _atualizar_status_agendamento(
                        agendamento,
                        ultimo_status="retry_agendado",
                        ultima_mensagem=(
                            f"Tentativa {tentativa_atual}/{max_tentativas_retry} falhou. "
                            f"Nova tentativa em {intervalo}s."
                        ),
                    )
                    db.commit()
            except Exception as db_error:
                logger.error("Erro ao atualizar status de retry do agendamento: %s", db_error)
            return

        logger.exception("Falha no agendamento id=%d: %s", agendamento_id, e)
        if db:
            try:
                agendamento = db.get(AgendamentoAtualizacao, agendamento_id)
                if agendamento:
                    _atualizar_status_agendamento(
                        agendamento,
                        ultimo_status="erro",
                        ultima_mensagem=f"Erro: {str(e)[:200]}",
                    )
                    db.commit()
            except Exception as db_error:
                logger.error("Erro ao atualizar status do agendamento: %s", db_error)
    finally:
        if db:
            db.close()