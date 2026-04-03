"""Cooldown entre disparos do ETL via POST /api/etl/executar (estado em arquivo em logs/)."""

import time
from pathlib import Path

from fastapi import HTTPException

_marcador: Path | None = None


def _path_marcador() -> Path:
    global _marcador
    if _marcador is None:
        raiz = Path(__file__).resolve().parent.parent.parent
        logs = raiz / "logs"
        logs.mkdir(parents=True, exist_ok=True)
        _marcador = logs / ".etl_api_ultima_chamada"
    return _marcador


def assegurar_cooldown_disparo_etl_api() -> None:
    """Lança HTTP 429 se ainda estiver em cooldown."""
    from asg_sistema.config import config

    limite = config.etl_api_cooldown_segundos
    path = _path_marcador()
    if not path.exists():
        return
    try:
        ultimo = float(path.read_text(encoding="utf-8").strip())
    except (ValueError, OSError):
        return
    decorrido = time.time() - ultimo
    if decorrido < limite:
        restante = max(1, int(limite - decorrido) + 1)
        raise HTTPException(
            status_code=429,
            detail=f"ETL em cooldown. Aguarde {restante}s (intervalo mínimo: {limite}s).",
            headers={"Retry-After": str(restante)},
        )


def registrar_disparo_etl_api() -> None:
    """Grava timestamp após disparo bem-sucedido (subprocess iniciado)."""
    _path_marcador().write_text(str(time.time()), encoding="utf-8")
