"""
Endpoints para agendamento de atualização da base de dados ASG.

Rotas:
  POST   /agendamentos/                → cria agendamento com recorrência simples
  GET    /agendamentos/                → lista todos
  GET    /agendamentos/{id}            → detalha um
  PATCH  /agendamentos/{id}            → atualiza recorrência ou ativa/desativa
  POST   /agendamentos/{id}/cancelar   → cancela agendamento (desativa + remove recorrências)
  DELETE /agendamentos/{id}            → remove
  GET    /agendamentos/{id}/status     → status da última execução
"""

from datetime import datetime, time
from typing import List

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy.orm import Session

from asg_sistema.db.conexao import obter_sessao
from asg_sistema.db.models import AgendamentoAtualizacao
from asg_sistema.schemas.agendamento import (
    AgendamentoCreate,
    AgendamentoResponse,
    AgendamentoUpdate,
    StatusExecucaoResponse,
    recorrencia_para_cron,
)
from asg_sistema.scheduler.gerenciador import (
    job_existe, 
    registrar_job, 
    remover_job, 
    obter_proxima_execucao
)
from asg_sistema.services.servico_atualizacao import executar_atualizacao_completa

router = APIRouter(prefix="/agendamentos", tags=["Agendamento de Atualização"])


@router.post(
    "/",
    response_model=AgendamentoResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Cria um novo agendamento de atualização",
)
def criar_agendamento(
    payload: AgendamentoCreate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(obter_sessao),
):
    """
    Cria um agendamento para atualização automática de todas as fontes ASG
    (FUNAI, INPE/DETER, INPE/Queimadas, INPE/PRODES, ICMBio, SICAR, Palmares).

    **Exemplos de recorrência:**
        - A cada 1 semana (pelo dia da data) às 02:00 →
            `{ "intervalo": 1, "unidade": "semana", "horario": "02:00", "data_inicio": "2026-04-08" }`
        - A cada 1 mês (pelo dia da data) às 01:00   →
            `{ "intervalo": 1, "unidade": "mes",    "horario": "01:00", "data_inicio": "2026-04-01" }`
        - A cada 2 dias às 06:30  → `{ "intervalo": 2, "unidade": "dia",    "horario": "06:30" }`
        - A cada 5 minutos        → `{ "intervalo": 5, "unidade": "minuto" }`
        - A cada 3 horas          → `{ "intervalo": 3, "unidade": "hora" }`
    """
    agendamento = AgendamentoAtualizacao(
        intervalo=payload.intervalo,
        unidade=payload.unidade,
        horario=payload.horario.strftime("%H:%M"),
        etapa=payload.etapa,
        cron_expressao=payload.cron_expressao,
    )
    db.add(agendamento)
    db.commit()
    db.refresh(agendamento)

    # Registra o job em background para evitar problemas com AsyncIOScheduler
    background_tasks.add_task(registrar_job, agendamento.id, agendamento.cron_expressao)

    return agendamento


@router.get(
    "/",
    response_model=List[AgendamentoResponse],
    summary="Lista todos os agendamentos",
)
def listar_agendamentos(db: Session = Depends(obter_sessao)):
    agendamentos = db.query(AgendamentoAtualizacao).order_by(AgendamentoAtualizacao.id).all()
    for ag in agendamentos:
        ag.proxima_execucao_em = obter_proxima_execucao(ag.id)
    return agendamentos


@router.get(
    "/{agendamento_id}",
    response_model=AgendamentoResponse,
    summary="Detalha um agendamento",
)
def obter_agendamento(agendamento_id: int, db: Session = Depends(obter_sessao)):
    agendamento = db.get(AgendamentoAtualizacao, agendamento_id)
    if not agendamento:
        raise HTTPException(status_code=404, detail="Agendamento não encontrado.")
    
    # Adiciona proxima_execucao_em dinamicamente para o schema
    agendamento.proxima_execucao_em = obter_proxima_execucao(agendamento_id)
    return agendamento


