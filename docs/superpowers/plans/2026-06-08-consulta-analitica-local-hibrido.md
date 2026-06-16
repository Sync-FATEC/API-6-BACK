# Consulta Analítica em Linguagem Natural — Pipeline Híbrida 100% Local (sem API externa)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Permitir que o ASG-SP responda perguntas **analíticas abertas** em português (top-N, somas, contagens, médias, agrupamentos por município/ano/bioma, janelas temporais) gerando SQL `SELECT` somente-leitura — **sem nenhuma API de LLM hospedada** (nada de Anthropic/OpenAI/Gemini). Tudo roda do próprio código com bibliotecas gratuitas já presentes no `requirements.txt`.

**Restrição central (decidida pelo usuário):** nada externo. O "cérebro" é uma **pipeline determinística** com:
- **sentence-transformers** (`paraphrase-multilingual-MiniLM-L12-v2`) → embeddings do transformer (já usado no projeto via `ExtratorCaracteristicas`) para **schema linking**;
- **spaCy** (`pt_core_news_md`, word2vec) → estrutura sintática (núcleo nominal, dependências) e similaridade lexical;
- **scikit-learn** → similaridade de cosseno;
- **RapidFuzz + Unidecode** → correção ortográfica e **value linking** (município, enums) tolerante a acento.

**Hardware-alvo (decidido):** máquina modesta. Logo, o **construtor determinístico é o caminho principal** (rápido, sem modelo pesado). Um **modelo generativo local pequeno** (via `transformers`, já instalado) fica como **fallback opcional, lazy e DESLIGADO por padrão** — para a cauda longa que o construtor não cobrir. Em máquina modesta o sistema roda 100% determinístico.

**Architecture (híbrida):**

```
pergunta
  → normalização (normalizar_pergunta — já existe) + correção ortográfica (RapidFuzz+Unidecode)
  → ROTEADOR (heurística + embeddings, sem rede):
        cod_imovel/CAR presente ............................→ ESPACIAL  (fluxo atual: CAR/AHP)
        sinais de agregação/ranking (regex + cosseno) ......→ ANALÍTICA (caminho NOVO)
        senão ..............................................→ DESCRITIVA (fluxo atual: NB + busca vetorial)

  [ANALÍTICA] pipeline Text-to-SQL LOCAL:
   1. EXTRAÇÃO DE SLOTS → Representação Intermediária (IR `ConsultaAnalitica`):
        · tabela base ....... schema linking por embeddings (MiniLM, reuso de ExtratorCaracteristicas)
        · métrica ........... COUNT | SUM(col) | AVG(col)  (embeddings + spaCy md p/ núcleo nominal)
        · dimensões ......... GROUP BY municipio|ano|mes|bioma|classe  (regex "por X" + embeddings)
        · filtros ........... município (RapidFuzz+Unidecode), período (datas ISO), enum status  ← reuso ExtratorEntidades
        · ordem + limite .... "top N", "mais/maiores"→DESC, "menos/menores"→ASC  (regex)
        · confiança ......... score combinado dos linkings
   2. CONSTRUTOR DETERMINÍSTICO  (IR → SELECT … GROUP BY … ORDER BY … LIMIT)    ← caminho principal
   3. FALLBACK GENERATIVO LOCAL  (só se confiança < limiar E habilitado)  ← transformers, lazy, OFF por padrão
   4. VALIDADOR (sqlglot): único SELECT + allowlist de tabelas/colunas + LIMIT  ← cinturão de segurança
   5. EXECUÇÃO read-only (statement_timeout + rollback)                          ← cinturão de segurança
   6. RENDERIZAÇÃO determinística → dict no contrato ConsultaResponse (resumo + dados + estatisticas + geojson)
```

**Princípio de "semantic parsing":** pergunta → **IR** (struct) → SQL. A IR torna tudo testável sem DB e à prova de erro para os padrões enumerados; o modelo generativo só entra na cauda longa.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2 + PostgreSQL/PostGIS. Novas libs: `sqlglot`, `rapidfuzz`, `Unidecode` (todas gratuitas e leves). spaCy `pt_core_news_md`. `torch`+`transformers` já presentes (fallback opcional). Reuso de `ExtratorCaracteristicas`, `ExtratorEntidades`, `normalizar_pergunta`.

---

## Realidades do código real (verificadas antes de planejar)

Repo real: `c:\Users\User\Desktop\Projetos\API\API-6-BACK`. Fatos que moldam o plano:

1. **Entrypoint:** [asg_sistema/motor/interpretador.py](../../asg_sistema/motor/interpretador.py) → classe **`InterpretadorConsulta`** (não "Interpretador"), método `processar(self, pergunta, cod_imovel=None) -> dict`. Retorna **dict**. O roteador entra no topo de `processar`.
2. **Contrato de resposta:** [asg_sistema/api/esquemas.py](../../asg_sistema/api/esquemas.py) `ConsultaResponse` e `_salvar_historico` em [rotas_consulta.py](../../asg_sistema/api/rotas_consulta.py) leem via `.get`: `resumo` (str), `estatisticas` (dict), `dados` (list[dict]), `fontes` (list[dict]), `geojson` (dict|None com `features`), `intencao_detectada` (str), `entidades` (dict), `nota_risco`, `grupos`, `total_resultados`, `tempo_processamento_ms`. O caminho analítico devolve um dict com essas chaves.
3. **Embeddings já prontos:** [pln/extrator_caracteristicas.py](../../asg_sistema/pln/extrator_caracteristicas.py) `ExtratorCaracteristicas` carrega `paraphrase-multilingual-MiniLM-L12-v2` (lazy) e expõe `embeddings(list)` e `embedding_unico(str)`. **Reusar para schema linking.**
4. **Value linking já existe:** [motor/entidades.py](../../asg_sistema/motor/entidades.py) `ExtratorEntidades(municipios)` → `extrair(texto)` devolve `municipios`, `periodo` (`inicio`/`fim` ISO), `status` (AT/PE/SU/CA), `cod_imovel`, `codigos_car`. Hoje usa `difflib.SequenceMatcher`; vamos **trocar por RapidFuzz+Unidecode** (mais rápido/robusto, e é o que o usuário usa).
5. **spaCy sem vetores:** `config.modelo_spacy = "pt_core_news_sm"` (sem word2vec). Para vetores → `pt_core_news_md`.
6. **DB layer:** [db/conexao.py](../../asg_sistema/db/conexao.py) tem `engine` global e `executar_consulta` que faz **commit**. Para SQL gerado precisamos de caminho **read-only** separado (timeout + rollback).
7. **Config singleton:** `from asg_sistema.config import config`; `env_prefix="ASG_"`; `caminho_treinamento` → `dados_treinamento/`.
8. **Singleton do interpretador:** `obter_interpretador()` em [rotas_consulta.py](../../asg_sistema/api/rotas_consulta.py) — ponto de injeção dos novos componentes.
9. **Repo não é git ainda** (Task 0 inicializa).

---

## File Structure

Novo pacote `asg_sistema/analitico/`:

| Arquivo | Responsabilidade |
|---|---|
| `analitico/__init__.py` | pacote |
| `analitico/catalogo.py` | catálogo curado: `TABELAS_PERMITIDAS`/`VIEWS_PERMITIDAS` (allowlist), `CATALOGO_TEXTO` (p/ fallback generativo) e `CATALOGO_SEMANTICO` (frases-âncora p/ schema linking por embedding) |
| `analitico/ir.py` | dataclass `ConsultaAnalitica` (IR): `tabela`, `metrica`, `dimensoes`, `filtros`, `ordem`, `limite`, `confianca` |
| `analitico/texto.py` | correção ortográfica/normalização (RapidFuzz+Unidecode) — helpers reutilizados |
| `analitico/linker.py` | schema linking por embeddings (MiniLM) + cosseno (sklearn): casa pergunta→tabela/métrica/dimensão |
| `analitico/slots.py` | `ExtratorSlots`: combina linker + spaCy md + regex + `ExtratorEntidades` → produz a IR com confiança |
| `analitico/construtor_sql.py` | IR → SQL determinístico (SELECT/GROUP BY/ORDER BY/LIMIT/WHERE) |
| `analitico/validador_sql.py` | `validar_sql()` via sqlglot: único SELECT + allowlist + LIMIT |
| `analitico/gerador_local.py` | fallback generativo opcional (transformers, lazy, OFF por padrão) |
| `analitico/renderizador.py` | IR+linhas → dict no contrato ConsultaResponse (resumo determinístico + geojson) |
| `analitico/roteador.py` | `rotear()` → `ANALITICA \| DESCRITIVA \| ESPACIAL` |
| `analitico/motor.py` | orquestrador: slots → construir/fallback → validar → explain → executar → renderizar |
| `db/schema_views.sql` | views da camada semântica |
| `db/role_readonly.sql` | role `asg_readonly` (GRANT SELECT) |
| `dados_treinamento/golden_analitico.json` | conjunto de avaliação |

Arquivos modificados:

| Arquivo | Mudança |
|---|---|
| `requirements.txt` | `+ sqlglot`, `+ rapidfuzz`, `+ Unidecode`; trocar wheel spaCy `sm`→`md` |
| `asg_sistema/config.py` | `+` flags analíticas/read-only/fallback; `modelo_spacy` default `pt_core_news_md` |
| `asg_sistema/db/conexao.py` | `+ executar_consulta_readonly()`, `+ explain_readonly()` |
| `asg_sistema/motor/entidades.py` | trocar `difflib` por RapidFuzz+Unidecode (mantendo a API) |
| `asg_sistema/motor/interpretador.py` | injetar `roteador`/`motor_analitico` opcionais no `__init__`; rotear no topo de `processar` |
| `asg_sistema/api/rotas_consulta.py` | montar componentes analíticos no `obter_interpretador()`; endpoint isolado `POST /consulta-analitica` (Fase 3) |

Testes (pytest, `tests/` plano — convenção do repo; **sem DB em unit**):

| Arquivo | Tipo | DB? |
|---|---|---|
| `tests/test_config_analitico.py` | unit | não |
| `tests/test_conexao_readonly.py` | unit (engine fake) | não |
| `tests/test_texto_fuzzy.py` | unit | não |
| `tests/test_catalogo_analitico.py` | unit | não |
| `tests/test_linker.py` | unit (usa MiniLM real, sem rede) | não |
| `tests/test_slots.py` | unit | não |
| `tests/test_construtor_sql.py` | unit | não |
| `tests/test_validador_sql.py` | unit | não |
| `tests/test_seguranca_sql.py` | unit (adversarial) | não |
| `tests/test_renderizador_analitico.py` | unit | não |
| `tests/test_roteador_analitico.py` | unit | não |
| `tests/test_motor_analitico.py` | unit (fakes) | não |
| `tests/test_interpretador_roteamento.py` | unit | não |
| `tests/integration/test_analitico_exec.py` | integração (golden set) | **sim** (skip sem `ASG_DB_INTEGRACAO=1`) |

> Nota: `test_linker.py` carrega o modelo MiniLM já baixado (offline). Se o CI não tiver o modelo em cache, marque-o com `@pytest.mark.modelo` e pule quando ausente — decida no Step de implementação.

---

## Convenções deste plano

- Rode testes com `python -m pytest <arquivo>::<classe>::<teste> -v` a partir de `c:\Users\User\Desktop\Projetos\API\API-6-BACK`.
- Commits frequentes no padrão do repo (`feat:`/`test:`/`chore:`), terminando com a linha `Co-Authored-By` exigida.
- Não tocar nos caminhos existentes (busca vetorial, CAR/AHP) até a Fase 4.
- Idioma de código/identificadores: português (segue o repo).
- **Sem dependência de rede em runtime**: tudo roda local. Modelos (MiniLM, spaCy md, e o opcional text2sql) são baixados uma vez e ficam em cache local.

---

## Fase 0 — Infraestrutura

### Task 0: Inicializar git

