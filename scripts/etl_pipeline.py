from __future__ import annotations
"""
Pipeline ETL completo para o Sistema ASG-SP.

Orquestra todas as etapas:
  1. EXTRACT  - Coleta dados das APIs publicas (INPE, FUNAI, ICMBio, etc.)
  2. TRANSFORM - Textualiza registros para o corpus de busca semantica
  3. LOAD      - Insere no PostgreSQL (estruturado + corpus + embeddings)
  4. LOG       - Registra execucao para rastreabilidade

Pode ser executado manualmente ou agendado via cron/Task Scheduler.

Uso:
    python scripts/etl_pipeline.py                 # Pipeline completo
    python scripts/etl_pipeline.py --etapa extract  # Apenas coleta
    python scripts/etl_pipeline.py --etapa load     # Apenas carga no banco
    python scripts/etl_pipeline.py --etapa embed    # Apenas vetorizacao
    python scripts/etl_pipeline.py --agendar 6      # Roda a cada 6 horas
"""

import argparse
import json
import logging
import os
import subprocess
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

LOG_DIR = Path(__file__).resolve().parent.parent / "logs"
LOG_DIR.mkdir(exist_ok=True)

log_arquivo = LOG_DIR / f"etl_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(str(log_arquivo), encoding="utf-8"),
    ],
)
logger = logging.getLogger("etl_pipeline")


