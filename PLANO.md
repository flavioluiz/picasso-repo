# Plano de Implementação: PiCASSO Media Manager

## Contexto

O repositório está em `~/github/PiCASSO_Repo`. O diretório de dados montado no container é `~/Documents/PiCASSO_Repository` (conforme `create-service.sh`).

A arquitetura atual é um container Alpine com SSH/SFTP + um servidor HTTP Python simples (`web-status.py`) servindo uma página estática de estatísticas, orquestrado via Podman com um sidecar Tailscale.

Este plano propõe evoluir esse serviço para uma **aplicação web fullstack** com CRUD completo de músicas e playlists, integração com YouTube (`yt-dlp`) e upload de MP3, mantendo a mesma infraestrutura de container Podman + Tailscale.

---

## 1. Visão Geral da Arquitetura

Manteremos a estrutura existente de **Podman Pod + Tailscale sidecar**, mas vamos evoluir o container principal de um servidor HTTP estático simples para uma **aplicação web fullstack** dentro do mesmo container.

**Por que tudo no mesmo container?**
O serviço é pequeno e focado. Separar backend/frontend em containers distintos adicionaria complexidade de rede interna e volumes compartilhados sem ganho real. O frontend (HTML/JS/CSS estático) será servido pelo próprio Uvicorn via `StaticFiles`.

### Stack Tecnológica
- **Backend:** FastAPI (Python) + Uvicorn
- **Banco de Dados:** SQLite (cache/index do filesystem)
- **Frontend:** Vanilla JavaScript + HTML/CSS (sem build step, leve e rápido)
- **Manipulação de ID3:** `mutagen` (mais robusto e atualizado que `eyed3`)
- **Download YouTube:** `yt-dlp` (instalado no container) + `ffmpeg`
- **Playlist:** Leitura/escrita nativa em `.m3u8`

---

## 2. Estrutura de Diretórios do Projeto

```
~/github/PiCASSO_Repo/
├── Containerfile
├── create-service.sh
├── start.sh                      # Substitui start-sshd.sh (inicia sshd + uvicorn)
├── requirements.txt
├── README.md
├── PLANO.md                      # Este arquivo
├── backend/
│   ├── __init__.py
│   ├── main.py                   # App FastAPI, monta rotas e static files
│   ├── config.py                 # Configs (REPOSITORY_DIR, DB_PATH, etc.)
│   ├── database.py               # Conexão SQLite, tabelas, migrations
│   ├── scanner.py                # Scan do filesystem, sync SQLite <-> tags ID3/M3U
│   ├── models.py                 # Modelos Pydantic (Track, Playlist, etc.)
│   └── api/
│       ├── tracks.py             # CRUD músicas, metadados ID3
│       ├── playlists.py          # CRUD playlists M3U
│       ├── upload.py             # Upload de MP3
│       └── youtube.py            # Download via yt-dlp
├── frontend/
│   ├── index.html
│   ├── css/
│   │   └── style.css
│   └── js/
│       ├── app.js                # Router SPA simples
│       ├── api.js                # Cliente HTTP para a API
│       ├── tracks.js             # UI lista de músicas
│       ├── playlists.js          # UI playlists
│       └── upload.js             # UI upload + youtube
└── data/                         # (Opcional) SQLite local para dev, ignorado no container
```

---

## 3. O Banco de Dados SQLite: O Desafio da Sincronização

A maior preocupação é o **desincronamento** entre o SQLite e o filesystem. A solução é tratá-lo como um **índice de leitura**, não como fonte da verdade.

**Fonte da verdade:** O filesystem (`~/Documents/PiCASSO_Repository`) — os arquivos MP3 com suas tags ID3 e os arquivos `.m3u8`.

**SQLite é um cache acelerado** para busca, listagem e relacionamentos.

### Estratégia de Sincronização

1. **Scan na inicialização:** Ao subir o serviço, o `scanner.py` percorre todo o repositório, lê as tags ID3 de cada MP3 e os arquivos M3U, e reconstrói/popula o SQLite.

2. **Escritas via API:** Quando você edita metadados de uma música pela UI, a API:
   - Primeiro escreve as tags ID3 no arquivo MP3 (usando `mutagen`).
   - Depois atualiza o registro correspondente no SQLite.
   - Se falhar no MP3, a transição no SQLite é abortada (consistência).

