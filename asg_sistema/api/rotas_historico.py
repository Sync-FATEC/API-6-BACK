"""Rotas de histórico de conversas e mensagens."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from asg_sistema.auth.deps import obter_usuario_atual
from asg_sistema.db.conexao import obter_sessao
from asg_sistema.db.models import Conversa, Mensagem, MensagemDados, Usuario

router = APIRouter()


@router.get("/historico")
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
    return {
        "conversas": [
            {
                "id": c.id,
                "titulo": c.titulo,
                "criado_em": c.criado_em,
                "atualizado_em": c.atualizado_em,
            }
            for c in conversas
        ]
    }


@router.get("/historico/todos")
def listar_todas_conversas(
    db: Session = Depends(obter_sessao),
    usuario: Usuario = Depends(obter_usuario_atual),
):
    if usuario.papel != "ADMIN":
        raise HTTPException(status_code=403, detail="Acesso negado.")

    results = (
        db.query(Conversa, Usuario)
        .join(Usuario, Conversa.usuario_id == Usuario.id)
        .order_by(Conversa.atualizado_em.desc())
        .all()
    )
    return {
        "conversas": [
            {
                "id": c.id,
                "titulo": c.titulo,
                "criado_em": c.criado_em,
                "atualizado_em": c.atualizado_em,
                "usuario": {"id": u.id, "nome": u.nome, "email": u.email},
            }
            for c, u in results
        ]
    }


@router.get("/historico/{conversa_id}")
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

    ids_sistema = [m.id for m in mensagens if m.papel == "sistema"]
    dados_map: dict[int, MensagemDados] = {}
    if ids_sistema:
        for d in db.query(MensagemDados).filter(MensagemDados.mensagem_id.in_(ids_sistema)).all():
            dados_map[d.mensagem_id] = d

    mensagens_out = []
    for m in mensagens:
        item: dict = {
            "id": m.id,
            "papel": m.papel,
            "conteudo_texto": m.conteudo_texto,
            "intencao_detectada": m.intencao_detectada,
            "entidades_json": m.entidades_json,
            "tem_dados_geo": m.tem_dados_geo,
            "criado_em": m.criado_em,
        }
        if m.papel == "sistema" and m.id in dados_map:
            d = dados_map[m.id]
            item["dados"] = {
                "geojson": d.geojson,
                "estatisticas": d.estatisticas,
                "nota_risco": d.nota_risco,
                "grupos": d.grupos,
                "fontes": d.fontes,
            }
        else:
            item["dados"] = None
        mensagens_out.append(item)

    return {
        "id": conversa.id,
        "titulo": conversa.titulo,
        "criado_em": conversa.criado_em,
        "atualizado_em": conversa.atualizado_em,
        "mensagens": mensagens_out,
    }


@router.delete("/historico/{conversa_id}")
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
    return {"ok": True}