- [ ] **Step 1:** `git -C "c:/Users/User/Desktop/Projetos/API/API-6-BACK" init` (pula se já for repo).
- [ ] **Step 2:** Garantir `.gitignore` cobrindo `__pycache__/`, `.env`, `*.pyc`, `.pytest_cache/`, `modelos_salvos/` (se grande).
- [ ] **Step 3:** Commit baseline:
```bash
git add -A
git commit -m "chore: baseline before analytical text-to-sql

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 1: Dependências (gratuitas/locais)

**Files:** Modify `requirements.txt`

- [ ] **Step 1: Adicionar libs**

Acrescente:
```
sqlglot>=25.0.0
rapidfuzz>=3.9.0
Unidecode>=1.3.8
```

E troque o wheel do spaCy de `pt_core_news_sm` para `pt_core_news_md` (linha 61 do requirements). A URL do md é:
`https://github.com/explosion/spacy-models/releases/download/pt_core_news_md-3.8.0/pt_core_news_md-3.8.0-py3-none-any.whl`
> Mantenha o `sm` também se outras partes dependerem dele; o `md` é o que tem vetores. Confirme a versão 3.8.0 compatível com `spacy==3.8.14`.

- [ ] **Step 2: Instalar**

Run: `python -m pip install "sqlglot>=25.0.0" "rapidfuzz>=3.9.0" "Unidecode>=1.3.8"`
Run: `python -m spacy download pt_core_news_md`
Expected: instalações concluídas.

- [ ] **Step 3: Verificar imports e vetores**

Run: `python -c "import sqlglot, rapidfuzz, unidecode; import spacy; nlp=spacy.load('pt_core_news_md'); print(sqlglot.__version__, rapidfuzz.__version__, nlp('desmatamento').vector_norm>0)"`
Expected: versões + `True` (vetores presentes no md).

- [ ] **Step 4: Commit**
```bash
git add requirements.txt
git commit -m "chore: add sqlglot/rapidfuzz/unidecode and spaCy md model for analytical path"
```

---

### Task 2: Configuração (`config.py`)

**Files:** Modify `asg_sistema/config.py`; Test `tests/test_config_analitico.py`

- [ ] **Step 1: Teste falho** — crie `tests/test_config_analitico.py`:

```python
import os
os.environ.setdefault("ASG_JWT_SEGREDO", "test-secret")
from asg_sistema.config import Configuracao


class TestConfigAnalitico:
    def test_defaults(self):
        cfg = Configuracao()
        assert cfg.modelo_spacy == "pt_core_news_md"      # agora com vetores
        assert cfg.sql_timeout_ms == 5000
        assert cfg.sql_max_limit == 100
        assert cfg.analitico_confianca_minima == 0.55
        assert cfg.gerador_local_ativo is False           # OFF por padrão (máquina modesta)
        assert cfg.usuario_ro == cfg.db_usuario           # cai p/ credencial principal

    def test_db_url_readonly(self):
        cfg = Configuracao(db_usuario_ro="asg_readonly", db_senha_ro="ro")
        assert "asg_readonly:ro@" in cfg.db_url_readonly
        assert cfg.db_url_readonly.startswith("postgresql://")
```

- [ ] **Step 2:** `python -m pytest tests/test_config_analitico.py -v` → FAIL.

- [ ] **Step 3: Implementar** — em `Configuracao`:
  - Trocar `modelo_spacy: str = "pt_core_news_sm"` → `"pt_core_news_md"`.
  - Após o bloco de e-mail (ou junto dos demais campos) adicionar:

```python
    # ---- Caminho analítico (Text-to-SQL local) ----
    sql_timeout_ms: int = 5000
    sql_max_limit: int = 100
    analitico_confianca_minima: float = 0.55
    # Fallback generativo local (transformers). OFF por padrão (máquina modesta).
    gerador_local_ativo: bool = False
    gerador_local_modelo: str = "cssupport/t5-small-awesome-text-to-sql"
    # Credenciais read-only (caem p/ as principais quando ausentes)
    db_usuario_ro: str | None = None
    db_senha_ro: str | None = None
```

  - Após a property `db_url`, adicionar:

```python
    @property
    def usuario_ro(self) -> str:
        return self.db_usuario_ro or self.db_usuario

    @property
    def senha_ro(self) -> str:
        return self.db_senha_ro or self.db_senha

    @property
    def db_url_readonly(self) -> str:
        return (
            f"postgresql://{self.usuario_ro}:{self.senha_ro}"
            f"@{self.db_host}:{self.db_port}/{self.db_nome}"
            f"?client_encoding=utf8"
        )
```

- [ ] **Step 4:** `python -m pytest tests/test_config_analitico.py -v` → PASS.

> ⚠️ Trocar `modelo_spacy` para `md` pode afetar quem chama `spacy.load(config.modelo_spacy)`. O `preprocessador.py` hoje faz `spacy.load("pt_core_news_sm")` **hardcoded** — não usa o config, então não quebra. Mas confirme com `grep` se algo carrega `config.modelo_spacy` e teste que ainda funciona.

- [ ] **Step 5: Commit**
```bash
git add asg_sistema/config.py tests/test_config_analitico.py
git commit -m "feat: add analytical/readonly config and switch spaCy to md (vectors)"
```

---

### Task 3: SQL — views e role read-only

**Files:** Create `asg_sistema/db/schema_views.sql`, `asg_sistema/db/role_readonly.sql`

> DDL idempotente. Sem teste unit (depende de DB); exercitado na integração (Fase 6). **Confira colunas contra [db/schema.sql](../../asg_sistema/db/schema.sql).**

- [ ] **Step 1:** Criar `asg_sistema/db/schema_views.sql`:

```sql
-- Camada semântica: views que pré-resolvem agregações comuns.
CREATE OR REPLACE VIEW vw_desmatamento_municipio AS
  SELECT municipio,
         EXTRACT(YEAR  FROM data_avistamento)::int AS ano,
         EXTRACT(MONTH FROM data_avistamento)::int AS mes,
         COUNT(*)            AS qtd_alertas,
         SUM(area_total_km2) AS area_km2
  FROM desmatamento_alertas
  WHERE data_avistamento IS NOT NULL
  GROUP BY municipio, ano, mes;

CREATE OR REPLACE VIEW vw_queimadas_municipio AS
  SELECT municipio,
         EXTRACT(YEAR  FROM data_hora)::int AS ano,
         EXTRACT(MONTH FROM data_hora)::int AS mes,
         COUNT(*)        AS qtd_focos,
         AVG(frp)        AS frp_medio,
         AVG(risco_fogo) AS risco_fogo_medio
  FROM queimadas
  WHERE data_hora IS NOT NULL
  GROUP BY municipio, ano, mes;

CREATE OR REPLACE VIEW vw_prodes_ano AS
  SELECT ano, classe_nome,
         SUM(area_km) AS area_km2,
         COUNT(*)     AS qtd_poligonos
  FROM prodes_desmatamento
  GROUP BY ano, classe_nome;
```

- [ ] **Step 2:** Criar `asg_sistema/db/role_readonly.sql`:

```sql
-- Role somente-leitura p/ execução de SQL gerado. Troque a senha antes de aplicar.
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'asg_readonly') THEN
    CREATE ROLE asg_readonly LOGIN PASSWORD 'troque_esta_senha';
  END IF;
END $$;

GRANT CONNECT ON DATABASE asg_sp TO asg_readonly;   -- nome do db conforme config (asg_sp)
GRANT USAGE ON SCHEMA public TO asg_readonly;

GRANT SELECT ON
  queimadas, desmatamento_alertas, prodes_desmatamento, sicar_imoveis,
  terras_indigenas, unidades_conservacao, comunidades_quilombolas, fontes,
  vw_desmatamento_municipio, vw_queimadas_municipio, vw_prodes_ano
TO asg_readonly;

ALTER ROLE asg_readonly SET default_transaction_read_only = on;
ALTER ROLE asg_readonly SET statement_timeout = '5s';
```

- [ ] **Step 3 (opcional, requer DB):** aplicar via `psql -f`. Pode adiar p/ deploy.
- [ ] **Step 4: Commit**
```bash
git add asg_sistema/db/schema_views.sql asg_sistema/db/role_readonly.sql
git commit -m "feat: add semantic views and read-only db role"
```

---

### Task 4: Execução read-only (`conexao.py`)

**Files:** Modify `asg_sistema/db/conexao.py`; Test `tests/test_conexao_readonly.py`

> `text` e `create_engine` já estão importados em conexao.py. Teste unit com engine fake (sem DB).

- [ ] **Step 1: Teste falho** — crie `tests/test_conexao_readonly.py`:

```python
import os
os.environ.setdefault("ASG_JWT_SEGREDO", "test-secret")
import asg_sistema.db.conexao as conexao


class _Res:
    def keys(self): return ["municipio", "total"]
    def fetchall(self): return [("Bauru", 3)]

class _Trans:
    def __init__(self, log): self.log = log
    def rollback(self): self.log.append("ROLLBACK")
    def commit(self): self.log.append("COMMIT")

class _Conn:
    def __init__(self, log): self.log = log
    def execute(self, stmt, params=None): self.log.append(str(stmt)); return _Res()
    def begin(self): self.log.append("BEGIN"); return _Trans(self.log)
    def __enter__(self): return self
    def __exit__(self, *a): return False

class _Engine:
    def __init__(self, log): self.log = log
    def connect(self): return _Conn(self.log)


class TestReadonly:
    def test_retorna_dicts(self, monkeypatch):
        log = []
        monkeypatch.setattr(conexao, "_ro_engine", _Engine(log))
        assert conexao.executar_consulta_readonly("SELECT municipio, COUNT(*) total FROM queimadas GROUP BY municipio") \
            == [{"municipio": "Bauru", "total": 3}]

    def test_timeout_readonly_rollback(self, monkeypatch):
        log = []
        monkeypatch.setattr(conexao, "_ro_engine", _Engine(log))
        conexao.executar_consulta_readonly("SELECT 1", timeout_ms=7000)
        j = " | ".join(log)
        assert "statement_timeout = 7000" in j
        assert "TRANSACTION READ ONLY" in j
        assert "ROLLBACK" in j and "COMMIT" not in j
```

- [ ] **Step 2:** `python -m pytest tests/test_conexao_readonly.py -v` → FAIL.

- [ ] **Step 3: Implementar** — após `SessionLocal` em conexao.py:

```python
_ro_engine = create_engine(
    config.db_url_readonly.replace("postgresql://", "postgresql+psycopg2://"),
    echo=False, pool_pre_ping=True,
)
```

E ao final do arquivo:

```python
def executar_consulta_readonly(sql: str, params: dict | None = None,
                               timeout_ms: int | None = None) -> list[dict]:
    """Executa SELECT já validado em transação READ ONLY com timeout, sem persistir."""
    timeout_ms = int(timeout_ms or config.sql_timeout_ms)
    with _ro_engine.connect() as conn:
        trans = conn.begin()
        try:
            conn.execute(text(f"SET LOCAL statement_timeout = {timeout_ms}"))
            conn.execute(text("SET TRANSACTION READ ONLY"))
            res = conn.execute(text(sql), params or {})
            cols = list(res.keys())
            return [dict(zip(cols, row)) for row in res.fetchall()]
        finally:
            trans.rollback()


def explain_readonly(sql: str, params: dict | None = None) -> str | None:
    """EXPLAIN sem executar. None se OK; senão a mensagem de erro do Postgres."""
    from sqlalchemy.exc import SQLAlchemyError
    with _ro_engine.connect() as conn:
        trans = conn.begin()
        try:
            conn.execute(text("SET TRANSACTION READ ONLY"))
            conn.execute(text(f"EXPLAIN {sql}"), params or {})
            return None
        except SQLAlchemyError as e:
            return str(getattr(e, "orig", e))
        finally:
            trans.rollback()
```

- [ ] **Step 4:** `python -m pytest tests/test_conexao_readonly.py -v` → PASS.
- [ ] **Step 5: Commit**
```bash
git add asg_sistema/db/conexao.py tests/test_conexao_readonly.py
git commit -m "feat: add read-only sql execution with timeout and rollback"
```

---

## Fase 1 — NLU core: catálogo, IR, value-linking, schema-linking e slots

Meta: transformar uma pergunta em uma **IR `ConsultaAnalitica`** confiável, tudo testável sem DB e sem rede (além do modelo local já em cache).

### Task 5: Catálogo + allowlist + catálogo semântico (`catalogo.py`)

**Files:** Create `asg_sistema/analitico/__init__.py`, `asg_sistema/analitico/catalogo.py`; Test `tests/test_catalogo_analitico.py`

- [ ] **Step 1:** Criar `asg_sistema/analitico/__init__.py` vazio.

- [ ] **Step 2: Teste falho** — `tests/test_catalogo_analitico.py`:

