"""Autenticação JWT: login, cadastro e alteração da própria senha."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from asg_sistema.auth.deps import obter_usuario_atual
from asg_sistema.auth import jwt_tokens, senha as senha_util
from asg_sistema.db.conexao import obter_sessao
from asg_sistema.db.models import Usuario
from asg_sistema.schemas.auth import (
    AlterarSenhaRequest,
    CadastroRequest,
    LoginRequest,
    MensagemResponse,
    TokenResponse,
)

router = APIRouter(prefix="/auth", tags=["Autenticação"])


@router.post("/cadastro", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
def cadastrar(payload: CadastroRequest, db: Session = Depends(obter_sessao)):
    """Cria usuário e retorna token (útil para desenvolvimento e primeiro acesso)."""
    usuario = Usuario(
        email=payload.email.lower().strip(),
        senha_hash=senha_util.hash_senha(payload.senha),
    )
    db.add(usuario)
    try:
        db.commit()
        db.refresh(usuario)
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="E-mail já cadastrado.",
        ) from None

    token = jwt_tokens.criar_token_acesso(str(usuario.id))
    return TokenResponse(access_token=token)


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, db: Session = Depends(obter_sessao)):
    email = payload.email.lower().strip()
    usuario = db.query(Usuario).filter(Usuario.email == email).first()
    if usuario is None or not senha_util.verificar_senha(payload.senha, usuario.senha_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="E-mail ou senha incorretos.",
        )
    token = jwt_tokens.criar_token_acesso(str(usuario.id))
    return TokenResponse(access_token=token)


@router.post("/alterar-senha", response_model=MensagemResponse)
def alterar_senha(
    payload: AlterarSenhaRequest,
    db: Session = Depends(obter_sessao),
    usuario: Usuario = Depends(obter_usuario_atual),
):
    """
    Altera a senha do usuário autenticado.

    Envie o header `Authorization: Bearer <token>` (obtido em `/auth/login`).
    """
    if not senha_util.verificar_senha(payload.senha_atual, usuario.senha_hash):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Senha atual incorreta.",
        )
    if payload.senha_atual == payload.nova_senha:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A nova senha deve ser diferente da senha atual.",
        )
    usuario.senha_hash = senha_util.hash_senha(payload.nova_senha)
    db.add(usuario)
    db.commit()
    return MensagemResponse(mensagem="Senha alterada com sucesso.")
