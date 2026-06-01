"""Exige Bearer JWT em rotas /api/v1 exceto prefixo público /api/v1/auth."""

from jose import JWTError
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from asg_sistema.auth import jwt_tokens


def _rota_exige_token(path: str) -> bool:
    """Rotas em /api/v1 que não são de autenticação exigem token válido."""
    if path == "/api/v1" or path.startswith("/api/v1/"):
        return not path.startswith("/api/v1/auth")
    return False


class MiddlewareAutenticacao(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.method == "OPTIONS":
            return await call_next(request)

        path = request.url.path
        if not _rota_exige_token(path):
            return await call_next(request)

        auth = request.headers.get("Authorization")
        if not auth or not auth.lower().startswith("bearer "):
            return JSONResponse(
                status_code=401,
                content={"detail": "Token de autenticação ausente. Use Authorization: Bearer <token>."},
                headers={"WWW-Authenticate": "Bearer"},
            )

        token = auth[7:].strip()
        if not token:
            return JSONResponse(
                status_code=401,
                content={"detail": "Token de autenticação ausente."},
                headers={"WWW-Authenticate": "Bearer"},
            )

        try:
            jwt_tokens.decodificar_token(token)
        except JWTError:
            return JSONResponse(
                status_code=401,
                content={"detail": "Token inválido ou expirado."},
                headers={"WWW-Authenticate": "Bearer"},
            )

        return await call_next(request)
