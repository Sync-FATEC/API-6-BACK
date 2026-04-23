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
import subprocess
import sys
import time
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

    def __init__(self, etapa_solicitada: str = "full", entidades_solicitadas: list = None):
        self.inicio = datetime.now()
        self.etapas = []
        self.erros = []
        self.etapa_solicitada = etapa_solicitada
        self.entidades_solicitadas = entidades_solicitadas or ["tudo"]

    def registrar_etapa(self, nome: str, status: str, registros: int = 0, duracao_s: float = 0):
        self.etapas.append({
            "etapa": nome,
            "status": status,
            "registros": registros,
            "duracao_segundos": round(duracao_s, 1),
            "timestamp": datetime.now().isoformat(),
        })

    def registrar_erro(self, etapa: str, erro: str):
        self.erros.append({
            "etapa": etapa, 
            "erro": erro, 
            "timestamp": datetime.now().isoformat()
        })

    def salvar(self):
        historico_path = LOG_DIR / "historico_etl.jsonl"
        execucao_id = self._proximo_id_execucao(historico_path)
        registro = {
            "pipeline": f"ETL ASG-SP #{execucao_id}",
            "execucao_id": execucao_id,
            "inicio": self.inicio.isoformat(),
            "fim": datetime.now().isoformat(),
            "duracao_total_segundos": round((datetime.now() - self.inicio).total_seconds(), 1),
            "etapa_solicitada": self.etapa_solicitada,
            "entidades": self.entidades_solicitadas,
            "etapas": self.etapas,
            "erros": self.erros,
            "sucesso": len(self.erros) == 0,
        }
        with open(historico_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(registro, ensure_ascii=False) + "\n")
        logger.info("Registro salvo em %s", historico_path)
        return registro

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


def etapa_extract(registro: RegistroETL, entidades: list) -> bool:
    """EXTRACT: Coleta dados de todas as fontes publicas."""
    logger.info("=" * 60)
    logger.info(f"ETAPA 1/4: EXTRACT - Coletando dados (Entidades: {entidades})")
    logger.info("=" * 60)
    inicio = time.time()

    try:
        coletor_path = Path(__file__).resolve().parent / "coletor_asg.py"
        
        cmd = [sys.executable, str(coletor_path), "--entidades"] + entidades
        
        resultado = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=900,
        )

        if resultado.returncode != 0:
            logger.error("Coletor finalizou com erro: %s", resultado.stderr[-500:] if resultado.stderr else "sem detalhes")
            registro.registrar_erro("extract", resultado.stderr[-300:] if resultado.stderr else "exit code != 0")
            return False

        duracao = time.time() - inicio
        dados_dir = Path(__file__).resolve().parent.parent / "dados"
        resumo_path = dados_dir / "resumo_coleta.json"
        total_registros = 0
        if resumo_path.exists():
            with open(resumo_path, "r", encoding="utf-8") as f:
                resumo = json.load(f)
            for item in resumo.get("resultados", []):
                total_registros += item.get("registros", 0)

        logger.info("Extract concluido: %d registros coletados em %.1fs", total_registros, duracao)
        registro.registrar_etapa("extract", "sucesso", total_registros, duracao)
        return True

    except subprocess.TimeoutExpired:
        logger.error("Timeout na coleta (limite: 900s)")
        registro.registrar_erro("extract", "timeout 900s")
        return False
    except Exception as e:
        logger.error("Erro no extract: %s", e)
        registro.registrar_erro("extract", str(e))
        return False


