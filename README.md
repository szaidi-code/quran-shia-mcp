# Shia Quran & Tafseer MCP Server (`v1.3.0`)

A high-performance Model Context Protocol (MCP) server providing the **complete 114 Surahs (6,236 verses)** of the Holy Quran with **verbatim Tanzil Simple v1.1 Arabic text**, verified Urdu & English translations, explanatory footnotes (*hawashi*), classical Shia Tafseer commentary, Arabic word morphology/paradigm/concordance tools, interactive Mushaf study, and structural metadata (including Ja‘fari *wājib* vs *mustaḥabb* Sajdah rulings).

Implements **100% of the 14-tool suite documented at [`mcp.quran.ai/documentation#available-tools`](https://mcp.quran.ai/documentation#available-tools)** plus **3 classic Shia Quran MCP tools** (**17 tools total across 5 groups**).

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
| `namoona-tafseer` | Tafseer | **تفسیر نمونہ (Tafseer e Namoona)** | Grand Ayatollah Naser Makarem Shirazi | Urdu / English | [tafseerenamoona.net](https://www.tafseerenamoona.net) |

---

## Tool Reference (`#available-tools` — 17 Tools Across 5 Groups)

### Group 1: Grounding and Setup (`#grounding-setup`)
| Tool | Parameters | Description |
| :--- | :--- | :--- |
| **`fetch_grounding_rules`** | *none* | Returns canonical grounding rules requiring verbatim Arabic quoting and scholarly attribution, plus a `grounding_nonce`. |
| **`list_editions`** | `edition_type` (`"all"` \| `"quran"` \| `"tafsir"` \| `"tafseer"` \| `"translation"` \| list), `lang` (opt) | Discover available Quran Arabic text, Urdu/English translation, and Shia Tafseer commentary editions. |

### Group 2: Search and Retrieval (`#search-and-retrieval`)
| Tool | Parameters | Description |
| :--- | :--- | :--- |
| **`fetch_quran`** | `ayahs` (str/list, e.g. `"2:255"`, `"26:88-89"`), `surah`, `ayah`, `editions`, `continuation`, `grounding_nonce` | Fetch canonical verbatim Tanzil Simple v1.1 Arabic text (`quran-simple`) by single verse, range, multi-range, or Surah. |
| **`search_quran`** | `query`, `surah`, `translations`, `intent`, `continuation`, `grounding_nonce` | Search semantically and lexically across Quran Arabic text (diacritics-insensitive) with Shia translations attached. |
| **`fetch_tafsir`** | `ayahs` (str/list), `surah`, `ayah`, `editions` / `source` (`"all"` \| `"kauthar"` \| `"namoona"`), `continuation`, `grounding_nonce` | Fetch full Shia Tafsir blocks (*Tafseer al-Kauthar* & *Tafseer e Namoona*, auto-resolving grouped Namoona ranges) for single verses, ranges, or lists. |
| **`fetch_tafseer`** | `surah`, `ayah`, `ayahs`, `source` (`"all"` \| `"kauthar"` \| `"namoona"`) | Classic Shia MCP alias for `fetch_tafsir`. |
| **`search_tafsir`** | `query`, `editions`, `surah`, `ayahs`, `include_ayah_text`, `intent`, `continuation`, `grounding_nonce` | Search Shia commentary content (*Al-Kauthar*, *Balagh* footnotes, and *Tafseer e Namoona*) by topic or phrase. |
| **`fetch_translation`** | `ayahs` (str/list), `surah`, `ayah`, `editions` / `edition` (`"all"` \| `"jawadi"` \| `"balagh"` \| `"namoona"` \| `"en"` \| `"ur"`) | Fetch verbatim Tanzil Arabic text with Jawadi, Balagh ul Quran, Namoona, and English translations. |
| **`search_translation`** | `query`, `surah`, `editions`, `intent`, `continuation`, `grounding_nonce` | Search translation text directly across Jawadi, Balagh, Namoona, and English editions. |
| **`search_verses`** | `query` (req), `edition` (`"all"` \| `"jawadi"` \| `"balagh"` \| `"namoona"`), `surah` (opt) | Diacritics-insensitive Arabic (`NORM_AR`) and full-text Urdu/English translation & commentary search. |

### Group 3: Word Study (`#word-study`)
| Tool | Parameters | Description |
| :--- | :--- | :--- |
| **`fetch_word_morphology`** | `ayah_key`, `word`, `word_position`, `word_text` | Inspect a Quranic word at the segment, grammar, root, lemma, and stem level with Shia verse translation context. |
| **`fetch_word_paradigm`** | `ayah_key`, `lemma`, `root`, `word_position`, `word_text` | Explore a Quranic word's derivational family across perfect, imperfect, and imperative stems and candidate lemmas. |
| **`fetch_word_concordance`** | `ayah_key`, `word`, `root`, `lemma`, `stem`, `word_position`, `word_text`, `match_by`, `group_by`, `page`, `page_size`, `rerank_from`, `continuation` | Find related occurrences by exact stem, lemma, or root, enriched with canonical Tanzil Arabic and Shia translations. |

### Group 4: Apps & Interactive Reader (`#apps`)
| Tool | Parameters | Description |
| :--- | :--- | :--- |
| **`interactive_study`** | `page` (1–604), `surah` (1–114), `ayah`, `juz` (1–30), `context_id`, `continuation_selection`, `render_mode`, `resume` | Open the 604-page Mushaf reader state together with `shia_study_verses` (translations & Tafseer URLs for every verse on the page). |
| **`resolve_reader_link`** | `ayahs` (req, e.g. `"3:37-38"`), `phrase` (opt), `reader_target` (opt) | Create a verified reader link to an ayah, range, or exact Arabic phrase with word-span coordinates and direct Shia Tafseer links. |

### Group 5: Utilities & Structural Metadata (`#utilities`)
| Tool | Parameters | Description |
| :--- | :--- | :--- |
| **`fetch_quran_metadata`** | `surah`, `ayah`, `juz` (1–30), `page` (1–604), `hizb` (1–60), `ruku` (1–558), `manzil` (1–7) | Fetch structural metadata including Sajdah verses with explicit Ja‘fari rulings (*wājib* obligatory in 32:15, 41:37–38, 53:62, 96:19 vs *mustaḥabb*). |
| **`list_surahs`** | *none* | List all 114 Surahs with Arabic name, English name, and canonical verse count. |
