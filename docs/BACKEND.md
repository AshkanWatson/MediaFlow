# MediaFlow backend / core engine

Python 3.11+ · FastAPI · yt-dlp (library) · httpx · FFmpeg/ffprobe · Pillow.
Rationale for the language choice: see [TECHNICAL_PLAN.md](TECHNICAL_PLAN.md) §3 (yt-dlp is Python; workload is I/O + FFmpeg bound).

## Layout

```text
backend/
  app.py                       # ASGI entrypoint (uvicorn app:app)
  core/
    api.py                     # FastAPI routes: auth, rate limit, serialisation only
    service.py                 # pipeline: validate → detect → analyze → select → download → validate/process
    models.py  errors.py  config.py
    security/                  # url_guard (SSRF), safe_fetcher (DNS-pinned HTTP), filenames, ratelimit
    extractor/
      base/                    # Extractor interface + registry
      common/                  # ytdlp client/base adapter, OpenGraph parser
      youtube/ instagram/ freepik/ shutterstock/   # one adapter each
    downloader/selection.py    # item/format selection + preview opt-in rule
    processor/ffmpeg.py        # ffprobe validation, fixed-template FFmpeg, image validation
    storage/job_storage.py     # per-job 0700 temp dirs, quota, stale purge
    jobs/                      # RunControl (cancel/deadline/progress), JobManager (queue, TTL)
  tests/                       # 140 tests, no network required
```

### Adding a platform
1. Create `core/extractor/<site>/extractor.py` subclassing `Extractor` (or `YtDlpExtractor` / `OpenGraphExtractor`) with `platform`, `hosts`, `analyze()`, `download()`.
2. Add the class to `DEFAULT_EXTRACTORS` in `core/extractor/__init__.py`.
3. Add a test with a fake client/fetcher (see `tests/test_extractors_*.py`). Nothing else changes.

## Pipeline

`URL → parse_url (scheme/port/credentials/IDNA) → host allow-list match (extractor registry) → analyze (metadata + formats) → resolve_selection (ids must come from a fresh analyze) → download into the job dir (size/time caps, cancel) → ffprobe/Pillow validation → optional FFmpeg audio extraction → file served once, deleted on DELETE or after TTL.`

## API

| Method | Path | Notes |
|---|---|---|
| GET | `/healthz` | status + supported platforms (no auth) |
| POST | `/v1/analyze` `{url}` | platform, title, thumbnail, duration, `items[]` → `formats[]` (id, kind, ext, height, fps, codecs, filesize, has_audio, is_preview) |
| POST | `/v1/jobs` | `{url, item_id?, format_id?, output: original\|mp3\|m4a, accept_preview?}` → 202 job |
| GET | `/v1/jobs/{id}` | `state` queued/running/ready/failed/cancelled, `stage`, `bytes_done`, `bytes_total`, `percent`, `error{code,message}`, `file` |
| GET | `/v1/jobs/{id}/events` | SSE stream of the same snapshot |
| GET | `/v1/jobs/{id}/file` | the result (Range supported, `nosniff`, `no-store`) |
| DELETE | `/v1/jobs/{id}` | cancel + delete files |

Errors: `{"error": {"code", "message"}}` with codes `INVALID_URL, BLOCKED_HOST, UNSUPPORTED_URL, AUTH_REQUIRED, RESTRICTED_CONTENT, PREVIEW_ONLY, MEDIA_NOT_FOUND, TOO_LARGE, TIMEOUT, RATE_LIMITED, BUSY, UPSTREAM_ERROR, INVALID_MEDIA, PROCESSING_FAILED, JOB_NOT_FOUND, CANCELLED, UNAUTHORIZED, INVALID_REQUEST`. Interactive docs at `/docs`.

```bash
curl -s localhost:8000/v1/analyze -H 'content-type: application/json' -d '{"url":"https://www.youtube.com/watch?v=VIDEO"}'
curl -s localhost:8000/v1/jobs -H 'content-type: application/json' -d '{"url":"https://youtu.be/VIDEO","format_id":"137"}'   # 1080p, audio merged automatically
curl -s localhost:8000/v1/jobs -H 'content-type: application/json' -d '{"url":"https://youtu.be/VIDEO","output":"mp3"}'       # audio-only stream, converted
curl -OJ localhost:8000/v1/jobs/JOB_ID/file
```

## Platform support (honest status)