def etapa_transform_load(registro: RegistroETL, entidades: list) -> bool:
    """TRANSFORM + LOAD: Textualiza e carrega no PostgreSQL."""
    logger.info("=" * 60)
    logger.info("ETAPA 2/4: TRANSFORM + LOAD - Aplicando UPSERT (inserção e atualização) no banco")
    logger.info("=" * 60)
    inicio = time.time()

    try:
        from asg_sistema.config import config
        from asg_sistema.db.conexao import executar_consulta
        from asg_sistema.ingestao.carregador import carregar_tudo

        logger.info("Atualizando tabelas com registros recentes...")
        
        carregar_tudo(config.caminho_dados, entidades)

        contagens = {}
        for tabela in ["queimadas", "terras_indigenas", "desmatamento_alertas", "unidades_conservacao", "prodes_desmatamento", "comunidades_quilombolas", "sicar_imoveis", "corpus_asg"]:            
            r = executar_consulta(f"SELECT COUNT(*) as total FROM {tabela}")
            contagens[tabela] = r[0]["total"]
            logger.info("  %s: %d registros", tabela, contagens[tabela])

        total = sum(contagens.values())
        duracao = time.time() - inicio
        logger.info("Transform+Load concluido: %d registros totais em %.1fs", total, duracao)
        registro.registrar_etapa("transform_load", "sucesso", total, duracao)
        return True

    except Exception as e:
        logger.error("Erro no transform+load: %s", e)
        registro.registrar_erro("transform_load", str(e))
        return False


def etapa_vetorizacao(registro: RegistroETL) -> bool:
    """EMBED: Gera embeddings para busca semantica via pgvector."""
    logger.info("=" * 60)
    logger.info("ETAPA 3/4: EMBED - Gerando embeddings para busca semantica")
    logger.info("=" * 60)
    inicio = time.time()

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
        registro.registrar_etapa("vetorizacao", "sucesso", total_processado, duracao)
        return True

    except Exception as e:
        logger.error("Erro na vetorizacao: %s", e)
        registro.registrar_erro("vetorizacao", str(e))
        return False


def etapa_validacao(registro: RegistroETL) -> bool:
    """Valida integridade dos dados apos o pipeline."""
    logger.info("=" * 60)
    logger.info("ETAPA 4/4: VALIDACAO - Verificando integridade")
    logger.info("=" * 60)
    inicio = time.time()

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
        registro.registrar_etapa("validacao", "sucesso" if todos_ok else "parcial", 0, duracao)
        return todos_ok

    except Exception as e:
        logger.error("Erro na validacao: %s", e)
        registro.registrar_erro("validacao", str(e))
        return False


def pipeline_completo(etapa: str, entidades: list):
    """Executa o pipeline ETL completo."""
    logger.info("=" * 60)
    logger.info("PIPELINE ETL ASG-SP - Inicio: %s", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    logger.info("=" * 60)

    registro = RegistroETL(etapa_solicitada=etapa, entidades_solicitadas=entidades)

    ok_extract = etapa_extract(registro, entidades)
    if not ok_extract:
        logger.warning("Extract falhou, tentando carregar dados existentes...")

    ok_load = etapa_transform_load(registro, entidades)
    if not ok_load:
        logger.error("Transform+Load falhou. Abortando pipeline.")
        registro.salvar()
        return False

    ok_embed = etapa_vetorizacao(registro)

    ok_valid = etapa_validacao(registro)

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
        pipeline_completo()
        logger.info("Proxima execucao em %d horas...", intervalo_horas)
        time.sleep(intervalo_horas * 3600)


def main():
    parser = argparse.ArgumentParser(description="Pipeline ETL do Sistema ASG-SP")
    parser.add_argument("--etapa", choices=["extract", "load", "embed", "validate", "full"], default="full",
                        help="Etapa a executar (default: full)")
    parser.add_argument("--entidades", nargs="+", default=["tudo"], help="Entidades para processar")
    parser.add_argument("--agendar", type=int, metavar="HORAS",
                        help="Roda em loop a cada N horas")
    
    args = parser.parse_args()

    if args.agendar:
        agendar(args.agendar)
        return

    if args.etapa == "full":
        pipeline_completo(args.etapa, args.entidades)
        return

    registro = RegistroETL(etapa_solicitada=args.etapa, entidades_solicitadas=args.entidades)
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
