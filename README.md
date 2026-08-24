# picasso-repo

Companion media service for [**PiCASSO**](https://github.com/flavioluiz/pi-car) — a Podman pod that exposes a media library over SSH/SFTP/rsync and joins a [Tailscale](https://tailscale.com/) tailnet under the hostname `picasso-repo`, so the car can sync music and playlists from anywhere on your tailnet without port-forwarding or static IPs.

It also runs a small FastAPI web UI on port 80 for browsing tracks and playlists, uploading MP3s, and importing audio from YouTube via `yt-dlp`.

> Optional. PiCASSO works fine without it — just drop files into `~/Music/` and `~/.mpd/playlists/` on the Pi. picasso-repo only matters if you want a single managed source of truth that the car pulls from over Tailscale.

---

## Architecture

```
┌──────────────────────────────────────────────────────────────┐
│  Host computer (NAS, desktop, mini PC…)                      │
│                                                              │
│   Podman pod: picasso-repo                                   │
│   ┌──────────────────────┐    ┌────────────────────────────┐ │
│   │  picasso-repo-app    │    │  Tailscale sidecar         │ │
│   │  • sshd (port 22)    │    │  hostname: picasso-repo    │ │
│   │  • FastAPI / Uvicorn │    │  joins your tailnet        │ │
│   │  • web UI (port 80)  │    │                            │ │
│   └─────────┬────────────┘    └────────────────────────────┘ │
│             │                                                │
│             ▼                                                │
│   /Volumes/MacSSD/Data/picasso-repository → /repository      │
│   ├── Musics/        (.mp3)                                  │
│   └── Playlists/     (.m3u / .m3u8)                          │
└──────────────────────────────────────────────────────────────┘
                              │
                       Tailscale tailnet
                              │
                              ▼
                ┌──────────────────────────┐
                │  Raspberry Pi (PiCASSO)  │
                │  Settings → Sync now     │
                │  rsync over SSH          │
                └──────────────────────────┘
```

---

## Folder layout

The data directory mounted into the pod **must** have this structure:

```
/Volumes/MacSSD/Data/picasso-repository/
├── Musics/        # MP3 files (any nested folder structure)
└── Playlists/     # .m3u / .m3u8 playlists
```

These two folders are what the Pi pulls from:

- `root@picasso-repo:/repository/Musics/` → `~/Music/` (MPD library)
- `root@picasso-repo:/repository/Playlists/` → `~/.mpd/playlists/` (MPD playlists)

---

## Prerequisites

- [Podman](https://podman.io/) on the host
- A [Tailscale](https://tailscale.com/) account (free tier works)
- A Tailscale **auth key** for the first pod creation (generate one at <https://login.tailscale.com/admin/settings/keys>)
- An SSH authorized-keys file that the Pi will use to authenticate (default:
  `/Volumes/MacSSD/Data/picasso-ssh/authorized_keys`)

---

## Quick start

```bash
git clone git@github.com:flavioluiz/picasso-repo.git
cd picasso-repo

# First run — pass the Tailscale auth key once
./create-service.sh --authkey tskey-auth-XXXXXXXX

# Subsequent recreates — the persistent volume keeps the tailnet identity
./create-service.sh
```

By default this:

- Builds the image `localhost/picasso-repo-app:latest` from the `Containerfile`
- Creates a pod named `picasso-repo`
- Mounts `/Volumes/MacSSD/Data/picasso-repository` into the pod at `/repository`
- Trusts the public keys at `/Volumes/MacSSD/Data/picasso-ssh/authorized_keys`
- Joins the tailnet under hostname `picasso-repo`

The data directory must already exist. When a path under `/Volumes/MacSSD` is
used, the script verifies that the encrypted SSD is really mounted and refuses
to create a fallback directory if it is absent.

Customize via flags:

```
--service <name>               Pod and Tailscale hostname (default: picasso-repo)
--authkey <key>                Tailscale auth key (only required on first creation)
--data-dir <path>              Host directory exposed at /repository
--authorized-keys-file <path>  Public keys allowed to connect as root
--port <port>                  Web UI port (default: 80)
--image <name>                 Image tag
```

Run `./create-service.sh --help` for the full list.

---

## Access

Once the pod is up and Tailscale is connected:

```bash
# Web UI (browse tracks, upload, import from YouTube)
open http://picasso-repo/

# Direct SSH / SFTP / rsync
ssh root@picasso-repo
sftp root@picasso-repo
rsync -av root@picasso-repo:/repository/ ./local/copy/
```

The container only accepts public-key authentication — passwords and keyboard-interactive auth are disabled.

---

## How PiCASSO uses it

The Pi runs `rsync` against the two well-known paths whenever the user taps **Sync now** in Settings:

```bash
rsync -avz --delete -e "ssh -i ~/.ssh/id_ed25519" \
  root@picasso-repo:/repository/Musics/ ~/Music/

rsync -avz --delete -e "ssh -i ~/.ssh/id_ed25519" \
  root@picasso-repo:/repository/Playlists/ ~/.mpd/playlists/
```

See the [PiCASSO README → Optional: Media sync from picasso-repo](https://github.com/flavioluiz/pi-car#optional-media-sync-from-picasso-repo) for the Pi-side setup.

---

## Web UI

The FastAPI app on port 80 provides:

- Track listing with ID3 metadata (powered by `mutagen`)
- Playlist management (`.m3u` / `.m3u8`)
- MP3 upload
- YouTube import via `yt-dlp` + `ffmpeg`
- A `POST /api/sync` endpoint to refresh the SQLite index after manual filesystem changes

Project status and roadmap: see [PLANO.md](PLANO.md).

---

## Without Tailscale

Tailscale is recommended but not mandatory. If you can give the host a stable name on your LAN, point the Pi at it instead — either by editing the host alias used by `backend/services/media_sync.py` in PiCASSO, or by adding `picasso-repo` to `/etc/hosts` on the Pi.

You will lose the ability to sync from outside your home network, but everything else works the same.

---

## License

MIT.
