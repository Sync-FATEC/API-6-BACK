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
