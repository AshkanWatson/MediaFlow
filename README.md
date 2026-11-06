# 🌊 MediaFlow

[![License: CC BY-NC 4.0](https://img.shields.io/badge/License-CC%20BY--NC%204.0-black.svg)](https://creativecommons.org/licenses/by-nc/4.0/)
[![Contributors](https://img.shields.io/github/contributors/AshkanWatson/MediaFlow?style=flat-square&color=black)](https://github.com/AshkanWatson/MediaFlow/graphs/contributors)
[![Downloads](https://img.shields.io/github/downloads/AshkanWatson/MediaFlow/total?style=flat-square&label=Downloads&color=black)](https://github.com/AshkanWatson/MediaFlow/releases)
[![Latest Release](https://img.shields.io/github/v/release/AshkanWatson/MediaFlow?style=flat-square&color=black)](https://github.com/AshkanWatson/MediaFlow/releases)

**MediaFlow** is a **cross-platform media downloader** built with **Flutter** and a **Python (FastAPI) backend / core engine** that lets you **download videos and images from multiple platforms**:  

- 🎥 **YouTube**  
- 📸 **Instagram**  
- 🎨 **Freepik**  
- 🖼 **Shutterstock**  
- ➕ **More platforms coming soon!**  

> **Non-commercial, community-driven project.**  
> Fork it, contribute, but don’t sell it. 🚫💰

---

## ✨ Features

- Multi-platform **video & image downloads**
- **Cross-platform support**: Android, iOS, Windows, macOS, Linux
- **Modular architecture** – add new downloaders easily
- **Python core engine** (`backend/`): URL validation + SSRF protection, platform adapters, job queue with progress, FFmpeg processing — see [docs/BACKEND.md](docs/BACKEND.md)
- **Open-source and community-friendly** 🚀

---

## 📥 Download

Get the **latest release** for your platform from our [Releases Page](https://github.com/AshkanWatson/MediaFlow/releases):

| Platform  | File Type | Download Link |
|----------|----------|---------------|
| **Android** | `.apk` | [Download](https://github.com/AshkanWatson/MediaFlow/releases/latest/download/MediaFlow.apk) |
| **Windows** | `.exe` | [Download](https://github.com/AshkanWatson/MediaFlow/releases/latest/download/MediaFlow.exe) |
| **macOS** | `.dmg` | [Download](https://github.com/AshkanWatson/MediaFlow/releases/latest/download/MediaFlow.dmg) |
| **Linux** | `.AppImage` | [Download](https://github.com/AshkanWatson/MediaFlow/releases/latest/download/MediaFlow.AppImage) |
| **Source Code** | `.zip` | [Download](https://github.com/AshkanWatson/MediaFlow/archive/refs/heads/main.zip) |

> [!TIP]
> Upload your builds to the **latest GitHub release** with these exact names to make the above links work automatically.

---

## 📦 Installation (from Source)

Clone the repository:

```bash
git clone https://github.com/AshkanWatson/MediaFlow.git
cd MediaFlow
```

Install dependencies:

```flutter pub get```

Run the project:

```flutter run```

### Backend (core engine)

```bash
cd backend && pip install -r requirements-dev.txt   # requires ffmpeg/ffprobe
python -m pytest -q
uvicorn app:app --host 127.0.0.1 --port 8000        # API docs at /docs
```

Supported sources: YouTube (formats, audio-only, mp3/m4a), Instagram (public posts/reels; login-gated content is
refused), Freepik and Shutterstock (public **previews only** — originals require a licence; no watermark removal,
no authentication/DRM/paywall bypass). Details, API usage, security model, limitations and deployment:
[docs/BACKEND.md](docs/BACKEND.md) · plan: [docs/TECHNICAL_PLAN.md](docs/TECHNICAL_PLAN.md).

> [!NOTE]
> The Flutter app does not call the backend yet; wiring it up is planned future work.

---

## 📸 Screenshots (Coming Soon)

| Platform  | File Type | Download Link |
|----------|----------|---------------|

---

## 🤝 Contributing

We love contributions! 🥳

1. Fork the repo
2. Create a feature branch
3. Commit your changes
4. Open a Pull Request

Check the [CONTRIBUTING.md](https://github.com/AshkanWatson/MediaFlow/blob/main/CONTRIBUTING.md) for full contribution guidelines.

---

## ⚖ License

This project is licensed under the Creative Commons Attribution-NonCommercial 4.0 International License.

- ✅ Free for personal and educational use
- ✅ Contributions welcome
- ❌ Commercial use is NOT allowed

See the [LICENSE](https://github.com/AshkanWatson/MediaFlow/blob/main/LICENSE.md) file for details.

---

## 🚀 Roadmap

- Support TikTok & Pinterest
- Desktop builds (Windows & macOS)
- Download queue and history
- Built-in media converter
- Multi-language support

---

## 🌎 Community

- 💬 Discussions: [GitHub Discussions](https://github.com/AshkanWatson/MediaFlow/discussions)
- 🐛 Issues: [Report a Bug](https://github.com/AshkanWatson/MediaFlow/issues)
- 📥 Latest Downloads: [Releases](https://github.com/AshkanWatson/MediaFlow/releases)

---

⭐️ Star MediaFlow if you love open-source media management and seamless content flow!

Made with ❤️ by AshkanWatson and the MediaFlow Community.
