# Quran Shia MCP Server

A high-performance Model Context Protocol (MCP) server providing authentic Shia Quranic translations and Tafseer commentary from authoritative scholarly sources:

1. **Balagh ul Quran (بلاغ القرآن)** — Urdu translation, footnotes, and *Tafseer al-Kauthar* (الکوثر فی تفسیر القرآن) by **Allama Sheikh Mohsin Ali Najafi**.
2. **Tafseer e Namoona (تفسیر نمونہ)** — Urdu translation by **Maulana Syed Safdar Hussain Najafi** and commentary by **Grand Ayatollah Naser Makarem Shirazi**.
3. **English Translations** — Abdullah Yusuf Ali & M. H. Shakir.

---

## Capabilities & MCP Tools

| Tool | Parameters | Description |
| :--- | :--- | :--- |
| `fetch_translation` | `surah` (int), `ayah` (int, optional), `edition` ("all" \| "balagh" \| "namoona") | Returns Arabic verse with selected Urdu and English translations & footnotes. |
| `fetch_tafseer` | `surah` (int), `ayah` (int), `source` ("kauthar" \| "namoona" \| "all") | Returns comprehensive scholarly Tafseer commentaries. |
| `search_verses` | `query` (str), `edition` ("all" \| "balagh" \| "namoona") | Full-text search across Arabic text, translations, and notes. |

---

## Architecture & Endpoints

- **Fast & Self-Contained**: Backed by a relational SQLite database (`quran_shia.db`). Zero external runtime dependencies.
- **Endpoints**:
  - `GET /health` — Health check endpoint.
  - `POST /mcp` — Standard JSON-RPC 2.0 MCP protocol endpoint.
  - `GET /sse` — Server-Sent Events (SSE) stream endpoint for remote MCP clients.

---

## Deploying on Render

This repository includes [`render.yaml`](render.yaml) for 1-click deployment on [Render](https://render.com):

1. Link this repository in Render as a **Web Service**.
2. Environment: **Python 3**
3. Build Command: `python3 builder.py`
4. Start Command: `python3 server.py`
5. Health Check Path: `/health`

Once deployed, your remote MCP endpoint will be:
```
https://<your-render-subdomain>.onrender.com/sse
```

### Adding to Antigravity, Claude, or Cursor

```json
{
  "mcpServers": {
    "quran-shia": {
      "url": "https://<your-render-subdomain>.onrender.com/sse"
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

### Run on Kubernetes (k3s / k3d)
```bash
docker build -t quran-shia-mcp:v1.0.0 .
kubectl apply -f k8s-local.yaml
```