class RegistroETL:
    """Registra cada execucao do pipeline para rastreabilidade."""

    def __init__(self, etapa_solicitada: str = "full", entidades_solicitadas: list = None, execution_id: str | None = None):
        self.execution_id = execution_id or uuid.uuid4().hex
        self.inicio = datetime.now()
        self.etapas = []
        self.erros = []
        self.etapa_solicitada = etapa_solicitada
        self.entidades_solicitadas = entidades_solicitadas or ["tudo"]
        self.status_path = LOG_DIR / f"status_etl_{self.execution_id}.json"
        self._inicializar_status()
    def _proximo_id_execucao(self, historico_path: Path) -> int:
        """Gera identificador incremental de execução para exibição no histórico."""
        if not historico_path.exists():
            return 1
    
        ultimo_id = 0
        with open(historico_path, "r", encoding="utf-8") as f:
            for linha in f:
                linha = linha.strip()
                if not linha:
                    continue
                try:
                    reg = json.loads(linha)
                except json.JSONDecodeError:
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
    
        return ultimo_id + 1
    
    

    def _status_base(self) -> dict:
        return {
            "execution_id": self.execution_id,
            "pipeline": "ETL ASG-SP",
            "inicio": self.inicio.isoformat(),
            "atualizado_em": self.inicio.isoformat(),
            "etapa_atual": "inicio",
            "status_execucao": "em_andamento",
            "finalizado": False,
            "mensagem": "Pipeline inicializado e aguardando processamento.",
            "etapas": [],
            "erros": [],
            "fontes": [],
            "eventos": [],
        }

    def _inicializar_status(self):
        if self.status_path.exists():
            status = self._ler_status()
            inicio_existente = status.get("inicio")
            if isinstance(inicio_existente, str):
                try:
                    self.inicio = datetime.fromisoformat(inicio_existente)
                except ValueError:
                    status["inicio"] = self.inicio.isoformat()
            else:
                status["inicio"] = self.inicio.isoformat()
            status.setdefault("etapas", [])
            status.setdefault("erros", [])
            status.setdefault("fontes", [])
            status.setdefault("eventos", [])
            status["status_execucao"] = "em_andamento"
            status["finalizado"] = False
            self._salvar_status(status)
            return

        status = self._status_base()
        self._salvar_status(status)

    def _ler_status(self) -> dict:
        if not self.status_path.exists():
            return self._status_base()

        try:
            with open(self.status_path, "r", encoding="utf-8") as f:
                conteudo = json.load(f)
                if isinstance(conteudo, dict):
                    return conteudo
        except Exception as e:
            logger.debug("Falha ao ler status ETL: %s", e)
        return self._status_base()

    def _salvar_status(self, status: dict):
        status["execution_id"] = self.execution_id
        status["pipeline"] = "ETL ASG-SP"
        status["atualizado_em"] = datetime.now().isoformat()
        self.status_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.status_path, "w", encoding="utf-8") as f:
            json.dump(status, f, ensure_ascii=False, indent=2)

    def atualizar_status(
        self,
        mensagem: str | None = None,
        etapa_atual: str | None = None,
        status_execucao: str | None = None,
        finalizado: bool | None = None,
    ):
        status = self._ler_status()
        status["etapas"] = self.etapas
        status["erros"] = self.erros
        if mensagem is not None:
            status["mensagem"] = mensagem
        if etapa_atual is not None:
            status["etapa_atual"] = etapa_atual
        if status_execucao is not None:
            status["status_execucao"] = status_execucao
        if finalizado is not None:
            status["finalizado"] = finalizado
        self._salvar_status(status)

    def registrar_evento(
        self,
        tipo: str,
        mensagem: str,
        etapa: str | None = None,
        fonte: str | None = None,
        tentativa: int | None = None,
        max_tentativas: int | None = None,
    ):
        status = self._ler_status()
        eventos = status.get("eventos")
        if not isinstance(eventos, list):
            eventos = []

        evento = {
            "timestamp": datetime.now().isoformat(),
            "tipo": tipo,
            "mensagem": mensagem,
        }
        if etapa is not None:
            evento["etapa"] = etapa
        if fonte is not None:
            evento["fonte"] = fonte
        if tentativa is not None:
            evento["tentativa"] = tentativa
        if max_tentativas is not None:
            evento["max_tentativas"] = max_tentativas

        eventos.append(evento)
        status["eventos"] = eventos
        status["mensagem"] = mensagem
        self._salvar_status(status)

    def definir_fontes(self, fontes: list[dict]):
        status = self._ler_status()
        status["fontes"] = fontes
        self._salvar_status(status)

    def registrar_etapa(self, nome: str, status: str, registros: int = 0, duracao_s: float = 0):
        self.etapas.append({
            "etapa": nome,
            "status": status,
            "registros": registros,
            "duracao_segundos": round(duracao_s, 1),
            "timestamp": datetime.now().isoformat(),
        })
        self.atualizar_status(
            mensagem=f"Etapa '{nome}' concluida com status {status}.",
            etapa_atual=nome,
            status_execucao="em_andamento",
        )

    def registrar_erro(self, etapa: str, erro: str):
        self.erros.append({
            "etapa": etapa, 
            "erro": erro, 
            "timestamp": datetime.now().isoformat()
        })
        self.registrar_evento("erro", f"Erro na etapa '{etapa}': {erro}", etapa=etapa)
        self.atualizar_status(
            mensagem=f"Erro detectado na etapa '{etapa}'.",
            etapa_atual=etapa,
            status_execucao="em_andamento",
        )

    def salvar(self):
        fim = datetime.now()
        duracao_total = round((fim - self.inicio).total_seconds(), 1)
        status_atual = self._ler_status()
        fontes = status_atual.get("fontes") if isinstance(status_atual.get("fontes"), list) else []
        eventos = status_atual.get("eventos") if isinstance(status_atual.get("eventos"), list) else []
        sucesso = len(self.erros) == 0

        historico_path = LOG_DIR / "historico_etl.jsonl"
        execucao_id = self._proximo_id_execucao(historico_path)
        registro = {
            "execution_id": self.execution_id,
            "pipeline": f"ETL ASG-SP #{execucao_id}",
            "execucao_id": execucao_id,
            "inicio": self.inicio.isoformat(),
            "fim": fim.isoformat(),
            "duracao_total_segundos": duracao_total,
            "etapa_solicitada": self.etapa_solicitada,
            "entidades": self.entidades_solicitadas,
            "etapas": self.etapas,
            "erros": self.erros,
            "fontes": fontes,
            "eventos": eventos,
            "status_arquivo": str(self.status_path),
            "sucesso": sucesso,
        }
        with open(historico_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(registro, ensure_ascii=False) + "\n")

        status_atual["inicio"] = self.inicio.isoformat()
        status_atual["fim"] = fim.isoformat()
        status_atual["duracao_total_segundos"] = duracao_total
        status_atual["etapas"] = self.etapas
        status_atual["erros"] = self.erros
        status_atual["fontes"] = fontes
        status_atual["eventos"] = eventos
        status_atual["etapa_atual"] = "concluido"
        status_atual["status_execucao"] = "sucesso" if sucesso else "falha"
        status_atual["finalizado"] = True
        status_atual["mensagem"] = (
            "Pipeline finalizado com sucesso."
            if sucesso
            else "Pipeline finalizado com falha definitiva."
        )
        self._salvar_status(status_atual)

        logger.info("Registro salvo em %s", historico_path)
        return registro


