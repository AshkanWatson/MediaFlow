# MediaFlow — Technical Plan: Media Downloader / Extractor

Status: **planning only**. No UI/UX/design changes and no downloader implementation are part of this document.

## 1. Current state (inspected)

| Area | Finding |
|---|---|
| Docs present | `README.md`, `CONTRIBUTING.md` only. No `PLAN.md` / `HANDOFF.md` / architecture docs existed. |
| Frontend | Flutter app (v1.3.1), almost everything in `lib/main.dart` (942 lines): UI, history, YouTube analysis, scraping, download, merge. |
| `lib/download_manager.dart` | Unused stub with fake delays (`_downloadYouTube`, `_downloadInstagram`). |
| On-device media logic | `youtube_explode_dart` (YouTube), `dio`/`http` (download), `html` + regex scraping (`og:video`, `"video_url"`, `.mp4`), `ffmpeg_kit_flutter_new` (merge audio+video, `-c:v copy -c:a aac`), `gal` (save to gallery). |
| Backend | `backend/app.py`: Flask, one `/convert` endpoint, `debug=True`, **accepts arbitrary `input_path`/`output_path` from the request** → arbitrary file read/write. Not used by the app. Must not be deployed as-is. |
| Tooling | Pub deps in `pubspec.yaml`; no CI, no tests, no `requirements.txt`, `.dart_tool/` and `build/` are committed to git (should be untracked). Build targets: android, ios, web, desktop. |
| Local env | Python 3.11 and FFmpeg 6.1 available; Flutter/Dart/yt-dlp not installed here. |

Observations that affect the plan:
- Instagram/Freepik/Shutterstock handling is a generic HTML regex scraper. It is fragile, and for Freepik/Shutterstock `og:image` is the **watermarked preview**. This must not be presented as "original media". Only content the user is entitled to (own account/licence, free/public assets) should be fetched.
- The Python backend is already mentioned in the README as "optional".
- Client-side extraction cannot run `yt-dlp`, can't safely hold site-specific logic that changes weekly, and web builds hit CORS. A server (or local sidecar) is needed for anything beyond direct URLs.

### Reusable as-is
Flutter UI, `HistoryService`, `DownloadRecord`/`MediaMetadata`/`StreamOption` models, Dio download-with-progress, `gal` saving, `ffmpeg_kit` for on-device merge/convert (mobile). `youtube_explode_dart` can remain as an offline fallback on mobile during migration.

## 2. Feasibility analysis

| Topic | Approach |
|---|---|
| URL handling | Parse with strict URL parser; allow only `http`/`https`; no credentials in URL; IDNA-normalise; length limit (2 KB); reject on any parse ambiguity. |
| Source detection | Order: (1) direct-media URL (HEAD + content-type sniff), (2) extractor match (yt-dlp extractor registry, allow-listed), (3) generic page metadata (`og:*`, `<video>`, `<img>`, JSON-LD) via safe fetcher. Unsupported → `UNSUPPORTED_URL`. |
| Extraction | yt-dlp (as a Python library, metadata-only first via `extract_info(download=False)`) for supported sites; native HTTP for direct media/images. No DRM, no login-walled content, no cookie import by default. |
| Video/audio | Select formats from yt-dlp's format list; if separate video+audio streams, download both and mux with FFmpeg **stream copy** (no re-encode, no watermark, no overlay filters). |
| Images | Direct download via the safe fetcher; validate with magic bytes + Pillow `verify()`; optionally convert with FFmpeg/Pillow only on explicit request. |
| Format detection | `ffprobe -print_format json -show_format -show_streams` on the finished file; reject if container/codec not on allow-list. |
| Metadata | Return title, uploader, duration, thumbnail, available formats (id, ext, res, fps, codec, filesize est.). Optionally embed title/artist via FFmpeg `-metadata`; strip unknown tags otherwise. |
| Progress | Job object with `state`, `bytes_done`, `bytes_total`, `speed`, `eta`; exposed via SSE (`/jobs/{id}/events`) with polling fallback (`GET /jobs/{id}`). yt-dlp progress hooks + FFmpeg `-progress pipe:1`. |
| Large files | Stream to disk in chunks; never buffer in RAM; serve with `Content-Length` + `Range`; hard cap (default 2 GB, configurable). |
| Temp files | Per-job directory under a dedicated work root (`/var/lib/mediaflow/jobs/<uuid>`); server-generated names only; atomic `.part` → final rename. |
| Storage / cleanup | TTL (default 30 min after completion), sweeper task, startup purge, disk-quota guard. Results are fetched once and deleted. |
| Concurrency | Bounded worker pool (e.g. 2–4 downloads, 1–2 FFmpeg), per-IP and global job caps, queue with back-pressure (429 when full). |
| Errors | Stable error codes: `INVALID_URL`, `BLOCKED_HOST`, `UNSUPPORTED_URL`, `AUTH_REQUIRED`, `GEO_OR_DRM_RESTRICTED`, `TOO_LARGE`, `TIMEOUT`, `RATE_LIMITED`, `UPSTREAM_ERROR`, `PROCESSING_FAILED`. Never leak stack traces or paths. |
| Rate limiting | Token bucket per client/IP on `/analyze` and `/jobs`; per-host politeness delay and retry/backoff with jitter on upstream 429/5xx. |
| Queue | In-process asyncio queue is enough for v1 (single node). Introduce Redis + worker (RQ/Arq) only if scaling beyond one host. |