3. **Modificações externas (SSH/SFTP/rsync):** Se alguém adiciona/deleta/edita arquivos por fora da UI, o SQLite ficará desatualizado.
   - **Solução:** Um endpoint `POST /api/sync` que força um re-scan completo.
   - **Solução automática (opcional):** Um job periódico (a cada 5-10 min) que compara `mtime` dos arquivos com o SQLite e re-scana apenas os modificados.

4. **Chave primária:** O path relativo do arquivo dentro do repositório (`"Artista/Album/musica.mp3"`). Se o arquivo for renomeado, é tratado como "delete + insert".

### Schema do SQLite

```sql
-- tracks: uma entrada por MP3
CREATE TABLE tracks (
    path TEXT PRIMARY KEY,         -- path relativo no repositório
    title TEXT,
    artist TEXT,
    album TEXT,
    genre TEXT,
    year INTEGER,
    duration REAL,                 -- em segundos
    bitrate INTEGER,
    size INTEGER,
    mtime REAL,                    -- para detectar mudanças externas
    has_cover BOOLEAN
);

-- playlists: uma entrada por arquivo .m3u8
CREATE TABLE playlists (
    path TEXT PRIMARY KEY,         -- path relativo (ex: "MinhaPlaylist.m3u8")
    name TEXT,
    mtime REAL,
    track_count INTEGER
);

-- playlist_items: ordem das músicas
CREATE TABLE playlist_items (
    playlist_path TEXT,
    track_path TEXT,
    position INTEGER,
    FOREIGN KEY (playlist_path) REFERENCES playlists(path) ON DELETE CASCADE,
    FOREIGN KEY (track_path) REFERENCES tracks(path) ON DELETE CASCADE,
    PRIMARY KEY (playlist_path, position)
);
```

---

## 4. Funcionalidades da API (FastAPI)

### Músicas (`/api/tracks`)
- `GET /api/tracks` — Lista todas as músicas (com paginação, busca por texto).
- `GET /api/tracks/{path}` — Detalhes de uma música (metadados ID3).
- `PUT /api/tracks/{path}` — Atualiza metadados (escreve no MP3 e no SQLite).
- `DELETE /api/tracks/{path}` — Deleta o arquivo MP3 e remove do SQLite/Playlists.
- `GET /api/tracks/{path}/cover` — Retorna a capa do álbum (extraída do ID3).

### Playlists (`/api/playlists`)
- `GET /api/playlists` — Lista todas as playlists.
- `GET /api/playlists/{path}` — Detalhes de uma playlist com suas músicas ordenadas.
- `POST /api/playlists` — Cria um novo arquivo `.m3u8`.
- `PUT /api/playlists/{path}` — Renomeia ou reordena músicas.
- `POST /api/playlists/{path}/tracks` — Adiciona uma música à playlist.
- `DELETE /api/playlists/{path}/tracks/{position}` — Remove música da playlist.
- `DELETE /api/playlists/{path}` — Deleta o arquivo `.m3u8`.

### Upload (`/api/upload`)
- `POST /api/upload` — Recebe um arquivo MP3 (multipart/form-data), salva no repositório, faz parse das tags ID3 e insere no SQLite. Suporta drag-and-drop múltiplo.

### YouTube (`/api/youtube`)
- `POST /api/youtube/download` — Recebe `{url, as_playlist: bool, target_dir?}`.
  - Se for vídeo único: baixa MP3 para o repositório.
  - Se for playlist do YouTube e `as_playlist=true`: baixa todos os MP3 para um subdiretório e cria um arquivo `.m3u8` com o nome da playlist.
  - Usa FastAPI `BackgroundTasks` para não travar a requisição.
  - Retorna um `job_id` para o frontend consultar o progresso (via polling simples).

### Sincronização (`/api/sync`)
- `POST /api/sync` — Re-scan do filesystem, rebuild do SQLite. Útil após uploads via SFTP.

### Status (`/api/healthz` e `/`)
- `GET /healthz` — Health check do container.
- `GET /` — Serve o `frontend/index.html`.

---

## 5. Funcionalidades do Frontend (Vanilla JS SPA)

