"""
Serviço de atualização da base ASG.

Chama diretamente as funções já existentes em scripts/coletor_asg.py,
reutilizando toda a lógica de coleta sem duplicar código.
"""

import asyncio
import logging
from datetime import datetime

from sqlalchemy.orm import Session

from asg_sistema.db.conexao import SessionLocal
from asg_sistema.db.models import AgendamentoAtualizacao

# Importa os coletores já implementados no projeto
from scripts.coletor_asg import (
    coletar_funai,
    coletar_deter,
    coletar_deter_amazonia,
    coletar_queimadas,
    coletar_prodes,
    coletar_unidades_conservacao,
    coletar_sicar,
    coletar_quilombolas,
    gerar_resumo,
)

logger = logging.getLogger(__name__)

# Mapeamento nome → função coletora (mesma ordem do main() do coletor_asg.py)
COLETORES = [
    ("FUNAI - Terras Indígenas",            coletar_funai),
    ("INPE/DETER - Desmatamento Cerrado",   coletar_deter),
    ("INPE/DETER - Desmatamento Amazônia",  coletar_deter_amazonia),
    ("INPE/Queimadas - Focos de Incêndio",  coletar_queimadas),
    ("INPE/PRODES - Desmatamento Anual",    coletar_prodes),
    ("MMA/ICMBio - Unidades de Conservação", coletar_unidades_conservacao),
    ("SICAR - Cadastro Ambiental Rural",    coletar_sicar),
    ("Palmares - Comunidades Quilombolas",  coletar_quilombolas),
]


async def _executar_coletor(nome: str, fn) -> dict:
    """Executa um coletor síncrono em thread separada para não bloquear o event loop."""
    import time
    inicio = time.time()
    try:
        total = await asyncio.to_thread(fn)
        return {"fonte": nome, "registros": total, "status": "OK", "duracao_segundos": round(time.time() - inicio, 1)}
    except Exception as e:
        logger.error("[%s] Erro: %s", nome, e)
        return {"fonte": nome, "registros": 0, "status": f"ERRO: {e}", "duracao_segundos": round(time.time() - inicio, 1)}


async def executar_atualizacao_completa(agendamento_id: int):
    """
    Função chamada pelo APScheduler.
    Executa todos os coletores do coletor_asg.py e atualiza o status no banco.
    """
    # Abre uma sessão própria (o APScheduler roda fora do ciclo de request do FastAPI)
    db: Session = SessionLocal()

    try:
        agendamento = db.get(AgendamentoAtualizacao, agendamento_id)
        if not agendamento:
            logger.warning("Agendamento id=%d não encontrado.", agendamento_id)
            return

        # Marca como "executando"
        agendamento.ultima_execucao_em = datetime.utcnow()
        agendamento.ultimo_status = "executando"
        agendamento.ultima_mensagem = "Coleta em andamento..."
        db.commit()

        logger.info("=== Agendamento id=%d iniciado ===", agendamento_id)

        # Executa todos os coletores de forma assíncrona
        tarefas = [_executar_coletor(nome, fn) for nome, fn in COLETORES]
        resultados = await asyncio.gather(*tarefas)

        # Gera o resumo_coleta.json (mesmo comportamento do main() do coletor)
        await asyncio.to_thread(gerar_resumo, resultados)

        erros = [r for r in resultados if r["status"].startswith("ERRO")]
        total_registros = sum(r["registros"] for r in resultados)

        if erros:
            fontes_com_erro = ", ".join(r["fonte"] for r in erros)
            agendamento.ultimo_status = "erro"
            agendamento.ultima_mensagem = (
                f"{len(erros)} fonte(s) com erro: {fontes_com_erro}. "
                f"Registros coletados com sucesso: {total_registros}."
            )
        else:
            agendamento.ultimo_status = "sucesso"
            agendamento.ultima_mensagem = (
                f"Todas as {len(resultados)} fontes atualizadas. "
                f"Total de registros coletados: {total_registros}."
            )

        db.commit()
        logger.info("=== Agendamento id=%d finalizado: %s ===", agendamento_id, agendamento.ultimo_status)

    except Exception as e:
        logger.exception("Falha crítica no agendamento id=%d: %s", agendamento_id, e)
        if db:
            try:
                agendamento = db.get(AgendamentoAtualizacao, agendamento_id)
                if agendamento:
                    agendamento.ultimo_status = "erro"
                    agendamento.ultima_mensagem = f"Falha crítica: {e}"
                    db.commit()
            except Exception:
                pass
    finally:
        db.close()