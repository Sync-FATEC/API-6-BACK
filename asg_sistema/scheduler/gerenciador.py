"""Gerenciador do APScheduler para o sistema ASG."""

import logging
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from asg_sistema.services.servico_atualizacao import executar_atualizacao_completa

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler(timezone="America/Sao_Paulo")


def iniciar_scheduler():
    if not scheduler.running:
        scheduler.start()
        logger.info("APScheduler iniciado (timezone: America/Sao_Paulo).")


def encerrar_scheduler():
    if scheduler.running:
        scheduler.shutdown()
        logger.info("APScheduler encerrado.")


def _job_id(agendamento_id: int) -> str:
    return f"atualizacao_asg_{agendamento_id}"


def registrar_job(agendamento_id: int, cron_expressao: str):
    """Registra ou substitui um job no scheduler."""
    minuto, hora, dia, mes, dia_semana = cron_expressao.split()

    scheduler.add_job(
        executar_atualizacao_completa,
        trigger=CronTrigger(
            minute=minuto,
            hour=hora,
            day=dia,
            month=mes,
            day_of_week=dia_semana,
            timezone="America/Sao_Paulo",
        ),
        id=_job_id(agendamento_id),
        kwargs={"agendamento_id": agendamento_id},
        replace_existing=True,
        misfire_grace_time=300,  # tolera até 5 min de atraso
    )
    logger.info("Job '%s' registrado com cron='%s'.", _job_id(agendamento_id), cron_expressao)


def remover_job(agendamento_id: int):
    """Remove um job do scheduler, se existir."""
    job_id = _job_id(agendamento_id)
    if scheduler.get_job(job_id):
        scheduler.remove_job(job_id)
        logger.info("Job '%s' removido.", job_id)


def job_existe(agendamento_id: int) -> bool:
    return scheduler.get_job(_job_id(agendamento_id)) is not None