O frontend será uma **Single Page Application (SPA)** simples, sem frameworks pesados. O JavaScript faz o roteamento entre "páginas" virtuais manipulando o DOM.

### Páginas/Telas

1. **Dashboard (Home):**
   - Cards com estatísticas (igual ao `web-status.py` atual): total de MP3, playlists, tamanho ocupado.
   - Botão "Sincronizar Repositório" (chama `/api/sync`).

2. **Biblioteca de Músicas:**
   - Tabela com todas as músicas, ordenável e com busca em tempo real.
   - Colunas: Título, Artista, Álbum, Gênero, Duração.
   - Clique em uma música abre **modal de edição** de metadados (formulário editando título, artista, álbum, ano, gênero).
   - Botão de deletar com confirmação.
   - Preview de capa do álbum.

3. **Gerenciador de Playlists:**
   - Lista de playlists existentes.
   - Criar nova playlist (input de nome).
   - Editar playlist: visualização das músicas na ordem, com busca para adicionar novas músicas da biblioteca.
   - Drag-and-drop para reordenar (ou botões de mover cima/baixa).
   - Deletar playlist.

4. **Adicionar Músicas:**
   - **Aba Upload:** Área de drag-and-drop para arquivos MP3. Barra de progresso.
   - **Aba YouTube:** Input para colar URL do YouTube (vídeo ou playlist). Checkbox "Criar playlist local". Botão "Download". Lista de downloads em andamento com status.

**Design:** Visual clean, minimalista, com suporte a dark mode (herdando a estética do `web-status.py` atual). Responsivo para mobile.

---

## 6. Atualização do Container

O `Containerfile` precisará de novos pacotes:

```dockerfile
FROM docker.io/alpine:3.20

RUN apk add --no-cache bash openssh-server python3 py3-pip rsync shadow tzdata \
    ffmpeg yt-dlp \
    && ssh-keygen -A \
    && mkdir -p /repository /root/.ssh /run/sshd /app \
    && chmod 700 /root/.ssh

COPY requirements.txt /app/
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY backend/ /app/backend/
COPY frontend/ /app/frontend/

COPY start.sh /usr/local/bin/start.sh
RUN chmod +x /usr/local/bin/start.sh

EXPOSE 22 80

CMD ["/usr/local/bin/start.sh"]
```

**`requirements.txt`:**
```
fastapi
uvicorn[standard]
python-multipart
mutagen
pydantic
```

**`start.sh`:** Combina o `start-sshd.sh` existente com o start do Uvicorn. Ambos rodam em background e o script aguarda.

---

## 7. Fluxo de Uso Exemplo

1. Você acessa `http://picasso-repo/` pela Tailnet.
2. A SPA carrega. O backend já fez um scan inicial do repositório ao subir.
3. Você vai em "Biblioteca" e vê todas as músicas com metadados.
4. Edita a tag de uma música → API escreve no MP3 via `mutagen` → atualiza SQLite.
5. Cria uma playlist "Viagem" → API cria `Viagem.m3u8` vazio.
6. Adiciona 10 músicas à playlist → API reescreve o arquivo `.m3u8` com os novos paths.
7. Manda um download do YouTube (playlist de rock) → `yt-dlp` baixa os MP3 para `/repository/youtube/Rock/` → API cria `Rock.m3u8` → insere no SQLite.
8. Você fecha o navegador, edita um MP3 via SFTP diretamente. Depois abre a UI e clica "Sincronizar" → SQLite se realinha com o filesystem.

---

## 8. Extensibilidade Futura (Logger do Carro)

A arquitetura foi pensada para ser extensível:
- O FastAPI permite adicionar novos routers facilmente (`api/car_logger.py`).
- Novas tabelas no SQLite (`car_logs`, `trips`, etc.).
- Novas páginas no frontend SPA (`car.html`, `logger.js`).
- Como o repositório (`~/Documents/PiCASSO_Repository`) é montado no container, o carro pode continuar enviando dados brutos via SFTP/rsync para uma subpasta `/repository/car_data/`. O serviço web lê e processa esses dados.

---

## 9. Resumo das Etapas de Implementação

