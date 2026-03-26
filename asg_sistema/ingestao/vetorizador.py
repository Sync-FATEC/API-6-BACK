"""Gera embeddings para todos os textos do corpus e grava no pgvector."""

import logging

from asg_sistema.db.conexao import executar_sql, executar_consulta
from asg_sistema.pln.extrator_caracteristicas import ExtratorCaracteristicas

logger = logging.getLogger(__name__)


def vetorizar_corpus(extrator: ExtratorCaracteristicas, batch_size: int = 256):
    registros = executar_consulta(
        "SELECT id, texto FROM corpus_asg WHERE embedding IS NULL ORDER BY id"
    )
    total = len(registros)
    logger.info("Vetorizando %d documentos do corpus...", total)

    for i in range(0, total, batch_size):
        lote = registros[i : i + batch_size]
        textos = [r["texto"] for r in lote]
        ids = [r["id"] for r in lote]

        embeddings = extrator.embeddings(textos)

        for doc_id, emb in zip(ids, embeddings):
            vetor_str = "[" + ",".join(str(float(v)) for v in emb) + "]"
            executar_sql(
                "UPDATE corpus_asg SET embedding = :emb WHERE id = :id",
                {"emb": vetor_str, "id": doc_id},
            )

        logger.info("  %d/%d vetorizados", min(i + batch_size, total), total)

    logger.info("Vetorizacao concluida.")
