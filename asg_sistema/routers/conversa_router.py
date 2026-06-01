"""Histórico de conversas: CRUD de conversas e lazy-load de dados de mensagem."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from asg_sistema.auth.deps import obter_usuario_atual
from asg_sistema.db.conexao import obter_sessao
from asg_sistema.db.models import Conversa, Mensagem, MensagemDados, Usuario
from asg_sistema.schemas.conversa import (
    ConversaDetalhe,
    ConversaListItem,
    ConversaUpdate,
    MensagemDadosResponse,
    MensagemPreview,
)

router_conversas = APIRouter(prefix="/conversas", tags=["Histórico"])
router_mensagens = APIRouter(prefix="/mensagens", tags=["Histórico"])


@router_conversas.get("/", response_model=list[ConversaListItem])
def listar_conversas(
    db: Session = Depends(obter_sessao),
    usuario: Usuario = Depends(obter_usuario_atual),
):
    conversas = (
        db.query(Conversa)
        .filter(Conversa.usuario_id == usuario.id)
        .order_by(Conversa.atualizado_em.desc())
        .all()
    )
    resultado = []
    for c in conversas:
        total = db.query(Mensagem).filter(Mensagem.conversa_id == c.id).count()
        primeira = (
            db.query(Mensagem)
            .filter(Mensagem.conversa_id == c.id, Mensagem.papel == "usuario")
            .order_by(Mensagem.criado_em.asc())
            .first()
        )
        resultado.append(
            ConversaListItem(
                id=c.id,
                titulo=c.titulo,
                criado_em=c.criado_em,
                atualizado_em=c.atualizado_em,
                total_mensagens=total,
                primeira_mensagem=primeira.conteudo_texto[:150] if primeira else None,
            )
        )
    return resultado


@router_conversas.get("/{conversa_id}", response_model=ConversaDetalhe)
def obter_conversa(
    conversa_id: int,
    db: Session = Depends(obter_sessao),
    usuario: Usuario = Depends(obter_usuario_atual),
):
    conversa = (
        db.query(Conversa)
        .filter(Conversa.id == conversa_id, Conversa.usuario_id == usuario.id)
        .first()
    )
    if not conversa:
        raise HTTPException(status_code=404, detail="Conversa não encontrada.")

    mensagens = (
        db.query(Mensagem)
        .filter(Mensagem.conversa_id == conversa_id)
        .order_by(Mensagem.criado_em.asc())
        .all()
    )
    return ConversaDetalhe(
        id=conversa.id,
        titulo=conversa.titulo,
        criado_em=conversa.criado_em,
        atualizado_em=conversa.atualizado_em,
        mensagens=[
            MensagemPreview(
                id=m.id,
                papel=m.papel,
                conteudo_texto=m.conteudo_texto,
                intencao_detectada=m.intencao_detectada,
                entidades_json=m.entidades_json,
                tem_dados_geo=m.tem_dados_geo,
                criado_em=m.criado_em,
            )
            for m in mensagens
        ],
    )


@router_conversas.patch("/{conversa_id}", response_model=ConversaDetalhe)
def renomear_conversa(
    conversa_id: int,
    payload: ConversaUpdate,
    db: Session = Depends(obter_sessao),
    usuario: Usuario = Depends(obter_usuario_atual),
):
    conversa = (
        db.query(Conversa)
        .filter(Conversa.id == conversa_id, Conversa.usuario_id == usuario.id)
        .first()
    )
    if not conversa:
        raise HTTPException(status_code=404, detail="Conversa não encontrada.")
    conversa.titulo = payload.titulo.strip()
    db.commit()
    return obter_conversa(conversa_id, db, usuario)


@router_conversas.delete("/{conversa_id}", status_code=status.HTTP_204_NO_CONTENT)
def deletar_conversa(
    conversa_id: int,
    db: Session = Depends(obter_sessao),
    usuario: Usuario = Depends(obter_usuario_atual),
):
    conversa = (
        db.query(Conversa)
        .filter(Conversa.id == conversa_id, Conversa.usuario_id == usuario.id)
        .first()
    )
    if not conversa:
        raise HTTPException(status_code=404, detail="Conversa não encontrada.")
    db.delete(conversa)
    db.commit()


@router_mensagens.get("/{mensagem_id}/dados", response_model=MensagemDadosResponse)
def obter_dados_mensagem(
    mensagem_id: int,
    db: Session = Depends(obter_sessao),
    usuario: Usuario = Depends(obter_usuario_atual),
):
    mensagem = db.query(Mensagem).filter(Mensagem.id == mensagem_id).first()
    if not mensagem:
        raise HTTPException(status_code=404, detail="Mensagem não encontrada.")

    # Garante que o usuário é dono da conversa
    conversa = (
        db.query(Conversa)
        .filter(Conversa.id == mensagem.conversa_id, Conversa.usuario_id == usuario.id)
        .first()
    )
    if not conversa:
        raise HTTPException(status_code=403, detail="Acesso negado.")

    dados = db.query(MensagemDados).filter(MensagemDados.mensagem_id == mensagem_id).first()
    if not dados:
        raise HTTPException(status_code=404, detail="Esta mensagem não possui dados geoespaciais.")

    return MensagemDadosResponse(
        mensagem_id=dados.mensagem_id,
        geojson=dados.geojson,
        estatisticas=dados.estatisticas,
        nota_risco=dados.nota_risco,
        grupos=dados.grupos,
        fontes=dados.fontes,
    )
