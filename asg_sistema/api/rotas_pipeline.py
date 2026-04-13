import asyncio
from datetime import datetime
from enum import Enum
import glob
import os
import subprocess
import sys
import json as _json
from pathlib import Path
import time

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query
from fastapi.responses import StreamingResponse

from asg_sistema.api.etl_cooldown import (
    assegurar_cooldown_disparo_etl_api, 
    registrar_disparo_etl_api
)
from asg_sistema.db import repositorio

router = APIRouter()

class EntidadeETL(str, Enum):
    tudo = "tudo"
    sicar = "sicar"
    queimadas = "queimadas"
    desmatamentos = "desmatamentos"
    unidades_conservacao = "unidades_conservacao"
    quilombos = "quilombos"
    terras_indigenas = "terras_indigenas"

class EtapaETL(str, Enum):
    extract = "extract"
    load = "load"
    embed = "embed"
    validate = "validate"
    full = "full"
    
pipeline_status = {
    "rodando": False,
    "inicio_execucao": 0.0
}

pipeline_status = {
    "rodando": False,
    "inicio_execucao": 0.0,
    "etapa": None,
    "entidades": []
}

current_process = None

def _entrada_historico_etl_valida(reg: dict) -> bool:
    """Descarta duplicata antiga: registro vazio com sucesso=true."""
    etapas = reg.get("etapas") or []
    erros = reg.get("erros") or []
    if not etapas and not erros and reg.get("sucesso") is True:
        return False
    return True


@router.get("/status")
def status_etl():
    """
    Retorna o estado atual do pipeline e o resumo de cada fonte de dados
    extraído diretamente da tabela 'fontes'.
    """
    global pipeline_status
    
    try:
        detalhes_fontes = repositorio.obter_resumo_fontes()
    except Exception as e:
        print(f"[ERRO] Falha ao carregar status das fontes: {e}")
        detalhes_fontes = {}

    return {
        "rodando": pipeline_status["rodando"],
        "inicio_execucao": pipeline_status["inicio_execucao"],
        "etapa_atual": pipeline_status["etapa"],
        "entidades_atuais": pipeline_status["entidades"],
        "fontes": detalhes_fontes
    }


@router.get("/historico")
def historico_etl():
    """Retorna o histórico das execuções do pipeline ETL com metadados de filtros."""
    log_path = Path(__file__).resolve().parent.parent.parent / "logs" / "historico_etl.jsonl"
    
    if not log_path.exists():
        return {"execucoes": [], "total": 0}
        
    execucoes = []
    with open(log_path, "r", encoding="utf-8") as f:
        for linha in f:
            linha = linha.strip()
            if not linha:
                continue
            try:
                reg = _json.loads(linha)
                if _entrada_historico_etl_valida(reg):
                    execucoes.append({
                        "pipeline": reg.get("pipeline", "Desconhecido"),
                        "inicio": reg.get("inicio"),
                        "fim": reg.get("fim"),
                        "sucesso": reg.get("sucesso"),
                        "etapa_solicitada": reg.get("etapa_solicitada", "N/A"),
                        "entidades_solicitadas": reg.get("entidades", ["tudo"]),
                        "duracao_total": reg.get("duracao_total_segundos"),
                        "etapas": reg.get("etapas", []),
                        "erros": reg.get("erros", [])
                    })
            except _json.JSONDecodeError:
                continue

    execucoes.reverse()
    return {"execucoes": execucoes[:20], "total": len(execucoes)}