```python
from asg_sistema.analitico import catalogo


class TestAllowlist:
    def test_tabelas_e_internas(self):
        for t in ("queimadas", "desmatamento_alertas", "prodes_desmatamento", "sicar_imoveis"):
            assert t in catalogo.TABELAS_PERMITIDAS
        for p in ("corpus_asg", "usuarios", "conversas", "mensagens"):
            assert p not in catalogo.TABELAS_PERMITIDAS and p not in catalogo.VIEWS_PERMITIDAS

    def test_colunas(self):
        assert "data_hora" in catalogo.TABELAS_PERMITIDAS["queimadas"]
        assert "area_total_km2" in catalogo.TABELAS_PERMITIDAS["desmatamento_alertas"]
        assert "area_km" in catalogo.TABELAS_PERMITIDAS["prodes_desmatamento"]

    def test_nomes_permitidos(self):
        n = catalogo.nomes_permitidos()
        assert "queimadas" in n and "vw_prodes_ano" in n


class TestCatalogoSemantico:
    def test_estrutura(self):
        # cada entrada liga uma frase-âncora a um alvo (tabela/métrica/dimensão)
        ancoras = catalogo.CATALOGO_SEMANTICO
        assert any(a["tipo"] == "tabela" and a["alvo"] == "queimadas" for a in ancoras)
        assert any(a["tipo"] == "metrica" for a in ancoras)
        assert all({"frase", "tipo", "alvo"} <= set(a) for a in ancoras)
```

- [ ] **Step 3:** FAIL.

- [ ] **Step 4: Implementar** `asg_sistema/analitico/catalogo.py`. Inclui: (a) allowlist tabela→colunas, (b) views, (c) `CATALOGO_TEXTO` (para o fallback generativo), (d) **`CATALOGO_SEMANTICO`** — lista de frases-âncora em PT que o linker embeda para casar a pergunta. Conferir colunas com `schema.sql`.

```python
"""Catálogo curado: allowlist (segurança), texto (fallback generativo) e
frases-âncora semânticas (schema linking por embedding)."""

TABELAS_PERMITIDAS: dict[str, set[str]] = {
    "queimadas": {"id","municipio","estado","data_hora","satelite","bioma","frp","risco_fogo","precipitacao","latitude","longitude","geom"},
    "desmatamento_alertas": {"id","classe","municipio","uf","data_avistamento","sensor","satelite","area_total_km2","area_uc_km2","nome_uc","geom"},
    "prodes_desmatamento": {"id","uid","estado","classe_principal","classe_nome","data_imagem","ano","area_km","fonte_bioma","satelite","sensor","geom"},
    "sicar_imoveis": {"id","cod_imovel","cod_tema","nom_tema","ind_status","ind_tipo","des_condic","municipio","cod_estado","num_area","mod_fiscal","dat_criacao","dat_atualizacao","geom"},
    "terras_indigenas": {"id","codigo","nome","etnia","municipio","uf","area_ha","fase","modalidade","geom"},
    "unidades_conservacao": {"id","nome","categoria","grupo","esfera","uf","municipio","area_ha","situacao","geom"},
    "comunidades_quilombolas": {"id","municipio","uf","comunidade","codigo_ibge","processo_fcp","ano_certificacao","processo_incra","regiao","geom"},
    "fontes": {"id","nome","descricao","url_origem","data_coleta","total_registros","escopo"},
}

VIEWS_PERMITIDAS: dict[str, set[str]] = {
    "vw_desmatamento_municipio": {"municipio","ano","mes","qtd_alertas","area_km2"},
    "vw_queimadas_municipio": {"municipio","ano","mes","qtd_focos","frp_medio","risco_fogo_medio"},
    "vw_prodes_ano": {"ano","classe_nome","area_km2","qtd_poligonos"},
}

# Métricas conhecidas por tabela: nome lógico -> (agregação, coluna|None)
METRICAS: dict[str, dict[str, tuple[str, str | None]]] = {
    "queimadas": {"focos": ("COUNT", None), "frp_medio": ("AVG", "frp"), "risco_medio": ("AVG", "risco_fogo")},
    "desmatamento_alertas": {"alertas": ("COUNT", None), "area": ("SUM", "area_total_km2")},
    "prodes_desmatamento": {"area": ("SUM", "area_km"), "poligonos": ("COUNT", None)},
    "sicar_imoveis": {"imoveis": ("COUNT", None), "area": ("SUM", "num_area")},
}

# Dimensões de agrupamento por tabela: nome lógico -> expressão SQL
DIMENSOES: dict[str, dict[str, str]] = {
    "queimadas": {"municipio": "municipio", "bioma": "bioma",
                  "ano": "EXTRACT(YEAR FROM data_hora)::int", "mes": "EXTRACT(MONTH FROM data_hora)::int"},
    "desmatamento_alertas": {"municipio": "municipio", "classe": "classe",
                             "ano": "EXTRACT(YEAR FROM data_avistamento)::int"},
    "prodes_desmatamento": {"ano": "ano", "classe": "classe_nome", "estado": "estado"},
    "sicar_imoveis": {"municipio": "municipio", "status": "ind_status"},
}


def nomes_permitidos() -> set[str]:
    return set(TABELAS_PERMITIDAS) | set(VIEWS_PERMITIDAS)

def colunas_de(nome: str) -> set[str]:
    return TABELAS_PERMITIDAS.get(nome) or VIEWS_PERMITIDAS.get(nome) or set()

def todas_as_colunas() -> set[str]:
    cols: set[str] = set()
    for c in list(TABELAS_PERMITIDAS.values()) + list(VIEWS_PERMITIDAS.values()):
        cols |= c
    return cols


# Frases-âncora em PT-BR para schema linking por embedding (MiniLM).
CATALOGO_SEMANTICO: list[dict] = [
    # tabela base
    {"frase": "queimadas focos de calor incêndio fogo", "tipo": "tabela", "alvo": "queimadas"},
    {"frase": "desmatamento alertas deter supressão de vegetação", "tipo": "tabela", "alvo": "desmatamento_alertas"},
    {"frase": "desmatamento consolidado anual prodes área desmatada por ano", "tipo": "tabela", "alvo": "prodes_desmatamento"},
    {"frase": "imóveis rurais fazendas car sicar propriedades", "tipo": "tabela", "alvo": "sicar_imoveis"},
    # métricas
    {"frase": "quantidade contagem número de ocorrências quantos", "tipo": "metrica", "alvo": "COUNT"},
    {"frase": "área total somatório soma de área km²", "tipo": "metrica", "alvo": "SUM"},
    {"frase": "média valor médio", "tipo": "metrica", "alvo": "AVG"},
    # dimensões
    {"frase": "por município por cidade cidades", "tipo": "dimensao", "alvo": "municipio"},
    {"frase": "por ano anual ao longo dos anos", "tipo": "dimensao", "alvo": "ano"},
    {"frase": "por mês mensal", "tipo": "dimensao", "alvo": "mes"},
    {"frase": "por bioma", "tipo": "dimensao", "alvo": "bioma"},
    {"frase": "por classe tipo categoria", "tipo": "dimensao", "alvo": "classe"},
]

CATALOGO_TEXTO = """\
TABELA queimadas (municipio, estado, data_hora TIMESTAMP, bioma, frp NUMERIC, risco_fogo NUMERIC, geom)
TABELA desmatamento_alertas (municipio, classe, data_avistamento DATE, area_total_km2 NUMERIC, geom)
TABELA prodes_desmatamento (estado, ano INT, area_km NUMERIC, classe_nome, geom)
TABELA sicar_imoveis (cod_imovel, municipio, num_area NUMERIC ha, ind_status AT|PE|SU|CA, mod_fiscal, geom)
VIEW vw_desmatamento_municipio (municipio, ano, mes, qtd_alertas, area_km2)
VIEW vw_queimadas_municipio (municipio, ano, mes, qtd_focos, frp_medio, risco_fogo_medio)
VIEW vw_prodes_ano (ano, classe_nome, area_km2, qtd_poligonos)
"""
```

- [ ] **Step 5:** PASS. **Step 6: Commit** `feat: add analytical catalog (allowlist + semantic anchors + metrics/dimensions)`.

---

### Task 6: Representação Intermediária (`ir.py`)

**Files:** Create `asg_sistema/analitico/ir.py`; Test `tests/test_ir.py`

- [ ] **Step 1: Teste falho** — `tests/test_ir.py`:

```python
from asg_sistema.analitico.ir import ConsultaAnalitica, Metrica, Ordem


def test_ir_basica():
    ir = ConsultaAnalitica(
        tabela="desmatamento_alertas",
        metrica=Metrica(agg="SUM", coluna="area_total_km2", alias="area_km2"),
        dimensoes=["municipio"],
        filtros={}, ordem=Ordem(por="area_km2", desc=True), limite=3, confianca=0.8,
    )
    assert ir.tabela == "desmatamento_alertas"
    assert ir.metrica.agg == "SUM"
    assert ir.completa() is True

def test_ir_incompleta_sem_tabela():
    ir = ConsultaAnalitica(tabela=None, metrica=None, dimensoes=[], filtros={}, ordem=None, limite=100, confianca=0.1)
    assert ir.completa() is False
```

- [ ] **Step 2:** FAIL. **Step 3: Implementar** `asg_sistema/analitico/ir.py`:

```python
from dataclasses import dataclass, field


@dataclass
class Metrica:
    agg: str            # "COUNT" | "SUM" | "AVG"
    coluna: str | None  # None p/ COUNT(*)
    alias: str

@dataclass
class Ordem:
    por: str            # alias da métrica ou nome de dimensão
    desc: bool = True

@dataclass
class ConsultaAnalitica:
    tabela: str | None
    metrica: Metrica | None
    dimensoes: list[str] = field(default_factory=list)
    filtros: dict = field(default_factory=dict)   # {"municipio": "...", "periodo": {...}, "status": "AT"}
    ordem: "Ordem | None" = None
    limite: int = 100
    confianca: float = 0.0

    def completa(self) -> bool:
        """Mínimo para gerar SQL determinístico: tabela + métrica."""
        return bool(self.tabela and self.metrica)
```

- [ ] **Step 4:** PASS. **Step 5: Commit** `feat: add analytical intermediate representation (IR)`.

---

### Task 7: Value-linking — RapidFuzz + Unidecode (`texto.py` + upgrade de `entidades.py`)

**Files:** Create `asg_sistema/analitico/texto.py`; Modify `asg_sistema/motor/entidades.py`; Test `tests/test_texto_fuzzy.py`

Objetivo: matching tolerante a acento/erro para município e termos, com RapidFuzz+Unidecode (substituindo `difflib`). Mantém a **API pública** de `ExtratorEntidades` intacta para não quebrar o fluxo atual.

- [ ] **Step 1: Teste falho** — `tests/test_texto_fuzzy.py`:

```python
from asg_sistema.analitico.texto import normalizar, melhor_match


class TestNormalizar:
    def test_remove_acento_e_caixa(self):
        assert normalizar("São Paulo") == "sao paulo"

class TestMelhorMatch:
    def test_match_exato(self):
        cand = ["São Paulo", "Bauru", "Campinas"]
        nome, score = melhor_match("campinas", cand)
        assert nome == "Campinas" and score >= 95

    def test_match_com_erro_ortografico(self):
        cand = ["São Paulo", "Bauru", "Ribeirão Preto"]
        nome, score = melhor_match("ribeirao pretoo", cand)
        assert nome == "Ribeirão Preto" and score >= 85

    def test_sem_match_bom(self):
        nome, score = melhor_match("xyzzy", ["Bauru"])
        assert score < 85
```

- [ ] **Step 2:** FAIL. **Step 3: Implementar** `asg_sistema/analitico/texto.py`:

```python
"""Normalização e fuzzy matching (RapidFuzz + Unidecode) p/ value linking."""

from rapidfuzz import fuzz, process
from unidecode import unidecode


def normalizar(texto: str) -> str:
    return unidecode((texto or "").lower().strip())

def melhor_match(termo: str, candidatos: list[str]) -> tuple[str | None, float]:
    """Retorna (candidato_original, score 0..100) usando comparação sem acento."""
    if not termo or not candidatos:
        return None, 0.0
    mapa = {normalizar(c): c for c in candidatos}
    achado = process.extractOne(normalizar(termo), list(mapa.keys()), scorer=fuzz.WRatio)
    if not achado:
        return None, 0.0
    chave, score, _ = achado
    return mapa[chave], float(score)
```