def _carregar_fontes_resumo_coleta() -> list[dict]:
    dados_dir = Path(__file__).resolve().parent.parent / "dados"
    resumo_path = dados_dir / "resumo_coleta.json"
    if not resumo_path.exists():
        return []

    with open(resumo_path, "r", encoding="utf-8") as f:
        resumo = json.load(f)

    itens = resumo.get("fontes")
    if not isinstance(itens, list):
        itens = resumo.get("resultados", [])
    if not isinstance(itens, list):
        return []

    fontes: list[dict] = []
    for item in itens:
        if not isinstance(item, dict):
            continue

        tentativas = item.get("tentativas", 1)
        max_tentativas = item.get("max_tentativas", tentativas)
        try:
            tentativas = max(1, int(tentativas))
        except Exception:
            tentativas = 1
        try:
            max_tentativas = max(1, int(max_tentativas))
        except Exception:
            max_tentativas = tentativas

        fontes.append({
            "fonte": item.get("fonte", "Base desconhecida"),
            "status": item.get("status", "ERRO"),
            "registros": int(item.get("registros", 0) or 0),
            "duracao_segundos": round(float(item.get("duracao_segundos", 0) or 0), 1),
            "tentativas": tentativas,
            "max_tentativas": max_tentativas,
            "mensagem_final": item.get("mensagem_final"),
            "historico_tentativas": (
                item.get("historico_tentativas")
                if isinstance(item.get("historico_tentativas"), list)
                else []
            ),
        })

    return fontes

