from passlib.context import CryptContext

_contexto = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_senha(senha_plana: str) -> str:
    return _contexto.hash(senha_plana)


def verificar_senha(senha_plana: str, senha_hash: str) -> bool:
    return _contexto.verify(senha_plana, senha_hash)
