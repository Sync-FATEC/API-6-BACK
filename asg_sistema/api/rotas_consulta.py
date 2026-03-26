"""Rota principal: consulta em linguagem natural."""

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse

from asg_sistema.api.esquemas import ConsultaRequest, ConsultaResponse

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
        import json

        preprocessador = PreprocessadorPLN()

        classificador = ClassificadorIntencao(preprocessador)
        classificador.carregar(config.caminho_modelos)

        extrator = ExtratorCaracteristicas(config.modelo_embeddings)
        _ = extrator.sentence_model  # força carregamento do modelo BERT no startup

        municipios_path = config.caminho_treinamento / "municipios_sp.json"
        municipios = []
        if municipios_path.exists():
            with open(municipios_path, "r", encoding="utf-8") as f:
                municipios = json.load(f)

        extrator_entidades = ExtratorEntidades(municipios)
        buscador = BuscadorSemantico(extrator)
        gerador = GeradorResposta()

        _interpretador = InterpretadorConsulta(
            preprocessador=preprocessador,
            classificador=classificador,
            extrator_entidades=extrator_entidades,
            buscador=buscador,
            gerador=gerador,
            top_k=config.busca_top_k,
        )
    return _interpretador


@router.post("/consulta")
def consultar(req: ConsultaRequest):
    import json
    try:
        interpretador = obter_interpretador()
        resposta = interpretador.processar(req.pergunta)
        return JSONResponse(
            content=json.loads(json.dumps(resposta, ensure_ascii=False, default=str)),
            media_type="application/json; charset=utf-8",
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