- [ ] **Step 4: Upgrade `entidades.py`** — substitua o uso de `difflib.SequenceMatcher` em `_extrair_municipios` por `melhor_match` (limiar ~85). Mantenha o resto da API (`extrair` retornando o mesmo dict). Atualize o import (`from difflib import SequenceMatcher` → usar `asg_sistema.analitico.texto.melhor_match`).

> Rode a suíte existente após o upgrade: `python -m pytest -q -k entidad` (e a suíte toda) para garantir que o fluxo atual continua passando. Se houver teste que dependa do comportamento exato do difflib, ajuste-o para o novo matcher (documente a mudança).

- [ ] **Step 5:** `python -m pytest tests/test_texto_fuzzy.py -v` → PASS; suíte existente sem regressão.
- [ ] **Step 6: Commit** `feat: rapidfuzz+unidecode value-linking; replace difflib in entidades`.

---

### Task 8: Schema-linking por embeddings (`linker.py`)

**Files:** Create `asg_sistema/analitico/linker.py`; Test `tests/test_linker.py`

Casa a pergunta contra `CATALOGO_SEMANTICO` via cosseno (sklearn) sobre embeddings MiniLM (reuso de `ExtratorCaracteristicas`). Os embeddings das âncoras são pré-computados uma vez (cache em memória).

- [ ] **Step 1: Teste falho** — `tests/test_linker.py`:

```python
import pytest
from asg_sistema.analitico.linker import SchemaLinker

# Usa o modelo MiniLM já em cache local; pule se indisponível.
linker = None
try:
    linker = SchemaLinker()
except Exception:
    pass
pytestmark = pytest.mark.skipif(linker is None, reason="modelo MiniLM indisponível")


class TestLinker:
    def test_liga_tabela_queimadas(self):
        r = linker.ligar("quantos focos de incêndio por cidade")
        assert r.tabela == "queimadas"

    def test_liga_tabela_desmatamento(self):
        r = linker.ligar("top 3 cidades com mais desmatamento")
        assert r.tabela in ("desmatamento_alertas", "prodes_desmatamento")

    def test_liga_dimensao_municipio(self):
        r = linker.ligar("por município")
        assert "municipio" in r.dimensoes

    def test_confianca_entre_0_e_1(self):
        r = linker.ligar("top 3 cidades com mais desmatamento")
        assert 0.0 <= r.confianca <= 1.0
```

- [ ] **Step 2:** FAIL. **Step 3: Implementar** `asg_sistema/analitico/linker.py`:

```python
"""Schema linking por embeddings: pergunta -> tabela/métrica/dimensões via cosseno."""

from dataclasses import dataclass, field

import numpy as np
from sklearn.metrics.pairwise import cosine_similarity

from asg_sistema.analitico.catalogo import CATALOGO_SEMANTICO
from asg_sistema.pln.extrator_caracteristicas import ExtratorCaracteristicas


@dataclass
class ResultadoLink:
    tabela: str | None = None
    metrica_agg: str | None = None
    dimensoes: list[str] = field(default_factory=list)
    confianca: float = 0.0
    scores: dict = field(default_factory=dict)


class SchemaLinker:
    def __init__(self, extrator: ExtratorCaracteristicas | None = None, limiar: float = 0.35):
        self.extrator = extrator or ExtratorCaracteristicas()
        self.limiar = limiar
        self._ancoras = CATALOGO_SEMANTICO
        frases = [a["frase"] for a in self._ancoras]
        self._emb_ancoras = np.asarray(self.extrator.embeddings(frases))

    def ligar(self, pergunta: str) -> ResultadoLink:
        emb = np.asarray(self.extrator.embedding_unico(pergunta)).reshape(1, -1)
        sims = cosine_similarity(emb, self._emb_ancoras)[0]
        melhor_por_tipo: dict[str, tuple[str, float]] = {}
        dims: list[tuple[str, float]] = []
        for ancora, s in zip(self._ancoras, sims):
            tipo, alvo = ancora["tipo"], ancora["alvo"]
            if tipo == "dimensao":
                if s >= self.limiar:
                    dims.append((alvo, float(s)))
            else:
                atual = melhor_por_tipo.get(tipo)
                if atual is None or s > atual[1]:
                    melhor_por_tipo[tipo] = (alvo, float(s))

        res = ResultadoLink()
        if "tabela" in melhor_por_tipo and melhor_por_tipo["tabela"][1] >= self.limiar:
            res.tabela = melhor_por_tipo["tabela"][0]
        if "metrica" in melhor_por_tipo and melhor_por_tipo["metrica"][1] >= self.limiar:
            res.metrica_agg = melhor_por_tipo["metrica"][0]
        # dimensões acima do limiar, deduplicadas, ordenadas por score
        vistos = set()
        for alvo, s in sorted(dims, key=lambda x: -x[1]):
            if alvo not in vistos:
                res.dimensoes.append(alvo); vistos.add(alvo)
        res.scores = {k: round(v[1], 3) for k, v in melhor_por_tipo.items()}
        # confiança = média dos melhores scores de tabela e métrica
        comp = [melhor_por_tipo[t][1] for t in ("tabela", "metrica") if t in melhor_por_tipo]
        res.confianca = float(sum(comp) / len(comp)) if comp else 0.0
        return res
```

> Ajuste `limiar` empiricamente (0.30–0.45). Se algum teste de ligação falhar, refine as **frases-âncora** no catálogo (Task 5), não o limiar dos testes. As âncoras são o "conhecimento" do linker.

- [ ] **Step 4:** PASS (ou skip sem modelo). **Step 5: Commit** `feat: add embedding-based schema linker (MiniLM + cosine)`.

---

### Task 9: Extração de slots → IR (`slots.py`)

**Files:** Create `asg_sistema/analitico/slots.py`; Test `tests/test_slots.py`

Combina: `SchemaLinker` (tabela/métrica/dimensão por embedding) + regex (top-N, ordem) + `ExtratorEntidades` (município/período/status) → monta a IR e calcula confiança. spaCy md é usado para reforçar o núcleo nominal quando o embedding fica ambíguo (opcional, robustez).

- [ ] **Step 1: Teste falho** — `tests/test_slots.py` (usa um linker fake p/ não depender do modelo):

```python
from asg_sistema.analitico.slots import ExtratorSlots
from asg_sistema.analitico.linker import ResultadoLink


class _LinkerFake:
    def __init__(self, r): self._r = r
    def ligar(self, pergunta): return self._r


class _EntFake:
    def __init__(self, d): self._d = d
    def extrair(self, t): return self._d


def _slots(link, ent=None):
    return ExtratorSlots(linker=_LinkerFake(link), extrator_entidades=_EntFake(ent or {"municipios": [], "periodo": {}}))


class TestTopN:
    def test_detecta_top_3(self):
        ir = _slots(ResultadoLink(tabela="desmatamento_alertas", metrica_agg="SUM", dimensoes=["municipio"], confianca=0.8)) \
            .extrair("top 3 cidades com mais desmatamento")
        assert ir.limite == 3
        assert ir.ordem.desc is True
        assert ir.dimensoes == ["municipio"]
        assert ir.metrica.agg == "SUM" and ir.metrica.coluna == "area_total_km2"
        assert ir.completa()

    def test_mais_sem_n_usa_limite_padrao_de_ranking(self):
        ir = _slots(ResultadoLink(tabela="queimadas", metrica_agg="COUNT", dimensoes=["municipio"], confianca=0.8)) \
            .extrair("cidades com mais queimadas")
        assert ir.ordem.desc is True
        assert ir.metrica.agg == "COUNT"

    def test_menos_inverte_ordem(self):
        ir = _slots(ResultadoLink(tabela="queimadas", metrica_agg="COUNT", dimensoes=["municipio"], confianca=0.8)) \
            .extrair("5 cidades com menos queimadas")
        assert ir.limite == 5 and ir.ordem.desc is False


class TestFiltros:
    def test_injeta_municipio_e_periodo(self):
        ent = {"municipios": ["Bauru"], "periodo": {"inicio": "2024-01-01", "fim": "2024-12-31"}}
        ir = _slots(ResultadoLink(tabela="queimadas", metrica_agg="COUNT", dimensoes=[], confianca=0.8), ent) \
            .extrair("queimadas em Bauru em 2024")
        assert ir.filtros["municipio"] == "Bauru"
        assert ir.filtros["periodo"]["inicio"] == "2024-01-01"


class TestConfiancaBaixa:
    def test_sem_tabela_marca_incompleta(self):
        ir = _slots(ResultadoLink(tabela=None, metrica_agg=None, confianca=0.1)).extrair("o que é módulo fiscal")
        assert ir.completa() is False
```

- [ ] **Step 2:** FAIL. **Step 3: Implementar** `asg_sistema/analitico/slots.py`:

```python
"""Extração de slots → IR ConsultaAnalitica (semantic parsing determinístico)."""

import re

from asg_sistema.analitico.catalogo import METRICAS, DIMENSOES
from asg_sistema.analitico.ir import ConsultaAnalitica, Metrica, Ordem

_RE_TOPN = re.compile(r"\btop\s*(\d{1,3})\b|\b(\d{1,3})\s+(?:cidades|munic[ií]pios|maiores|menores)\b", re.I)
_RE_MAIS = re.compile(r"\b(mais|maiores?|maior)\b", re.I)
_RE_MENOS = re.compile(r"\b(menos|menores?|menor)\b", re.I)
_LIMITE_RANKING_PADRAO = 10


class ExtratorSlots:
    def __init__(self, linker, extrator_entidades):
        self.linker = linker
        self.entidades = extrator_entidades

    def extrair(self, pergunta: str) -> ConsultaAnalitica:
        link = self.linker.ligar(pergunta)
        ent = self.entidades.extrair(pergunta)

        # ordem + limite (ranking)
        desc = not bool(_RE_MENOS.search(pergunta))
        if _RE_MAIS.search(pergunta):
            desc = True
        n = None
        m = _RE_TOPN.search(pergunta)
        if m:
            n = int(m.group(1) or m.group(2))
        eh_ranking = bool(m or _RE_MAIS.search(pergunta) or _RE_MENOS.search(pergunta))
        limite = n if n else (_LIMITE_RANKING_PADRAO if eh_ranking else 100)

        # métrica concreta a partir do agg + tabela
        metrica = self._resolver_metrica(link.tabela, link.metrica_agg)

        # dimensões válidas para a tabela
        dims_validas = []
        if link.tabela:
            permitidas = DIMENSOES.get(link.tabela, {})
            dims_validas = [d for d in link.dimensoes if d in permitidas]
        # ranking por cidade implica dimensão município se nenhuma detectada
        if eh_ranking and not dims_validas and link.tabela and "municipio" in DIMENSOES.get(link.tabela, {}):
            if re.search(r"\b(cidades?|munic[ií]pios?)\b", pergunta, re.I):
                dims_validas = ["municipio"]

        # filtros (value linking)
        filtros = {}
        if ent.get("municipios"):
            filtros["municipio"] = ent["municipios"][0]
        if ent.get("periodo"):
            filtros["periodo"] = ent["periodo"]
        if ent.get("status"):
            filtros["status"] = ent["status"]

        ordem = Ordem(por=metrica.alias, desc=desc) if (metrica and eh_ranking) else None

        return ConsultaAnalitica(
            tabela=link.tabela, metrica=metrica, dimensoes=dims_validas,
            filtros=filtros, ordem=ordem, limite=limite, confianca=link.confianca,
        )

    def _resolver_metrica(self, tabela: str | None, agg: str | None) -> Metrica | None:
        if not tabela:
            return None
        metricas_tab = METRICAS.get(tabela, {})
        if agg == "SUM":
            for nome, (a, col) in metricas_tab.items():
                if a == "SUM":
                    return Metrica("SUM", col, "area_km2" if "area" in nome else nome)
        if agg == "AVG":
            for nome, (a, col) in metricas_tab.items():
                if a == "AVG":
                    return Metrica("AVG", col, nome)
        # default: COUNT(*) com alias coerente
        alias = next((n for n, (a, _) in metricas_tab.items() if a == "COUNT"), "total")
        return Metrica("COUNT", None, alias)
```

