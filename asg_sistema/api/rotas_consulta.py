"""Rota principal: consulta em linguagem natural."""

import json
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from asg_sistema.api.esquemas import ConsultaRequest, ConsultaResponse
from asg_sistema.api.rotas_pipeline import pipeline_status
from asg_sistema.auth.deps import obter_usuario_opcional
from asg_sistema.db.conexao import obter_sessao
from asg_sistema.db.models import Conversa, Mensagem, MensagemDados, Usuario

router = APIRouter()

_interpretador = None


def obter_interpretador():
    global _interpretador
    if _interpretador is None:
        from asg_sistema.config import config
        from asg_sistema.pln.preprocessador import PreprocessadorPLN
        from asg_sistema.pln.classificador import ClassificadorIntencao
        from asg_sistema.pln.extrator_caracteristicas import ExtratorCaracteristicas
        from asg_sistema.pln.buscador_semantico import BuscadorSemantico
        from asg_sistema.motor.entidades import ExtratorEntidades
        from asg_sistema.motor.gerador_resposta import GeradorResposta
        from asg_sistema.motor.interpretador import InterpretadorConsulta

        preprocessador = PreprocessadorPLN()

        classificador = ClassificadorIntencao(preprocessador)
        classificador.carregar(config.caminho_modelos)

        extrator = ExtratorCaracteristicas(config.modelo_embeddings)
        _ = extrator.sentence_model

        municipios_path = config.caminho_treinamento / "municipios_sp.json"
        municipios = []
        if municipios_path.exists():
            with open(municipios_path, "r", encoding="utf-8") as f:
                municipios = json.load(f)

        extrator_entidades = ExtratorEntidades(municipios)
        buscador = BuscadorSemantico(extrator)
        gerador = GeradorResposta()

        # Caminho analítico (Text-to-SQL local). Reusa o mesmo ExtratorCaracteristicas.
        from asg_sistema.analitico.linker import SchemaLinker
        from asg_sistema.analitico.slots import ExtratorSlots
        from asg_sistema.analitico.motor import MotorAnalitico
        from asg_sistema.db.conexao import executar_consulta_readonly, explain_readonly

        linker = SchemaLinker(extrator)
        slots = ExtratorSlots(linker=linker, extrator_entidades=extrator_entidades)
        motor_analitico = MotorAnalitico(
            extrator_slots=slots,
            executor=executar_consulta_readonly,
            explain=explain_readonly,
        )

        _interpretador = InterpretadorConsulta(
            preprocessador=preprocessador,
            classificador=classificador,
            extrator_entidades=extrator_entidades,
            buscador=buscador,
            gerador=gerador,
            top_k=config.busca_top_k,
            motor_analitico=motor_analitico,
            roteador_linker=linker,
        )
    return _interpretador


def _serializar(obj):
    """Garante que qualquer objeto seja serializável para JSON antes de salvar."""
    return json.loads(json.dumps(obj, ensure_ascii=False, default=str))