## 3. Backend recommendation

| Option | Pros | Cons for this project |
|---|---|---|
| **Python (FastAPI)** | `yt-dlp` is Python and is best consumed as a library; huge media ecosystem (Pillow, ffmpeg wrappers, `httpx`); repo already has a Python backend and README/CONTRIBUTING already name Python; fastest iteration when extractors break. | Slower than compiled languages (irrelevant: workload is I/O + FFmpeg-bound); needs care with GIL (solved by subprocess/threads). |
| Node.js | Good async I/O. | yt-dlp only via subprocess; weaker media tooling; new language in repo. |
| Go | Great concurrency, single binary. | No native yt-dlp; would shell out; new language. |
| Rust | Max safety/perf. | Same shelling-out; slow development; no benefit when FFmpeg does the heavy work. |
| C++ | Direct libav access. | Highest complexity and memory-safety risk handling untrusted media; unjustified. |

**Recommendation: Python 3.11+ with FastAPI + `yt-dlp` (library) + `httpx` + FFmpeg/ffprobe subprocess.** Reuse and replace the existing Flask `backend/app.py` (its `/convert` endpoint is unsafe and is removed), keeping the `backend/` location. The hot path (bytes transfer, transcoding) is I/O/FFmpeg-bound, so language speed doesn't matter; yt-dlp compatibility does. Introducing Rust/Go/C++ would add a language and build chain for no measurable gain. Revisit only if a profiled bottleneck appears.

Flutter stays the client; it calls the backend through a single API client (replacing the scattered scraping in `main.dart`, done later and without visual changes).

## 4. Proposed architecture

```text
User
  ↓
Flutter app (existing UI; thin ApiClient replaces on-device scraping)
  ↓  HTTPS, JSON + SSE
FastAPI backend (backend/)
  ├─ Auth/rate-limit middleware, request size/time limits
  ↓
URL validation + SSRF guard      ← scheme/port allow-list, DNS resolve, IP deny-list, pinned IP
  ↓
Source detector → Extractor registry
  ├─ yt-dlp adapter (metadata only, allow-listed extractors)
  ├─ Direct-media/image adapter
  └─ Generic page-metadata adapter (safe fetcher)
  ↓
Job queue (asyncio, bounded)
  ↓
Download manager (httpx stream / yt-dlp with injected safe opener, size+time caps)
  ↓
ffprobe validation → FFmpeg (only for mux/extract-audio/convert, fixed arg templates)
  ↓
Job temp dir (isolated, TTL)
  ↓
Result endpoint (Range-capable) → Flutter saves via path_provider / gal
```

Suggested layout (not created yet):

```text
backend/
  app/main.py            # FastAPI app factory, routers
  app/api/               # analyze.py, jobs.py, health.py, schemas.py
  app/security/          # url_guard.py, ssrf.py, limits.py
  app/extractors/        # base.py, ytdlp.py, direct.py, generic.py
  app/download/          # manager.py, fetcher.py, progress.py
  app/media/             # ffmpeg.py (arg templates), ffprobe.py, validate.py
  app/storage/           # jobs.py, cleanup.py
  tests/
  requirements.txt  Dockerfile  .env.example
```