| Etapa | Descrição | Complexidade |
|-------|-----------|--------------|
| 1 | Setup do projeto FastAPI + estrutura de pastas | Baixa |
| 2 | Modelos Pydantic + Schema SQLite + conexão DB | Baixa |
| 3 | Módulo `scanner.py` (leitura recursiva de MP3/M3U) | Média |
| 4 | API CRUD de Músicas (com escrita ID3 via mutagen) | Média |
| 5 | API CRUD de Playlists (leitura/escrita M3U) | Média |
| 6 | API de Upload de MP3 | Baixa |
| 7 | Integração yt-dlp (download + criação de playlist) | Média-Alta |
| 8 | Frontend SPA (HTML/CSS/JS) — Dashboard + Biblioteca + Playlists | Média |
| 9 | Frontend — Upload drag-and-drop + YouTube downloader UI | Média |
| 10 | Atualizar Containerfile e scripts de deploy | Baixa |
| 11 | Testes e ajustes | Média |

---

## 10. Decisões de Design Definidas

Estas decisões foram discutidas com o usuário e definidas para a implementação:

- **Backend:** FastAPI (Python)
- **Frontend:** Separado (Vanilla JS SPA, servido por Uvicorn StaticFiles)
- **Metadados:** Escrita direta nas tags ID3 dos MP3 (usando `mutagen`)
- **Banco de Dados:** SQLite como índice/cache, com estratégia de re-scan para manter sincronizado com o filesystem
- **YouTube:** Integração via `yt-dlp` diretamente no container
- **Playlists:** Formato `.m3u8` nativo apenas
- **Autenticação:** Apenas via Tailscale (rede privada). A interface web fica aberta sem login adicional.
- **Volume de Downloads:** Geralmente baixo, mas playlists do YouTube podem conter muitos arquivos. Requer job queue com polling de status.
- **Visual/UI:** Dashboard elaborado com sidebar de navegação (não minimalista).
- **Logger do Carro:** Escopo futuro, arquitetura preparada para extensão

---

## 11. Plano de Commits

A implementação será dividida em commits incrementais e funcionais, seguindo o fluxo: backend base → APIs individuais → frontend → infraestrutura. Cada commit deve compilar/rodar sem quebrar o estado anterior (onde possível).

### Commit 1: Setup do Backend FastAPI
**Branch:** `feat/media-manager` (a partir de `main`)

- Criar estrutura de pastas (`backend/`, `backend/api/`, `frontend/`, etc.)
- Criar `backend/config.py` (leitura de variáveis de ambiente: `REPOSITORY_DIR`, `DB_PATH`, `WEB_PORT`)
- Criar `backend/models.py` (Pydantic models: `Track`, `TrackUpdate`, `Playlist`, `PlaylistCreate`, `PlaylistUpdate`, `YouTubeDownloadRequest`, `JobStatus`)
- Criar `backend/database.py` (conexão SQLite, funções `init_db()`, `get_db()`, schema completo)
- Criar `backend/main.py` (app FastAPI básico com healthcheck e montagem de `StaticFiles`)
- Criar `requirements.txt`
- Remover `web-status.py` do tree (será substituído, mas não deletar ainda do filesystem para não quebrar o container atual)

**Critério de aceite:** `uvicorn backend.main:app --reload` sobe sem erro e responde em `/healthz`.

---

### Commit 2: Scanner e Sincronização SQLite <-> Filesystem

- Criar `backend/scanner.py` com funções:
  - `scan_repository(repo_dir)` → lista todos os MP3 e M3U
  - `extract_id3(path)` → retorna dict com metadados usando `mutagen`
  - `parse_m3u(path)` → retorna lista de paths de tracks
  - `sync_database(db, repo_dir)` → trunca e repopula o SQLite
  - `sync_single_file(db, path)` → atualiza apenas um arquivo no SQLite
- Adicionar endpoint `POST /api/sync` que chama `sync_database`
- Adicionar scan automático na inicialização do app (startup event do FastAPI)
- Criar teste manual simples (não precisa de framework de teste ainda)

**Critério de aceite:** Endpoint `/api/sync` funciona e o SQLite reflete o estado real do repositório de MP3/M3U.

---

### Commit 3: API CRUD de Músicas (Tracks)

