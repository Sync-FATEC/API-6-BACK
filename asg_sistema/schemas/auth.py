"""Schemas Pydantic para autenticação e alteração de senha."""

from pydantic import BaseModel, EmailStr, Field


class LoginRequest(BaseModel):
    email: EmailStr
    senha: str = Field(min_length=1)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class AlterarSenhaRequest(BaseModel):
    senha_atual: str = Field(min_length=1)
    nova_senha: str = Field(min_length=8, description="Mínimo de 8 caracteres")


class MensagemResponse(BaseModel):
    mensagem: str


class CadastroRequest(BaseModel):
    """Permite criar o primeiro usuário para testes; em produção restrinja ou desative."""

    email: EmailStr
    senha: str = Field(min_length=8)
