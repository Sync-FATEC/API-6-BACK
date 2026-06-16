"""Fallback generativo LOCAL via transformers (lazy). OFF por padrão.

O SQL gerado aqui passa pelo mesmo validador de segurança no MotorAnalitico,
então alucinação de tabela/coluna é barrada antes de executar.
"""

import re

from asg_sistema.config import config
from asg_sistema.analitico.catalogo import CATALOGO_TEXTO


class GeradorLocal:
    def __init__(self, pipeline=None, ativo: bool | None = None, modelo: str | None = None):
        self._pipeline = pipeline
        self._ativo = config.gerador_local_ativo if ativo is None else ativo
        self._modelo = modelo or config.gerador_local_modelo

    @property
    def pipeline(self):
        if self._pipeline is None:
            from transformers import pipeline as hf_pipeline
            self._pipeline = hf_pipeline("text2text-generation", model=self._modelo)
        return self._pipeline

    def gerar(self, pergunta: str) -> str | None:
        if not self._ativo:
            return None
        prompt = (
            "Converta a pergunta em UMA consulta SQL SELECT para PostgreSQL, "
            "usando apenas estas tabelas/colunas:\n"
            f"{CATALOGO_TEXTO}\n"
            f"Pergunta: {pergunta}\nSQL:"
        )
        saida = self.pipeline(prompt, max_new_tokens=160, num_beams=1)
        texto = saida[0].get("generated_text", "") if saida else ""
        m = re.search(r"(select|with)\b.+", texto, re.IGNORECASE | re.DOTALL)
        return m.group(0).strip() if m else (texto.strip() or None)
