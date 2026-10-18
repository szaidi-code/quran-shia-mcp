# Quran Shia MCP Server (v1.2.0 — Complete 114 Surahs & Allama Jawadi Edition)

A high-performance Model Context Protocol (MCP) server providing the complete 114 Surahs (6,236 verses) of the Holy Quran with authentic Shia translations, footnotes, and Tafseer commentary from authoritative scholarly sources:

1. **Allama Syed Zeeshan Haider Jawadi (علامہ سید ذیشان حیدر جوادی)** — Complete Urdu translation (`ur.jawadi`) across all 114 Surahs / 6,236 ayahs via [Tanzil.net](https://tanzil.net/trans/ur.jawadi).
2. **Balagh ul Quran (بلاغ القرآن)** — Urdu translation, explanatory footnotes (حواشی), and *Tafseer al-Kauthar* (الکوثر فی تفسیر القرآن) by **Allama Sheikh Mohsin Ali Najafi**.
3. **Tafseer e Namoona (تفسیر نمونہ)** — Urdu translation by **Maulana Syed Safdar Hussain Najafi** and full multi-volume commentary (Urdu & English) by **Grand Ayatollah Naser Makarem Shirazi**.
4. **English Translations** — Abdullah Yusuf Ali & M. H. Shakir.

---

## Capabilities & MCP Tools

| Tool | Parameters | Description |
| :--- | :--- | :--- |
| `fetch_translation` | `surah` (1–114), `ayah` (int, optional), `edition` ("all" \| "balagh" \| "namoona" \| "jawadi") | Returns Arabic verse(s) with Urdu and English translations, Balagh footnotes, and Tanzil attribution. |
| `fetch_tafseer` | `surah` (1–114), `ayah` (int), `source` ("kauthar" \| "namoona" \| "all") | Returns comprehensive scholarly Tafseer commentaries from *Al-Kauthar* and *Tafseer e Namoona*. |
| `search_verses` | `query` (str), `edition` ("all" \| "balagh" \| "namoona" \| "jawadi") | Full-text search across all 6,236 verses (Arabic text, translations, footnotes, and commentary). |
| `list_surahs` | *none* | Lists all 114 Surahs with Arabic name, English name, and canonical verse count. |

---

## Licensing & Attribution (Tanzil.net)

- The Allama Syed Zeeshan Haider Jawadi Urdu translation (`data/tanzil/ur.jawadi.txt`) is provided verbatim from **[Tanzil.net](https://tanzil.net/trans/ur.jawadi)** under the **Creative Commons Attribution-NonCommercial-NoDerivs 3.0** license ([Tanzil Translation Terms](https://tanzil.net/trans/)).
- It is for **non-commercial use only**, must not be altered, and every API response carrying Jawadi text includes a `sources.jawadi` attribution block linking back to `https://tanzil.net/trans/ur.jawadi`.

---

## Architecture & Endpoints

- **Fast & Self-Contained**: Backed by a pre-indexed relational SQLite database (`quran_shia.db`) and verified Tanzil corpus (`data/tanzil/ur.jawadi.txt`) containing all **114 Surahs** and **6,236 verses**. Zero external runtime dependencies.
- **Endpoints**:
  - `GET /` or `GET /documentation` — Interactive 114-Surah Verse & Tafseer Explorer + Setup Documentation Portal.
  - `GET /health` — Health check endpoint (`version: "1.2.0"`).
  - `POST /mcp` — Standard Streamable HTTP JSON-RPC 2.0 MCP protocol endpoint.
  - `GET /sse` — Server-Sent Events (SSE) stream endpoint for remote MCP clients.

---

## Deploying on Render

This repository includes [`render.yaml`](render.yaml) for 1-click deployment on [Render](https://render.com):

1. Link this repository in Render as a **Web Service**.
2. Environment: **Python 3**
3. Build Command: `python3 builder.py`
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