- Criar `backend/api/tracks.py` com router FastAPI:
  - `GET /api/tracks` (query params: `q` para busca, `skip`, `limit`)
  - `GET /api/tracks/{path}` (path é URL-encoded relative path)
  - `PUT /api/tracks/{path}` (atualiza ID3 via mutagen, depois SQLite)
  - `DELETE /api/tracks/{path}` (deleta arquivo, remove do SQLite e playlists)
  - `GET /api/tracks/{path}/cover` (retorna bytes da capa, content-type `image/jpeg` ou `image/png`, 404 se não houver)
- Montar router em `backend/main.py`
- Garantir que a escrita ID3 seja atômica (escreve em arquivo temporário, depois move)

**Critério de aceite:** Pode listar, editar tags, deletar e ver capa de uma música via `curl`/Swagger UI.

---

### Commit 4: API CRUD de Playlists (M3U)

- Criar `backend/api/playlists.py` com router FastAPI:
  - `GET /api/playlists`
  - `GET /api/playlists/{path}` (retorna playlist com array de tracks ordenado)
  - `POST /api/playlists` (cria arquivo `.m3u8`, insere no SQLite)
  - `PUT /api/playlists/{path}` (renomeia arquivo e/ou reordena tracks)
  - `POST /api/playlists/{path}/tracks` (adiciona track em posição específica ou no final)
  - `DELETE /api/playlists/{path}/tracks/{position}` (remove track da posição)
  - `DELETE /api/playlists/{path}` (deleta arquivo `.m3u8`)
- Implementar leitura/escrita M3U com paths relativos ao repo
- Atualizar `playlist_items` no SQLite após cada modificação

**Critério de aceite:** Pode criar playlist, adicionar/remover/reordenar músicas, e o arquivo `.m3u8` no disco reflete as mudanças.

---

### Commit 5: API de Upload de MP3

- Criar `backend/api/upload.py` com router FastAPI:
  - `POST /api/upload` (multipart/form-data, múltiplos arquivos)
  - Salva arquivo em subdiretório opcional (`target_dir` no form)
  - Extrai ID3 do arquivo recebido
  - Insere no SQLite
- Validação: aceitar apenas `.mp3` (case-insensitive), limite de tamanho generoso
- Sanitização de nome de arquivo

**Critério de aceite:** Upload via `curl -F` funciona, arquivo aparece no repositório e no banco.

---

### Commit 6: API de Download YouTube com Job Queue

- Criar `backend/api/youtube.py` com router FastAPI:
  - `POST /api/youtube/download` (aceita `url`, `as_playlist: bool`, `target_dir: str?`)
  - Cria um job em memória (dict/thread-safe) com `job_id`, `status` (queued/running/completed/failed), `progress`, `message`
  - Usa `asyncio.create_subprocess_exec` para rodar `yt-dlp` de forma não-bloqueante
  - Se `as_playlist=true`, baixa para subdiretório e cria `.m3u8` após conclusão
  - `GET /api/youtube/jobs/{job_id}` — consulta status do job
  - `GET /api/youtube/jobs` — lista jobs recentes
- Job worker simples: permite até N downloads simultâneos (ex: 2), fila o resto
- Após download bem-sucedido, chama `sync_single_file` ou `sync_database` para atualizar o SQLite
- Log de saída do `yt-dlp` salvo no job para debug

**Critério de aceite:** Enviar URL de vídeo e playlist funciona, job retorna ID, polling mostra progresso, arquivo aparece no repo.

---

### Commit 7: Frontend — Estrutura SPA Base + Dashboard

- Criar `frontend/index.html` (estrutura base com sidebar e main content area)
- Criar `frontend/css/style.css` (design elaborado, sidebar fixa, cards, dark mode via `prefers-color-scheme` e toggle manual, responsivo)
- Criar `frontend/js/app.js` (router SPA simples: intercepta clicks em links, troca conteúdo do `<main>` sem reload)
- Criar `frontend/js/api.js` (cliente HTTP: funções `get`, `post`, `put`, `del` usando `fetch`, tratamento de erro base)
- Implementar view `Dashboard`:
  - Cards com contagem de MP3, playlists, tamanho total
  - Botão "Sincronizar Repositório" com spinner/feedback
  - Últimas músicas adicionadas (opcional)
- Montar `frontend/` como `StaticFiles` em `/` no FastAPI (já configurado no commit 1, mas verificar)

