"""Schemas Pydantic para autenticação e alteração de senha."""

from typing import Literal

from pydantic import BaseModel, EmailStr, Field

PapelUsuario = Literal["ADMIN", "USER"]


class LoginRequest(BaseModel):
    email: EmailStr
    senha: str = Field(min_length=1)


class UsuarioPublico(BaseModel):
    id: int
    nome: str
    cargo: str
    email: str
    papel: PapelUsuario


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    usuario: UsuarioPublico


class AlterarSenhaRequest(BaseModel):
    senha_atual: str = Field(min_length=1)
    nova_senha: str = Field(min_length=8, description="Mínimo de 8 caracteres")


class MensagemResponse(BaseModel):
    mensagem: str


class CadastroRequest(BaseModel):
    """Cadastro de usuário (nome, cargo, e-mail, papel ADMIN ou USER e senha)."""

    nome: str = Field(min_length=1, max_length=255)
    cargo: str = Field(min_length=1, max_length=200)
    email: EmailStr
    senha: str = Field(min_length=8)
    papel: PapelUsuario = "USER"


class EditarUsuarioRequest(BaseModel):
    """Edição de usuário (campos opcionais)."""

    nome: str | None = Field(default=None, min_length=1, max_length=255)
    cargo: str | None = Field(default=None, min_length=1, max_length=200)
    email: EmailStr | None = Field(default=None)
    papel: PapelUsuario | None = Field(default=None)
    nova_senha: str | None = Field(default=None, min_length=8)
