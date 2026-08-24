# Plano - Car Datalog no picasso-repo

Este documento descreve a inclusao do datalog veicular no `picasso-repo`, assumindo que o Raspberry Pi envia arquivos `JSONL` brutos para o repositorio de dados montado em `/repository`.

## Objetivo

Permitir que o usuario, pela UI web do `picasso-repo`, consiga:

- listar sessoes de datalog
- abrir uma sessao especifica
- visualizar metadados e estatisticas da sessao
- plotar graficos de variaveis OBD, GPS e contexto
- baixar o `JSONL` bruto da sessao

## Premissas

- Fonte da verdade: filesystem montado em `/repository`
- Host tipico: `/Volumes/MacSSD/Data/picasso-repository` ou equivalente
  configurado em `--data-dir`
- Diretorio de datalog: `/repository/Car_datalog/`
- Formato de ingestao: `JSONL` bruto, uma linha por snapshot
- Cada arquivo representa uma sessao

## Estrutura esperada no filesystem

Os arquivos recebidos do carro devem permanecer crus:

```text
/repository/Car_datalog/<device>/<yyyy>/<mm>/<dd>/<vin>/session-YYYY-MM-DDTHH-MM-SSZ.jsonl
```

Exemplo:

```text
/repository/Car_datalog/c3-picasso-2013/2026/05/07/935F.../session-2026-05-07T02-35-29Z.jsonl
```

## Decisoes de arquitetura

- Manter `JSONL` bruto como formato canonico
- Nao transformar no Raspberry Pi
- Nao armazenar todas as amostras no SQLite no MVP
- Usar SQLite apenas para indice e metadados de sessoes
- Ler a serie temporal detalhada sob demanda a partir do arquivo
- Tolerar ultima linha truncada para lidar com desligamento abrupto do Raspberry Pi
- Integrar o datalog ao `POST /api/sync` ja existente

## Modelo de dados no SQLite

Adicionar tabelas novas em `backend/database.py`.

### Tabela `car_log_sessions`

- `session_id TEXT PRIMARY KEY`
- `device_name TEXT NOT NULL`
- `vin TEXT`
- `vehicle TEXT`
- `relative_path TEXT NOT NULL UNIQUE`
- `file_size INTEGER NOT NULL`
- `sample_count INTEGER NOT NULL`
- `started_at TEXT`
- `ended_at TEXT`
- `duration_s REAL`
- `first_logged_at TEXT`
- `last_logged_at TEXT`
- `first_sample_time TEXT`
- `last_sample_time TEXT`
- `wifi_seen BOOLEAN`
- `gps_seen BOOLEAN`
- `gps_fix_seen BOOLEAN`
- `created_at TEXT NOT NULL`
- `updated_at TEXT NOT NULL`
- `scan_mtime REAL NOT NULL`

### Tabela `car_log_session_fields`

- `session_id TEXT NOT NULL`
- `field_path TEXT NOT NULL`
- `min_value REAL`
- `max_value REAL`
- `avg_value REAL`
- `last_value REAL`
- `sample_count INTEGER`
- `PRIMARY KEY (session_id, field_path)`
- `FOREIGN KEY (session_id) REFERENCES car_log_sessions(session_id) ON DELETE CASCADE`

Uso:

- `car_log_sessions`: lista rapida e filtros
- `car_log_session_fields`: saber quais variaveis existem e montar resumo sem reparsear tudo

## Parser e scanner

Criar novo modulo:

- `backend/carlog_scanner.py`

Responsabilidades:

- varrer `/repository/Car_datalog/**/*.jsonl`
- detectar sessoes novas ou alteradas por `mtime` e `size`
- parsear arquivo linha a linha
- ignorar ultima linha invalida/truncada sem invalidar a sessao inteira
- extrair metadados da sessao
- calcular estatisticas por campo numerico
- atualizar as tabelas novas

### Regras de parsing

Usar dotted paths para variaveis:

- `direct.rpm`
- `direct.speed_kmh`
- `direct.o2_b1s1_voltage_v`
- `inferred.instant_km_l`
- `gps.speed`
- `wifi.connected`
- `time_context.wifi_connected`

So campos numericos e booleanos entram como series/graficos.

Strings, listas e objetos ficam como metadados.

Booleanos podem ser convertidos para `0/1` quando plotados.

## API nova

Criar novo router:

- `backend/api/car_logs.py`

Registrar em `backend/main.py`.

### Endpoints

#### `GET /api/car-logs/sessions`

Lista sessoes.

Filtros sugeridos:

- `device`
- `vin`
- `date_from`
- `date_to`
- `has_gps`
- `has_wifi`
- `q`
- `skip`
- `limit`

Ordenacao padrao:

- `started_at DESC`