**Critério de aceite:** Acessar `http://localhost:8000/` mostra dashboard funcional com dados reais da API.

---

### Commit 8: Frontend — Biblioteca de Músicas

- Criar `frontend/js/tracks.js` (view da Biblioteca)
- Implementar:
  - Tabela/lista de músicas com colunas (título, artista, álbum, gênero, duração)
  - Campo de busca com debounce (filtro no backend via `?q=`)
  - Paginação (ou scroll infinito, a decidir)
  - Modal de edição de metadados (form com campos ID3)
  - Botão deletar com confirmação (`confirm()` ou modal)
  - Preview de capa ao lado da música ou no modal
- Integrar com `api.js`

**Critério de aceite:** Pode navegar em "Biblioteca", buscar, editar e deletar músicas pela UI.

---

### Commit 9: Frontend — Gerenciador de Playlists

- Criar `frontend/js/playlists.js` (view de Playlists)
- Implementar:
  - Lista de playlists com nome e contagem de músicas
  - Criar nova playlist (input + botão)
  - Tela de edição de playlist:
    - Lista ordenada das músicas já na playlist
    - Busca da biblioteca para adicionar novas músicas (autocomplete/search)
    - Botões para remover e reordenar (setas ou drag-and-drop simples)
  - Deletar playlist com confirmação
- Integrar com endpoints de playlist

**Critério de aceite:** Pode criar, editar (adicionar/remover/reordenar) e deletar playlists pela UI.

---

### Commit 10: Frontend — Upload e YouTube

- Criar `frontend/js/upload.js` (view de "Adicionar Músicas")
- Implementar:
  - **Aba Upload:** Área drag-and-drop destacada, lista de arquivos selecionados, upload individual com barra de progresso (`XMLHttpRequest` para ter progresso, ou `fetch` com streaming se possível), feedback de sucesso/erro
  - **Aba YouTube:** Input de URL, checkbox "Criar playlist local", botão "Download". Lista de jobs ativos/completados recentes com status, progresso (se disponível) e link para o arquivo quando concluído. Polling a cada 3s para jobs em andamento.
- Integrar com endpoints de upload e YouTube

**Critério de aceite:** Upload drag-and-drop funciona, download do YouTube inicia e mostra status em tempo real.

---

### Commit 11: Infraestrutura — Container e Deploy

- Criar `start.sh` (combina `start-sshd.sh` + start do Uvicorn, gerencia processos em background, trap SIGTERM)
- Atualizar `Containerfile`:
  - Adicionar `py3-pip`, `ffmpeg`, `yt-dlp`
  - Instalar dependências Python via `requirements.txt`
  - Copiar `backend/` e `frontend/`
  - Entrypoint `start.sh`
- Atualizar `requirements.txt` se necessário
- Testar build local do container (se possível)
- Atualizar `README.md` com instruções de uso da nova aplicação
- Marcar `web-status.py` e `start-sshd.sh` como obsoletos (ou deletar, dependendo da preferência do usuário)

**Critério de aceite:** `./create-service.sh` cria o pod e a nova aplicação funciona em `http://picasso-repo/`.

---

### Commit 12: Polimento, Testes e Ajustes Finais

- Revisar tratamento de erros em todas as APIs (mensagens claras, status codes corretos)
- Verificar comportamento com caracteres especiais em nomes de arquivo/ID3
- Testar edge cases: repositório vazio, arquivo MP3 corrompido, download YouTube falho
- Ajustes de CSS para mobile (sidebar vira hamburger menu em telas pequenas)
- Limpeza de jobs antigos em memória (evitar memory leak)
- Adicionar favicon
- Revisão final do `PLANO.md` para refletir implementação real

**Critério de aceite:** Aplicação estável, usável e pronta para uso diário.

---

### Possíveis Commits Adicionais (se necessário)

- **Commit 13:** Suporte a re-scan periódico automático (cron job ou timer no FastAPI)
- **Commit 14:** Suporte a múltiplos formatos de capa (PNG, etc.) ou extração de capa do YouTube
- **Commit 15:** Filtros avançados na biblioteca (por artista, álbum, gênero)
- **Commit 16:** Player de preview (HTML5 audio) para ouvir trechos direto no navegador
