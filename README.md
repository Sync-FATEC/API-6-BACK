# ASG-SP - Sistema de Analise Ambiental, Social e Governanca

Sistema de consulta por linguagem natural a dados ASG (Ambiental, Social e Governanca) de propriedades rurais do Estado de Sao Paulo.

**Desafio do Parceiro Academico** - Fatec SJC / Visiona Espacial - 6o Semestre DSM (2026-01)

---

## Sumario

1. [Visao Geral](#visao-geral)
2. [Arquitetura do Sistema](#arquitetura-do-sistema)
3. [Pipeline ETL](#pipeline-etl)
4. [Fontes de Dados](#fontes-de-dados)
5. [Pipeline de PLN](#pipeline-de-pln)
6. [Banco de Dados](#banco-de-dados)
7. [API REST](#api-rest)
8. [Frontend](#frontend)
9. [Estrutura de Diretorios](#estrutura-de-diretorios)
10. [Como Executar](#como-executar)
11. [Endpoints da API](#endpoints-da-api)
12. [Tecnologias Utilizadas](#tecnologias-utilizadas)

---

## Visao Geral

O sistema permite que um usuario digite uma pergunta em linguagem natural (ex: "Houve queimadas em Avai nos ultimos meses?") e receba uma resposta estruturada com:

- Resumo textual da consulta
- Dados encontrados com fontes rastreaveis
- Visualizacao em mapa interativo (Leaflet)
- Exportacao em GeoJSON compativel com QGIS

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
        |
        v
[Frontend: chat + mapa Leaflet com marcadores]
```

---

## Arquitetura do Sistema

```
                    +----------------------------+
                    |       Frontend Web         |
                    | Satelite Esri + Leaflet.js |
                    | Chat + Mapa + Legenda      |
                    +-------------+--------------+
                                  |
                                  v
                    +----------------------------+
                    |      FastAPI (REST)         |
                    | /api/consulta (PLN)         |
                    | /api/dados/* /api/geo/*     |
                    | /api/etl/* (monitoramento)  |
                    +-------------+--------------+
                                  |
                 +----------------+----------------+
                 |                                 |
    +------------v-----------+       +-------------v----------+
    |    Motor de PLN        |       |    PostgreSQL 16       |
    | - Preprocessador NLTK  |       | + PostGIS (geometrias) |
    | - Classificador NB     |       | + pgvector (embeddings)|
    | - Busca Semantica      |       +------------------------+
    | - Gerador Resposta     |                ^
    +------------------------+                |
                                              |
                    +-------------------------+
                    |     Pipeline ETL         |
                    | etl_pipeline.py (orq.)   |
                    | coletor_asg.py (extract)  |
                    | carregador.py (load)      |
                    | vetorizador.py (embed)    |
                    +-------------------------+
                             ^
                             |
              +--------------+--------------+
              |       |       |       |     |
            INPE   FUNAI   ICMBio  SICAR  Palmares
          (queimadas, DETER, PRODES)  (UCs)  (quilombolas)
```

---

## Pipeline ETL

O pipeline ETL (Extract, Transform, Load) eh responsavel por manter a base de dados atualizada. Pode ser executado manualmente ou agendado.

### Etapas

```
[EXTRACT]  coletor_asg.py
    |  Conecta em 8 APIs publicas governamentais
    |  Baixa dados via WFS, CSV e Shapefile
    |  Salva JSONs em API/dados/
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
    |  Gera embedding (vetor 384-dim) para cada texto do corpus
    |  Modelo: paraphrase-multilingual-MiniLM-L12-v2
    |  Salva na coluna pgvector do corpus_asg
    v
[VALIDATE]
    |  Verifica contagens, embeddings, geometrias
    |  Registra log da execucao
    v
[LOG]  logs/historico_etl.jsonl
       Cada execucao gera registro com:
       - data/hora, duracao, registros por etapa
       - erros encontrados, status final
```

### Como Executar o ETL

```bash
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

# Agendar execucao a cada 6 horas
python scripts/etl_pipeline.py --agendar 6
```

### Agendamento (Windows Task Scheduler)

```
schtasks /create /tn "ETL_ASG_SP" /tr "python C:\...\scripts\etl_pipeline.py" /sc daily /st 06:00
```

---

## Fontes de Dados

O coletor (`coletor_asg.py`) acessa 8 fontes governamentais de dados abertos:

| # | Fonte | Tipo de Acesso | Dados Coletados | Registros |
|---|-------|---------------|-----------------|-----------|
| 1 | **FUNAI** | WFS (GeoServer) | Terras Indigenas em SP - poligonos, etnia, area, fase | ~29 |
| 2 | **INPE/DETER Cerrado** | WFS (TerraBrasilis) | Alertas de desmatamento - classe, area, satelite | ~31 |
| 3 | **INPE/DETER Amazonia** | WFS (TerraBrasilis) | Alertas na regiao de SP (normalmente 0 - SP nao esta na Amazonia) | 0 |
| 4 | **INPE/Queimadas** | CSV (servidor INPE) | Focos de incendio - lat/lon, satelite, FRP, municipio | ~14.000 |
| 5 | **INPE/PRODES** | WFS (TerraBrasilis) | Desmatamento anual Mata Atlantica | ~50.000 |
| 6 | **MMA/ICMBio** | Shapefile (download) | Unidades de Conservacao - nome, categoria, esfera, area | ~2.147 |
| 7 | **SICAR/CAR** | WFS (GeoServer) | Cadastro Ambiental Rural (servidor indisponivel - bloqueio SSL) | 0 |
| 8 | **Palmares** | CSV (Google Sheets) | Comunidades quilombolas certificadas em SP | ~52 |

### Detalhes Tecnicos por Fonte

#### FUNAI - Terras Indigenas
- **URL**: `https://geoserver.funai.gov.br/geoserver/Funai/wfs`
- **Camada**: `Funai:tis_poligonais`
- **Filtro**: `uf_sigla = 'SP'`
- **Formato**: GeoJSON com MultiPolygon (EPSG:4674)
- **Dados**: nome, etnia, municipio, area (ha), fase (Regularizada/Declarada/etc)

#### INPE/DETER - Desmatamento
- **URL**: `https://terrabrasilis.dpi.inpe.br/geoserver/deter-cerrado-nb/wfs`
- **Camada**: `deter-cerrado-nb:deter_cerrado`
- **Filtro**: BBOX de Sao Paulo
- **Formato**: GeoJSON com MultiPolygon
- **Dados**: classe (DESMATAMENTO_CR, etc), municipio, satelite, area (km2)

#### INPE/Queimadas - Focos de Incendio
- **URL**: `https://dataserver-coids.inpe.br/queimadas/queimadas/focos/csv/mensal/Brasil/`
- **Formato**: CSV mensal do Brasil inteiro, filtrado para SP
- **Periodo**: Ultimos 6 meses
- **Dados**: latitude, longitude, data/hora, satelite, municipio, bioma, FRP

#### INPE/PRODES - Desmatamento Anual
- **URL**: `https://terrabrasilis.dpi.inpe.br/geoserver/prodes-mata-atlantica-nb/wfs`
- **Camada**: `prodes-mata-atlantica-nb:yearly_deforestation`
- **Filtro**: BBOX de Sao Paulo
- **Dados**: area (km2), ano, classe, satelite

#### MMA/ICMBio - Unidades de Conservacao
- **URL**: `https://dados.mma.gov.br/dataset/unidadesdeconservacao`
- **Formato**: Shapefile ZIP (CNUC) -> extraido DBF -> JSON
- **Filtro**: UF contendo 'SP'
- **Dados**: nome, categoria, grupo, esfera (Federal/Estadual/Municipal), area (ha)

#### Palmares - Comunidades Quilombolas
- **URL**: Google Sheets da Fundacao Cultural Palmares (export CSV)
- **Filtro**: UF = 'SP'
- **Dados**: municipio, nome da comunidade, numero do processo, data de publicacao

### Arquivos Gerados

Todos salvos em `API/dados/`:

```
dados/
  funai_terras_indigenas_sp.json   (2.3 MB - GeoJSON com poligonos)
  queimadas_focos_sp.json          (4.6 MB - pontos com coordenadas)
  deter_desmatamento_sp.json       (119 KB - GeoJSON com poligonos)
  prodes_desmatamento_sp.json      (variavel - desmatamento anual)
  unidades_conservacao_sp.json     (2.5 MB - dados tabulares)
  palmares_quilombolas_sp.json     (variavel - dados tabulares)
  deter_amazonia_sp.json           (minimo - SP fora da Amazonia)
  sicar_imoveis_sp.json            (minimo - servidor indisponivel)
  resumo_coleta.json               (resumo com totais e status)
```

---

## Pipeline de PLN

Implementa as 5 etapas do pipeline de Processamento de Linguagem Natural conforme ensinado no semestre:

### Etapa 1 - Pre-processamento (`preprocessador.py`)

```python
entrada: "Houve queimadas em Avai nos ultimos meses?"

tokenizacao (NLTK):     ["Houve", "queimadas", "em", "Avai", "nos", "ultimos", "meses", "?"]
remocao stopwords:      ["queimadas", "Avai", "ultimos", "meses"]
stemming (RSLPStemmer): ["queim", "avai", "ultim", "mes"]
lematizacao (SpaCy):    ["queimada", "avai", "ultimo", "mes"]
```

**Tecnologias**: NLTK (tokenizacao, stopwords PT, RSLPStemmer), SpaCy (pt_core_news_sm)

### Etapa 2 - Extracao de Caracteristicas (`extrator_caracteristicas.py`)

Tres representacoes numericas do texto:

| Metodo | Descricao | Uso |
|--------|-----------|-----|
| **Bag of Words** | CountVectorizer (unigrams + bigrams) | Baseline |
| **TF-IDF** | TfidfVectorizer (sublinear_tf, ngrams 1-2) | Classificacao de intencao |
| **Embeddings** | sentence-transformers MiniLM (384 dims) | Busca semantica |

### Etapa 3 - Modelo de Linguagem (`modelo_linguagem.py`)

Constroi as matrizes TF-IDF e de embeddings do corpus ASG (~17.000 documentos textualizados).

### Etapa 4 - Treinamento de IA (`classificador.py`)

Classificador **Naive Bayes Multinomial** treinado com TF-IDF para detectar a intencao do usuario:

| Intencao | Exemplo | Tabela consultada |
|----------|---------|-------------------|
| `consultar_queimadas` | "Houve fogo em Bauru?" | queimadas |
| `consultar_terra_indigena` | "Terras indigenas em Ubatuba" | terras_indigenas |
| `consultar_desmatamento` | "Desmatamento no Cerrado" | desmatamento_alertas |
| `consultar_unidade_conservacao` | "UCs em Bertioga" | unidades_conservacao |
| `consultar_quilombola` | "Quilombolas no Vale do Ribeira" | comunidades_quilombolas |
| `consultar_prodes` | "Desmatamento anual na Mata Atlantica" | prodes_desmatamento |
| `resumo_municipal` | "Situacao ambiental de Campinas" | todas |

- **Dados de treino**: 111 exemplos rotulados manualmente (`dados_treinamento/intencoes.json`)
- **Acuracia**: >90% com validacao cruzada
- **Modelo salvo**: `modelos_salvos/classificador_intencao.pkl`

### Etapa 5 - Aplicacao (`buscador_semantico.py`)

Busca hibrida combinando:
1. **Similaridade vetorial** (pgvector): embedding da pergunta vs embeddings do corpus
2. **Filtros estruturados**: fonte, municipio, periodo temporal

```sql
SELECT texto, municipio, fonte, metadados_json,
       1 - (embedding <=> :query_embedding) AS similaridade
FROM corpus_asg
WHERE fonte = :fonte AND municipio ILIKE :municipio
ORDER BY embedding <=> :query_embedding
LIMIT 15
```

### Extracao de Entidades (`entidades.py`)

- **Municipios**: SpaCy PhraseMatcher com lista dos 645 municipios de SP (IBGE)
- **Periodos temporais**: Regex para "ultimos X meses", "em 2025", etc.

---

## Banco de Dados

**PostgreSQL 16** com extensoes:
- **PostGIS**: geometrias espaciais (pontos, poligonos), indices GiST
- **pgvector**: vetores de embeddings (384 dimensoes), busca por similaridade coseno

### Schema

```
fontes
  id, nome, descricao, url_origem, data_coleta, total_registros, escopo

queimadas
  id, fonte_id (FK), latitude, longitude, data_hora, satelite,
  municipio, estado, bioma, frp, risco_fogo, precipitacao,
  geom GEOMETRY(Point, 4674)  -- indice GiST

terras_indigenas
  id, fonte_id (FK), codigo, nome, etnia, municipio, uf,
  area_ha, fase, modalidade,
  geom GEOMETRY(MultiPolygon, 4674)  -- indice GiST

desmatamento_alertas
  id, fonte_id (FK), classe, municipio, uf, data_avistamento,
  sensor, satelite, area_total_km2, area_uc_km2, nome_uc,
  geom GEOMETRY(MultiPolygon, 4674)  -- indice GiST

unidades_conservacao
  id, fonte_id (FK), nome, categoria, grupo, esfera, uf,
  municipio, area_ha, situacao

prodes_desmatamento
  id, fonte_id (FK), uid, estado, classe_principal, classe_nome,
  data_imagem, ano, area_km, fonte_bioma, satelite, sensor,
  geom GEOMETRY(MultiPolygon, 4674)  -- indice GiST

comunidades_quilombolas
  id, fonte_id (FK), municipio, uf, comunidade, codigo_ibge,
  processo_fcp, ano_certificacao, processo_incra, regiao

corpus_asg  (busca semantica)
  id, fonte, tipo_registro, municipio, data_referencia,
  texto TEXT,                    -- frase textualizada em PT-BR
  texto_preprocessado TEXT,      -- tokens/stems
  embedding vector(384),         -- embedding semantico (pgvector)
  metadados_json JSONB           -- dados originais para GeoJSON
```

### Indices

- `idx_queimadas_geom` (GiST) - consultas espaciais
- `idx_queimadas_municipio` - filtro por municipio
- `idx_queimadas_data` - filtro temporal
- `idx_ti_geom` (GiST) - cruzamento com propriedades
- `idx_prodes_geom` (GiST) - poligonos PRODES
- `idx_prodes_ano` - filtro por ano
- `idx_quilombola_municipio` - filtro por municipio
- `idx_corpus_fonte` - filtro por fonte no corpus
- `idx_corpus_municipio` - filtro por municipio no corpus

---

## API REST

**Framework**: FastAPI (Python)

### Endpoints

| Metodo | Rota | Descricao |
|--------|------|-----------|
| `GET` | `/` | Frontend web (chat + mapa) |
| `POST` | `/api/consulta` | Consulta em linguagem natural |
| `GET` | `/api/dados/queimadas` | Dados estruturados de queimadas |
| `GET` | `/api/dados/terras_indigenas` | Dados de terras indigenas |
| `GET` | `/api/dados/desmatamento` | Alertas de desmatamento |
| `GET` | `/api/dados/unidades_conservacao` | Unidades de conservacao |
| `GET` | `/api/dados/prodes` | Dados PRODES desmatamento anual |
| `GET` | `/api/dados/quilombolas` | Comunidades quilombolas |
| `GET` | `/api/geo/queimadas` | GeoJSON para mapa/QGIS |
| `GET` | `/api/geo/terras_indigenas` | GeoJSON para mapa/QGIS |
| `GET` | `/api/geo/desmatamento` | GeoJSON DETER para mapa/QGIS |
| `GET` | `/api/geo/prodes` | GeoJSON PRODES para mapa/QGIS |
| `GET` | `/api/geo/quilombolas` | Dados quilombolas (tabulares) |
| `GET` | `/api/saude` | Health check com contagens |
| `GET` | `/api/etl/historico` | Historico de execucoes ETL |
| `POST` | `/api/etl/executar` | Dispara pipeline ETL via API |

### Exemplo de Requisicao

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

### Integracao com QGIS

Os endpoints GeoJSON podem ser consumidos diretamente pelo QGIS:

1. Abrir QGIS
2. Layer > Add Layer > Add Vector Layer
3. Protocol: HTTP(S)
4. URI: `http://localhost:8000/api/geo/queimadas`
5. Os dados aparecem no mapa com geometrias corretas (EPSG:4674/SIRGAS 2000)

---

## Frontend

Interface web com dois paineis: chat (esquerda) e mapa (direita).

### Chat
- Campo de texto para perguntas em linguagem natural
- Botoes de exemplo com perguntas pre-definidas
- Respostas com resumo, estatisticas, fontes e tempo de processamento
- Botao **"Ocultar/Mostrar no mapa"** em cada resposta com dados geograficos
- Tratamento de perguntas fora do escopo (ex: "oi") com mensagem amigavel

### Mapa (Leaflet.js)
- **Base**: Imagem de satelite Esri WorldImagery (sem OpenStreetMap)
- **Marcadores**: circulos coloridos (radius 10) por tipo de fonte
  - Vermelho (#ff4444): Queimadas
  - Azul (#4488ff): Terras Indigenas (FUNAI)
  - Laranja (#ff8c00): Desmatamento (DETER)
  - Verde (#22cc66): Unidades de Conservacao (ICMBio)
  - Rosa (#e056c1): Quilombolas (Palmares)
  - Laranja escuro (#cc6600): Desmatamento PRODES
- **Painel de camadas**: toggle para ativar/desativar cada fonte no mapa (Queimadas, Terras Indigenas, DETER, PRODES)
- **Zoom inteligente**: detecta resultados pontuais e faz flyTo zoom 13 com animacao (resolve o problema de fitBounds em pontos unicos que zoomava para o mundo inteiro)
- **Popups estruturados** por fonte: exibe campos especificos (satelite, bioma, FRP para queimadas; nome, etnia, area, fase para terras indigenas; etc.)
- **Legenda dinamica**: aparece no canto inferior direito com as cores das fontes presentes
- **Botao "Limpar mapa"**: canto superior direito, remove todos os marcadores e volta ao zoom inicial de SP
- **Toggle de resultados**: usuario pode mostrar/ocultar os dados no mapa via botao no chat

---

## Estrutura de Diretorios

```
API/
  docker-compose.yml                # PostgreSQL + PostGIS + pgvector
  Dockerfile.db                     # Imagem customizada do banco
  requirements.txt                  # Dependencias Python
  .env                              # Configuracoes (porta, banco, modelos)
  |
  dados/                            # JSONs coletados (saida do Extract)
  |   queimadas_focos_sp.json
  |   funai_terras_indigenas_sp.json
  |   deter_desmatamento_sp.json
  |   unidades_conservacao_sp.json
  |   palmares_quilombolas_sp.json
  |   resumo_coleta.json
  |
  asg_sistema/                      # Pacote principal
  |   config.py                     # Configuracoes centralizadas (.env)
  |   |
  |   db/                           # Camada de banco de dados
  |   |   schema.sql                # DDL: tabelas, indices, extensoes
  |   |   conexao.py                # SQLAlchemy engine (psycopg v3)
  |   |   repositorio.py            # Queries (vetorial + espacial)
  |   |
  |   ingestao/                     # ETL: Transform + Load
  |   |   textualizador.py          # Registro -> frase em PT-BR
  |   |   carregador.py             # JSON -> PostgreSQL
  |   |   vetorizador.py            # Texto -> embedding (pgvector)
  |   |
  |   pln/                          # Pipeline PLN (5 etapas)
  |   |   preprocessador.py         # Etapa 1: tokenizacao, stemming, lemma
  |   |   extrator_caracteristicas.py # Etapa 2: BoW, TF-IDF, embeddings
  |   |   modelo_linguagem.py       # Etapa 3: representacao numerica
  |   |   classificador.py          # Etapa 4: Naive Bayes (intencao)
  |   |   buscador_semantico.py     # Etapa 5: busca vetorial pgvector
  |   |
  |   motor/                        # Orquestracao de consultas
  |   |   interpretador.py          # Pergunta -> resposta completa
  |   |   entidades.py              # Extracao: municipios, periodos
  |   |   gerador_resposta.py       # Monta resumo, fontes, GeoJSON
  |   |
  |   api/                          # API REST
  |   |   app.py                    # FastAPI factory + rotas
  |   |   esquemas.py               # Pydantic models
  |   |   rotas_consulta.py         # POST /api/consulta
  |   |   rotas_dados.py            # GET /api/dados/*
  |   |   rotas_geo.py              # GET /api/geo/* (GeoJSON)
  |   |
  |   frontend/                     # Interface web
  |       templates/index.html      # Chat + mapa
  |       static/css/estilo.css
  |       static/js/chat.js         # Logica do chat
  |       static/js/mapa.js         # Leaflet.js
  |
  scripts/                          # Scripts de operacao
  |   coletor_asg.py               # ETL: Extract (coleta de 8 fontes)
  |   etl_pipeline.py               # Orquestrador ETL completo
  |   criar_banco.py                # Executa schema.sql
  |   ingerir_dados.py              # Carrega JSONs no banco
  |   treinar_classificador.py      # Treina Naive Bayes
  |
  dados_treinamento/                # Dados para treino do classificador
  |   intencoes.json                # 75 exemplos rotulados
  |   municipios_sp.json            # 645 municipios (IBGE)
  |
  modelos_salvos/                   # Modelos serializados
  |   classificador_intencao.pkl
  |   vetorizador_tfidf.pkl
  |   label_encoder.pkl
  |
  logs/                             # Logs de execucao ETL
      historico_etl.jsonl           # Registro de cada execucao
      etl_YYYYMMDD_HHMMSS.log      # Log detalhado
```

---

## Como Executar

### Pre-requisitos

- Python 3.11+
- Docker Desktop (para PostgreSQL)
- Git
- ~2 GB de disco (modelo de embeddings + dados)

### 1. Clonar e Instalar Dependencias

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python -m spacy download pt_core_news_sm
```

### 2. Subir o Banco de Dados

```bash
docker compose up -d --build
```

Isso cria um PostgreSQL 16 com PostGIS + pgvector na porta 5433. Aguarde ~5 min na primeira vez (compila pgvector).

### 3. Criar Tabelas

```bash
python scripts/criar_banco.py
```

### 4. Executar o Pipeline ETL

```bash
# Opcao A: Pipeline completo (coleta + carga + embeddings) ~15-20 min
python scripts/etl_pipeline.py

# Opcao B: Passo a passo
python scripts/coletor_asg.py              # 1. Coletar dados das APIs (~2 min)
python scripts/ingerir_dados.py            # 2. Carregar no banco (~10 min)
python scripts/treinar_classificador.py    # 3. Treinar classificador (~5 seg)
```

**Nota**: Se der erro de memoria nos embeddings (OS error 1455), feche outros programas e rode separadamente:

```bash
python scripts/etl_pipeline.py --etapa embed
```

### 5. Treinar Classificador (se nao usou Opcao A)

```bash
python scripts/treinar_classificador.py
```

### 6. Iniciar a API

```bash
uvicorn asg_sistema.api.app:app --reload
```

Acesse: **http://127.0.0.1:8000**

---

## Tecnologias Utilizadas

| Camada | Tecnologia | Versao | Funcao |
|--------|-----------|--------|--------|
| **Linguagem** | Python | 3.13 | Toda a aplicacao |
| **API** | FastAPI | 0.115+ | REST API + servir frontend |
| **Banco** | PostgreSQL | 16 | Armazenamento principal |
| **Geoespacial** | PostGIS | 3.4 | Geometrias, consultas espaciais |
| **Vetorial** | pgvector | 0.8 | Busca semantica por similaridade |
| **PLN** | NLTK | 3.8+ | Tokenizacao, stemming, stopwords |
| **PLN** | SpaCy | 3.7+ | Lematizacao, NER, PhraseMatcher |
| **PLN** | scikit-learn | 1.5+ | TF-IDF, Naive Bayes |
| **Embeddings** | sentence-transformers | 3.0+ | Modelo multilingual MiniLM |
| **ORM** | SQLAlchemy | 2.0+ | Conexao com banco |
| **Driver** | psycopg | 3.3+ | Driver PostgreSQL (v3, sem bug de encoding) |
| **Frontend** | Leaflet.js | 1.9 | Mapa interativo |
| **Frontend** | Jinja2 | 3.1+ | Templates HTML |
| **Infra** | Docker | 24+ | Container do banco |
| **Dados** | GeoJSON | RFC 7946 | Formato de intercambio geoespacial |

---

## Configuracao

Todas as configuracoes estao no arquivo `.env` (nao requer alteracao de codigo):

```env
ASG_DB_HOST=localhost
ASG_DB_PORT=5433
ASG_DB_NOME=asg_sp
ASG_DB_USUARIO=asg_user
ASG_DB_SENHA=asg_pass

ASG_MODELO_SPACY=pt_core_news_sm
ASG_MODELO_EMBEDDINGS=sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2
ASG_DIMENSAO_EMBEDDING=384

ASG_BUSCA_TOP_K=15
ASG_CONFIANCA_MINIMA=0.3
```

---

## Requisitos Atendidos

### Requisitos do Parceiro Academico (Visiona/Fatec)

| Requisito | Status | Implementacao |
|-----------|--------|---------------|
| Python 3.x | OK | Todo o sistema |
| Dados abertos governamentais | OK | 8 fontes (INPE/Queimadas, INPE/DETER, INPE/PRODES, FUNAI, ICMBio, SICAR, Palmares) |
| Orientacao a servicos | OK | API REST FastAPI |
| Integravel com QGIS | OK | Endpoints GeoJSON (EPSG:4674) |
| Rastreabilidade das fontes | OK | Tabela `fontes` + campo `metadados_json` |
| Performance < 10s | OK | ~100ms apos carregamento inicial |
| LGPD | OK | Apenas dados publicos, sem dados pessoais |
| Pipeline ETL | OK | `etl_pipeline.py` com agendamento e logs |
| Escopo SP | OK | Todos os dados filtrados para Sao Paulo |

### Requisitos do Semestre (PLN)

| Requisito | Status | Implementacao |
|-----------|--------|---------------|
| Pipeline PLN (5 etapas) | OK | Diretorio `pln/` mapeia 1:1 com as etapas |
| Corpora de texto | OK | ~17.000 documentos textualizados no `corpus_asg` (6 fontes) |
| Tokenizacao | OK | NLTK `word_tokenize` para PT |
| Stemming | OK | NLTK `RSLPStemmer` (portugues) |
| Lematizacao | OK | SpaCy `pt_core_news_sm` |
| Bag of Words | OK | scikit-learn `CountVectorizer` |
| TF-IDF | OK | scikit-learn `TfidfVectorizer` |
| Modelo de IA | OK | `MultinomialNB` (Naive Bayes) - 7 intencoes, 111 exemplos |
| Busca semantica | OK | sentence-transformers + pgvector |

### Cobertura de Dados (banco ~66.000 registros)

| Tabela | Registros | Geometria | Fonte |
|--------|-----------|-----------|-------|
| `queimadas` | ~14.000 | Point | INPE/Queimadas |
| `prodes_desmatamento` | ~50.000 | MultiPolygon | INPE/PRODES |
| `terras_indigenas` | 29 | MultiPolygon | FUNAI |
| `desmatamento_alertas` | 31 | MultiPolygon | INPE/DETER |
| `unidades_conservacao` | ~2.147 | Tabular | MMA/ICMBio |
| `comunidades_quilombolas` | 52 | Tabular | Palmares |
| `corpus_asg` | ~17.000 | - | Todas (textos + embeddings) |

**Nota**: PRODES insere 1 amostra a cada 50 registros no corpus (~1.000 textos) para otimizar embeddings. Os 50K registros completos ficam na tabela `prodes_desmatamento` com geometria.
