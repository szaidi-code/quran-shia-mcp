# Quran Shia MCP Server (v2.0.0 — All 114 Surahs)

A high-performance Model Context Protocol (MCP) server providing the complete 114 Surahs (6,236 verses) of the Holy Quran with authentic Shia translations, footnotes, and Tafseer commentary from authoritative scholarly sources:

1. **Balagh ul Quran (بلاغ القرآن)** — Urdu translation, explanatory footnotes (حواشی), and *Tafseer al-Kauthar* (الکوثر فی تفسیر القرآن) by **Allama Sheikh Mohsin Ali Najafi**.
2. **Tafseer e Namoona (تفسیر نمونہ)** — Urdu translation by **Maulana Syed Safdar Hussain Najafi** and full multi-volume commentary (Urdu & English) by **Grand Ayatollah Naser Makarem Shirazi**.
3. **English Translations** — Abdullah Yusuf Ali & M. H. Shakir.

---

## Capabilities & MCP Tools

| Tool | Parameters | Description |
| :--- | :--- | :--- |
| `fetch_translation` | `surah` (1–114), `ayah` (int, optional), `edition` ("all" \| "balagh" \| "namoona") | Returns Arabic verse(s) with Urdu and English translations & Balagh ul Quran footnotes. |
| `fetch_tafseer` | `surah` (1–114), `ayah` (int), `source` ("kauthar" \| "namoona" \| "all") | Returns comprehensive scholarly Tafseer commentaries from *Al-Kauthar* and *Tafseer e Namoona*. |
| `search_verses` | `query` (str), `edition` ("all" \| "balagh" \| "namoona") | Full-text search across all 6,236 verses (Arabic text, translations, footnotes, and commentary). |
| `list_surahs` | *none* | Lists all 114 Surahs with Arabic name, English name, and canonical verse count. |

---

## Architecture & Endpoints

- **Fast & Self-Contained**: Backed by a pre-indexed relational SQLite database (`quran_shia.db`) containing all **114 Surahs** and **6,236 verses**. Zero external runtime dependencies.
- **Endpoints**:
  - `GET /` or `GET /documentation` — Interactive 114-Surah Verse & Tafseer Explorer + Setup Documentation Portal.
  - `GET /health` — Health check endpoint with live database statistics (`surahs: 114`, `verses: 6236`).
  - `POST /mcp` — Standard Streamable HTTP JSON-RPC 2.0 MCP protocol endpoint.
  - `GET /sse` — Server-Sent Events (SSE) stream endpoint for remote MCP clients.

---

## Deploying on Render

This repository includes [`render.yaml`](render.yaml) for 1-click deployment on [Render](https://render.com):

1. Link this repository in Render as a **Web Service**.
2. Environment: **Python 3**
3. Build Command: `python3 builder.py` (verifies the pre-built 114-Surah `quran_shia.db` or builds from scratch if `--rebuild` is passed)
4. Start Command: `python3 server.py`
5. Health Check Path: `/health`

Once deployed, your remote MCP endpoint is:
```
https://quran-shia-mcp.onrender.com/mcp
```

### Adding to Antigravity, Claude, or Cursor

```json
{
  "mcpServers": {
    "quran-shia": {
      "url": "https://quran-shia-mcp.onrender.com/mcp"
    }
  }
}
```

---

## Local Development & Kubernetes

### Run Locally
```bash
python3 builder.py
python3 server.py
```

### Rebuild All 114 Surahs from Scratch
```bash
python3 builder.py --rebuild
```

### Run on Kubernetes (k3s / k3d)
```bash
docker build -t quran-shia-mcp:v2.0.0 .
kubectl apply -f k8s-local.yaml
```
