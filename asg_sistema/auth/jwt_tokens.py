from datetime import datetime, timedelta, timezone

from jose import jwt

from asg_sistema.config import config


def criar_token_acesso(usuario_id: int, email: str, papel: str) -> str:
    """Gera JWT (HS256) com identificação do usuário e papel para autorização."""
    agora = datetime.now(timezone.utc)
    expira = agora + timedelta(minutes=config.jwt_expiracao_minutos)
    payload = {
        "sub": str(usuario_id),
        "exp": expira,
        "email": email,
        "papel": papel,
        "typ": "access",
    }
    return jwt.encode(payload, config.jwt_segredo, algorithm=config.jwt_algoritmo)


def decodificar_token(token: str) -> dict:
    return jwt.decode(token, config.jwt_segredo, algorithms=[config.jwt_algoritmo])


def criar_token_reset(email: str) -> str:
    """Gera JWT de redefinição de senha, válido por 15 minutos."""
    agora = datetime.now(timezone.utc)
    payload = {
        "sub": email,
        "exp": agora + timedelta(minutes=15),
        "typ": "reset",
    }
    return jwt.encode(payload, config.jwt_segredo, algorithm=config.jwt_algoritmo)


def decodificar_token_reset(token: str) -> str | None:
    """Decodifica token de reset; retorna o e-mail ou None se inválido/expirado."""
    try:
        payload = jwt.decode(token, config.jwt_segredo, algorithms=[config.jwt_algoritmo])
    except Exception:
        return None
    if payload.get("typ") != "reset":
        return None
    return payload.get("sub")