def _salvar_historico(
    db: Session,
    usuario_id: int,
    conversa_id: int | None,
    pergunta: str,
    resposta: dict,
) -> tuple[int, int, datetime, datetime]:
    if conversa_id is not None:
        conversa = (
            db.query(Conversa)
            .filter(Conversa.id == conversa_id, Conversa.usuario_id == usuario_id)
            .first()
        )
        if not conversa:
            conversa_id = None

    if conversa_id is None:
        conversa = Conversa(usuario_id=usuario_id, titulo=pergunta[:100].strip())
        db.add(conversa)
        db.flush()

    msg_usuario = Mensagem(
        conversa_id=conversa.id,
        papel="usuario",
        conteudo_texto=pergunta,
    )
    db.add(msg_usuario)

    geojson = resposta.get("geojson")
    tem_dados_geo = bool(geojson and geojson.get("features"))

    msg_sistema = Mensagem(
        conversa_id=conversa.id,
        papel="sistema",
        conteudo_texto=resposta.get("resumo") or "",
        intencao_detectada=resposta.get("intencao_detectada"),
        entidades_json=_serializar(resposta.get("entidades")) if resposta.get("entidades") else None,
        tem_dados_geo=tem_dados_geo,
    )
    db.add(msg_sistema)
    db.flush()

    dados = MensagemDados(
        mensagem_id=msg_sistema.id,
        geojson=_serializar(geojson) if geojson else None,
        estatisticas=_serializar(resposta.get("estatisticas")) if resposta.get("estatisticas") else None,
        nota_risco=_serializar(resposta.get("nota_risco")) if resposta.get("nota_risco") else None,
        grupos=_serializar(resposta.get("grupos")) if resposta.get("grupos") else None,
        fontes=_serializar(resposta.get("fontes")) if resposta.get("fontes") else None,
    )
    db.add(dados)
    db.commit()
    db.refresh(msg_usuario)
    db.refresh(msg_sistema)

    return conversa.id, msg_sistema.id, msg_usuario.criado_em, msg_sistema.criado_em


class ConsultaAnaliticaRequest(BaseModel):
    pergunta: str


@router.post("/consulta-analitica")
def consulta_analitica(req: ConsultaAnaliticaRequest):
    """Caminho analítico (Text-to-SQL local) isolado, para validação/depuração."""
    motor = obter_interpretador().motor_analitico
    if motor is None:
        return JSONResponse(
            content={"erro": "motor analítico indisponível", "dados": [], "total_resultados": 0},
            media_type="application/json; charset=utf-8",
        )
    resp = motor.consultar(req.pergunta)
    return JSONResponse(
        content=json.loads(json.dumps(resp, ensure_ascii=False, default=str)),
        media_type="application/json; charset=utf-8",
    )


def _carregar_contexto(db: Session, conversa_id: int | None) -> dict | None:
    """Lê o ir_contexto da última resposta do sistema na conversa (p/ follow-up)."""
    if not conversa_id:
        return None
    try:
        msg = (
            db.query(Mensagem)
            .filter(Mensagem.conversa_id == conversa_id, Mensagem.papel == "sistema")
            .order_by(Mensagem.id.desc())
            .first()
        )
        if not msg:
            return None
        dados = db.query(MensagemDados).filter(MensagemDados.mensagem_id == msg.id).first()
        est = (dados.estatisticas if dados else None) or {}
        return est.get("ir_contexto")
    except Exception:
        return None


@router.post("/consulta")
def consultar(
    req: ConsultaRequest,
    db: Session = Depends(obter_sessao),
    usuario: Usuario | None = Depends(obter_usuario_opcional),
):
    if pipeline_status["rodando"]:
        return JSONResponse(
            status_code=503,
            content={},
            media_type="application/json; charset=utf-8",
        )

    try:
        enviada_em = datetime.utcnow()
        interpretador = obter_interpretador()
        contexto = _carregar_contexto(db, req.conversa_id)
        resposta = interpretador.processar(
            req.pergunta, cod_imovel=req.cod_imovel, contexto=contexto,
        )
        recebida_em = datetime.utcnow()

        if usuario is not None:
            conversa_id, mensagem_id, enviada_em, recebida_em = _salvar_historico(
                db=db,
                usuario_id=usuario.id,
                conversa_id=req.conversa_id,
                pergunta=req.pergunta,
                resposta=resposta,
            )
            resposta["conversa_id"] = conversa_id
            resposta["mensagem_id"] = mensagem_id

        resposta["mensagem_enviada_em"] = enviada_em.isoformat()
        resposta["mensagem_recebida_em"] = recebida_em.isoformat()

        return JSONResponse(
            content=json.loads(json.dumps(resposta, ensure_ascii=False, default=str)),
            media_type="application/json; charset=utf-8",
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