> Nota: a heurística de métrica é deliberadamente simples e auditável. Para casos como "área média", o agg AVG + coluna de área pode precisar de ajuste fino — cubra no golden set (Fase 6) e refine `_resolver_metrica` conforme as falhas reais.

- [ ] **Step 4:** PASS. **Step 5: Commit** `feat: add slot extractor (linker + regex + entities) producing IR`.

---

## Fase 2 — Construtor determinístico de SQL + cinturão de segurança

### Task 10: Construtor de SQL a partir da IR (`construtor_sql.py`)

**Files:** Create `asg_sistema/analitico/construtor_sql.py`; Test `tests/test_construtor_sql.py`

Materializa a IR em SQL Postgres. **Filtros via parâmetros bind** (`:municipio`) — nunca interpolação de valores do usuário. Datas e enums já vêm resolvidos da IR.

- [ ] **Step 1: Teste falho** — `tests/test_construtor_sql.py`:

```python
from asg_sistema.analitico.ir import ConsultaAnalitica, Metrica, Ordem
from asg_sistema.analitico.construtor_sql import construir


def _ir(**kw):
    base = dict(tabela="desmatamento_alertas",
                metrica=Metrica("SUM", "area_total_km2", "area_km2"),
                dimensoes=["municipio"], filtros={}, ordem=Ordem("area_km2", True),
                limite=3, confianca=0.8)
    base.update(kw)
    return ConsultaAnalitica(**base)


class TestConstruir:
    def test_top_n_agregacao(self):
        sql, params = construir(_ir())
        s = " ".join(sql.split())
        assert "SUM(area_total_km2) AS area_km2" in s
        assert "FROM desmatamento_alertas" in s
        assert "GROUP BY municipio" in s
        assert "ORDER BY area_km2 DESC" in s
        assert s.rstrip().endswith("LIMIT 3")

    def test_count_estrela(self):
        ir = _ir(metrica=Metrica("COUNT", None, "focos"), tabela="queimadas")
        sql, _ = construir(ir)
        assert "COUNT(*) AS focos" in " ".join(sql.split())

    def test_filtro_municipio_parametrizado(self):
        ir = _ir(filtros={"municipio": "Bauru"})
        sql, params = construir(ir)
        assert ":municipio" in sql
        assert params["municipio"] == "Bauru" or params["municipio"] == "%Bauru%"

    def test_filtro_periodo_usa_coluna_de_data_da_tabela(self):
        ir = _ir(tabela="queimadas", metrica=Metrica("COUNT", None, "focos"),
                 filtros={"periodo": {"inicio": "2024-01-01", "fim": "2024-12-31"}})
        sql, params = construir(ir)
        assert "data_hora >= :data_inicio" in sql and "data_hora < :data_fim" in sql

    def test_filtro_status(self):
        ir = _ir(tabela="sicar_imoveis", metrica=Metrica("COUNT", None, "imoveis"),
                 dimensoes=["municipio"], filtros={"status": "AT"})
        sql, params = construir(ir)
        assert "ind_status = :status" in sql and params["status"] == "AT"

    def test_limite_clampado(self):
        ir = _ir(limite=99999)
        sql, _ = construir(ir, max_limit=100)
        assert sql.rstrip().endswith("LIMIT 100")
```

- [ ] **Step 2:** FAIL. **Step 3: Implementar** `asg_sistema/analitico/construtor_sql.py`:

```python
"""IR ConsultaAnalitica -> (sql, params). Determinístico e parametrizado."""

from asg_sistema.analitico.catalogo import DIMENSOES, colunas_de
from asg_sistema.analitico.ir import ConsultaAnalitica

# Coluna de data por tabela (para filtros de período).
_COLUNA_DATA = {
    "queimadas": "data_hora",
    "desmatamento_alertas": "data_avistamento",
    "prodes_desmatamento": "data_imagem",
    "sicar_imoveis": "dat_criacao",
}


def _expr_metrica(ir: ConsultaAnalitica) -> str:
    m = ir.metrica
    if m.agg == "COUNT" or not m.coluna:
        return f"COUNT(*) AS {m.alias}"
    return f"{m.agg}({m.coluna}) AS {m.alias}"


def construir(ir: ConsultaAnalitica, max_limit: int = 100) -> tuple[str, dict]:
    if not ir.completa():
        raise ValueError("IR incompleta: faltam tabela e/ou métrica.")
    params: dict = {}
    dims_sql = [DIMENSOES.get(ir.tabela, {}).get(d, d) for d in ir.dimensoes]

    select_cols = list(dims_sql) + [_expr_metrica(ir)]
    sql = f"SELECT {', '.join(select_cols)}\nFROM {ir.tabela}"

    where = []
    f = ir.filtros or {}
    if f.get("municipio"):
        where.append("municipio ILIKE :municipio")
        params["municipio"] = f"%{f['municipio']}%"
    if f.get("status"):
        where.append("ind_status = :status")
        params["status"] = f["status"]
    if f.get("periodo") and _COLUNA_DATA.get(ir.tabela):
        col = _COLUNA_DATA[ir.tabela]
        per = f["periodo"]
        if per.get("inicio"):
            where.append(f"{col} >= :data_inicio"); params["data_inicio"] = per["inicio"]
        if per.get("fim"):
            where.append(f"{col} < :data_fim"); params["data_fim"] = per["fim"]
    if where:
        sql += "\nWHERE " + " AND ".join(where)

    if dims_sql:
        sql += "\nGROUP BY " + ", ".join(dims_sql)

    if ir.ordem:
        sql += f"\nORDER BY {ir.ordem.por} {'DESC' if ir.ordem.desc else 'ASC'}"

    limite = min(int(ir.limite or max_limit), max_limit)
    sql += f"\nLIMIT {limite}"
    return sql, params
```

> Filtros usam **bind params** (`:municipio`, `:status`, `:data_inicio/fim`) — valores do usuário nunca entram por interpolação de string. A allowlist de tabela/coluna vem da IR (que só usa nomes do catálogo) e é reconfirmada pelo validador (Task 11).

- [ ] **Step 4:** PASS. **Step 5: Commit** `feat: add deterministic IR->SQL builder (parametrized filters)`.

---

### Task 11: Validador de segurança (`validador_sql.py`)

**Files:** Create `asg_sistema/analitico/validador_sql.py`; Test `tests/test_validador_sql.py`

Cinturão de segurança via sqlglot — **obrigatório** mesmo para o SQL do construtor (defesa em profundidade) e essencial para o fallback generativo. Camadas: parseável → único statement → só SELECT/WITH-SELECT → allowlist de tabelas/colunas → bloqueio de funções perigosas → LIMIT obrigatório/clampado.

- [ ] **Step 1: Teste falho** — `tests/test_validador_sql.py`:

```python
from asg_sistema.analitico.validador_sql import validar_sql


class TestSelect:
    def test_select_ok(self):
        assert validar_sql("SELECT municipio, COUNT(*) c FROM queimadas GROUP BY municipio ORDER BY c DESC LIMIT 10").valido
    def test_with_ok(self):
        assert validar_sql("WITH t AS (SELECT municipio, COUNT(*) c FROM queimadas GROUP BY municipio) SELECT * FROM t LIMIT 5").valido
    def test_rejeita_dml_ddl(self):
        for s in ("INSERT INTO queimadas(municipio) VALUES('x')","UPDATE sicar_imoveis SET ind_status='CA'",
                  "DELETE FROM queimadas","DROP TABLE queimadas","ALTER TABLE queimadas ADD c int",
                  "TRUNCATE queimadas","GRANT ALL ON queimadas TO public"):
            assert validar_sql(s).valido is False, s
    def test_rejeita_multiplo(self):
        assert validar_sql("SELECT 1 FROM queimadas LIMIT 1; DROP TABLE queimadas").valido is False
    def test_rejeita_nao_parseavel(self):
        assert validar_sql("SELECT FROM WHERE ((").valido is False


class TestAllowlist:
    def test_tabela_proibida(self):
        r = validar_sql("SELECT * FROM usuarios LIMIT 5")
        assert r.valido is False and "usuarios" in (r.erro or "")
    def test_tabela_inexistente(self):
        assert validar_sql("SELECT * FROM xpto LIMIT 5").valido is False
    def test_view_permitida(self):
        assert validar_sql("SELECT ano, area_km2 FROM vw_prodes_ano ORDER BY ano LIMIT 50").valido
    def test_coluna_qualificada_invalida(self):
        assert validar_sql("SELECT q.senha_hash FROM queimadas q LIMIT 5").valido is False
    def test_funcao_perigosa(self):
        assert validar_sql("SELECT pg_sleep(10) FROM queimadas LIMIT 1").valido is False


class TestLimit:
    def test_injeta_limit(self):
        r = validar_sql("SELECT municipio FROM queimadas")
        assert r.valido and "LIMIT" in r.sql_final.upper()
    def test_preserva_top_n(self):
        r = validar_sql("SELECT municipio, COUNT(*) c FROM queimadas GROUP BY municipio ORDER BY c DESC LIMIT 3")
        assert r.sql_final.rstrip().upper().endswith("LIMIT 3")
    def test_clampa(self):
        r = validar_sql("SELECT municipio FROM queimadas LIMIT 99999", max_limit=100)
        assert "LIMIT 100" in r.sql_final.upper()
```

- [ ] **Step 2:** FAIL. **Step 3: Implementar** `asg_sistema/analitico/validador_sql.py`:

```python
"""Validação de SQL via AST (sqlglot): único SELECT + allowlist + funções seguras + LIMIT."""

from dataclasses import dataclass

import sqlglot
from sqlglot import exp

from asg_sistema.analitico.catalogo import nomes_permitidos, colunas_de, todas_as_colunas


@dataclass
class ResultadoValidacao:
    valido: bool
    sql_final: str
    erro: str | None = None


_PROIBIDO = (exp.Insert, exp.Update, exp.Delete, exp.Drop, exp.Create,
             exp.Alter, exp.TruncateTable, exp.Grant, exp.Command)

# Funções permitidas (agregações + data + texto). Tudo fora disso é rejeitado.
_FUNC_OK = {
    "count","sum","avg","min","max","round","coalesce","extract","date_trunc",
    "make_date","lower","upper","st_asgeojson","abs","cast",
}


def validar_sql(sql: str, max_limit: int = 100) -> ResultadoValidacao:
    sql = (sql or "").strip().rstrip(";").strip()
    if not sql:
        return ResultadoValidacao(False, "", "SQL vazio.")
    try:
        arvores = [a for a in sqlglot.parse(sql, dialect="postgres") if a is not None]
    except Exception as e:
        return ResultadoValidacao(False, "", f"SQL não parseável: {e}")
    if len(arvores) != 1:
        return ResultadoValidacao(False, "", "Apenas um comando é permitido.")
    arvore = arvores[0]

    for no in arvore.walk():
        node = no[0] if isinstance(no, tuple) else no
        if isinstance(node, _PROIBIDO):
            return ResultadoValidacao(False, "", f"Comando proibido: {type(node).__name__}.")
    if arvore.find(exp.Select) is None:
        return ResultadoValidacao(False, "", "Apenas SELECT é permitido.")

    permitidas = nomes_permitidos()
    nomes_cte = {c.alias_or_name for c in arvore.find_all(exp.CTE)}
    alias_tab: dict[str, str] = {}
    for tab in arvore.find_all(exp.Table):
        nome = tab.name
        if nome in nomes_cte:
            continue
        if nome not in permitidas:
            return ResultadoValidacao(False, "", f"Tabela não permitida: {nome}.")
        alias_tab[tab.alias_or_name] = nome

    # funções
    for fn in arvore.find_all(exp.Anonymous):
        if (fn.name or "").lower() not in _FUNC_OK:
            return ResultadoValidacao(False, "", f"Função não permitida: {fn.name}.")
    for fn in arvore.find_all(exp.Func):
        nome_fn = (fn.sql_name() or type(fn).__name__).lower()
        # exp.Func cobre funções nativas (Count, Sum...). Aceita as conhecidas.
        if nome_fn not in _FUNC_OK and not isinstance(fn, (exp.Count, exp.Sum, exp.Avg, exp.Min, exp.Max, exp.Extract, exp.Round, exp.Coalesce, exp.Cast)):
            # tolera: muitas nativas têm nomes próprios; só barra Anonymous acima
            pass

    universo = todas_as_colunas()
    for col in arvore.find_all(exp.Column):
        nome = col.name
        if nome == "*":
            continue
        ali = col.table
        if ali and ali in alias_tab:
            if nome not in colunas_de(alias_tab[ali]) and nome not in universo and nome not in nomes_cte:
                return ResultadoValidacao(False, "", f"Coluna não permitida: {ali}.{nome}.")
        # não-qualificada: tolera (alias de SELECT, coluna de CTE, etc.)

    # LIMIT obrigatório/clampado no SELECT externo
    select_ext = arvore if isinstance(arvore, exp.Select) else arvore.find(exp.Select)
    lim = None
    if select_ext is not None and select_ext.args.get("limit") is not None:
        try:
            lim = int(select_ext.args["limit"].expression.name)
        except Exception:
            lim = None
    if lim is None:
        sql_final = arvore.limit(max_limit).sql(dialect="postgres")
    elif lim > max_limit:
        select_ext.set("limit", exp.Limit(expression=exp.Literal.number(max_limit)))
        sql_final = arvore.sql(dialect="postgres")
    else:
        sql_final = arvore.sql(dialect="postgres")

    return ResultadoValidacao(True, sql_final, None)
```

