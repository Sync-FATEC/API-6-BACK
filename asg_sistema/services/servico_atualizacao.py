"""
Serviço de atualização da base ASG.

Agendamento dispara o script ETL diretamente via subprocess.
"""

import asyncio
import logging
import subprocess
from datetime import datetime
from pathlib import Path

from sqlalchemy.orm import Session

from asg_sistema.config import config
from asg_sistema.db.conexao import SessionLocal
from asg_sistema.db.models import AgendamentoAtualizacao

logger = logging.getLogger(__name__)
MAX_TENTATIVAS_RETRY = max(1, int(config.etl_retry_max_tentativas))
INTERVALO_RETRY = max(1, int(config.etl_retry_intervalo_erro_api_segundos))


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
    """Dispara o script ETL diretamente via subprocess."""
    repo_root = Path(__file__).resolve().parent.parent.parent
    script_etl = repo_root / "scripts" / "etl_pipeline.py"
    
    if not script_etl.exists():
        raise FileNotFoundError(f"Script ETL não encontrado em: {script_etl}")
    
    logger.info("[ETL] Iniciando subprocess: python %s --etapa %s", script_etl, etapa)
    
    # Define arquivo de log para o ETL
    log_dir = repo_root / "logs"
    log_dir.mkdir(exist_ok=True)
    log_arquivo = log_dir / f"etl_agendado_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
    
    # Executa o script ETL diretamente
    process = await asyncio.create_subprocess_exec(
        "python", str(script_etl),
        "--etapa", etapa,
        "--entidades", "tudo",
        "--log-file", str(log_arquivo),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    
    stdout, stderr = await process.communicate()
    
    if process.returncode != 0:
        error_msg = stderr.decode() if stderr else "Erro desconhecido"
        raise RuntimeError(f"ETL falhou com código {process.returncode}: {error_msg}")
    
    logger.info("[ETL] Script finalizado com sucesso (código 0)")
    return {"status": "sucesso", "etapa": etapa}


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
        logger.info("[AGENDAMENTO] Iniciando executar_atualizacao_completa(id=%d, tentativa=%d)", agendamento_id, tentativa_atual)
        
        agendamento = db.get(AgendamentoAtualizacao, agendamento_id)
        if not agendamento:
            logger.warning("[AGENDAMENTO] Agendamento id=%d não encontrado no banco.", agendamento_id)
            return

        db.commit()

        logger.info(
            "[AGENDAMENTO] id=%d iniciado (tentativa %d/%d, etapa=%s)",
            agendamento_id,
            tentativa_atual,
            max_tentativas_retry,
            agendamento.etapa,
        )

        # Dispara o script ETL diretamente com a etapa do agendamento
        logger.info("[AGENDAMENTO] id=%d chamando ETL com etapa=%s", agendamento_id, agendamento.etapa)
        resultado = await _disparar_etl(etapa=agendamento.etapa)
        logger.info("[AGENDAMENTO] id=%d resposta da API: %s", agendamento_id, resultado)

        # Se chegou aqui, sucesso!
        _atualizar_status_agendamento(
            agendamento,
            ultimo_status="sucesso",
            ultima_mensagem="Pipeline executado com sucesso",
            atualizar_execucao=True,
        )
        db.commit()
        logger.info("[AGENDAMENTO] id=%d finalizado: SUCESSO ✓", agendamento_id)

    except Exception as e:
        logger.error("[AGENDAMENTO] id=%d erro na tentativa %d: %s", agendamento_id, tentativa_atual, type(e).__name__, exc_info=True)
        
        if tentativa_atual < max_tentativas_retry:
            proxima_tentativa = tentativa_atual + 1
    
            _agendar_nova_tentativa_async(
                agendamento_id=agendamento_id,
                proxima_tentativa=proxima_tentativa,
                intervalo_segundos=intervalo,
            )

            logger.warning(
                "[AGENDAMENTO] id=%d tentativa %d/%d falhou. "
                "Agendando retry em %ds. Erro: %s",
                agendamento_id,
                tentativa_atual,
                max_tentativas_retry,
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
                            f"Retry em {intervalo}s."
                        ),
                    )
                    db.commit()
                    logger.info("[AGENDAMENTO] id=%d status atualizado para retry_agendado", agendamento_id)
            except Exception as db_error:
                logger.error("[AGENDAMENTO] id=%d erro ao atualizar status de retry: %s", agendamento_id, db_error)
            return

        logger.error("[AGENDAMENTO] id=%d FALHA FINAL após %d tentativas: %s", agendamento_id, max_tentativas_retry, e)
        if db:
            try:
                agendamento = db.get(AgendamentoAtualizacao, agendamento_id)
                if agendamento:
                    _atualizar_status_agendamento(
                        agendamento,
                        ultimo_status="erro",
                        ultima_mensagem=f"Erro após {max_tentativas_retry} tentativas: {str(e)[:200]}",
                        atualizar_execucao=True,
                    )
                    db.commit()
                    logger.info("[AGENDAMENTO] id=%d status atualizado para erro", agendamento_id)
            except Exception as db_error:
                logger.error("[AGENDAMENTO] id=%d erro ao atualizar status final: %s", agendamento_id, db_error)
    finally:
        logger.info("[AGENDAMENTO] id=%d finalizando (fechando sessão do DB)", agendamento_id)
        if db:
            db.close()