## 5. API design (v1)

| Method & path | Purpose |
|---|---|
| `GET /healthz` | Liveness; reports ffmpeg/yt-dlp versions. |
| `POST /v1/analyze` `{url}` | Validate + detect + return metadata and format list. No download. |
| `POST /v1/jobs` `{url, format_id?, kind: video\|audio\|image, audio_format?}` | Create download job → `202 {job_id}`. Format IDs must come from a prior analyze result; never free-form. |
| `GET /v1/jobs/{id}` | State + progress. |
| `GET /v1/jobs/{id}/events` | SSE progress stream. |
| `GET /v1/jobs/{id}/file` | Stream result (Range, `Content-Disposition` with sanitised name). |
| `DELETE /v1/jobs/{id}` | Cancel/cleanup. |

Job states: `queued → analyzing → downloading → processing → ready → expired | failed | cancelled`. Job IDs are unguessable UUIDv4 + per-client ownership token.

## 6. FFmpeg integration

- Backend-side: call `ffmpeg`/`ffprobe` via `asyncio.create_subprocess_exec` with an **argument list, never `shell=True`**. User input never becomes an argument; only server-chosen templates with validated enums/ints:
  - mux: `ffmpeg -nostdin -hide_banner -protocol_whitelist file,pipe -i V -i A -c copy -map 0:v:0 -map 1:a:0 -movflags +faststart OUT`
  - audio extract: `-vn -c:a libmp3lame -b:a {128|192|320}k` or `-c:a copy`
  - always: `-nostdin`, `-protocol_whitelist file`, `-threads N`, `-t`/size cap (`-fs`), explicit input/output paths inside the job dir, `-progress pipe:1`.
- No `-vf`/`drawtext`/`overlay` filters, so output carries **no added watermark**; default is stream copy to avoid quality loss.
- Run under a timeout, `RLIMIT_CPU/AS/NOFILE`, as a non-root user, ideally in a container with no network access for the FFmpeg step (inputs are already local files).
- Pin FFmpeg ≥ 6.x/7.x and patch regularly (demuxer CVEs).
- Client-side `ffmpeg_kit_flutter_new` remains an offline option on mobile, but the command at `main.dart:479` interpolates file paths into a command string; when touched, move to a fixed argument list.

## 7. Security model

| Threat | Mitigation |
|---|---|
| SSRF / localhost / private IPs | Resolve DNS once, check **all** A/AAAA against deny-list (loopback, RFC1918, link-local incl. `169.254.169.254`, CGNAT, multicast, ULA/`fc00::/7`, IPv4-mapped IPv6, `0.0.0.0`); connect to the **pinned IP** (defeats DNS rebinding); re-validate on **every redirect** (max 5); ports 80/443 only; reject userinfo, non-HTTP(S) schemes (`file:`, `ftp:`, `gopher:`, `data:`). Also enforce at network layer (egress firewall / separate network namespace). Apply the same guard to yt-dlp via a custom handler or by resolving through our fetcher; disable yt-dlp's generic extractor and `--enable-file-urls`. |
| Command injection | No shell; arg lists; fixed templates; URLs passed to libraries, not command lines; any URL starting with `-` rejected. |
| Unsafe FFmpeg args | Allow-listed options/enums; `-protocol_whitelist file,pipe`; reject HLS/concat playlist inputs from untrusted files unless first fetched and rewritten by us. |
| Arbitrary file write / path traversal | Server-generated filenames (UUID); job-dir confinement via `Path.resolve()` + `is_relative_to`; sanitised download name only in header. Remove existing `input_path`/`output_path` API. |
| Malicious media | `ffprobe` validation, codec/container allow-list, magic-byte check, Pillow `verify()` + max pixel count (decompression bomb), max duration/streams; process in a sandboxed, unprivileged container. |
| Size / time / resource exhaustion | Max response bytes (streamed counter), max duration, wall-clock timeouts, per-job CPU/mem limits, disk quota, bounded queue, per-IP concurrency, request body limit. |
| Abuse / open proxy | Rate limit, optional API key/auth, don't return raw upstream bodies, only normalised metadata. |
| Info leakage | Generic errors; log URL host only, redact query strings/tokens; CORS locked to known origins; `debug=False`. |
| Supply chain | Pin and hash dependencies; keep yt-dlp updatable independently (scheduled update + smoke tests). |

