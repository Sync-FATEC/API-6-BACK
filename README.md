# ASG-SP Back-end - Sistema de Análise Ambiental, Social e Governança

Sistema de consulta por linguagem natural a dados ASG (Ambiental, Social e Governança) de propriedades rurais do Estado de São Paulo.

## Sumário
1. [Visão Geral](#visão-geral)
2. [Pipeline ETL](#pipeline-etl)
3. [Fontes de Dados](#fontes-de-dados)
4. [Pipeline de PLN](#pipeline-de-pln)
5. [Banco de Dados](#banco-de-dados)
6. [API REST](#api-rest)
7. [Como Executar](#como-executar)
8. [Tecnologias Utilizadas](#tecnologias-utilizadas)

---

## Visão Geral

O sistema permite que um usuário digite uma pergunta em linguagem natural (ex: "Houve queimadas em Avaí nos últimos meses?") e receba uma resposta estruturada com:

- Resumo textual da consulta
- Dados encontrados com fontes rastreáveis
- GeoJSON compatível com QGIS e sistemas de mapa

### Fluxo de uma Consulta

```
Usuario: "Quais terras indigenas existem em Ubatuba?"
        |
        v
[POST /api/consulta]
        |
        v
[preprocessador.py]  ->  tokens: ["terras", "indigenas", "ubatuba"]
        |                 stems: ["terr", "indigen", "ubatub"]
        v
[classificador.py]   ->  intencao: "consultar_terra_indigena" (86%)
        |
        v
[entidades.py]       ->  municipio: "Ubatuba"
        |
        v
[buscador_semantico] ->  pgvector: embedding <=> query
        |                 WHERE fonte='funai' AND municipio ILIKE '%Ubatuba%'
        v
[gerador_resposta]   ->  {
                            resumo: "Foram encontradas 2 terras indigenas...",
                            fontes: [{nome: "FUNAI", url: "..."}],
                            geojson: {type: "FeatureCollection", ...},
                            tempo_ms: 88
                          }
```

---

## Pipeline ETL

O pipeline ETL (Extract, Transform, Load) é responsável por manter a base de dados atualizada. Pode ser executado manualmente ou agendado via API.

### Etapas

```
[EXTRACT]  coletor_asg.py
    |  Conecta em APIs publicas governamentais
    |  Baixa dados via WFS, CSV e Shapefile
    |  Baixa shapefile SICAR via https://consultapublica.car.gov.br/publico/estados/downloads
    |  Salva JSONs em dados/
    v
[TRANSFORM]  textualizador.py
    |  Converte cada registro estruturado em frase em portugues
    |  Ex: "Foco de queimada detectado pelo satelite NOAA-21
    |       no municipio de Fernando Prestes, SP, em 2026-03-01.
    |       Fonte: INPE/Queimadas."
    v
[LOAD]  carregador.py
    |  Insere nas tabelas estruturadas (queimadas, terras_indigenas, etc.)
    |  Insere no corpus textualizado (corpus_asg)
    |  Cria geometrias PostGIS (pontos e poligonos)
    v
[EMBED]  vetorizador.py / extrator_caracteristicas.py
    |  Gera embedding (vetor 384-dim) para cada texto do corpus sem embedding
    |  Modelo: paraphrase-multilingual-MiniLM-L12-v2
    |  Salva na coluna pgvector do corpus_asg
    v
[VALIDATE]
    |  Verifica contagens, embeddings, geometrias
    |  Registra log da execucao
    v
[LOG]  logs/etl_YYYYMMDD_HHMMSS.log
       Cada execucao gera registro com:
       - data/hora, duracao, registros por etapa
       - erros encontrados, status final
```

### Como Executar o ETL

```bash
# Pre-ETL: baixa shapefile do SICAR (CAR) e converte para GeoJSON
python scripts/sicar/coletar_sicar.py

# Pipeline completo (todas as etapas)
python scripts/etl_pipeline.py

# Apenas coleta de dados (Extract)
python scripts/etl_pipeline.py --etapa extract

# Apenas carga no banco (Transform + Load)
python scripts/etl_pipeline.py --etapa load

# Apenas geracao de embeddings
python scripts/etl_pipeline.py --etapa embed

# Apenas validacao
python scripts/etl_pipeline.py --etapa validate
```

### Agendamento via API

O sistema possui agendamento de ETL via API REST com APScheduler. O agendamento persiste entre reinicializações.

```bash
# Criar agendamento (ex: todo dia 5 do mês às 16h55)
POST /api/agendamento/

# Listar agendamentos ativos
GET /api/agendamento/

# Disparar ETL imediatamente via API
POST /api/etl/executar
```

O cooldown padrão entre execuções é de 6 horas (configurável). O histórico de execuções fica em `/api/etl/historico`.

---

## Fontes de Dados

| # | Fonte | Tipo de Acesso | Dados Coletados |
|---|-------|---------------|-----------------|
| 1 | **FUNAI** | WFS (GeoServer) | Terras Indígenas em SP — polígonos, etnia, área, fase |
| 2 | **INPE/DETER Cerrado** | WFS (TerraBrasilis) | Alertas de desmatamento — classe, área, satélite |
| 3 | **INPE/Queimadas** | CSV (servidor INPE) | Focos de incêndio — lat/lon, satélite, FRP, município |
| 4 | **INPE/PRODES** | WFS (TerraBrasilis) | Desmatamento anual Mata Atlântica |
| 5 | **MMA/ICMBio** | Shapefile (CNUC) | Unidades de Conservação — nome, categoria, esfera, área |
| 6 | **SICAR/CAR** | Shapefile (download) | Cadastro Ambiental Rural — imóveis rurais de SP |
| 7 | **Palmares** | CSV (Google Sheets) | Comunidades quilombolas certificadas em SP |

### Detalhes por Fonte

#### FUNAI - Terras Indígenas
- **URL**: `https://geoserver.funai.gov.br/geoserver/Funai/wfs`
- **Camada**: `Funai:tis_poligonais`
- **Filtro**: `uf_sigla = 'SP'`
- **Formato**: GeoJSON com MultiPolygon (EPSG:4674)

#### INPE/DETER - Desmatamento
- **URL**: `https://terrabrasilis.dpi.inpe.br/geoserver/deter-cerrado-nb/wfs`
- **Filtro**: BBOX de São Paulo

#### INPE/Queimadas - Focos de Incêndio
- **URL**: `https://dataserver-coids.inpe.br/queimadas/queimadas/focos/csv/mensal/Brasil/`
- **Período**: Últimos 6 meses, filtrado para SP

#### INPE/PRODES - Desmatamento Anual
- **URL**: `https://terrabrasilis.dpi.inpe.br/geoserver/prodes-mata-atlantica-nb/wfs`
- **Filtro**: BBOX de São Paulo

#### MMA/ICMBio - Unidades de Conservação
- **URL**: `https://dados.mma.gov.br/dataset/unidadesdeconservacao`
- **Formato**: Shapefile ZIP (CNUC) → DBF/GeoPandas → JSON
- **Filtro**: campo UF = 'SP'; fallback por bounding box geográfico de SP

#### SICAR/CAR - Cadastro Ambiental Rural
- **URL**: https://consultapublica.car.gov.br/publico/estados/downloads
- **Formato**: Shapefile ZIP baixado via biblioteca SICAR → GeoJSON via `coletar_sicar.py`
- **Script**: `scripts/sicar/coletar_sicar.py` (requer biblioteca SICAR + Tesseract OCR)
- **Saída**: `dados/geojson/SP_AREA_IMOVEL.geojson` (~466k imóveis rurais)

#### Palmares - Comunidades Quilombolas
- **URL**: Google Sheets da Fundação Cultural Palmares (export CSV)
- **Filtro**: UF = 'SP'

### Arquivos Gerados

Todos salvos em `dados/`:

```
dados/
  funai_terras_indigenas_sp.json
  queimadas_focos_sp.json
  deter_desmatamento_sp.json
  prodes_desmatamento_sp.json
  unidades_conservacao_sp.json
  palmares_quilombolas_sp.json
  resumo_coleta.json
  geojson/
    SP_AREA_IMOVEL.geojson       (~466k imoveis SICAR)
```

---

## Pipeline de PLN

Implementa as 5 etapas do pipeline de Processamento de Linguagem Natural:

### Etapa 1 - Pré-processamento (`preprocessador.py`)

```python
entrada: "Houve queimadas em Avai nos ultimos meses?"

tokenizacao (NLTK):     ["Houve", "queimadas", "em", "Avai", "nos", "ultimos", "meses", "?"]
remocao stopwords:      ["queimadas", "Avai", "ultimos", "meses"]
stemming (RSLPStemmer): ["queim", "avai", "ultim", "mes"]
lematizacao (SpaCy):    ["queimada", "avai", "ultimo", "mes"]
```

### Etapa 2 - Extração de Características (`extrator_caracteristicas.py`)

| Método | Descrição | Uso |
|--------|-----------|-----|
| **Bag of Words** | CountVectorizer (unigrams + bigrams) | Baseline |
| **TF-IDF** | TfidfVectorizer (sublinear_tf, ngrams 1-2) | Classificação de intenção |
| **Embeddings** | sentence-transformers MiniLM (384 dims) | Busca semântica |

### Etapa 3 - Modelo de Linguagem (`modelo_linguagem.py`)

Constrói as matrizes TF-IDF e de embeddings do corpus ASG (~18.000 documentos textualizados).

### Etapa 4 - Treinamento de IA (`classificador.py`)

Classificador **Naive Bayes Multinomial** treinado com TF-IDF para detectar a intenção do usuário:

| Intenção | Exemplo | Tabela consultada |
|----------|---------|-------------------|
| `consultar_queimadas` | "Houve fogo em Bauru?" | queimadas |
| `consultar_terra_indigena` | "Terras indígenas em Ubatuba" | terras_indigenas |
| `consultar_desmatamento` | "Desmatamento no Cerrado" | desmatamento_alertas + prodes_desmatamento |
| `consultar_unidade_conservacao` | "UCs em Bertioga" | unidades_conservacao |
| `consultar_quilombola` | "Quilombolas no Vale do Ribeira" | comunidades_quilombolas |
| `consultar_prodes` | "Desmatamento anual na Mata Atlântica" | prodes_desmatamento |
| `consultar_imovel_rural` | "Imóveis rurais em Campinas" | sicar_imoveis |
| `resumo_municipal` | "Situação ambiental de Campinas" | todas |

- **Dados de treino**: 111 exemplos rotulados manualmente (`dados_treinamento/intencoes.json`)
- **Acurácia**: >90% com validação cruzada
- **Modelo salvo**: `modelos_salvos/classificador_intencao.pkl`

### Etapa 5 - Aplicação (`buscador_semantico.py`)

Busca híbrida combinando:
1. **Similaridade vetorial** (pgvector): embedding da pergunta vs embeddings do corpus
2. **Filtros estruturados**: fonte, município, período temporal
3. **Intenções múltiplas**: detecta palavras-chave secundárias e faz merge de resultados de fontes diferentes

```sql
SELECT texto, municipio, fonte, metadados_json,
       1 - (embedding <=> :query_embedding) AS similaridade
FROM corpus_asg
WHERE fonte = :fonte AND municipio ILIKE :municipio
ORDER BY embedding <=> :query_embedding
LIMIT 15
```

### Extração de Entidades (`entidades.py`)

- **Municípios**: SpaCy PhraseMatcher com lista dos 645 municípios de SP (IBGE)
- **Períodos temporais**: Regex para "últimos X meses", "em 2025", etc.

---

## Banco de Dados

**PostgreSQL 16** com extensões:
- **PostGIS**: geometrias espaciais (pontos, polígonos), índices GiST
- **pgvector**: vetores de embeddings (384 dimensões), busca por similaridade cosseno


### Índices

- Índices GiST em todas as colunas `geom` (queimadas, terras_indigenas, desmatamento_alertas, prodes_desmatamento, sicar_imoveis)
- Índices por `municipio` em todas as tabelas
- `idx_corpus_fonte`, `idx_corpus_municipio`, `idx_corpus_uf_sigla` no corpus
- `idx_sicar_cod_imovel`, `idx_sicar_status` na tabela SICAR

### Cobertura de Dados

| Tabela | Registros | Geometria | Fonte |
|--------|-----------|-----------|-------|
| `queimadas` | ~14.000 | Point | INPE/Queimadas |
| `prodes_desmatamento` | ~50.000 | MultiPolygon | INPE/PRODES |
| `sicar_imoveis` | ~466.000 | Geometry | SICAR/CAR |
| `terras_indigenas` | ~29 | MultiPolygon | FUNAI |
| `desmatamento_alertas` | ~31 | MultiPolygon | INPE/DETER |
| `unidades_conservacao` | ~15 | Tabular | MMA/ICMBio |
| `comunidades_quilombolas` | 52 | Tabular | Palmares |
| `corpus_asg` | ~18.000 | — | Todas (textos + embeddings) |

**Nota PRODES**: insere 1 amostra a cada 50 registros no corpus (~1.000 textos) para otimizar tempo de embedding. Os 50K registros completos ficam na tabela `prodes_desmatamento` com geometria.

**Nota SICAR**: os ~466K imóveis rurais são carregados na tabela `sicar_imoveis`. No corpus, 1 amostra a cada 50 registros (~9.300 textos).

---

## API REST

**Framework**: FastAPI (Python)

### Endpoints

| Método | Rota | Descrição |
|--------|------|-----------|
| `POST` | `/api/consulta` | Consulta em linguagem natural |
| `GET` | `/api/dados/queimadas` | Dados estruturados de queimadas |
| `GET` | `/api/dados/terras_indigenas` | Dados de terras indígenas |
| `GET` | `/api/dados/desmatamento` | Alertas de desmatamento |
| `GET` | `/api/dados/unidades_conservacao` | Unidades de conservação |
| `GET` | `/api/dados/prodes` | Dados PRODES desmatamento anual |
| `GET` | `/api/dados/quilombolas` | Comunidades quilombolas |
| `GET` | `/api/geo/queimadas` | GeoJSON para mapa/QGIS |
| `GET` | `/api/geo/terras_indigenas` | GeoJSON para mapa/QGIS |
| `GET` | `/api/geo/desmatamento` | GeoJSON DETER para mapa/QGIS |
| `GET` | `/api/geo/prodes` | GeoJSON PRODES para mapa/QGIS |
| `GET` | `/api/geo/quilombolas` | Dados quilombolas (tabulares) |
| `GET` | `/api/saude` | Health check com contagens por tabela |
| `GET` | `/api/etl/historico` | Histórico de execuções ETL |
| `POST` | `/api/etl/executar` | Dispara pipeline ETL via API |
| `GET` | `/api/agendamento/` | Lista agendamentos ativos |
| `POST` | `/api/agendamento/` | Cria novo agendamento ETL |
| `DELETE` | `/api/agendamento/{id}` | Remove agendamento |

### Exemplo de Requisição

```bash
curl -X POST http://localhost:8000/api/consulta \
  -H "Content-Type: application/json" \
  -d '{"pergunta": "Quais terras indigenas existem em Ubatuba?"}'
```

### Exemplo de Resposta

```json
{
  "pergunta": "Quais terras indigenas existem em Ubatuba?",
  "intencao_detectada": "consultar_terra_indigena",
  "confianca": 0.86,
  "entidades": {
    "municipios": ["Ubatuba"],
    "periodo": {}
  },
  "resumo": "Foram encontradas 2 terras indigenas no municipio de Ubatuba.",
  "estatisticas": {"total": 2},
  "fontes": [{"nome": "FUNAI", "identificador": "funai"}],
  "geojson": {
    "type": "FeatureCollection",
    "features": [...]
  },
  "total_resultados": 2,
  "tempo_processamento_ms": 88.1
}
```

### Integração com QGIS

1. Abrir QGIS
2. Layer > Add Layer > Add Vector Layer
3. Protocol: HTTP(S)
4. URI: `http://localhost:8000/api/geo/queimadas`
5. Os dados aparecem no mapa com geometrias corretas (EPSG:4674/SIRGAS 2000)

---

## Como Executar

### Pré-requisitos

- Python 3.11+
- Docker Desktop (para PostgreSQL)
- ~2 GB de disco (modelo de embeddings + dados SICAR)

#### Dependência SICAR e OCR

1. Instale o Tesseract OCR:

- **Windows**: https://github.com/UB-Mannheim/tesseract/wiki
- **macOS**: `brew install tesseract`
- **Linux**: `apt install tesseract-ocr`

2. No Windows, adicione o Tesseract no PATH:

```powershell
setx PATH "$env:PATH;C:\Program Files\Tesseract-OCR"
```

### 1. Configurar Variáveis de Ambiente

```bash
cp .env.example .env
```

Edite `.env` com as credenciais do banco se necessário (os valores padrão funcionam com o Docker Compose incluso):

```env
ASG_DB_HOST=localhost
ASG_DB_PORT=5433
ASG_DB_NOME=asg_sp
ASG_DB_USUARIO=asg_user
ASG_DB_SENHA=asg_pass
```

### 2. Instalar Dependências

```bash
python -m venv .venv
# Windows:
.venv\Scripts\activate
# Linux/macOS:
source .venv/bin/activate

pip install -r requirements.txt
python -m spacy download pt_core_news_sm
```

### 3. Subir o Banco de Dados

```bash
docker compose up -d --build
```

Cria PostgreSQL 16 com PostGIS + pgvector na porta 5433. Aguarde ~5 min na primeira vez (compila pgvector).

### 4. Criar Tabelas

```bash
python scripts/criar_banco.py
```

### 5. Baixar Dados do SICAR

```bash
python scripts/sicar/coletar_sicar.py
```

### 6. Executar o Pipeline ETL

```bash
# Opcao A: Pipeline completo (coleta + carga + embeddings) ~15-20 min
python scripts/etl_pipeline.py

# Opcao B: Passo a passo
python scripts/coletor_asg.py              # 1. Coletar dados das APIs
python scripts/ingerir_dados.py            # 2. Carregar no banco
python scripts/treinar_classificador.py    # 3. Treinar classificador
```

### 7. Treinar Classificador (se não usou Opção A)

```bash
python scripts/treinar_classificador.py
```

### 8. Iniciar a API

```bash
uvicorn asg_sistema.api.app:app --reload
```

API disponível em: **http://127.0.0.1:8000**

---

## Tecnologias Utilizadas

| Camada | Tecnologia | Versão | Função |
|--------|-----------|--------|--------|
| **Linguagem** | Python | 3.13 | Toda a aplicação |
| **API** | FastAPI | 0.115+ | REST API |
| **Agendamento** | APScheduler | 3.x | Cron jobs para ETL automático |
| **Banco** | PostgreSQL | 16 | Armazenamento principal |
| **Geoespacial** | PostGIS | 3.4 | Geometrias, consultas espaciais |
| **Vetorial** | pgvector | 0.8 | Busca semântica por similaridade |
| **PLN** | NLTK | 3.8+ | Tokenização, stemming, stopwords |
| **PLN** | SpaCy | 3.7+ | Lematização, NER, PhraseMatcher |
| **PLN** | scikit-learn | 1.5+ | TF-IDF, Naive Bayes |
| **Embeddings** | sentence-transformers | 3.0+ | Modelo multilingual MiniLM |
| **ORM** | SQLAlchemy | 2.0+ | Conexão com banco |
| **Driver** | psycopg2 | 2.9+ | Driver PostgreSQL |
| **Geo** | GeoPandas | 1.0+ | Leitura de shapefiles (UCs) |
| **SICAR** | SICAR (lib) | — | Download shapefile CAR com OCR |
| **Infra** | Docker | 24+ | Container do banco |
| **Dados** | GeoJSON | RFC 7946 | Formato de intercâmbio geoespacial |

