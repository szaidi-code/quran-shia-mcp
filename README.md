# Shia Quran & Tafseer MCP Server (`v1.2.0`)

A high-performance Model Context Protocol (MCP) server providing the **complete 114 Surahs (6,236 verses)** of the Holy Quran with **verbatim Tanzil Simple v1.1 Arabic text**, verified Urdu & English translations, explanatory footnotes (*hawashi*), and classical Shia Tafseer commentary.

- **Hosted MCP Endpoint (Streamable HTTP & SSE):** `https://quran-shia-mcp.onrender.com/mcp`
- **Interactive Explorer & Documentation Portal:** [`https://quran-shia-mcp.onrender.com/documentation`](https://quran-shia-mcp.onrender.com/documentation)
- **Tool Reference (`#available-tools`):** [`https://quran-shia-mcp.onrender.com/documentation#available-tools`](https://quran-shia-mcp.onrender.com/documentation#available-tools)

---

## Scholarly Corpus & Supported Editions

| Edition ID | Category | Title | Scholar / Author | Language | Source & License |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `quran-simple` | Quran Text | **Tanzil Quran Text (Simple, v1.1)** | Tanzil Project | Arabic (`ar`) | [Tanzil.net](https://tanzil.net) (CC BY 3.0 Verbatim) |
| `jawadi` (`ur.jawadi`) | Translation | **ترجمہ علامہ سید ذیشان حیدر جوادی** | Allama Syed Zeeshan Haider Jawadi | Urdu (`ur`) | [Tanzil.net](https://tanzil.net/trans/ur.jawadi) (CC BY-NC-ND 3.0) |
| `balagh` | Translation & Hawashi | **بلاغ القرآن (Balagh ul Quran)** | Allama Sheikh Mohsin Ali Najafi | Urdu (`ur`) | [balaghulquran.com](https://www.balaghulquran.com) |
| `namoona` | Translation | **ترجمہ تفسیر نمونہ** | Maulana Syed Safdar Hussain Najafi | Urdu (`ur`) | [tafseerenamoona.net](https://www.tafseerenamoona.net) |
| `en.yusufali-shakir` | Translation | **English Translation** | Abdullah Yusuf Ali & M. H. Shakir | English (`en`) | [tafseerenamoona.net](https://www.tafseerenamoona.net) |
| `kauthar` | Tafseer | **الکوثر فی تفسیر القرآن (Tafseer al-Kauthar)** | Allama Sheikh Mohsin Ali Najafi | Urdu (`ur`) | [balaghulquran.com](https://www.balaghulquran.com) |
| `namoona` | Tafseer | **تفسیر نمونہ (Tafseer e Namoona)** | Grand Ayatollah Naser Makarem Shirazi | Urdu / English | [tafseerenamoona.net](https://www.tafseerenamoona.net) |

---

## Quick Setup: Connect Your AI Client

### 1. Antigravity, Claude Desktop, or Cursor IDE (`mcp_config.json`)
Add the following block to your MCP configuration (`~/.gemini/config/mcp_config.json`, `claude_desktop_config.json`, or Cursor MCP settings):

```json
{
  "mcpServers": {
    "quran-shia": {
      "url": "https://quran-shia-mcp.onrender.com/mcp"
    }
  }
}
```

### 2. Claude Web Connectors (Pro / Team)
1. Go to **Settings > Connectors > Add custom connector**.
2. Set **Name** to `Shia Quran & Tafseer` and **URL** to `https://quran-shia-mcp.onrender.com/mcp`.
3. *Note:* Because this is a public server requiring no OAuth login, if Claude displays *"Couldn't determine how this server signs in"*, click **Continue anyway** and leave authentication set to **None**.

### 3. ChatGPT (Developer MCP / Custom GPT Actions)
1. In ChatGPT Developer Mode / Connectors, add `https://quran-shia-mcp.onrender.com/mcp` with Authentication set to **None**.

---

## How to Use: Your First Study Session

Once connected, ask your AI assistant questions by **Surah:Ayah reference**, **Arabic phrase** (with or without diacritics), or **theological topic**. Every tool response embeds `grounding_rules` instructing the AI assistant to **always render the full verbatim Arabic verse text (`arabic`) visibly at the top of its response**.

### Example Prompts to Try

1. **Classical Shia Exegesis (Ayat al-Istikhlaf — 24:55):**
   > *"Give me the Tafseer of Ayat al-Istikhlaf (Surah An-Nur 24:55) with the Arabic verse and Urdu/English translations."*
   - Calls `fetch_tafseer(surah=24, ayah=55, source="all")`
   - Displays the verbatim Tanzil Arabic verse:
     > وَعَدَ اللَّهُ الَّذِينَ آمَنُوا مِنكُمْ وَعَمِلُوا الصَّالِحَاتِ لَيَسْتَخْلِفَنَّهُمْ فِي الْأَرْضِ كَمَا اسْتَخْلَفَ الَّذِينَ مِن قَبْلِهِمْ وَلَيُمَكِّنَنَّ لَهُمْ دِينَهُمُ الَّذِي ارْتَضَىٰ لَهُمْ وَلَيُبَدِّلَنَّهُم مِّن بَعْدِ خَوْفِهِمْ أَمْنًا ۚ يَعْبُدُونَنِي لَا يُشْرِكُونَ بِي شَيْئًا ۚ وَمَن كَفَرَ بَعْدَ ذَٰلِكَ فَأُولَٰئِكَ هُمُ الْفَاسِقُونَ
   - Summarizes commentary from *Tafseer e Namoona* and *Tafseer al-Kauthar* (including narrations from the Ahlulbayt (a.s.) regarding the universal government of Imam al-Mahdi a.s.).

2. **Comparative Scholarly Translation (Verse of Wilayah — 5:55):**
   > *"Compare Allama Jawadi, Balagh ul Quran, and Tafseer e Namoona on Surah Al-Ma'idah 5:55 and explain its Shan-e-Nuzool."*
   - Calls `fetch_translation(surah=5, ayah=55, edition="all")` and `fetch_tafseer(surah=5, ayah=55, source="all")`.

3. **Diacritics-Insensitive Arabic Search (Verse of Tatheer — 33:33):**
   > *"Search the Quran for 'ليذهب عنكم الرجس اهل البيت' and show the full vocalized Arabic verse and translations."*
   - Calls `search_verses(query="ليذهب عنكم الرجس اهل البيت", edition="all")` using custom Arabic normalization (`NORM_AR`).

---

## Tool Reference (`#available-tools`)

7 documented MCP tools across 2 ordered groups:

### Group 1: Search & Retrieval

| Tool | Parameters | Status | Description |
| :--- | :--- | :--- | :--- |
| **`fetch_quran`** | `surah` (int, req), `ayah` (int, opt), `ayahs` (str, opt) | 1 req · 2 opt | Fetch canonical verbatim Tanzil Simple v1.1 Arabic text (`quran-simple`) by Surah, Ayah, or Ayah range (e.g. `"24:55"` or `"2:255-257"`). |
| **`fetch_translation`** | `surah` (int, req), `ayah` (int, opt), `edition` (`"all"` \| `"jawadi"` \| `"balagh"` \| `"namoona"`) | 1 req · 2 opt | Fetch verbatim Tanzil Simple v1.1 Arabic text with Urdu and English translations, Balagh footnotes, and Tanzil attribution. |
| **`fetch_tafseer`** | `surah` (int, req), `ayah` (int, req), `source` (`"all"` \| `"kauthar"` \| `"namoona"`) | 2 req · 1 opt | Fetch verbatim Arabic text, translations, and full classical Shia Tafseer commentaries from *Al-Kauthar* and *Tafseer e Namoona*. |
| **`search_verses`** | `query` (str, req), `edition` (`"all"` \| `"jawadi"` \| `"balagh"` \| `"namoona"`) | 1 req · 1 opt | Diacritics-insensitive & Alef-normalized Arabic search (`NORM_AR`) plus full-text search across translations, footnotes, and commentary. |

### Group 2: Grounding & Structural Discovery

| Tool | Parameters | Status | Description |
| :--- | :--- | :--- | :--- |
| **`list_editions`** | `edition_type` (`"all"` \| `"quran"` \| `"translation"` \| `"tafseer"`) | 0 req · 1 opt | Discover available Quran Arabic text, Urdu/English translation, and Shia Tafseer commentary editions with author and license metadata. |
| **`fetch_grounding_rules`** | *none* | 0 req · 0 opt | Retrieve canonical grounding rules requiring verbatim Arabic quoting and explicit scholarly attribution. |
| **`list_surahs`** | *none* | 0 req · 0 opt | List all 114 Surahs with Arabic name, English name, and canonical verse count. |

---

## Licensing & Attribution (Tanzil.net)

- **Canonical Arabic Text (`quran-simple` v1.1):** Provided verbatim from the **[Tanzil Project](https://tanzil.net)** (`data/tanzil/quran-simple.sql`) under **Creative Commons Attribution 3.0** (verbatim copy; changing text is not allowed).
- **Allama Syed Zeeshan Haider Jawadi Urdu Translation (`ur.jawadi`):** Provided verbatim from **[Tanzil.net](https://tanzil.net/trans/ur.jawadi)** (`data/tanzil/ur.jawadi.txt`) under **Creative Commons Attribution-NonCommercial-NoDerivs 3.0** ([Tanzil Translation Terms](https://tanzil.net/trans/)).

---

## Architecture & Deployment on Render

- **Fast & Self-Contained:** Backed by a pre-indexed relational SQLite database (`quran_shia.db`) and verified Tanzil corpus (`data/tanzil/`) containing all **114 Surahs** and **6,236 verses**. Zero external Python runtime dependencies.
- **Endpoints:**
  - `GET /` or `GET /documentation` — Interactive 114-Surah Verse & Tafseer Explorer + Setup & Tool Reference Documentation Portal.
  - `GET /health` — Health check endpoint (`version: "1.2.0"`).
  - `POST /mcp` — Standard Streamable HTTP JSON-RPC 2.0 MCP protocol endpoint.
  - `GET /sse` — Server-Sent Events (SSE) stream endpoint for remote MCP clients.