def etapa_extract(registro: RegistroETL, entidades: list) -> bool:
    """EXTRACT: Coleta dados de todas as fontes publicas."""
    logger.info("=" * 60)
    logger.info(f"ETAPA 1/4: EXTRACT - Coletando dados (Entidades: {entidades})")
    logger.info("=" * 60)
    inicio = time.time()

    registro.atualizar_status(
        mensagem="Coletando bases de dados e monitorando tentativas automáticas.",
        etapa_atual="extract",
        status_execucao="em_andamento",
    )
    registro.registrar_evento(
        "etapa_iniciada",
        "Iniciando etapa EXTRACT.",
        etapa="extract",
    )

    try:
        coletor_path = Path(__file__).resolve().parent / "coletor_asg.py"
        env = os.environ.copy()
        env["ETL_STATUS_PATH"] = str(registro.status_path)
        env["ETL_EXECUTION_ID"] = registro.execution_id
        env.setdefault("ETL_MAX_TENTATIVAS", "3")

        
        cmd = [sys.executable, str(coletor_path), "--entidades"] + entidades
        
        resultado = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=1200,
            env=env,
        )

        if resultado.returncode != 0:
            logger.error("Coletor finalizou com erro: %s", resultado.stderr[-500:] if resultado.stderr else "sem detalhes")
            registro.registrar_erro("extract", resultado.stderr[-300:] if resultado.stderr else "exit code != 0")
            return False

        fontes = _carregar_fontes_resumo_coleta()
        registro.definir_fontes(fontes)

        duracao = time.time() - inicio
        total_registros = sum(item.get("registros", 0) for item in fontes)
        fontes_com_erro = [
            item
            for item in fontes
            if not str(item.get("status", "")).upper().startswith("OK")
        ]

        if fontes_com_erro:
            for item in fontes_com_erro:
                nome_fonte = item.get("fonte", "base_desconhecida")
                mensagem_erro = item.get("mensagem_final") or item.get("status") or "Falha no extract"
                registro.registrar_erro(f"extract:{nome_fonte}", str(mensagem_erro))

            registro.registrar_evento(
                "extract_parcial",
                f"Extract finalizado com erro definitivo em {len(fontes_com_erro)} base(s).",
                etapa="extract",
            )
            logger.warning(
                "Extract finalizado com erro em %d base(s): %s",
                len(fontes_com_erro),
                ", ".join(str(item.get("fonte", "?")) for item in fontes_com_erro),
            )
            registro.registrar_etapa("extract", "parcial", total_registros, duracao)
            return False

        logger.info("Extract concluido: %d registros coletados em %.1fs", total_registros, duracao)
        registro.registrar_evento(
            "extract_sucesso",
            "Extract finalizado com sucesso em todas as bases.",
            etapa="extract",
        )
        registro.registrar_etapa("extract", "sucesso", total_registros, duracao)
        return True

    except subprocess.TimeoutExpired:
        logger.error("Timeout na coleta (limite: 1200s)")
        registro.registrar_erro("extract", "timeout 1200s")
        registro.registrar_evento(
            "extract_timeout",
            "Timeout na coleta de dados (limite 1200s).",
            etapa="extract",
        )
        return False
    except Exception as e:
        logger.error("Erro no extract: %s", e)
        registro.registrar_erro("extract", str(e))
        registro.registrar_evento(
            "extract_erro",
            f"Falha inesperada no extract: {e}",
            etapa="extract",
        )
        return False


def etapa_transform_load(registro: RegistroETL, entidades: list) -> bool:
    """TRANSFORM + LOAD: Textualiza e carrega no PostgreSQL."""
    logger.info("=" * 60)
    logger.info("ETAPA 2/4: TRANSFORM + LOAD - Aplicando UPSERT (inserção e atualização) no banco")
    logger.info("=" * 60)
    inicio = time.time()

    registro.atualizar_status(
        mensagem="Executando transformação e carga no banco.",
        etapa_atual="transform_load",
        status_execucao="em_andamento",
    )
    registro.registrar_evento(
        "etapa_iniciada",
        "Iniciando etapa TRANSFORM + LOAD.",
        etapa="transform_load",
    )

    try:
        from asg_sistema.config import config
        from asg_sistema.db.conexao import executar_consulta
        from asg_sistema.ingestao.carregador import carregar_tudo

        logger.info("Atualizando tabelas com registros recentes...")
        
        carregar_tudo(config.caminho_dados, entidades)

        contagens = {}
        for tabela in ["queimadas", "terras_indigenas", "desmatamento_alertas", "unidades_conservacao", "prodes_desmatamento", "comunidades_quilombolas", "sicar_imoveis", "corpus_asg"]:
            contagens[tabela] = r[0]["total"]
            logger.info("  %s: %d registros", tabela, contagens[tabela])

        total = sum(contagens.values())
        duracao = time.time() - inicio
        logger.info("Transform+Load concluido: %d registros totais em %.1fs", total, duracao)
        registro.registrar_evento(
            "transform_load_sucesso",
            "Transform+Load concluido com sucesso.",
            etapa="transform_load",
        )
        registro.registrar_etapa("transform_load", "sucesso", total, duracao)
        return True

    except Exception as e:
        logger.error("Erro no transform+load: %s", e)
        registro.registrar_erro("transform_load", str(e))
        registro.registrar_evento(
            "transform_load_erro",
            f"Falha no transform+load: {e}",
            etapa="transform_load",
        )
        return False