#### `GET /api/car-logs/sessions/{session_id}`

Retorna:

- metadados da sessao
- estatisticas resumidas
- lista de campos disponiveis

#### `GET /api/car-logs/sessions/{session_id}/preview`

Retorna:

- primeiras `N` amostras
- ultimas `N` amostras

Uso:

- debug
- confirmar integridade

#### `GET /api/car-logs/sessions/{session_id}/series`

Parametros:

- `fields=direct.rpm,direct.speed_kmh,...`
- `time_axis=sample_time|logged_at|relative_s`
- `max_points=1000`

Retorno:

- pontos prontos para graficos
- unidades e labels

Formato sugerido:

```json
{
  "session": {
    "session_id": "session-2026-05-07T02-35-29Z",
    "started_at": "2026-05-07T02:35:29.519474+00:00",
    "ended_at": "2026-05-07T02:38:13.510790+00:00",
    "sample_count": 164
  },
  "time_axis": "relative_s",
  "series": [
    {
      "field": "direct.rpm",
      "label": "RPM",
      "unit": "rpm",
      "points": [[0.0, 850], [1.0, 900]]
    }
  ]
}
```

#### `GET /api/car-logs/sessions/{session_id}/raw`

Retorna o arquivo `JSONL` bruto.

#### `POST /api/car-logs/sync`

Opcional no MVP.

Pode ser omitido se o `POST /api/sync` passar a sincronizar tambem o datalog.

## Integracao com `/api/sync`

Ampliar `POST /api/sync` em `backend/main.py` para:

- sincronizar musicas/playlists como hoje
- sincronizar tambem `Car_datalog`

Resposta sugerida:

```json
{
  "synced_tracks": 123,
  "synced_playlists": 8,
  "synced_car_log_sessions": 41,
  "updated_car_log_sessions": 3
}
```

## UI web

Adicionar um novo item na sidebar:

- `Car Datalog`

Arquivo impactado:

- `frontend/index.html`
- `frontend/js/app.js`
- `frontend/js/api.js`
- `frontend/css/style.css`

## UX proposta

### Vista 1 - Lista de sessoes

Rota SPA:

- `#car-logs`

Conteudo:

- filtros por device, VIN e periodo
- cards ou tabela de sessoes
- campos exibidos:
  - inicio
  - duracao
  - device
  - VIN
  - tamanho do arquivo
  - numero de amostras
  - GPS disponivel?
  - Wi-Fi visto?

Acoes por sessao:

- abrir sessao
- baixar `JSONL`

### Vista 2 - Detalhe da sessao

Ao abrir uma sessao, mostrar:

- cabecalho:
  - `session_id`
  - inicio/fim
  - duracao
  - samples
  - tamanho
  - device
  - VIN

- resumo:
  - velocidade maxima
  - RPM maximo
  - coolant maximo
  - tensao minima
  - consumo instantaneo medio, se houver

- seletor de variaveis
- grafico principal
- bloco de debug/raw preview

### Vista 3 - Graficos

Presets sugeridos:

- `Motor`
  - `direct.rpm`
  - `direct.engine_load_pct`
  - `direct.throttle_pct`
  - `direct.timing_advance_deg`

- `Combustao`
  - `direct.short_fuel_trim_b1_pct`
  - `direct.long_fuel_trim_b1_pct`
  - `direct.o2_b1s1_voltage_v`
  - `direct.o2_b1s2_voltage_v`

- `Temperaturas`
  - `direct.coolant_temp_c`
  - `direct.intake_temp_c`

- `Consumo`
  - `inferred.instant_km_l`
  - `inferred.selected_fuel_rate_l_h`
  - `inferred.trip_average_km_l`

- `Movimento`
  - `direct.speed_kmh`
  - `gps.speed`

### Eixo do tempo

Padrao recomendado:

- `relative_s`

Opcoes secundarias:

- `sample_time`
- `logged_at`

## Biblioteca de graficos

Recomendacao:

- `uPlot`

Motivo:

- leve
- rapido para muitas amostras
- bom encaixe em SPA vanilla JS

Alternativa aceitavel:

- `Chart.js`

## Downsampling

Necessario para sessoes maiores.

MVP:

- downsampling por stride uniforme no backend usando `max_points`

Fase seguinte:

- min/max por bucket para preservar picos

## Tratamento de arquivos em crescimento

Como uma sessao atual pode estar sendo sincronizada enquanto ainda cresce:

- o scanner deve reprocessar arquivo se `mtime` ou `size` mudarem
- a ultima linha invalida deve ser ignorada
- o arquivo nao deve ser marcado como corrompido por isso

## Fases de implementacao

### Fase 1 - Backend MVP