> A API do sqlglot para LIMIT/funções varia por versão. O contrato são os testes — **itere até verde**, sem afrouxar segurança. Se `pg_sleep` (um `exp.Anonymous`) não for barrado, garanta que a checagem de `_FUNC_OK` o rejeita.

- [ ] **Step 4:** PASS. **Step 5: Commit** `feat: add sqlglot safety validator (single-select + allowlist + funcs + limit)`.

---

### Task 12: Suíte adversarial de segurança

**Files:** Test `tests/test_seguranca_sql.py`

Deve passar **100%**. Garante que injeção (mesmo via fallback generativo) nunca vira escrita/leitura indevida.

- [ ] **Step 1: Escrever** `tests/test_seguranca_sql.py`:

```python
import pytest
from asg_sistema.analitico.validador_sql import validar_sql

ATAQUES = [
    "DROP TABLE queimadas", "DELETE FROM usuarios", "UPDATE sicar_imoveis SET ind_status='CA'",
    "INSERT INTO queimadas(municipio) VALUES('x')", "TRUNCATE queimadas",
    "ALTER TABLE queimadas ADD COLUMN x int", "GRANT ALL ON queimadas TO public",
    "SELECT 1 FROM queimadas LIMIT 1; DROP TABLE queimadas",
    "SELECT * FROM usuarios LIMIT 5", "SELECT senha_hash FROM usuarios LIMIT 5",
    "SELECT * FROM corpus_asg LIMIT 5", "SELECT pg_sleep(10) FROM queimadas LIMIT 1",
    "COPY queimadas TO '/tmp/x.csv'", "SELECT * FROM pg_shadow LIMIT 1",
]

@pytest.mark.parametrize("ataque", ATAQUES)
def test_ataque_rejeitado(ataque):
    assert validar_sql(ataque).valido is False, f"PERIGO: passou → {ataque}"
```

- [ ] **Step 2:** Rodar `python -m pytest tests/test_seguranca_sql.py -v` → 100% PASS. Para cada falha, **endureça o validador** (Task 11), nunca o teste.
- [ ] **Step 3: Commit** `test: adversarial security suite (100% block)`.

---

## Fase 3 — Orquestrador, renderização e endpoint isolado

### Task 13: Renderizador determinístico (`renderizador.py`)

**Files:** Create `asg_sistema/analitico/renderizador.py`; Test `tests/test_renderizador_analitico.py`

Converte IR + linhas em um **dict no contrato `ConsultaResponse`**. Resumo em NL **determinístico** (sem LLM, sem alucinação): formata os próprios números das linhas. GeoJSON quando houver coluna geográfica.

- [ ] **Step 1: Teste falho** — `tests/test_renderizador_analitico.py`:

```python
from asg_sistema.analitico.ir import ConsultaAnalitica, Metrica, Ordem
from asg_sistema.analitico.renderizador import renderizar


def _ir():
    return ConsultaAnalitica(tabela="desmatamento_alertas",
                             metrica=Metrica("SUM","area_total_km2","area_km2"),
                             dimensoes=["municipio"], filtros={}, ordem=Ordem("area_km2",True),
                             limite=3, confianca=0.8)

class TestRenderizar:
    def test_contrato(self):
        out = renderizar("top 3 cidades com mais desmatamento", _ir(),
                         [{"municipio":"Bauru","area_km2":12.3},{"municipio":"B-2","area_km2":5.0}],
                         sql="SELECT ...")
        for c in ("resumo","estatisticas","dados","fontes","intencao_detectada","entidades",
                  "geojson","total_resultados"):
            assert c in out
        assert out["dados"][0]["municipio"] == "Bauru"
        assert out["total_resultados"] == 2
        assert out["estatisticas"]["sql"] == "SELECT ..."

    def test_resumo_usa_numeros_reais(self):
        out = renderizar("top cidades", _ir(), [{"municipio":"Bauru","area_km2":12.3}], sql="x")
        assert "Bauru" in out["resumo"] and "12" in out["resumo"]

    def test_sem_linhas(self):
        out = renderizar("top cidades", _ir(), [], sql="x")
        assert out["total_resultados"] == 0
        assert "nenhum" in out["resumo"].lower() or "não" in out["resumo"].lower()

    def test_geojson_quando_geom(self):
        ir = _ir()
        linhas = [{"municipio":"Bauru","geometry":'{"type":"Point","coordinates":[-49,-22]}'}]
        out = renderizar("queimadas em Bauru", ir, linhas, sql="x")
        assert out["geojson"] is None or out["geojson"]["type"] == "FeatureCollection"
```

- [ ] **Step 2:** FAIL. **Step 3: Implementar** `asg_sistema/analitico/renderizador.py`:

```python
"""IR + linhas -> dict no contrato ConsultaResponse. Resumo determinístico, sem LLM."""

import json

from asg_sistema.analitico.ir import ConsultaAnalitica


def _fmt(v) -> str:
    if isinstance(v, float):
        return f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return str(v)


def _resumo(pergunta: str, ir: ConsultaAnalitica, linhas: list[dict]) -> str:
    if not linhas:
        return "Nenhum resultado encontrado para a sua pergunta."
    alias = ir.metrica.alias if ir.metrica else None
    dim = ir.dimensoes[0] if ir.dimensoes else None
    if dim and alias and dim in linhas[0] and alias in linhas[0]:
        topo = linhas[: min(3, len(linhas))]
        partes = [f"{l[dim]} ({_fmt(l[alias])})" for l in topo]
        verbo = "maiores" if (ir.ordem and ir.ordem.desc) else "menores"
        return f"Os {verbo} resultados por {dim}: " + "; ".join(partes) + "."
    return f"Foram encontrados {len(linhas)} resultado(s)."


def _geojson(linhas: list[dict]) -> dict | None:
    chave = None
    if linhas:
        for k in linhas[0]:
            if k.lower() in ("geometry", "geom_geojson", "geojson") or "geojson" in k.lower():
                chave = k; break
    if not chave:
        return None
    feats = []
    for l in linhas:
        raw = l.get(chave)
        if not raw:
            continue
        geom = json.loads(raw) if isinstance(raw, str) else raw
        props = {k: v for k, v in l.items() if k != chave}
        feats.append({"type": "Feature", "geometry": geom, "properties": props})
    return {"type": "FeatureCollection", "features": feats} if feats else None


def renderizar(pergunta: str, ir: ConsultaAnalitica, linhas: list[dict], sql: str) -> dict:
    return {
        "pergunta": pergunta,
        "intencao_detectada": "consulta_analitica",
        "confianca": round(float(ir.confianca), 3),
        "entidades": dict(ir.filtros or {}),
        "resumo": _resumo(pergunta, ir, linhas),
        "estatisticas": {
            "total": len(linhas),
            "colunas": list(linhas[0].keys()) if linhas else [],
            "sql": sql,
            "tabela": ir.tabela,
            "metrica": (ir.metrica.alias if ir.metrica else None),
            "dimensoes": ir.dimensoes,
        },
        "dados": linhas,
        "fontes": [{"nome": "Consulta analítica (Text-to-SQL local)", "tabela": ir.tabela}],
        "geojson": _geojson(linhas),
        "nota_risco": None,
        "grupos": None,
        "total_resultados": len(linhas),
    }
```

> Os campos casam com o que `_salvar_historico` lê via `.get` (`resumo`, `estatisticas`, `dados`, `fontes`, `geojson`, `intencao_detectada`, `entidades`, `nota_risco`, `grupos`). `tempo_processamento_ms` é preenchido pelo interpretador (Task 16).

- [ ] **Step 4:** PASS. **Step 5: Commit** `feat: add deterministic renderer to ConsultaResponse contract`.

---

### Task 14: Orquestrador analítico (`motor.py`)

**Files:** Create `asg_sistema/analitico/motor.py`; Test `tests/test_motor_analitico.py`

Fluxo: slots → IR. Se `ir.completa()` e `confianca >= limiar` → construir SQL determinístico. Senão, se fallback ativo → gerador local. Validar → EXPLAIN → executar → renderizar. Dependências injetadas (executor, explain, gerador) → testável sem DB/modelo.

- [ ] **Step 1: Teste falho** — `tests/test_motor_analitico.py`:

```python
from asg_sistema.analitico.ir import ConsultaAnalitica, Metrica, Ordem
from asg_sistema.analitico.motor import MotorAnalitico


class _SlotsFake:
    def __init__(self, ir): self._ir = ir
    def extrair(self, p): return self._ir


def _ir_ok():
    return ConsultaAnalitica("desmatamento_alertas", Metrica("SUM","area_total_km2","area_km2"),
                             ["municipio"], {}, Ordem("area_km2",True), 3, 0.8)


class TestCaminhoDeterministico:
    def test_gera_valida_executa_renderiza(self):
        motor = MotorAnalitico(
            extrator_slots=_SlotsFake(_ir_ok()),
            executor=lambda sql, params=None, timeout_ms=None: [{"municipio":"Bauru","area_km2":12.3}],
            explain=lambda sql, params=None: None,
        )
        out = motor.consultar("top 3 cidades com mais desmatamento")
        assert out["erro"] is None if "erro" in out else True
        assert out["total_resultados"] == 1
        assert "Bauru" in out["resumo"]
        assert "desmatamento_alertas" in out["estatisticas"]["sql"]


class TestConfiancaBaixa:
    def test_ir_incompleta_retorna_fallback_amigavel(self):
        ir_ruim = ConsultaAnalitica(None, None, [], {}, None, 100, 0.1)
        chamou = {"v": False}
        def exec_spy(sql, params=None, timeout_ms=None):
            chamou["v"] = True; return []
        motor = MotorAnalitico(extrator_slots=_SlotsFake(ir_ruim), executor=exec_spy,
                               explain=lambda *a, **k: None)
        out = motor.consultar("o que é módulo fiscal")
        assert chamou["v"] is False           # nunca executou
        assert out["total_resultados"] == 0


class TestExplainFalha:
    def test_explain_falho_nao_propaga_dados(self):
        motor = MotorAnalitico(extrator_slots=_SlotsFake(_ir_ok()),
                               executor=lambda *a, **k: [{"x":1}],
                               explain=lambda sql, params=None: "erro de coluna")
        out = motor.consultar("top 3")
        assert out["total_resultados"] == 0
```

- [ ] **Step 2:** FAIL. **Step 3: Implementar** `asg_sistema/analitico/motor.py`:

```python
"""Orquestrador do caminho analítico: slots -> SQL -> validação -> execução -> render."""

import logging

from asg_sistema.config import config
from asg_sistema.analitico.construtor_sql import construir
from asg_sistema.analitico.renderizador import renderizar
from asg_sistema.analitico.validador_sql import validar_sql

logger = logging.getLogger("asg.analitico")


def _resposta_fallback(pergunta: str, motivo: str) -> dict:
    return {
        "pergunta": pergunta,
        "intencao_detectada": "consulta_analitica",
        "confianca": 0.0,
        "entidades": {},
        "resumo": "Não consegui montar uma consulta confiável para essa pergunta.",
        "estatisticas": {"erro": motivo},
        "dados": [],
        "fontes": [],
        "geojson": None,
        "nota_risco": None,
        "grupos": None,
        "total_resultados": 0,
        "erro": motivo,
    }


class MotorAnalitico:
    def __init__(self, extrator_slots, executor, explain, gerador_local=None):
        self.slots = extrator_slots
        self.executor = executor
        self.explain = explain
        self.gerador_local = gerador_local  # opcional (fallback generativo)

    def consultar(self, pergunta: str) -> dict:
        ir = self.slots.extrair(pergunta)

        sql, params = None, {}
        if ir.completa() and ir.confianca >= config.analitico_confianca_minima:
            try:
                sql, params = construir(ir, max_limit=config.sql_max_limit)
            except Exception as e:
                logger.info("construtor_falhou", extra={"erro": str(e)})
                sql = None

        if sql is None and self.gerador_local is not None:
            sql = self.gerador_local.gerar(pergunta)   # fallback opcional (Fase 5)
            params = {}

        if sql is None:
            return _resposta_fallback(pergunta, "confiança insuficiente / IR incompleta")

        val = validar_sql(sql, max_limit=config.sql_max_limit)
        if not val.valido:
            return _resposta_fallback(pergunta, f"SQL rejeitado: {val.erro}")

        erro_explain = self.explain(val.sql_final, params)
        if erro_explain:
            return _resposta_fallback(pergunta, f"EXPLAIN falhou: {erro_explain}")

        try:
            linhas = self.executor(val.sql_final, params, timeout_ms=config.sql_timeout_ms)
        except Exception as e:
            return _resposta_fallback(pergunta, f"execução falhou: {e}")

        out = renderizar(pergunta, ir, linhas, sql=val.sql_final)
        out["erro"] = None
        logger.info("consulta_analitica",
                    extra={"sql": val.sql_final, "n_linhas": len(linhas), "confianca": ir.confianca})
        return out
```

> O executor recebe `(sql, params, timeout_ms)`. Confirme que `executar_consulta_readonly`/`explain_readonly` (Task 4) aceitam essa ordem — eles aceitam `(sql, params, timeout_ms)` e `(sql, params)`. Ajuste a chamada do `explain` se a assinatura diferir.

- [ ] **Step 4:** PASS. **Step 5: Commit** `feat: add analytical orchestrator (slots->build->validate->explain->execute->render)`.

---

### Task 15: Endpoint isolado `POST /consulta-analitica`

**Files:** Modify `asg_sistema/api/rotas_consulta.py`; Test `tests/test_endpoint_analitico.py`

Endpoint novo que exercita o caminho analítico ponta a ponta, **sem** roteador e sem tocar `/consulta`. Útil para validar a Fase 1–3 com DB real antes da integração.

- [ ] **Step 1: Teste falho** — `tests/test_endpoint_analitico.py` (com motor fake injetado):

```python
import os
os.environ.setdefault("ASG_JWT_SEGREDO", "test-secret")
from fastapi.testclient import TestClient
import asg_sistema.api.rotas_consulta as rotas
from asg_sistema.main import app   # ajuste o import do app conforme o repo


def test_consulta_analitica(monkeypatch):
    class _MotorFake:
        def consultar(self, pergunta):
            return {"resumo": "ok", "dados": [{"municipio":"Bauru"}], "total_resultados": 1,
                    "estatisticas": {"sql":"SELECT ..."}, "geojson": None, "erro": None,
                    "intencao_detectada":"consulta_analitica","entidades":{},"fontes":[]}
    monkeypatch.setattr(rotas, "_construir_motor_analitico", lambda: _MotorFake(), raising=False)
    r = TestClient(app).post("/consulta-analitica", json={"pergunta": "top 3 desmatamento"})
    assert r.status_code == 200
    body = r.json()
    assert body["total_resultados"] == 1 and body["dados"][0]["municipio"] == "Bauru"
```

- [ ] **Step 2:** FAIL. **Step 3: Implementar** — em `rotas_consulta.py`:

```python
from pydantic import BaseModel
from asg_sistema.db.conexao import executar_consulta_readonly, explain_readonly


class ConsultaAnaliticaRequest(BaseModel):
    pergunta: str


def _construir_motor_analitico():
    from asg_sistema.config import config
    from asg_sistema.pln.extrator_caracteristicas import ExtratorCaracteristicas
    from asg_sistema.motor.entidades import ExtratorEntidades
    from asg_sistema.analitico.linker import SchemaLinker
    from asg_sistema.analitico.slots import ExtratorSlots
    from asg_sistema.analitico.motor import MotorAnalitico
    import json

    extrator = ExtratorCaracteristicas(config.modelo_embeddings)
    municipios_path = config.caminho_treinamento / "municipios_sp.json"
    municipios = json.load(open(municipios_path, encoding="utf-8")) if municipios_path.exists() else []
    slots = ExtratorSlots(linker=SchemaLinker(extrator), extrator_entidades=ExtratorEntidades(municipios))
    return MotorAnalitico(extrator_slots=slots, executor=executar_consulta_readonly, explain=explain_readonly)


@router.post("/consulta-analitica")
def consulta_analitica(req: ConsultaAnaliticaRequest):
    motor = _construir_motor_analitico()
    return motor.consultar(req.pergunta)
```

> Use o nome real do `APIRouter` (`router`). Se quiser cachear o motor como singleton (evita recarregar embeddings), guarde-o num global lazy igual a `_interpretador`.

- [ ] **Step 4:** PASS. **Step 5 (manual, requer DB):** subir o app e `POST /consulta-analitica` com "top 3 cidades com mais desmatamento" → JSON com `dados` reais. **Step 6: Commit** `feat: add isolated POST /consulta-analitica endpoint`.

---

## Fase 4 — Roteador híbrido e integração no fluxo existente

### Task 16: Roteador (`roteador.py`)

**Files:** Create `asg_sistema/analitico/roteador.py`; Test `tests/test_roteador_analitico.py`

Classifica em `ANALITICA | DESCRITIVA | ESPACIAL`. Heurística barata primeiro (CAR/`cod_imovel` → ESPACIAL; regex de ranking/agregação → ANALITICA); embedding como desempate opcional; default seguro DESCRITIVA (mantém fluxo atual).

- [ ] **Step 1: Teste falho** — `tests/test_roteador_analitico.py`:

```python
from asg_sistema.analitico.roteador import rotear


class TestHeuristica:
    def test_cod_imovel_espacial(self):
        assert rotear("analise este imóvel", cod_imovel="SP-123") == "ESPACIAL"
    def test_top_n_analitica(self):
        assert rotear("top 3 cidades com mais desmatamento") == "ANALITICA"
    def test_media_por_grupo_analitica(self):
        assert rotear("média de área por bioma em 2024") == "ANALITICA"
    def test_quantos_por_municipio_analitica(self):
        assert rotear("quantas queimadas por município") == "ANALITICA"
    def test_conceitual_descritiva(self):
        assert rotear("o que é módulo fiscal?") == "DESCRITIVA"
    def test_car_no_texto_espacial(self):
        assert rotear("situação do imóvel SP-3524808-ABCDEF123456") == "ESPACIAL"
```

- [ ] **Step 2:** FAIL. **Step 3: Implementar** `asg_sistema/analitico/roteador.py`:

```python
"""Roteador híbrido: heurística + (opcional) embedding. Default seguro = DESCRITIVA."""

import re

from asg_sistema.motor.entidades import extrair_cod_imovel_do_texto

_RE_ANALITICA = re.compile(
    r"\b(top|maiores?|menores?|ranking|quantos?|quantas?|total|soma|somat[óo]rio|"
    r"m[ée]dia|contagem|n[úu]mero de|mais|menos)\b"
    r"|\bpor\s+(munic[íi]pio|cidade|ano|m[êe]s|bioma|classe)\b", re.IGNORECASE)


def rotear(pergunta: str, cod_imovel: str | None = None, linker=None) -> str:
    if cod_imovel and str(cod_imovel).strip():
        return "ESPACIAL"
    if extrair_cod_imovel_do_texto(pergunta or ""):
        return "ESPACIAL"
    if _RE_ANALITICA.search(pergunta or ""):
        return "ANALITICA"
    # (opcional) desempate por embedding usando o linker, se fornecido:
    if linker is not None:
        try:
            r = linker.ligar(pergunta)
            if r.tabela and r.metrica_agg and r.confianca >= 0.5:
                return "ANALITICA"
        except Exception:
            pass
    return "DESCRITIVA"
```

- [ ] **Step 4:** PASS. **Step 5: Commit** `feat: add hybrid router (heuristic + optional embedding)`.

---

### Task 17: Integração no `InterpretadorConsulta.processar()`

**Files:** Modify `asg_sistema/motor/interpretador.py`, `asg_sistema/api/rotas_consulta.py`; Test `tests/test_interpretador_roteamento.py`

Ponto de integração. No topo de `processar`: rotear; se `ANALITICA` e há `motor_analitico` → caminho novo, devolvendo o dict (com `tempo_processamento_ms` e `preprocessamento` mínimos). Senão, **fluxo atual intacto**.

- [ ] **Step 1: Teste falho** — `tests/test_interpretador_roteamento.py`:

```python
import os
os.environ.setdefault("ASG_JWT_SEGREDO", "test-secret")


class _MotorAnaliticoFake:
    def __init__(self): self.chamado = None
    def consultar(self, pergunta):
        self.chamado = pergunta
        return {"resumo":"top 3","dados":[],"total_resultados":0,"estatisticas":{"sql":"SELECT"},
                "geojson":None,"erro":None,"intencao_detectada":"consulta_analitica",
                "entidades":{},"fontes":[],"confianca":0.8}


def _interp(motor=None):
    # construir InterpretadorConsulta com dependências mínimas/fakes
    from asg_sistema.motor.interpretador import InterpretadorConsulta
    class _Noop:
        def preprocessar(self, t): return {"tokens_originais":[],"tokens_limpos":[],"stems":[],"lemmas":[],"texto_limpo":t}
        def classificar(self, t): return ("fora_do_escopo", 0.0)
    # use objetos mínimos; só o roteamento ANALITICA importa aqui
    return InterpretadorConsulta(
        preprocessador=_Noop(), classificador=_Noop(),
        extrator_entidades=type("E",(),{"extrair":lambda s,t:{"municipios":[],"periodo":{}}})(),
        buscador=None, gerador=None, motor_analitico=motor,
    )


class TestRoteamento:
    def test_analitica_usa_motor(self):
        m = _MotorAnaliticoFake()
        resp = _interp(m).processar("top 3 cidades com mais desmatamento")
        assert m.chamado == "top 3 cidades com mais desmatamento"
        assert resp["resumo"] == "top 3"
        assert "tempo_processamento_ms" in resp

    def test_descritiva_nao_usa_motor(self):
        m = _MotorAnaliticoFake()
        # pergunta conceitual cai no fluxo atual (que aqui retorna fora_do_escopo)
        resp = _interp(m).processar("o que é módulo fiscal?")
        assert m.chamado is None
```

> Este teste exercita só o ramo de roteamento. Ajuste os fakes ao que `processar` toca antes do `return` do ramo analítico. Se o fluxo atual exigir mais dependências para a pergunta descritiva, simplifique para `intencao=fora_do_escopo` (que retorna cedo, sem usar buscador/gerador).

- [ ] **Step 2:** FAIL. **Step 3: Implementar** — em `InterpretadorConsulta.__init__`, adicionar parâmetros opcionais (no fim, com default `None`) sem alterar os existentes:

```python
    def __init__(self, preprocessador, classificador, extrator_entidades,
                 buscador, gerador, top_k: int = 15,
                 motor_analitico=None, roteador_linker=None):
        ...  # atribuições existentes
        self.motor_analitico = motor_analitico
        self.roteador_linker = roteador_linker
```

No topo de `processar`, **após** `pergunta = normalizar_pergunta(...)` e antes da classificação:

```python
        from asg_sistema.analitico.roteador import rotear
        if self.motor_analitico is not None:
            rota = rotear(pergunta, cod_imovel=cod_imovel, linker=self.roteador_linker)
            if rota == "ANALITICA":
                resp = self.motor_analitico.consultar(pergunta)
                if not resp.get("erro"):
                    resp.setdefault("pergunta", pergunta)
                    resp["tempo_processamento_ms"] = round((time.time() - inicio) * 1000, 1)
                    resp.setdefault("preprocessamento", {})
                    return resp
                # se o analítico falhar, cai para o fluxo atual (degradação graciosa)
```