def etapa_vetorizacao(registro: RegistroETL) -> bool:
    """EMBED: Gera embeddings para busca semantica via pgvector."""
    logger.info("=" * 60)
    logger.info("ETAPA 3/4: EMBED - Gerando embeddings para busca semantica")
    logger.info("=" * 60)
    inicio = time.time()

    registro.atualizar_status(
        mensagem="Gerando embeddings para as bases carregadas.",
        etapa_atual="vetorizacao",
        status_execucao="em_andamento",
    )
    registro.registrar_evento(
        "etapa_iniciada",
        "Iniciando etapa EMBED.",
        etapa="vetorizacao",
    )

    try:
        from asg_sistema.config import config
        from asg_sistema.db.conexao import executar_consulta, executar_sql
        from asg_sistema.pln.extrator_caracteristicas import ExtratorCaracteristicas

        pendentes = executar_consulta(
            "SELECT COUNT(*) as total FROM corpus_asg WHERE embedding IS NULL"
        )
        total_pendente = pendentes[0]["total"]

        if total_pendente == 0:
            logger.info("Todos os registros ja possuem embedding.")
            registro.registrar_evento(
                "vetorizacao_sem_pendencias",
                "Nenhum embedding pendente para gerar.",
                etapa="vetorizacao",
            )
            registro.registrar_etapa("vetorizacao", "sucesso", 0, 0)
            return True

        logger.info("Gerando embeddings para %d registros...", total_pendente)
        extrator = ExtratorCaracteristicas(config.modelo_embeddings)

        batch_size = 200
        offset = 0
        total_processado = 0

        while True:
            lote = executar_consulta(
                "SELECT id, texto FROM corpus_asg WHERE embedding IS NULL ORDER BY id LIMIT :lim OFFSET :off",
                {"lim": batch_size, "off": 0},
            )
            if not lote:
                break

            textos = [r["texto"] for r in lote]
            ids = [r["id"] for r in lote]

            embeddings = extrator.embeddings(textos)

            for doc_id, emb in zip(ids, embeddings):
                emb_str = "[" + ",".join(str(float(v)) for v in emb) + "]"
                executar_sql(
                    "UPDATE corpus_asg SET embedding = :emb WHERE id = :id",
                    {"emb": emb_str, "id": doc_id},
                )

            total_processado += len(lote)
            logger.info("  %d/%d embeddings gerados", total_processado, total_pendente)

        duracao = time.time() - inicio
        logger.info("Vetorizacao concluida: %d embeddings em %.1fs", total_processado, duracao)
        registro.registrar_evento(
            "vetorizacao_sucesso",
            "Etapa EMBED concluida com sucesso.",
            etapa="vetorizacao",
        )
        registro.registrar_etapa("vetorizacao", "sucesso", total_processado, duracao)
        return True

    except Exception as e:
        logger.error("Erro na vetorizacao: %s", e)
        registro.registrar_erro("vetorizacao", str(e))
        registro.registrar_evento(
            "vetorizacao_erro",
            f"Falha na vetorizacao: {e}",
            etapa="vetorizacao",
        )
        return False


