# ASG-SP Back-end - Sistema de Análise Ambiental, Social e Governança

Sistema de consulta por linguagem natural a dados ASG (Ambiental, Social e Governança) de propriedades rurais do Estado de São Paulo.

## Sumário
1. [Visão Geral](#visão-geral)
2. [Pipeline ETL](#pipeline-etl)
3. [Fontes de Dados](#fontes-de-dados)
4. [Pipeline de PLN](#pipeline-de-pln)
5. [Banco de Dados](#banco-de-dados)
6. [API REST](#api-rest)
7. [Autenticação](#autenticação)
8. [Histórico de Conversas](#histórico-de-conversas)
9. [Dashboard](#dashboard)
10. [Nota de Risco ASG](#nota-de-risco-asg)
11. [Relatório PDF](#relatório-pdf)
12. [Imagens de Satélite Sentinel-2](#imagens-de-satélite-sentinel-2)
13. [Integração com QGIS](#integração-com-qgis)
14. [Como Executar](#como-executar)
15. [Tecnologias Utilizadas](#tecnologias-utilizadas)

---

## Visão Geral

O sistema permite que um usuário digite uma pergunta em linguagem natural (ex: "Houve queimadas em Avaí nos últimos meses?") e receba uma resposta estruturada com:

- Resumo textual da consulta
- Dados encontrados com fontes rastreáveis
- GeoJSON compatível com QGIS e sistemas de mapa
- Nota de risco ASG calculada via método AHP
- URL de exportação para QGIS

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
                            nota_risco: 7.4,
                            qgis_url: "http://localhost:8000/api/geo/...",
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
POST /api/v1/agendamento/

# Listar agendamentos ativos
GET /api/v1/agendamento/

# Remover agendamento
DELETE /api/v1/agendamento/{id}

# Disparar ETL imediatamente via API
POST /api/etl/executar?etapa=full&skip_sicar=false

# Acompanhar status de uma execução
GET /api/etl/status/{execution_id}
```

O cooldown padrão entre execuções é de 6 horas (configurável). O histórico de execuções fica em `/api/etl/historico`.

### Status em Tempo Real do ETL

Cada execução via API gera um `execution_id` único. O endpoint `/api/etl/status/{execution_id}` retorna o estado detalhado da execução:

```json
{
  "execution_id": "abc123...",
  "etapa_atual": "pipeline",
  "status_execucao": "em_andamento",
  "finalizado": false,
  "mensagem": "Iniciando subprocesso ETL (etapa: full).",
  "eventos": [...]
}
```

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
| `consultar_status_fazenda` | "Qual o status da fazenda com CAR SP-123?" | sicar_imoveis |

- **Dados de treino**: 111 exemplos rotulados manualmente (`dados_treinamento/intencoes.json`)
- **Acurácia**: >90% com validação cruzada
- **Modelo salvo**: `modelos_salvos/classificador_intencao.pkl`

### Etapa 5 - Aplicação (`buscador_semantico.py`)

Busca híbrida combinando:
1. **Similaridade vetorial** (pgvector): embedding da pergunta vs embeddings do corpus
2. **Filtros estruturados**: fonte, município, período temporal
3. **Intenções múltiplas**: detecta palavras-chave secundárias e faz merge de resultados de fontes diferentes
4. **Tolerância a erros tipográficos**: busca fuzzy de municípios para maior resiliência

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
- **Código CAR**: Extração e validação de código CAR/SICAR dentro da pergunta

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
| `usuarios` | — | — | Sistema (autenticação) |
| `conversas` | — | — | Sistema (histórico) |
| `mensagens` | — | — | Sistema (histórico) |

**Nota PRODES**: insere 1 amostra a cada 50 registros no corpus (~1.000 textos) para otimizar tempo de embedding. Os 50K registros completos ficam na tabela `prodes_desmatamento` com geometria.

**Nota SICAR**: os ~466K imóveis rurais são carregados na tabela `sicar_imoveis`. No corpus, 1 amostra a cada 50 registros (~9.300 textos).

---

## API REST

**Framework**: FastAPI (Python)

### Endpoints

| Método | Rota | Descrição | Auth |
|--------|------|-----------|------|
| `POST` | `/api/consulta` | Consulta em linguagem natural | Sim |
| `GET` | `/api/dados/queimadas` | Dados estruturados de queimadas | Sim |
| `GET` | `/api/dados/terras_indigenas` | Dados de terras indígenas | Sim |
| `GET` | `/api/dados/desmatamento` | Alertas de desmatamento | Sim |
| `GET` | `/api/dados/unidades_conservacao` | Unidades de conservação | Sim |
| `GET` | `/api/dados/prodes` | Dados PRODES desmatamento anual | Sim |
| `GET` | `/api/dados/quilombolas` | Comunidades quilombolas | Sim |
| `GET` | `/api/dados/queimadas/{id}/imagem-satelite` | Imagem Sentinel-2 da queimada | Sim |
| `GET` | `/api/geo/queimadas` | GeoJSON para mapa/QGIS | Sim |
| `GET` | `/api/geo/terras_indigenas` | GeoJSON para mapa/QGIS | Sim |
| `GET` | `/api/geo/desmatamento` | GeoJSON DETER para mapa/QGIS | Sim |
| `GET` | `/api/geo/prodes` | GeoJSON PRODES para mapa/QGIS | Sim |
| `GET` | `/api/geo/quilombolas` | Dados quilombolas (tabulares) | Sim |
| `GET` | `/api/dashboard` | Dashboard completo (métricas + municípios + anos) | Sim |
| `GET` | `/api/dashboard/metricas` | Métricas consolidadas | Sim |
| `GET` | `/api/dashboard/municipios` | Dados agregados por município | Sim |
| `GET` | `/api/dashboard/anos` | Dados agregados por ano | Sim |
| `GET` | `/api/historico` | Lista conversas do usuário autenticado | Sim |
| `GET` | `/api/historico/todos` | Lista histórico de todos os usuários (ADMIN) | Admin |
| `GET` | `/api/historico/{conversa_id}` | Detalhes de uma conversa | Sim |
| `DELETE` | `/api/historico/{conversa_id}` | Exclui uma conversa | Sim |
| `GET` | `/api/saude` | Health check com contagens por tabela | Não |
| `GET` | `/api/etl/historico` | Histórico de execuções ETL | Sim |
| `GET` | `/api/etl/status/{execution_id}` | Status detalhado de uma execução ETL | Sim |
| `POST` | `/api/etl/executar` | Dispara pipeline ETL via API | Admin |
| `GET` | `/api/v1/agendamento/` | Lista agendamentos ativos | Admin |
| `POST` | `/api/v1/agendamento/` | Cria novo agendamento ETL | Admin |
| `DELETE` | `/api/v1/agendamento/{id}` | Remove agendamento | Admin |

### Exemplo de Requisição

```bash
curl -X POST http://localhost:8000/api/consulta \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <token>" \
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
  "nota_risco": 7.4,
  "fontes": [{"nome": "FUNAI", "identificador": "funai"}],
  "geojson": {
    "type": "FeatureCollection",
    "features": [...]
  },
  "qgis_url": "http://localhost:8000/api/geo/terras_indigenas?municipio=Ubatuba",
  "exportacao_relatorio": {...},
  "total_resultados": 2,
  "tempo_processamento_ms": 88.1
}
```

---

## Autenticação

O sistema utiliza **JWT (JSON Web Token)** para autenticação. Todos os endpoints de dados exigem o header `Authorization: Bearer <token>`.

### Endpoints de Autenticação

| Método | Rota | Descrição | Auth |
|--------|------|-----------|------|
| `POST` | `/api/v1/auth/login` | Login com e-mail e senha | Não |
| `POST` | `/api/v1/auth/cadastro` | Cria novo usuário | Admin |
| `POST` | `/api/v1/auth/alterar-senha` | Altera a própria senha | Sim |
| `GET` | `/api/v1/auth/usuarios` | Lista todos os usuários | Admin |
| `PUT` | `/api/v1/auth/usuarios/{id}` | Edita dados de um usuário | Sim* |
| `DELETE` | `/api/v1/auth/usuarios/{id}` | Exclui usuário | Admin |
| `POST` | `/api/v1/auth/esqueci-senha` | Envia link de redefinição por e-mail | Não |
| `POST` | `/api/v1/auth/redefinir-senha` | Redefine a senha via token do e-mail | Não |

> `*` ADMIN pode editar qualquer usuário; USER só pode editar a si mesmo.

### Papéis

| Papel | Permissões |
|-------|-----------|
| `ADMIN` | Acesso total: cadastro, exclusão, listagem de usuários, ETL, histórico de todos |
| `USER` | Consultas, histórico próprio, edição do próprio perfil |

### Recuperação de Senha

O fluxo de "Esqueci minha senha" envia um link por e-mail com token JWT de uso único (válido por 15 minutos). O token nunca revela se o e-mail está ou não cadastrado no sistema.

```bash
# 1. Solicitar link de redefinição
POST /api/v1/auth/esqueci-senha
{ "email": "usuario@empresa.com" }

# 2. Clicar no link recebido por e-mail e enviar nova senha
POST /api/v1/auth/redefinir-senha
{ "token": "<token_do_email>", "nova_senha": "NovaSenha@123" }
```

Variáveis de ambiente necessárias para envio de e-mail:

```env
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=seu_email@gmail.com
SMTP_PASSWORD=sua_senha_de_app
FRONTEND_URL=http://localhost:3000
```

---

## Histórico de Conversas

O sistema persiste automaticamente cada conversa do usuário no banco de dados, permitindo retomar o contexto de consultas anteriores.

### Estrutura

- **Conversa**: agrupamento de mensagens com título gerado automaticamente pela primeira pergunta
- **Mensagem**: cada turno (usuário ou sistema), com timestamp
- **MensagemDados**: dados geoespaciais associados à resposta (GeoJSON, estatísticas, nota de risco)

### Endpoints

```bash
# Listar conversas do usuário
GET /api/historico

# Obter mensagens de uma conversa (com dados GeoJSON embutidos)
GET /api/historico/{conversa_id}

# Excluir uma conversa
DELETE /api/historico/{conversa_id}

# [ADMIN] Listar histórico de todos os usuários
GET /api/historico/todos
```

---

## Dashboard

O dashboard agrega os dados ambientais do Estado de SP para visualização gerencial.

### Endpoints

```bash
# Dashboard completo (único endpoint)
GET /api/dashboard

# Apenas métricas gerais
GET /api/dashboard/metricas

# Dados por município (limite configurável, padrão 20)
GET /api/dashboard/municipios?limite=20

# Dados por ano
GET /api/dashboard/anos
```

### Métricas Disponíveis

- Total de propriedades rurais cadastradas (SICAR)
- Média de risco de fogo
- Totais de queimadas, alertas de desmatamento, UCs, terras indígenas, quilombolas
- Área total de propriedades (hectares) e área desmatada (km²)
- Dados temporais: queimadas e desmatamento por ano
- Dados geográficos: ranking de municípios por ocorrências

---

## Nota de Risco ASG

Cada resposta de consulta inclui uma **nota de risco ASG** calculada pelo método **AHP (Analytic Hierarchy Process)**, que pondera múltiplos critérios ambientais, sociais e de governança:

| Critério | Peso | Descrição |
|----------|------|-----------|
| Queimadas | Alto | Focos de incêndio próximos ao imóvel |
| Desmatamento | Alto | Alertas DETER/PRODES na região |
| Unidades de Conservação | Médio | Sobreposição com UCs |
| Terras Indígenas | Médio | Sobreposição com TIs |
| Comunidades Quilombolas | Médio | Proximidade com comunidades certificadas |
| Imóvel Rural (CAR) | Baixo | Regularidade no cadastro |

A nota varia de **0 a 10** (quanto maior, maior o risco socioambiental). Respostas agrupam os resultados por tipo de dado para facilitar a análise.

---

## Relatório PDF

O sistema gera relatórios ASG em PDF para imóveis rurais, consolidando todos os dados encontrados em um documento estruturado.

```bash
# Exportar relatório de uma consulta em PDF
POST /api/fazenda/relatorio
{ "car": "SP-3509502-...", "pergunta": "Situação ambiental da fazenda" }
```

O relatório inclui:
- Mapa com geometria do imóvel e ocorrências ao redor
- Nota de risco ASG com detalhamento por critério
- Tabelas de queimadas, desmatamento, UCs e TIs próximas
- Fontes dos dados com rastreabilidade

---

## Imagens de Satélite Sentinel-2

Para cada foco de queimada, é possível obter uma imagem de satélite recortada do **Sentinel-2 (L2A)** via Microsoft Planetary Computer.

```bash
# Obter imagem de satélite de um foco de queimada
GET /api/dados/queimadas/{id}/imagem-satelite

# Forçar lat/lon/data (sobrescreve banco)
GET /api/dados/queimadas/{id}/imagem-satelite?lat=-22.9&lon=-47.1&data=2025-03-01
```

**Funcionamento**:
1. Busca coordenadas e data no banco pelo `id`
2. Verifica cache em disco (`static/sentinel_cache/`)
3. Se sem cache: busca no Planetary Computer (±10 dias, cobertura de nuvem < 80%), recorta ~3 km ao redor do ponto e normaliza a imagem
4. Retorna PNG via `StreamingResponse` com header `X-Cache: HIT|MISS`

---

## Integração com QGIS

O sistema exporta dados GeoJSON prontos para visualização no QGIS. Cada resposta de consulta já inclui a `qgis_url` correspondente.

### Via URL direta

1. Abrir QGIS
2. Layer > Add Layer > Add Vector Layer
3. Protocol: HTTP(S)
4. URI: `http://localhost:8000/api/geo/queimadas`
5. Os dados aparecem no mapa com geometrias corretas (EPSG:4674/SIRGAS 2000)

### Camadas disponíveis para exportação

| Camada | URL |
|--------|-----|
| Queimadas | `/api/geo/queimadas` |
| Terras Indígenas | `/api/geo/terras_indigenas` |
| Desmatamento (DETER) | `/api/geo/desmatamento` |
| Desmatamento (PRODES) | `/api/geo/prodes` |
| Quilombolas | `/api/geo/quilombolas` |

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

Edite `.env` com as credenciais do banco e configurações de e-mail:

```env
DATABASE_URL=postgresql://user:pass@localhost:5433/asg_db
SECRET_KEY=sua_chave_secreta_jwt
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=seu_email@gmail.com
SMTP_PASSWORD=sua_senha_de_app
FRONTEND_URL=http://localhost:3000
```

### 2. Instalar Dependências

```bash
python -m venv .venv
# Windows:
.venv\Scripts\activate
# Linux/macOS:
source venv/bin/activate

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
python scripts/coletar_sicar.py
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

Documentação interativa: **http://127.0.0.1:8000/docs**

---

## Tecnologias Utilizadas

| Camada | Tecnologia | Versão | Função |
|--------|-----------|--------|--------|
| **Linguagem** | Python | 3.13 | Toda a aplicação |
| **API** | FastAPI | 0.115+ | REST API |
| **Autenticação** | python-jose / passlib | — | JWT, hash de senhas |
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
| **PDF** | WeasyPrint / Jinja2 | — | Geração de relatórios PDF |
| **Satélite** | pystac-client / rasterio | — | Imagens Sentinel-2 via Planetary Computer |
| **Infra** | Docker | 24+ | Container do banco |
| **CI/CD** | GitHub Actions + AWS ECS | — | Deploy automático |
| **Dados** | GeoJSON | RFC 7946 | Formato de intercâmbio geoespacial |