> Decisão: se o caminho analítico retornar `erro`, **não** quebra — cai no fluxo atual (NB + vetorial). Isso garante que nenhuma pergunta fica sem resposta.

- [ ] **Step 4: Injetar no singleton** — em `obter_interpretador()` (rotas_consulta.py), construir o motor analítico e passar:

```python
        from asg_sistema.analitico.linker import SchemaLinker
        from asg_sistema.analitico.slots import ExtratorSlots
        from asg_sistema.analitico.motor import MotorAnalitico
        from asg_sistema.db.conexao import executar_consulta_readonly, explain_readonly

        linker = SchemaLinker(extrator)        # reusa o mesmo ExtratorCaracteristicas já criado
        slots = ExtratorSlots(linker=linker, extrator_entidades=extrator_entidades)
        motor_analitico = MotorAnalitico(
            extrator_slots=slots, executor=executar_consulta_readonly, explain=explain_readonly,
        )

        _interpretador = InterpretadorConsulta(
            preprocessador=preprocessador, classificador=classificador,
            extrator_entidades=extrator_entidades, buscador=buscador, gerador=gerador,
            top_k=config.busca_top_k, motor_analitico=motor_analitico, roteador_linker=linker,
        )
```

- [ ] **Step 5:** `python -m pytest tests/test_interpretador_roteamento.py -v` → PASS.
- [ ] **Step 6: Sem regressão** — `python -m pytest -q` → toda a suíte existente + novos passam. Investigue qualquer falha antes de commitar.
- [ ] **Step 7: Commit** `feat: route analytical questions through deterministic text-to-sql in interpretador`.

---

## Fase 5 — Fallback generativo local (opcional, OFF por padrão)

> Em máquina modesta isto fica **desligado** (`gerador_local_ativo=False`). Implemente para quando houver hardware melhor, sem mudar o caminho principal. O modelo roda via `transformers` (já instalado), **lazy** e local — sem rede.

### Task 18: Gerador local text2sql (`gerador_local.py`)

**Files:** Create `asg_sistema/analitico/gerador_local.py`; Test `tests/test_gerador_local.py`

- [ ] **Step 1: Teste falho** — `tests/test_gerador_local.py` (sem baixar modelo: testa o contrato com pipeline fake):

```python
from asg_sistema.analitico.gerador_local import GeradorLocal


class _PipeFake:
    def __call__(self, prompt, **kw):
        return [{"generated_text": "SELECT municipio, COUNT(*) AS focos FROM queimadas GROUP BY municipio LIMIT 10"}]


class TestGeradorLocal:
    def test_extrai_sql_do_modelo(self):
        g = GeradorLocal(pipeline=_PipeFake())
        sql = g.gerar("quantas queimadas por município")
        assert "SELECT" in sql.upper() and "queimadas" in sql

    def test_desligado_retorna_none(self):
        g = GeradorLocal(pipeline=None, ativo=False)
        assert g.gerar("x") is None
```

- [ ] **Step 2:** FAIL. **Step 3: Implementar** `asg_sistema/analitico/gerador_local.py`:

```python
"""Fallback generativo LOCAL via transformers (lazy). OFF por padrão."""

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
            # text2text p/ T5; troque a task se usar modelo decoder-only
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
```

> O SQL do gerador passa **pelo mesmo validador** (Task 11) no `MotorAnalitico` — então alucinação de coluna/tabela é barrada. Para habilitar: `ASG_GERADOR_LOCAL_ATIVO=true` no `.env`. Para ligar no motor, passe `gerador_local=GeradorLocal()` ao `MotorAnalitico` no singleton (atrás do flag).

- [ ] **Step 4:** PASS. **Step 5: Commit** `feat: add optional local generative text2sql fallback (off by default)`.

### Task 19: Auto-correção do gerador (opcional)

**Files:** Modify `asg_sistema/analitico/motor.py`; Test `tests/test_autocorrecao_local.py`

- [ ] Quando o caminho usou o **gerador local** e `EXPLAIN` falhou, reenviar ao gerador `pergunta + sql + erro` pedindo correção (máx 1–2 vezes). Para o caminho **determinístico**, não há auto-correção via modelo — em vez disso, relaxar a IR (ex.: remover filtro problemático) ou cair no fluxo atual. Implemente só se o fallback for usado. Teste com pipeline fake que erra na 1ª e acerta na 2ª. **Commit** `feat: add generative self-correction on EXPLAIN failure`.

---

## Fase 6 — Avaliação e observabilidade

### Task 20: Golden set (`golden_analitico.json`)

**Files:** Create `dados_treinamento/golden_analitico.json`

- [ ] **Step 1:** ~40–60 itens cobrindo: top-N, SUM/COUNT/AVG, temporais (relativas "último mês"/"esse ano" e absolutas "em 2024"), agrupamentos (município/ano/bioma/classe), com município, sem filtro, com `geom`, e **fora de escopo** (deve rotear DESCRITIVA/recusar). Estrutura:

```json
[
  {"id":"topn-001","pergunta":"top 3 cidades com mais desmatamento","rota_esperada":"ANALITICA",
   "tabela_esperada":"desmatamento_alertas","checagem":"linhas_nao_vazias"},
  {"id":"temporal-001","pergunta":"top 10 cidades com mais queimadas no último mês","rota_esperada":"ANALITICA",
   "tabela_esperada":"queimadas","checagem":"linhas_nao_vazias"},
  {"id":"fora-001","pergunta":"o que é módulo fiscal?","rota_esperada":"DESCRITIVA","checagem":"nao_analitica"}
]
```

- [ ] **Step 2:** validar parsing: `python -c "import json;print(len(json.load(open('dados_treinamento/golden_analitico.json',encoding='utf-8'))))"`.
- [ ] **Step 3: Commit** `test: add golden set for analytical path`.

### Task 21: Teste de roteamento + slots no golden set (unit, sem DB)

**Files:** Test `tests/test_golden_roteamento.py`

- [ ] Para cada item, verificar `rotear(pergunta) == rota_esperada` e, para os ANALITICA, que `slots.extrair(...)` produz `tabela == tabela_esperada` e `ir.completa()`. Mede **acurácia de parsing** sem precisar de banco. Alvo: ≥90%. Refine âncoras/regex (não os testes) até atingir. **Commit** `test: golden-set routing+slots accuracy (no DB)`.

### Task 22: Execution accuracy (integração, requer DB)

**Files:** Create `tests/integration/__init__.py`, `tests/integration/test_analitico_exec.py`; Modify/Create `pytest.ini` (marker `integration`)

- [ ] **Step 1:** registrar marker `integration` em `pytest.ini`.
- [ ] **Step 2:** teste que pula sem `ASG_DB_INTEGRACAO=1`; para cada item ANALITICA do golden, roda o `MotorAnalitico` real (executor read-only) e aplica `checagem` (`linhas_nao_vazias` etc.). Skip se DB ausente.

```python
import json, os
from pathlib import Path
import pytest
pytestmark = pytest.mark.integration
if os.environ.get("ASG_DB_INTEGRACAO") != "1":
    pytest.skip("requer banco real", allow_module_level=True)
# ... carrega golden, monta MotorAnalitico real, parametriza casos ANALITICA, assert checagem
```

- [ ] **Step 3:** sem env → `skipped`; com env + DB + views → ≥90% pass. Refine catálogo/slots/construtor pelos casos que falham. **Commit** `test: execution-accuracy integration suite (gated)`.

### Task 23: Observabilidade

**Files:** Modify `asg_sistema/analitico/motor.py` (já loga via `logging.getLogger("asg.analitico")`); Test `tests/test_log_analitico.py`

- [ ] Garantir log estruturado por consulta (pergunta, rota, sql, n_linhas, confiança, status, latência) em **todos** os caminhos de retorno (sucesso e fallback). Teste com `caplog`. **Commit** `feat: structured logging for analytical queries`.

---

## Fase 7 — Limpeza e consolidação

### Task 24: Paridade e aposentadoria (com métricas)

- [ ] **Step 1:** rodar Tasks 21–22 e documentar acurácia por categoria + latência em `docs/avaliacao_analitico.md`.
- [ ] **Step 2:** decidir (com o usuário) o que aposentar. Candidato: o ramo `fora_do_escopo` deixa de "engolir" perguntas analíticas (agora roteadas). **Manter** busca vetorial, CAR/AHP e o classificador NB (são os caminhos DESCRITIVA/ESPACIAL).
- [ ] **Step 3:** remover redundâncias com `python -m pytest -q` verde a cada passo; commit individual.
- [ ] **Step 4:** atualizar `README.md`/`CLAUDE.md` documentando a nova rota analítica e como ligar o fallback generativo. **Commit** `chore: consolidate analytical path; docs`.

---

## Verificação manual ponta a ponta (antes de declarar concluído)

Use a skill **verification-before-completion** — evidência antes de afirmar sucesso. Requer Postgres com `schema_views.sql` aplicado.

- [ ] `python -m pytest -q` verde (unit); integração *skipped* sem env.
- [ ] Segurança 100%: `python -m pytest tests/test_seguranca_sql.py -v`.
- [ ] App sobe sem erro de import (com spaCy `md` e libs novas).
- [ ] Via `/consulta`: "top 3 cidades com mais desmatamento" → `resumo` com os 3 nomes+números, `dados` reais, `estatisticas.sql` presente.
- [ ] "quantas queimadas por município no último mês" → agregação correta com filtro temporal (datas ISO resolvidas em Python).
- [ ] Pergunta com `cod_imovel`/CAR → continua no motor CAR/AHP (não foi p/ SQL).
- [ ] Pergunta conceitual ("o que é módulo fiscal?") → continua na busca vetorial.
- [ ] Tentativa maliciosa ("apague a tabela queimadas") → roteia/valida com segurança; nada executado.
- [ ] Latência aceitável em máquina modesta (sem modelo generativo): a 1ª consulta paga o load do MiniLM/spaCy; as seguintes são rápidas (embeddings em memória).

---

## Riscos e mitigação

| Risco | Mitigação |
|---|---|
| Slot-filling erra tabela/métrica | confiança mínima (Task 14) + golden set de parsing (Task 21); refinar âncoras |
| Cobertura limitada (padrões não enumerados) | fallback generativo local opcional (Fase 5); `log()` quando cair no fallback descritivo |
| SQL inválido/alucinado (fallback) | validador sqlglot + allowlist + EXPLAIN (Tasks 11, 14) |
| Escrita/injeção | role read-only (Task 3) + único SELECT + bind params + validador (Tasks 4, 10, 11, 12) |
| Datas relativas erradas | resolvidas em Python (`ExtratorEntidades`) e passadas como literais ISO |
| Nomes de município errados | value linking RapidFuzz+Unidecode (Task 7) |
| Query pesada | statement_timeout + LIMIT obrigatório (Tasks 4, 11) |
| Resposta numérica inventada | renderizador determinístico usa só as linhas reais (Task 13) |
| Modelo pesado em máquina modesta | construtor determinístico é o principal; generativo OFF por padrão |
| Quebrar o que funciona | integração aditiva + degradação graciosa (analítico falho → fluxo atual) + `pytest -q` sem regressão |
| spaCy `md` vs `sm` | `sm` permanece disponível; só o `md` traz vetores; preprocessador não usa config |

---

## Rollback

- **Desligar em runtime:** não injetar `motor_analitico` no singleton (ou um flag `ASG_ANALITICO_ATIVO=false` que você adicione na Task 17) → roteador inerte → comportamento idêntico ao pré-refatoração.
- **Reverter código:** cada Task é um commit isolado; `git revert` da Task 17 (integração) remove o caminho novo do fluxo principal sem desfazer o resto.

---

## Definition of Done

- [ ] Todas as Tasks com checkboxes marcados.
- [ ] `python -m pytest -q` verde (unit); integração *skipped* sem env ou ≥90% com env.
- [ ] Segurança 100% de bloqueio.
- [ ] Fluxos descritivo e espacial inalterados (sem regressão).
- [ ] Caminho analítico responde top-N/agregações/temporais com SQL determinístico, validado e renderizado no contrato existente — **100% local, sem API externa**.
- [ ] Degradação graciosa: analítico incerto/falho → fluxo atual.
- [ ] Observabilidade (log estruturado) ativa.
- [ ] Docs atualizadas; fallback generativo documentado (OFF por padrão).