def etapa_validacao(registro: RegistroETL) -> bool:
    """Valida integridade dos dados apos o pipeline."""
    logger.info("=" * 60)
    logger.info("ETAPA 4/4: VALIDACAO - Verificando integridade")
    logger.info("=" * 60)
    inicio = time.time()

    registro.atualizar_status(
        mensagem="Validando integridade dos dados carregados.",
        etapa_atual="validacao",
        status_execucao="em_andamento",
    )
    registro.registrar_evento(
        "etapa_iniciada",
        "Iniciando etapa VALIDACAO.",
        etapa="validacao",
    )

    try:
        from asg_sistema.db.conexao import executar_consulta

        checks = []

        r = executar_consulta("SELECT COUNT(*) as total FROM corpus_asg")
        total_corpus = r[0]["total"]
        checks.append(("corpus_asg nao vazio", total_corpus > 0))

        r = executar_consulta("SELECT COUNT(*) as total FROM corpus_asg WHERE embedding IS NOT NULL")
        total_com_embedding = r[0]["total"]
        checks.append(("embeddings gerados", total_com_embedding > 0))

        r = executar_consulta("SELECT COUNT(*) as total FROM fontes")
        total_fontes = r[0]["total"]
        checks.append(("fontes registradas", total_fontes > 0))

        r = executar_consulta("SELECT COUNT(*) as total FROM queimadas WHERE geom IS NOT NULL")
        total_geo = r[0]["total"]
        checks.append(("geometrias queimadas", total_geo > 0))

        # Garantia de escopo: nenhum registro fora de SP.
        r = executar_consulta(
            """SELECT COUNT(*) as total
               FROM queimadas
               WHERE UPPER(TRIM(COALESCE(estado, ''))) NOT IN ('SP', 'SAO PAULO', 'SÃO PAULO')"""
        )
        checks.append(("queimadas apenas SP", r[0]["total"] == 0))

        r = executar_consulta(
            """SELECT COUNT(*) as total
               FROM terras_indigenas
               WHERE UPPER(TRIM(COALESCE(uf, ''))) <> 'SP'"""
        )
        checks.append(("terras indigenas apenas SP", r[0]["total"] == 0))

        r = executar_consulta(
            """SELECT COUNT(*) as total
               FROM desmatamento_alertas
               WHERE UPPER(TRIM(COALESCE(uf, ''))) <> 'SP'"""
        )
        checks.append(("desmatamento apenas SP", r[0]["total"] == 0))

        r = executar_consulta(
            """SELECT COUNT(*) as total
               FROM prodes_desmatamento
               WHERE UPPER(TRIM(COALESCE(estado, ''))) <> 'SP'"""
        )
        checks.append(("prodes apenas SP", r[0]["total"] == 0))

        r = executar_consulta(
            """SELECT COUNT(*) as total
               FROM comunidades_quilombolas
               WHERE UPPER(TRIM(COALESCE(uf, ''))) <> 'SP'"""
        )
        checks.append(("quilombolas apenas SP", r[0]["total"] == 0))

        r = executar_consulta(
            """SELECT COUNT(*) as total
               FROM corpus_asg
               WHERE UPPER(TRIM(COALESCE(uf_sigla, ''))) <> 'SP'"""
        )
        checks.append(("corpus apenas SP", r[0]["total"] == 0))

        todos_ok = True
        for nome, ok in checks:
            status = "OK" if ok else "FALHA"
            logger.info("  [%s] %s", status, nome)
            if not ok:
                todos_ok = False

        cobertura = (total_com_embedding / total_corpus * 100) if total_corpus > 0 else 0
        logger.info("  Cobertura embeddings: %d/%d (%.1f%%)", total_com_embedding, total_corpus, cobertura)

        duracao = time.time() - inicio
        registro.registrar_evento(
            "validacao_concluida",
            "Etapa de validacao finalizada.",
            etapa="validacao",
        )
        registro.registrar_etapa("validacao", "sucesso" if todos_ok else "parcial", 0, duracao)
        return todos_ok

    except Exception as e:
        logger.error("Erro na validacao: %s", e)
        registro.registrar_erro("validacao", str(e))
        registro.registrar_evento(
            "validacao_erro",
            f"Falha na validacao: {e}",
            etapa="validacao",
        )
        return False


