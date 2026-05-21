"""Configuracao compartilhada de testes.

Define variaveis de ambiente minimas para que `asg_sistema.config` carregue
sem precisar de banco real ou .env populado.
"""

import os

os.environ.setdefault("ASG_JWT_SEGREDO", "test-secret")