@router.post("/executar")
def executar_etl_api(
    background_tasks: BackgroundTasks, 
    etapa: EtapaETL = Query(default=EtapaETL.full, description="Escolha a etapa do pipeline"),
    entidades: list[EntidadeETL] = Query(default=[EntidadeETL.tudo], description="Escolha as entidades para processar")
):
    """Dispara execução do pipeline ETL via API."""
    global pipeline_status

    if pipeline_status["rodando"]:
        raise HTTPException(
            status_code=409, 
            detail="Um pipeline já está em execução neste momento. Tente novamente mais tarde."
        )

    pipeline_status["rodando"] = True
    pipeline_status["inicio_execucao"] = datetime.now().isoformat()
    pipeline_status["etapa"] = etapa.value
    pipeline_status["entidades"] = [e.value for e in entidades]
    
    try:
        assegurar_cooldown_disparo_etl_api()
    except Exception as e:
        pipeline_status["rodando"] = False
        raise e
    
    repo_root = Path(__file__).resolve().parent.parent.parent
    script_etl = repo_root / "scripts" / "etl_pipeline.py"
    script_sicar = repo_root / "scripts" / "coletar_sicar.py"

    if not script_etl.exists():
        pipeline_status["rodando"] = False
        raise HTTPException(status_code=500, detail=f"Script ETL não encontrado em: {script_etl}")

    def _rodar_pipeline():
        global pipeline_status, current_process
        try:
            entidades_str = [e.value for e in entidades] 
            
            if "tudo" in entidades_str or "sicar" in entidades_str: 
                print(f"[INFO] Iniciando coleta SICAR: {script_sicar}")
                current_process = subprocess.Popen([sys.executable, str(script_sicar)], cwd=str(repo_root))
                current_process.wait()
                
                if current_process.returncode != 0:
                    print("[INFO] Processo SICAR interrompido/falhou.")
                    return

            print(f"[INFO] Iniciando pipeline ETL (etapa: {etapa}): {script_etl}")
            cmd_etl = [sys.executable, str(script_etl), "--etapa", etapa, "--entidades"] + entidades_str 
            
            current_process = subprocess.Popen(cmd_etl, cwd=str(repo_root))
            current_process.wait()
            
            if current_process.returncode == 0:
                repositorio.atualizar_data_coleta_fontes(entidades_str, datetime.now())
                print("[INFO] Pipeline ETL finalizado com sucesso pela API.")
            elif current_process.returncode == -15:
                print("[INFO] Execução do pipeline cancelada pelo usuário.")
            
        except Exception as e:
            print(f"[ERRO] Falha inesperada no worker do ETL: {e}")
        finally:
            pipeline_status["rodando"] = False
            current_process = None

    background_tasks.add_task(_rodar_pipeline)
    registrar_disparo_etl_api()
    
    return {
        "status": "iniciado", 
        "etapa": etapa, 
        "entidades_solicitadas": entidades,
    }

@router.get("/stream")
async def stream_etl_logs():
    """Acompanha os logs do pipeline ETL em tempo real usando Server-Sent Events (SSE)."""
    async def log_generator():
        global pipeline_status
        
        if not pipeline_status["rodando"]:
            yield "data: [INFO] Nenhuma execução em andamento. Stream não iniciado.\n\n"
            return

        repo_root = Path(__file__).resolve().parent.parent.parent
        log_dir = repo_root / "logs"
        
        log_recente = None
        tentativas = 0
        limite_tentativas = 20
        
        try:
            inicio_str = pipeline_status["inicio_execucao"]
            inicio_ts = datetime.fromisoformat(inicio_str).timestamp()
        except (TypeError, ValueError):
            inicio_ts = time.time() 

        while tentativas < limite_tentativas:
            arquivos_log = glob.glob(str(log_dir / "etl_*.log"))
            if arquivos_log:
                candidato = max(arquivos_log, key=os.path.getmtime)
                tempo_arquivo = os.path.getmtime(candidato)
                
                tempo_esperado = inicio_ts - 3.0
                
                if tempo_arquivo >= tempo_esperado:
                    log_recente = candidato
                    break
            
            await asyncio.sleep(0.5)
            tentativas += 1

        if not log_recente:
            yield "data: [ERRO] Tempo esgotado (Timeout) aguardando inicialização do log no servidor.\n\n"
            return
        
        with open(log_recente, "r", encoding="utf-8") as f:
            while True:
                linha = f.readline()
                if linha:
                    yield f"data: {linha.strip()}\n\n"
                else:
                    if not pipeline_status["rodando"]:
                        yield "data: [INFO] Pipeline finalizado. Stream encerrado.\n\n"
                        break
                    await asyncio.sleep(0.5)

    return StreamingResponse(log_generator(), media_type="text/event-stream")

@router.post("/cancelar")
def cancelar_etl_api():
    global pipeline_status, current_process
    
    if not pipeline_status["rodando"] or current_process is None:
        raise HTTPException(status_code=400, detail="Nenhum pipeline em execução para cancelar.")

    current_process.terminate()
    
    return {"status": "cancelado", "mensagem": "Sinal de cancelamento enviado com sucesso."}