@router.patch(
    "/{agendamento_id}",
    response_model=AgendamentoResponse,
    summary="Atualiza recorrência ou ativa/desativa um agendamento",
)
def atualizar_agendamento(
    agendamento_id: int,
    payload: AgendamentoUpdate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(obter_sessao),
):
    """
    Atualiza parcialmente um agendamento.

    - Qualquer combinação de **intervalo**, **unidade**, **horario** ou **data_inicio** recalcula o cron automaticamente.
    - `ativo=false` pausa o job sem excluí-lo do banco.
    - `ativo=true` reativa com a recorrência atual.
    """
    agendamento = db.get(AgendamentoAtualizacao, agendamento_id)
    if not agendamento:
        raise HTTPException(status_code=404, detail="Agendamento não encontrado.")

    novo_intervalo = payload.intervalo if payload.intervalo is not None else agendamento.intervalo
    nova_unidade   = payload.unidade   if payload.unidade   is not None else agendamento.unidade
    novo_horario   = payload.horario   if payload.horario   is not None else time(
        *map(int, agendamento.horario.split(":"))
    )

    agendamento.intervalo      = novo_intervalo
    agendamento.unidade        = nova_unidade
    agendamento.horario        = novo_horario.strftime("%H:%M")
    agendamento.cron_expressao = recorrencia_para_cron(
        novo_intervalo,
        nova_unidade,
        novo_horario,
        data_base=payload.data_inicio,
    )

    if payload.ativo is not None:
        agendamento.ativo = payload.ativo

    agendamento.atualizado_em = datetime.utcnow()
    db.commit()
    db.refresh(agendamento)

    if agendamento.ativo:
        background_tasks.add_task(registrar_job, agendamento.id, agendamento.cron_expressao)
    else:
        background_tasks.add_task(remover_job, agendamento.id)

    # Adiciona proxima_execucao_em dinamicamente para o schema
    agendamento.proxima_execucao_em = obter_proxima_execucao(agendamento_id)
    return agendamento


@router.post(
    "/{agendamento_id}/cancelar",
    response_model=AgendamentoResponse,
    status_code=status.HTTP_200_OK,
    summary="Cancela um agendamento (desativa e remove recorrências)",
)
def cancelar_agendamento(agendamento_id: int, background_tasks: BackgroundTasks, db: Session = Depends(obter_sessao)):
    """
    Cancela um agendamento de forma completa.
    
    - Marca o agendamento como inativo
    - Remove o job do scheduler (cancela todas as recorrências)
    - Mantém o histórico do agendamento no banco (não o deleta)
    
    Diferente de DELETE que remove completamente, este endpoint apenas 
    desativa o agendamento para preservar histórico.
    """
    agendamento = db.get(AgendamentoAtualizacao, agendamento_id)
    if not agendamento:
        raise HTTPException(status_code=404, detail="Agendamento não encontrado.")
    
    if not agendamento.ativo:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="O agendamento já foi cancelado.",
        )

    agendamento.ativo = False
    agendamento.atualizado_em = datetime.utcnow()
    
    db.commit()
    db.refresh(agendamento)
    
    # Remove o job em background
    background_tasks.add_task(remover_job, agendamento.id)

    return agendamento


@router.post(
    "/{agendamento_id}/executar",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Dispara o agendamento manualmente agora",
)
async def executar_agendamento_agora(
    agendamento_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(obter_sessao),
):
    """
    Dispara a execução do agendamento imediatamente, sem esperar pela próxima recorrência.
    Utiliza BackgroundTasks para não bloquear a resposta da API.
    """
    agendamento = db.get(AgendamentoAtualizacao, agendamento_id)
    if not agendamento:
        raise HTTPException(status_code=404, detail="Agendamento não encontrado.")

    # Dispara a execução em background
    background_tasks.add_task(executar_atualizacao_completa, agendamento_id)

    return {"status": "disparado", "mensagem": "A execução foi iniciada em background."}


@router.delete(
    "/{agendamento_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove um agendamento",
)
def remover_agendamento(agendamento_id: int, background_tasks: BackgroundTasks, db: Session = Depends(obter_sessao)):
    agendamento = db.get(AgendamentoAtualizacao, agendamento_id)
    if not agendamento:
        raise HTTPException(status_code=404, detail="Agendamento não encontrado.")

    db.delete(agendamento)
    db.commit()
    
    # Remove o job em background
    background_tasks.add_task(remover_job, agendamento_id)


@router.get(
    "/{agendamento_id}/status",
    response_model=StatusExecucaoResponse,
    summary="Consulta status da última execução",
)
def status_agendamento(agendamento_id: int, db: Session = Depends(obter_sessao)):
    """
    Retorna o resultado da última execução e confirma se o job
    está ativo no APScheduler.
    """
    agendamento = db.get(AgendamentoAtualizacao, agendamento_id)
    if not agendamento:
        raise HTTPException(status_code=404, detail="Agendamento não encontrado.")

    return StatusExecucaoResponse(
        agendamento_id=agendamento.id,
        intervalo=agendamento.intervalo,
        unidade=agendamento.unidade,
        horario=agendamento.horario,
        cron_expressao=agendamento.cron_expressao,
        ativo=agendamento.ativo,
        job_registrado_no_scheduler=job_existe(agendamento.id),
        ultima_execucao_em=agendamento.ultima_execucao_em,
        proxima_execucao_em=obter_proxima_execucao(agendamento.id),
        ultimo_status=agendamento.ultimo_status,
        ultima_mensagem=agendamento.ultima_mensagem,
    )