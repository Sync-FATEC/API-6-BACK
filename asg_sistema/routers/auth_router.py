"""Autenticação JWT: login, cadastro e alteração da própria senha."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from asg_sistema.auth.deps import obter_usuario_atual, exigir_admin
from asg_sistema.auth import jwt_tokens, senha as senha_util
from asg_sistema.auth.email import enviar_email_reset_senha
from asg_sistema.config import config
from asg_sistema.db.conexao import obter_sessao
from asg_sistema.db.models import Usuario
from asg_sistema.schemas.auth import (
    AlterarSenhaRequest,
    CadastroRequest,
    EditarUsuarioRequest,
    EsqueciSenhaRequest,
    LoginRequest,
    LoginResponse,
    MensagemResponse,
    RedefinirSenhaRequest,
    UsuarioPublico,
)

router = APIRouter(prefix="/auth", tags=["Autenticação"])


def _usuario_publico(usuario: Usuario) -> UsuarioPublico:
    return UsuarioPublico.model_validate(
        {
            "id": usuario.id,
            "nome": usuario.nome,
            "cargo": usuario.cargo,
            "email": usuario.email,
            "papel": usuario.papel,
        }
    )

@router.post("/cadastro", response_model=LoginResponse, status_code=status.HTTP_201_CREATED)
def cadastrar(
    payload: CadastroRequest,
    db: Session = Depends(obter_sessao),
    usuario_admin: Usuario = Depends(exigir_admin),
):
    """Cria usuário ADMIN ou USER. Requer usuário ADMIN autenticado."""

    usuario = Usuario(
        nome=payload.nome.strip(),
        cargo=payload.cargo.strip(),
        email=payload.email.lower().strip(),
        senha_hash=senha_util.hash_senha(payload.senha),
        papel=payload.papel,
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

    token = jwt_tokens.criar_token_acesso(usuario.id, usuario.email, usuario.papel)

    return LoginResponse(
        access_token=token,
        usuario=_usuario_publico(usuario),
    )

@router.post("/login", response_model=LoginResponse)
def login(payload: LoginRequest, db: Session = Depends(obter_sessao)):
    """
    Valida e-mail e senha, busca o usuário no banco e retorna um JWT (Bearer) com dados públicos.
    """
    email = payload.email.lower().strip()
    usuario = db.query(Usuario).filter(Usuario.email == email).first()
    if usuario is None or not senha_util.verificar_senha(payload.senha, usuario.senha_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="E-mail ou senha incorretos.",
        )
    token = jwt_tokens.criar_token_acesso(usuario.id, usuario.email, usuario.papel)
    return LoginResponse(
        access_token=token,
        usuario=_usuario_publico(usuario),
    )


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


@router.put("/usuarios/{usuario_id}", response_model=UsuarioPublico)
def editar_usuario(
    usuario_id: int,
    payload: EditarUsuarioRequest,
    db: Session = Depends(obter_sessao),
    usuario_logado: Usuario = Depends(obter_usuario_atual),
):
    """
    Edita um usuário existente.
    - ADMIN pode editar qualquer usuário.
    - USER só pode editar a si mesmo.
    """
    usuario_alvo = db.query(Usuario).filter(Usuario.id == usuario_id).first()
    if usuario_alvo is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Usuário não encontrado.",
        )

    if usuario_logado.papel != "ADMIN" and usuario_logado.id != usuario_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Você só pode editar seu próprio perfil.",
        )

    novo_email = payload.email.lower().strip() if payload.email else None

    if novo_email and novo_email != usuario_alvo.email:
        email_existente = db.query(Usuario).filter(
            Usuario.email == novo_email,
            Usuario.id != usuario_id
        ).first()
        if email_existente:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="E-mail já está em uso por outro usuário.",
            )

    if payload.nome is not None:
        nome_limpo = payload.nome.strip()
        if not nome_limpo:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="O nome não pode ser vazio.",
            )
        usuario_alvo.nome = nome_limpo

    if payload.cargo is not None:
        cargo_limpo = payload.cargo.strip()
        if not cargo_limpo:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="O cargo não pode ser vazio.",
            )
        usuario_alvo.cargo = cargo_limpo

    if novo_email:
        usuario_alvo.email = novo_email

    if payload.papel is not None:
        if payload.papel == "ADMIN" and usuario_logado.papel != "ADMIN":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Apenas administradores podem definir o papel ADMIN.",
            )
        usuario_alvo.papel = payload.papel

    if payload.nova_senha is not None:
        if len(payload.nova_senha) < 8:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="A nova senha deve ter pelo menos 8 caracteres.",
            )
        if senha_util.verificar_senha(payload.nova_senha, usuario_alvo.senha_hash):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="A nova senha deve ser diferente da senha atual.",
            )
        usuario_alvo.senha_hash = senha_util.hash_senha(payload.nova_senha)

    try:
        db.commit()
        db.refresh(usuario_alvo)
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="E-mail já está em uso por outro usuário.",
        ) from None

    return _usuario_publico(usuario_alvo)


@router.get("/usuarios", response_model=list[UsuarioPublico])
def listar_usuarios(
    db: Session = Depends(obter_sessao),
    usuario_admin: Usuario = Depends(exigir_admin),
):
    """
    Lista todos os usuários do sistema.
    - Requer autenticação como ADMIN.
    """
    usuarios = db.query(Usuario).order_by(Usuario.id).all()
    return [_usuario_publico(u) for u in usuarios]


@router.post("/esqueci-senha", response_model=MensagemResponse)
def esqueci_senha(payload: EsqueciSenhaRequest, db: Session = Depends(obter_sessao)):
    """
    Envia link de redefinição de senha por e-mail.
    Sempre retorna sucesso para não revelar se o e-mail está cadastrado.
    """
    email = payload.email.lower().strip()
    usuario = db.query(Usuario).filter(Usuario.email == email).first()

    if usuario:
        token = jwt_tokens.criar_token_reset(email)
        link = f"{config.get_frontend_url()}/redefinir-senha?token={token}"
        try:
            enviar_email_reset_senha(email, link)
        except RuntimeError as e:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=str(e),
            ) from e

    return MensagemResponse(
        mensagem="Se o e-mail estiver cadastrado, você receberá as instruções em breve."
    )


@router.post("/redefinir-senha", response_model=MensagemResponse)
def redefinir_senha(payload: RedefinirSenhaRequest, db: Session = Depends(obter_sessao)):
    """Redefine a senha usando o token recebido por e-mail (válido por 15 minutos)."""
    email = jwt_tokens.decodificar_token_reset(payload.token)
    if email is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Token inválido ou expirado.",
        )

    usuario = db.query(Usuario).filter(Usuario.email == email).first()
    if usuario is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Usuário não encontrado.",
        )

    usuario.senha_hash = senha_util.hash_senha(payload.nova_senha)
    db.add(usuario)
    db.commit()

    return MensagemResponse(mensagem="Senha redefinida com sucesso.")


@router.delete("/usuarios/{usuario_id}", response_model=MensagemResponse)
def excluir_usuario(
    usuario_id: int,
    db: Session = Depends(obter_sessao),
    usuario_admin: Usuario = Depends(exigir_admin),
):
    """
    Exclui um usuário do sistema.
    - Requer autenticação como ADMIN.
    - O ADMIN não pode excluir a si mesmo.
    """

    if usuario_admin.id == usuario_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Você não pode excluir seu próprio usuário.",
        )

    usuario_alvo = db.query(Usuario).filter(Usuario.id == usuario_id).first()

    if usuario_alvo is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Usuário não encontrado.",
        )

    db.delete(usuario_alvo)
    db.commit()

    return MensagemResponse(mensagem="Usuário excluído com sucesso.")