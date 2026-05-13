from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError
from sqlalchemy.orm import Session

from asg_sistema.auth import jwt_tokens
from asg_sistema.db.conexao import obter_sessao
from asg_sistema.db.models import Usuario

_esquema_bearer = HTTPBearer(auto_error=False)


def obter_usuario_atual(
    credenciais: HTTPAuthorizationCredentials | None = Depends(_esquema_bearer),
    db: Session = Depends(obter_sessao),
) -> Usuario:
    if credenciais is None or not credenciais.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token de autenticação ausente ou inválido.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    token = credenciais.credentials
    try:
        payload = jwt_tokens.decodificar_token(token)
        sub = payload.get("sub")
        if sub is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token inválido.",
                headers={"WWW-Authenticate": "Bearer"},
            )
        usuario_id = int(sub)
    except (JWTError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token inválido ou expirado.",
            headers={"WWW-Authenticate": "Bearer"},
        ) from None

    usuario = db.query(Usuario).filter(Usuario.id == usuario_id).first()
    if usuario is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Usuário não encontrado.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return usuario