## 8. Processing flow

1. Client `POST /v1/analyze` → URL guard → detect → extractor returns metadata/formats.
2. User picks a format (UI unchanged) → `POST /v1/jobs`.
3. Worker re-validates URL, downloads with caps, streams progress.
4. `ffprobe` validates; FFmpeg muxes/converts only if needed (stream copy preferred).
5. File moved to result slot; state `ready`; client downloads once, then job dir deleted (or by TTL).

## 9. Dependencies and deployment

Backend: `fastapi`, `uvicorn[standard]`, `httpx`, `yt-dlp` (update-able), `pydantic`, `Pillow`, `python-magic` (or `filetype`), `slowapi` (or custom limiter), `pytest`, `respx`/`pytest-asyncio`, `ruff`. System: `ffmpeg` + `ffprobe` (≥ 6), `libmagic`.
Deployment: Docker image (python:3.11-slim + ffmpeg), non-root user, read-only root FS with a tmpfs/volume work dir, resource limits, egress filtering, reverse proxy (TLS, request-size caps), `/healthz`. Local dev: `uvicorn app.main:app` on `127.0.0.1`; desktop builds may bundle it as a local sidecar. Frontend config: `API_BASE_URL` via `--dart-define`.

## 10. Development phases

0. **Hygiene**: untrack `.dart_tool/` and `build/`, add `requirements.txt`, `.env.example`, CI (flutter analyze/test, ruff, pytest). Remove/replace unsafe `/convert`.
1. **Security core**: `url_guard`, SSRF-safe fetcher, limits, with thorough unit tests (private IPs, redirects, rebinding, odd encodings).
2. **Backend skeleton**: FastAPI, `/healthz`, `/v1/analyze` for direct media/images.
3. **Download manager + jobs**: queue, progress, temp storage, cleanup, file endpoint.
4. **yt-dlp adapter**: allow-listed extractors, format selection, video+audio mux via FFmpeg.
5. **FFmpeg/ffprobe module**: fixed templates, validation, timeouts, tests.
6. **Flutter integration**: `ApiClient`, wire `DownloadManager` to the backend with no visual change; keep `youtube_explode_dart` fallback until parity.
7. **Hardening**: fuzz/abuse tests, load test, container sandbox, observability, docs.
8. **Per-site adapters** (Instagram, TikTok, Pinterest, etc.) one at a time, each reviewed against that site's ToS.

## 11. Limitations

- Site extractors break often; yt-dlp must be kept current.
- Many sites need login/cookies, use DRM or signed short-lived URLs; those are out of scope.
- Server-side downloading means server IP reputation/rate-limits from platforms; heavy bandwidth/storage cost if public.
- Stock sites (Freepik, Shutterstock) serve watermarked previews publicly; full-resolution files require a licence/account. The app must not strip watermarks and should only fetch what the user is entitled to.
- Web build cannot download cross-origin media directly (CORS) — it relies on the backend.
- iOS/Android store policies may restrict downloader apps (e.g. YouTube).

## 12. Legal / ToS considerations

- "No watermark" means **MediaFlow never adds its own** and preserves the original bytes (stream copy) — it does **not** remove existing watermarks.
- Do not bypass DRM, paywalls, private/age/geo gates, or authentication; return `AUTH_REQUIRED`/`RESTRICTED` instead.
- Many platforms (YouTube, Instagram, TikTok, stock sites) prohibit downloading in their ToS; provide a notice that users are responsible for rights to content, support only content the user owns, has a licence for, or that is openly licensed, and honour takedown requests.
- Respect `robots.txt`-style signals and rate limits for generic fetching; identify with an honest User-Agent for generic fetches (the current browser-spoofing UA in `main.dart` should be reconsidered).
- Project licence is CC BY-NC 4.0; yt-dlp (Unlicense) and FFmpeg (LGPL/GPL depending on build) have their own obligations — prefer an LGPL FFmpeg build and avoid linking GPL-only components in distributed binaries.
- Include a user-facing disclaimer/terms page (content change deferred; no design work now).
