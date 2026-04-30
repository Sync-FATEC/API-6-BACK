import asyncio
from datetime import datetime
from enum import Enum
import glob
import os
import subprocess
import sys
import json as _json
import uuid
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

pipeline_status = {
    "rodando": False,
    "inicio_execucao": 0.0,
    "etapa": None,
    "entidades": [],
    "log_arquivo": None,
}

_pipeline_cancelado = False

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

current_process = None

def _entrada_historico_etl_valida(reg: dict) -> bool:
    """Descarta duplicata antiga: registro vazio com sucesso=true."""
    etapas = reg.get("etapas") or []
    erros = reg.get("erros") or []
    if not etapas and not erros and reg.get("sucesso") is True:
        return False
    return True


def _registrar_cancelamento_historico(inicio_str: str, etapa: str, entidades: list):
    historico_path = Path(__file__).resolve().parent.parent.parent / "logs" / "historico_etl.jsonl"
    historico_path.parent.mkdir(parents=True, exist_ok=True)

    ultimo_id = 0
    if historico_path.exists():
        with open(historico_path, "r", encoding="utf-8") as f:
            for linha in f:
                linha = linha.strip()
                if not linha:
                    continue
                try:
                    reg = _json.loads(linha)
                except _json.JSONDecodeError:
                    continue
                valor = reg.get("execucao_id")
                if isinstance(valor, int):
                    ultimo_id = max(ultimo_id, valor)
                    continue
                pipeline_nome = str(reg.get("pipeline", ""))
                if pipeline_nome.startswith("ETL ASG-SP #"):
                    try:
                        numero = int(pipeline_nome.rsplit("#", 1)[-1].strip())
                        ultimo_id = max(ultimo_id, numero)
                    except ValueError:
                        pass

    execucao_id = ultimo_id + 1
    fim = datetime.now()
    try:
        inicio = datetime.fromisoformat(inicio_str)
        duracao = round((fim - inicio).total_seconds(), 1)
    except (TypeError, ValueError):
        duracao = 0.0

    registro = {
        "execution_id": uuid.uuid4().hex,
        "pipeline": f"ETL ASG-SP #{execucao_id}",
        "execucao_id": execucao_id,
        "inicio": inicio_str,
        "fim": fim.isoformat(),
        "duracao_total_segundos": duracao,
        "etapa_solicitada": etapa,
        "entidades": entidades,
        "etapas": [],
        "erros": [{"etapa": "cancelamento", "erro": "Pipeline cancelado manualmente pelo usuário", "timestamp": fim.isoformat()}],
        "fontes": [],
        "eventos": [{"timestamp": fim.isoformat(), "tipo": "cancelamento", "mensagem": "Execução cancelada manualmente pelo usuário"}],
        "status_arquivo": None,
        "sucesso": False,
    }
    with open(historico_path, "a", encoding="utf-8") as f:
        f.write(_json.dumps(registro, ensure_ascii=False) + "\n")


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
    entidades: list[EntidadeETL] = Query(default=[EntidadeETL.tudo], description="Escolha as entidades para processar"),
    skip_sicar: bool = Query(default=False, description="Skip SICAR collection")
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

    log_dir = repo_root / "logs"
    log_dir.mkdir(exist_ok=True)
    pipeline_status["log_arquivo"] = str(log_dir / f"etl_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log")

    def _rodar_pipeline():
        global pipeline_status, current_process, _pipeline_cancelado
        log_arquivo = Path(pipeline_status["log_arquivo"])
        entidades_str = [e.value for e in entidades]

        try:
            env = os.environ.copy()
            env["PYTHONUNBUFFERED"] = "1"
            env["PYTHONIOENCODING"] = "utf-8"

            with open(log_arquivo, "w", encoding="utf-8") as lf:
                lf.write(f"[INFO] {datetime.now().isoformat()} - Pipeline ETL iniciado (etapa: {etapa.value}, entidades: {entidades_str})\n")

            if not skip_sicar and ("tudo" in entidades_str or "sicar" in entidades_str):
                with open(log_arquivo, "ab") as lf:
                    lf.write(f"[INFO] {datetime.now().isoformat()} - Iniciando coleta de dados do SICAR\n".encode("utf-8"))
                    lf.flush()
                    current_process = subprocess.Popen(
                        [sys.executable, str(script_sicar)],
                        cwd=str(repo_root),
                        stdout=lf,
                        stderr=subprocess.STDOUT,
                        env=env,
                    )
                current_process.wait()

                if _pipeline_cancelado:
                    with open(log_arquivo, "a", encoding="utf-8") as lf:
                        lf.write(f"[INFO] {datetime.now().isoformat()} - Coleta SICAR cancelada manualmente pelo usuário\n")
                    _registrar_cancelamento_historico(pipeline_status["inicio_execucao"], etapa.value, entidades_str)
                    return

                if current_process.returncode != 0:
                    with open(log_arquivo, "a", encoding="utf-8") as lf:
                        lf.write(f"[ERRO] {datetime.now().isoformat()} - Processo SICAR falhou (código: {current_process.returncode})\n")
                    print("[INFO] Processo SICAR interrompido/falhou.")
                    return

            print(f"[INFO] Iniciando pipeline ETL (etapa: {etapa}): {script_etl}")
            cmd_etl = [sys.executable, str(script_etl), "--etapa", etapa.value, "--entidades"] + entidades_str + ["--log-file", str(log_arquivo)]

            current_process = subprocess.Popen(cmd_etl, cwd=str(repo_root), env=env)
            current_process.wait()

            if _pipeline_cancelado:
                with open(log_arquivo, "a", encoding="utf-8") as lf:
                    lf.write(f"[INFO] {datetime.now().isoformat()} - Pipeline ETL cancelado manualmente pelo usuário\n")
                _registrar_cancelamento_historico(pipeline_status["inicio_execucao"], etapa.value, entidades_str)
                return

            if current_process.returncode == 0:
                repositorio.atualizar_data_coleta_fontes(entidades_str, datetime.now())
                print("[INFO] Pipeline ETL finalizado com sucesso pela API.")
            else:
                print(f"[AVISO] Pipeline ETL encerrou com código {current_process.returncode}.")

        except Exception as e:
            print(f"[ERRO] Falha inesperada no worker do ETL: {e}")
        finally:
            pipeline_status["rodando"] = False
            pipeline_status["log_arquivo"] = None
            _pipeline_cancelado = False
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
        limite_tentativas = 30

        try:
            inicio_str = pipeline_status["inicio_execucao"]
            inicio_ts = datetime.fromisoformat(inicio_str).timestamp()
        except (TypeError, ValueError):
            inicio_ts = time.time()

        log_arquivo_direto = pipeline_status.get("log_arquivo")

        while tentativas < limite_tentativas:
            if log_arquivo_direto and Path(log_arquivo_direto).exists():
                log_recente = log_arquivo_direto
                break

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
    global pipeline_status, current_process, _pipeline_cancelado

    if not pipeline_status["rodando"] or current_process is None:
        raise HTTPException(status_code=400, detail="Nenhum pipeline em execução para cancelar.")

    _pipeline_cancelado = True
    current_process.terminate()

    return {"status": "cancelado", "mensagem": "Sinal de cancelamento enviado com sucesso."}