def pipeline_completo(etapa: str, entidades: list, execution_id: str | None = None):
    """Executa o pipeline ETL completo."""
    logger.info("=" * 60)
    logger.info("PIPELINE ETL ASG-SP - Inicio: %s", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    logger.info("=" * 60)

    registro = RegistroETL(etapa_solicitada=etapa, entidades_solicitadas=entidades, execution_id=execution_id)
    registro.atualizar_status(
        mensagem="Pipeline iniciado. Preparando etapas.",
        etapa_atual="inicio",
        status_execucao="em_andamento",
        finalizado=False,
    )
    registro.registrar_evento(
        "pipeline_iniciado",
        "Pipeline ETL iniciado.",
    )

    ok_extract = etapa_extract(registro, entidades)
    if not ok_extract:
        logger.warning("Extract falhou, tentando carregar dados existentes...")
        registro.registrar_evento(
            "extract_com_falhas",
            "Extract retornou falhas e o pipeline seguira com os dados disponiveis.",
            etapa="extract",
        )

    ok_load = etapa_transform_load(registro, entidades)
    if not ok_load:
        logger.error("Transform+Load falhou. Abortando pipeline.")
        registro.registrar_evento(
            "pipeline_abortado",
            "Pipeline abortado por falha definitiva no transform+load.",
            etapa="transform_load",
        )
        registro.salvar()
        return False

    etapa_vetorizacao(registro)

    ok_valid = etapa_validacao(registro)
    if not ok_valid:
        registro.registrar_erro("validacao", "Um ou mais checks de validacao falharam.")

    resultado = registro.salvar()

    logger.info("=" * 60)
    if resultado["sucesso"]:
        logger.info("PIPELINE CONCLUIDO COM SUCESSO em %.1fs", resultado["duracao_total_segundos"])
    else:
        logger.warning("PIPELINE CONCLUIDO COM ERROS em %.1fs", resultado["duracao_total_segundos"])
        for erro in resultado["erros"]:
            logger.warning("  Erro em %s: %s", erro["etapa"], erro["erro"])
    logger.info("=" * 60)

    return resultado["sucesso"]


def agendar(intervalo_horas: int):
    """Roda o pipeline em loop com intervalo definido."""
    logger.info("Pipeline agendado a cada %d horas. Ctrl+C para parar.", intervalo_horas)
    while True:
        pipeline_completo(etapa="full", entidades=["tudo"])
        logger.info("Proxima execucao em %d horas...", intervalo_horas)
        time.sleep(intervalo_horas * 3600)


def main():
    parser = argparse.ArgumentParser(description="Pipeline ETL do Sistema ASG-SP")
    parser.add_argument("--etapa", choices=["extract", "load", "embed", "validate", "full"], default="full",
                        help="Etapa a executar (default: full)")
    parser.add_argument("--entidades", nargs="+", default=["tudo"], help="Entidades para processar")
    parser.add_argument("--agendar", type=int, metavar="HORAS",
                        help="Roda em loop a cada N horas")
    parser.add_argument(
        "--execution-id",
        type=str,
        default=None,
        help="Identificador da execucao para rastreamento de status.",
    )
    
    args = parser.parse_args()

    if args.agendar:
        agendar(args.agendar)
        return

    if args.etapa == "full":
        pipeline_completo(args.etapa, args.entidades, execution_id=args.execution_id)
        return

    registro = RegistroETL(etapa_solicitada=args.etapa, entidades_solicitadas=args.entidades, execution_id=args.execution_id)
    if args.etapa == "extract":
        etapa_extract(registro, args.entidades)
    elif args.etapa == "load":
        etapa_transform_load(registro, args.entidades)
    elif args.etapa == "embed":
        etapa_vetorizacao(registro)
    elif args.etapa == "validate":
        etapa_validacao(registro)
    
    registro.salvar()


if __name__ == "__main__":
    main()
