# Chromecast Web

Controlla il tuo **Chromecast** (pensato per il Chromecast Ultra) da qualsiasi browser della rete di casa,
soprattutto dal telefono. Tutte le schede e i dispositivi aperti restano **sincronizzati in tempo reale**
(WebSocket): se metti in pausa dal telefono, il tablet lo vede subito.

> Il contratto tecnico completo (modelli, endpoint, messaggi WebSocket, regole di test) è in
> [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

## Funzionalità

- **Trasmetti qualsiasi cosa**
  - URL diretti: HLS (`.m3u8`), DASH, MP4, MPEG-TS…
  - **Pagine web** con il video dentro: vengono aperte in un Chromium vero sul server (JavaScript, iframe
    annidati, click su "play") e lo stream viene intercettato a livello di rete.
  - **Playlist M3U / IPTV**: import da URL o file, gruppi, ricerca, migliaia di canali.
  - **YouTube e altri siti** tramite `yt-dlp`.
  - **File locali** del server (cartella `MEDIA_ROOT`).
- **Browser remoto interattivo**: navighi la pagina dal telefono (tap, scroll, tastiera), gli stream trovati
  compaiono in un pannello con anteprima, qualità e badge *Live*, e li mandi alla TV con **Cast / Coda / Play / Salva**.
- **Blocco pubblicità stile uBlock Origin** nel browser remoto: motore `adblock` (Brave) con le liste di uBO
  (uBlock filters, EasyList, EasyPrivacy, Peter Lowe, EasyList Italy) aggiornate ogni 24 ore, filtri cosmetici,
  interruttore per sito, contatore delle richieste bloccate, **popup trattenuti** ("La pagina vuole aprire…"
  Apri / Blocca / Blocca sempre) e **chiusura immediata** della sessione con la ×.
- **Proxy integrato** per gli stream che richiedono Referer/Cookie/CORS e **restream ffmpeg** per formati che
  il Chromecast non legge (TS grezzo, RTMP, AVI…).
- **Telecomando completo**: play/pausa, seek, "vai al live", volume, sottotitoli/tracce audio, coda riordinabile,
  immagine di attesa sulla TV, preferiti e cronologia.
- **PWA** installabile sulla schermata Home, tema scuro, interfaccia in italiano.

## Architettura

```
┌──────────── telefono / PC (browser) ────────────┐
│ Next.js (export statico) ── REST /api + WS /ws  │
└───────────────────────┬─────────────────────────┘
                        │ stessa origine (porta 8000)
┌───────────────────────▼─────────────────────────┐      ┌──────────────┐
│ FastAPI (backend/)                              │      │  Chromecast  │
│  · pychromecast (mDNS) ─────── comandi ─────────┼─────▶│  (stessa LAN)│
│  · resolver: diretto, pagina web (Playwright),  │      └──────┬───────┘
│    M3U, yt-dlp, file locali                     │             │
│  · proxy HLS / restream ffmpeg  ◀───── stream ──┼─────────────┘
│  · browser remoto (Chromium) + adblock          │
│  · SQLite in DATA_DIR (preferiti, playlist…)    │
└─────────────────────────────────────────────────┘
```

- **Un'unica immagine Docker**: il frontend è compilato come export statico e servito da FastAPI su `/`.
- Il Chromecast scarica gli stream **dal server** (`/proxy`, `/restream`, `/local`): per questo il server deve
  essere raggiungibile dal Chromecast sulla LAN.

| Cartella | Contenuto |
|---|---|
| `backend/` | FastAPI, Python 3.12+ (`app/`, test in `tests/`) |
| `frontend/` | Next.js App Router, TypeScript, Tailwind v4, shadcn/ui (test in `tests/`) |
| `docs/ARCHITECTURE.md` | contratto API condiviso |
| `Dockerfile`, `docker-compose.yml` | immagine unica e deploy (Coolify) |
| `_old/` | vecchio prototipo Flask, solo come riferimento |

## Requisito fondamentale: stessa LAN

Il server e il Chromecast devono stare **sulla stessa rete locale**:

- la scoperta automatica usa **mDNS** (multicast), che non attraversa NAT/bridge Docker: per questo il container
  gira con `network_mode: host`;
- il Chromecast deve poter aprire `http://<IP-del-server>:8000/proxy/...`. Se il rilevamento automatico dell'IP
  sbaglia interfaccia (VPN, Docker, più schede di rete) imposta **`PUBLIC_BASE_URL`**, es. `http://192.168.1.10:8000`
  (si può cambiare anche da *Impostazioni → Rete*);
- se mDNS non funziona puoi sempre aggiungere il Chromecast **a mano per IP** dal foglio "Invia video a…".

## Sviluppo locale

Requisiti: Python 3.12+, Node 20+ (testato con Node 25), `ffmpeg` nel PATH. Non serve un Chromecast:
con `CAST_DRIVER=fake` il backend simula due dispositivi.

```bash
make setup        # crea backend/.venv e installa le dipendenze del frontend
make browsers     # (consigliato) installa Chromium per Playwright: pagine web, browser remoto, test @browser
make dev          # backend fake su :8000 + Next dev su :3000 (apri http://localhost:3000,
                  # o dal telefono http://<ip-lan-del-pc>:3000: l'API è sullo stesso host, porta 8000)
```

Senza `make`:

```bash
# backend
cd backend
python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
.venv/bin/playwright install chromium
CAST_DRIVER=fake .venv/bin/uvicorn app.main:app --reload --port 8000

# frontend (altro terminale)
cd frontend
npm ci
NEXT_PUBLIC_API_PORT=8000 npx next dev -H 0.0.0.0   # API = stesso host della pagina, porta 8000
# (oppure un backend fisso: NEXT_PUBLIC_API_BASE=http://192.168.1.10:8000 npm run dev)
```

Per provare la build "di produzione" in locale: `make serve` (compila l'export statico e lo serve dal backend
su http://localhost:8000).

### Variabili d'ambiente (backend)

| Variabile | Default | Significato |
|---|---|---|
| `CAST_DRIVER` | `pychromecast` | `fake` per sviluppo/test |
| `PUBLIC_BASE_URL` | IP LAN rilevato + porta | URL con cui il **Chromecast** raggiunge il server |
| `PORT` | `8000` | porta HTTP |
| `DATA_DIR` | `./data` (`/data` nel container) | database SQLite, liste filtri, file temporanei di restream |
| `MEDIA_ROOT` | non impostata | cartella dei file locali (sezione File disattivata se assente) |
| `FRONTEND_DIR` | `../frontend/out` | export statico servito su `/` |
| `ENABLE_PLAYWRIGHT` | `true` | estrazione da pagine web e browser remoto |
| `FILTERS_AUTO_UPDATE` | `true` | scarica/aggiorna le liste uBO ogni 24 ore |
| `FFMPEG_PATH` / `FFPROBE_PATH` | `ffmpeg` / `ffprobe` accanto | binari usati dal restream |
| `CORS_ORIGINS` / `CORS_ORIGIN_REGEX` | localhost:3000 / host della LAN privata | solo sviluppo (`make dev` aperto dal telefono); in produzione è tutto same-origin |

### Controlli

```bash
make test          # tutto: backend (pytest + ruff) e frontend (typecheck, lint, vitest, build)
make test-backend  # cd backend && .venv/bin/pytest -q && .venv/bin/ruff check .
make test-browser  # solo i test con Chromium reale (@pytest.mark.browser)
make test-frontend # cd frontend && npm run typecheck && npm run lint && npm test && npm run build
```

I test non usano rete né Chromecast (driver fake, HTTP simulato). I test `@pytest.mark.browser` usano un
Chromium vero contro un sito di prova locale e vengono saltati se Chromium non è installato.

## Deploy con Coolify

1. **New Resource → Docker Compose** (o "Public/Private Repository" con build pack *Docker Compose*) e punta a
   questo repository; Coolify usa `docker-compose.yml` nella root.
2. Il compose usa **`network_mode: host`**: non configurare porte/domìni nel proxy di Coolify per la parte che usa
   il Chromecast. L'app ascolta direttamente su `http://<IP-del-server>:8000` (cambia con la variabile `PORT`).
   Puoi comunque aggiungere un dominio per l'interfaccia, ma il Chromecast deve usare l'IP LAN (`PUBLIC_BASE_URL`).
3. Variabili d'ambiente consigliate in Coolify:
   - `PUBLIC_BASE_URL=http://192.168.1.10:8000` (IP LAN del server: il Chromecast userà questo indirizzo);
   - opzionale `PORT`, `LOG_LEVEL`, `FILTERS_AUTO_UPDATE`.
4. **Dati persistenti**: il volume `chromecast-web-data` è montato su `/data` (database, liste filtri).
5. **File locali (opzionale)**: decommenta in `docker-compose.yml` il bind mount `- /percorso/Media:/media:ro`
   e la variabile `MEDIA_ROOT: /media`.
6. Deploy. L'healthcheck interroga `GET /api/health`; poi apri `http://<IP-del-server>:8000` dal telefono e
   aggiungilo alla schermata Home.

Senza Coolify: `docker compose up -d --build` (oppure `make docker-up`).

Note sull'immagine: build multi-stage (Node → export statico; `python:3.12-slim` con `ffmpeg` e Chromium
installato via `playwright install --with-deps chromium`), gira come utente non-root `app`, `shm_size: 1gb` per
Chromium.

## Limiti noti

- Testato solo con il driver fake: il primo collaudo con un Chromecast reale va fatto in casa.
- I file da convertire (`.avi`, `.ts`, `.wmv`… locali o via HTTP) vengono convertiti in tempo reale
  (playlist HLS `EVENT`): partono dall'inizio, ma il seek in avanti arriva solo fin dove ffmpeg è già arrivato;
  il video non H.264 (Xvid/DivX, MPEG-2, WMV) viene ricodificato e richiede CPU sul server.
- DASH: il manifest viene riscritto (BaseURL, `media`, `initialization`, `Location` → `/proxy/{token}/a/…`) e,
  se il server d'origine non risponde all'Origin del Chromecast, trasmesso tramite `/proxy`; l'anteprima in app
  supporta solo HLS e MP4 (per il DASH dice che il formato non è visualizzabile, ma si può trasmettere).
- Filtri cosmetici sì, *scriptlet* di uBO no.
- Feedback aptico solo su Android (iOS Safari ignora la Vibration API).

## Ringraziamenti

[pychromecast](https://github.com/home-assistant-libs/pychromecast), [yt-dlp](https://github.com/yt-dlp/yt-dlp),
[Playwright](https://playwright.dev), [adblock-rust](https://github.com/brave/adblock-rust) e le liste di
[uBlock Origin](https://github.com/gorhill/uBlock), [FastAPI](https://fastapi.tiangolo.com), [Next.js](https://nextjs.org).