| Platform | Mechanism | What works | Limits |
|---|---|---|---|
| YouTube | yt-dlp | Public videos; per-resolution list; video+audio merge (stream copy); audio-only (m4a/opus) with optional mp3/m4a conversion; audio-only jobs never download the video stream | Private/members/age-gated/DRM/bot-check → `AUTH_REQUIRED`/`RESTRICTED_CONTENT`. YouTube changes often; keep yt-dlp updated. Server IPs are sometimes challenged. |
| Instagram | yt-dlp | Public posts/reels, carousels as separate items | Instagram often demands login even for public content; **stories always need login** → `AUTH_REQUIRED`. No cookies/credentials are used. |
| Freepik | OpenGraph/JSON-LD of the public page | Public **preview** image/video | Originals need an account/licence. Previews must be requested with `accept_preview: true`. No bypass. |
| Shutterstock | OpenGraph/JSON-LD of the public page | Public **preview** only (watermarked by Shutterstock) | Licensed originals need purchase. MediaFlow never removes watermarks. |

"No watermark" means MediaFlow adds none and re-encodes nothing unless you ask for audio conversion.
Not verified against live sites: the development sandbox blocks YouTube/Instagram/stock-site traffic, so
adapters are covered by unit tests with recorded-style fixtures. Run a live smoke test before release.

## Security model (implemented)

- **URL validation**: http/https only, ports 80/443, no userinfo, no control chars/backslashes, ≤2048 chars, IDNA-normalised, numeric/hex pseudo-IPs and `localhost/.local/.internal` rejected.
- **Host allow-list**: only domains owned by a registered extractor are accepted — arbitrary URLs are never fetched on the user's behalf by `/analyze`. Dot-boundary matching (`evilyoutube.com`, `youtube.com.evil.com` rejected).
- **SSRF**: `SafeFetcher` resolves DNS, requires *every* address to be globally routable (IPv4-mapped, NAT64, 6to4, Teredo unwrapped), connects to the validated IP (Host/SNI preserved → DNS-rebinding safe), re-validates each redirect (max 5), `identity` encoding, no proxy env.
- **Limits**: max file bytes (streamed counter + `Content-Length` precheck + yt-dlp `max_filesize`), page bytes, duration (ffprobe), image pixels, wall-clock job timeout with cooperative cancel, FFmpeg timeout, bounded concurrency/queue, per-client active-job cap, per-client request rate limit, disk quota.
- **Process safety**: no shell anywhere; FFmpeg argv from fixed templates with `-protocol_whitelist file`, absolute confined paths, enumerated output formats; yt-dlp used as a library with `ignoreconfig`, allowed-extractors restriction, no cookies.
- **Files**: server-generated names only; job dirs `0700` under one root, path confinement incl. symlink escape check; user-visible filename sanitised to `[A-Za-z0-9_-]`; magic-byte/Pillow/ffprobe validation, SVG/HTML rejected; atomic `.part` renames; failed/cancelled jobs deleted immediately, finished jobs after TTL, orphans purged at startup.
- **Access**: optional `X-API-Key` (constant-time compare); job ids are 192-bit random and scoped to the creating client IP; generic error messages (no stack traces/paths).

Known gaps: yt-dlp performs its own HTTP requests (restricted to allow-listed sites, but not routed through `SafeFetcher`/DNS pinning) → use egress filtering in production; rate limiting and job state are in-memory (single instance); client identity is IP-based (use `--proxy-headers` only behind a trusted proxy).

## Local development

```bash
cd backend
python -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt        # needs ffmpeg + ffprobe on PATH
python -m pytest -q
uvicorn app:app --reload --host 127.0.0.1 --port 8000
```

## Deployment

```bash
docker build -t mediaflow-backend backend
docker run -p 8000:8000 -v mediaflow-work:/work --read-only --tmpfs /tmp \
  -e MEDIAFLOW_API_KEY=change-me mediaflow-backend
```
Put it behind a TLS reverse proxy; block egress to private ranges at the network layer; run one replica (or add Redis-backed state/limits before scaling out); update yt-dlp regularly (`pip install -U yt-dlp`) and smoke-test.

## Not done yet / future work
- Flutter app still uses its on-device logic; wiring `lib/download_manager.dart` to this API (no UI change) is the next step. Web builds need `MEDIAFLOW_CORS_ORIGINS`.
- Official licensed-download integrations (Freepik / Shutterstock APIs with the user's own key and licence) for original-quality files.
- Live integration tests per platform; yt-dlp traffic through an egress proxy with SSRF filtering.
- Redis-backed queue/limits for multi-instance, per-user auth, metrics/structured logging, CI workflow.