- migrar SQLite com tabelas de datalog
- criar `backend/carlog_scanner.py`
- integrar scanner ao startup e ao `POST /api/sync`
- criar router `backend/api/car_logs.py`
- implementar:
  - `GET /api/car-logs/sessions`
  - `GET /api/car-logs/sessions/{session_id}`
  - `GET /api/car-logs/sessions/{session_id}/raw`

### Fase 2 - UI de sessoes

- adicionar item `Car Datalog` na sidebar
- criar tela de listagem
- filtros basicos
- abrir detalhe da sessao

### Fase 3 - Graficos por sessao

- implementar endpoint `/series`
- criar tela de detalhe com seletor de variaveis
- graficos com `uPlot`
- presets de variaveis

### Fase 4 - Refinos

- preview raw
- downsampling melhor
- cards de resumo no dashboard principal
- comparacao entre sessoes

## Arquivos previstos

Novos:

- `backend/carlog_scanner.py`
- `backend/api/car_logs.py`

Alterados:

- `backend/main.py`
- `backend/database.py`
- `backend/models.py`
- `frontend/index.html`
- `frontend/js/api.js`
- `frontend/js/app.js`
- `frontend/css/style.css`

## Criterios de aceite do MVP

- sessoes em `Car_datalog/` aparecem indexadas na UI
- usuario consegue listar sessoes e abrir uma especifica
- usuario consegue baixar o `JSONL` bruto
- usuario consegue plotar ao menos:
  - `direct.rpm`
  - `direct.speed_kmh`
  - `direct.coolant_temp_c`
  - `inferred.instant_km_l`
  - `gps.speed` quando existir
- arquivos com ultima linha truncada nao quebram a indexacao

## Recomendacao final

Implementar primeiro o caminho completo de leitura:

1. scanner
2. indice SQLite
3. API de sessoes
4. UI de listagem
5. graficos sob demanda

Sem tentar normalizar tudo em banco na primeira iteracao.

## Plano detalhado por commit

### Commit 1 - Base do datalog no banco e nos modelos

Objetivo:

- preparar o `picasso-repo` para indexar sessoes de datalog no SQLite

Arquivos:

- `backend/database.py`
- `backend/models.py`

Mudancas:

- adicionar tabelas:
  - `car_log_sessions`
  - `car_log_session_fields`
- adicionar modelos Pydantic para:
  - resumo de sessao
  - detalhe de sessao
  - estatisticas por campo
  - resposta de series

Critério de aceite:

- o app sobe sem quebrar
- o SQLite passa a ter as tabelas novas
- nenhum endpoint atual de musica/playlists regressa

### Commit 2 - Scanner de `Car_datalog`

Objetivo:

- indexar arquivos `JSONL` de sessoes no filesystem

Arquivos:

- `backend/carlog_scanner.py` novo
- `backend/config.py` opcionalmente com constante para subpasta `Car_datalog`

Mudancas:

- criar scanner que varre `/repository/Car_datalog/**/*.jsonl`
- parse linha a linha
- ignorar ultima linha truncada/invalida
- extrair:
  - `session_id`
  - `device_name`
  - `vin`
  - `vehicle`
  - `sample_count`
  - `file_size`
  - `started_at`
  - `ended_at`
  - `duration_s`
  - indicadores de GPS/Wi-Fi
- calcular estatisticas por campo numerico
- gravar no SQLite

Critério de aceite:

- arquivos de sessao existentes passam a aparecer indexados no banco
- arquivos com ultima linha truncada nao derrubam a indexacao

### Commit 3 - Integracao do scanner no startup e no sync geral

Objetivo:

- fazer o datalog ser indexado automaticamente

Arquivos:

- `backend/main.py`

Mudancas:

- no startup (`lifespan`), rodar tambem o scanner de datalog
- ampliar `POST /api/sync` para incluir datalog
- resposta do sync passa a incluir:
  - `synced_car_log_sessions`
  - `updated_car_log_sessions`

Critério de aceite:

- ao subir o serviço, o datalog ja aparece no banco
- `POST /api/sync` reindexa tambem `Car_datalog`

### Commit 4 - API de listagem e detalhe de sessoes

Objetivo:

- expor sessoes indexadas para a UI

Arquivos:

- `backend/api/car_logs.py` novo
- `backend/main.py`

Mudancas:

- criar endpoints:
  - `GET /api/car-logs/sessions`
  - `GET /api/car-logs/sessions/{session_id}`
  - `GET /api/car-logs/sessions/{session_id}/raw`
- suportar filtros:
  - `device`
  - `vin`
  - `date_from`
  - `date_to`
  - `has_gps`
  - `has_wifi`
  - `skip`
  - `limit`

Critério de aceite:

- cliente HTTP consegue listar sessoes
- cliente HTTP consegue abrir detalhe de uma sessao
- cliente HTTP consegue baixar o `JSONL` bruto

### Commit 5 - API de series por sessao

Objetivo:

- expor dados temporais para os graficos

Arquivos:

- `backend/api/car_logs.py`
- `backend/carlog_scanner.py` se precisar de utilitarios compartilhados

Mudancas:

- criar endpoint:
  - `GET /api/car-logs/sessions/{session_id}/series`
- aceitar parametros:
  - `fields`
  - `time_axis`
  - `max_points`
- implementar downsampling simples por stride no backend
- suportar eixos:
  - `relative_s`
  - `sample_time`
  - `logged_at`

Critério de aceite:

- uma sessao retorna series numericas plotaveis
- sessoes maiores nao explodem o browser por excesso de pontos

### Commit 6 - Navegacao e tela de lista na SPA

Objetivo:

- tornar o datalog visivel na UI web

Arquivos:

- `frontend/index.html`
- `frontend/js/api.js`
- `frontend/js/app.js`
- `frontend/css/style.css`

Mudancas:

- adicionar item `Car Datalog` na sidebar
- adicionar rota SPA `#car-logs`
- implementar tela de listagem com:
  - filtros
  - cards/tabela de sessoes
  - acao de abrir sessao
  - acao de baixar raw

Critério de aceite:

- usuario ve a lista de sessoes no browser
- consegue filtrar e abrir uma sessao

### Commit 7 - Detalhe da sessao

Objetivo:

- mostrar os metadados de uma sessao de forma util

Arquivos:

- `frontend/js/app.js`
- `frontend/css/style.css`

Mudancas:

- criar view de detalhe da sessao
- mostrar:
  - `session_id`
  - inicio/fim
  - duracao
  - tamanho
  - numero de amostras
  - device
  - VIN
  - indicadores de GPS/Wi-Fi
- mostrar estatisticas resumidas de campos importantes

Critério de aceite:

- usuario abre uma sessao e entende rapidamente do que se trata

### Commit 8 - Graficos por sessao

Objetivo:

- permitir analise visual das variaveis

Arquivos:

- `frontend/js/app.js`
- `frontend/css/style.css`
- opcional: `frontend/js/charting.js` novo, se preferir separar

Mudancas:

- implementar grafico principal
- permitir selecionar variaveis
- incluir presets:
  - Motor
  - Combustao
  - Temperaturas
  - Consumo
  - Movimento
- usar `relative_s` por padrao

Critério de aceite:

- usuario consegue plotar ao menos:
  - `direct.rpm`
  - `direct.speed_kmh`
  - `direct.coolant_temp_c`
  - `inferred.instant_km_l`
  - `gps.speed` quando existir

### Commit 9 - Preview raw e robustez de debug

Objetivo:

- facilitar depuracao e validacao das sessoes

Arquivos:

- `backend/api/car_logs.py`
- `frontend/js/app.js`
- `frontend/css/style.css`

Mudancas:

- adicionar endpoint:
  - `GET /api/car-logs/sessions/{session_id}/preview`
- mostrar primeiras/ultimas amostras no detalhe
- mostrar avisos:
  - arquivo mudou desde o ultimo scan
  - linhas invalidas ignoradas
  - sessao ainda em crescimento

Critério de aceite:

- usuario tecnico consegue verificar integridade basica de uma sessao sem sair da UI

### Commit 10 - Dashboard e refinamento do sync

Objetivo:

- integrar o datalog ao fluxo principal do produto

Arquivos:

- `frontend/js/app.js`
- `frontend/css/style.css`
- `backend/main.py`

Mudancas:

- adicionar cards de datalog no dashboard:
  - total de sessoes
  - espaco usado por datalog
  - ultimo sync
- atualizar mensagem do `POST /api/sync`
- opcionalmente adicionar contador de sessoes novas/reindexadas

Critério de aceite:

- dashboard principal passa a refletir tambem o estado do datalog

## Ordem recomendada de implementacao

Sequencia exata recomendada:

1. Commit 1
2. Commit 2
3. Commit 3
4. Commit 4
5. Commit 6
6. Commit 7
7. Commit 5
8. Commit 8
9. Commit 9
10. Commit 10

Motivo:

- primeiro deixar ingestao e indexacao solidas
- depois listar e abrir sessoes
- so depois investir em graficos e refinamentos de UX

## MVP minimo para considerar entregue

O MVP pode ser considerado entregue ao final do Commit 8, desde que:

- sessoes aparecam na UI
- detalhe de sessao funcione
- `JSONL` bruto possa ser baixado
- graficos basicos de variaveis principais funcionem

Os commits 9 e 10 sao refinamentos importantes, mas nao bloqueiam o valor principal para o usuario.
