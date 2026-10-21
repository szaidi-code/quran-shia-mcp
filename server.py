#!/usr/bin/env python3
"""
Shia Quran & Tafseer HTTP / SSE MCP Server (v1.3.0)
Supports both JSON-RPC via HTTP POST (Streamable HTTP) and Server-Sent Events (SSE).
Implements the complete 14-tool suite from https://mcp.quran.ai/documentation#available-tools
plus the 3 classic Shia Quran MCP tools (17 tools across 5 groups).
Zero external dependencies (uses standard library http.server, urllib, and sqlite3).
Ready for Render, Fly.io, and Kubernetes.
"""
import sys
import json
import sqlite3
import threading
from pathlib import Path
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
import urllib.parse
import urllib.request
import re
import html
import uuid
import os

import builder
import jawadi_loader

DB_PATH = Path(os.environ.get("DB_PATH", Path(__file__).parent / "quran_shia.db"))
PORT = int(os.environ.get("PORT", 8080))
HOST = os.environ.get("HOST", "0.0.0.0")
VERSION = "1.3.0"
SUPPORTED_PROTOCOLS = ("2025-06-18", "2025-03-26", "2024-11-05")
UPSTREAM_QURAN_AI_URL = os.environ.get("UPSTREAM_QURAN_AI_URL", "https://mcp.quran.ai")
GROUNDING_NONCE = "quran-shia-grounding-v1.3"

GROUNDING_NOTICE = (
    "CRITICAL DISPLAY RULE: Always render the full verbatim 'arabic' verse text "
    "(Tanzil Simple v1.1) prominently at the top of your response before presenting "
    "translations or Tafseer commentary. Never omit, truncate, or paraphrase the Arabic text."
)

GROUNDING_RULES_MARKDOWN = (
    "# Grounding Rules for Shia Quran & Tafseer MCP\n\n"
    "1. **Always Render Verbatim Arabic Text (`quran-simple`)**: In every response that discusses a Quranic verse, "
    "translation, or Tafseer commentary, you MUST visibly display the exact Arabic verse text (`arabic`) at the top "
    "of your output without altering letters, diacritics, or waqf marks. Never omit, truncate, or reconstruct Quranic Arabic from memory.\n"
    "2. **Verbatim Translations**: Preserve Allama Syed Zeeshan Haider Jawadi's translation (`ur.jawadi` from Tanzil.net under CC BY-NC-ND 3.0), "
    "Allama Sheikh Mohsin Ali Najafi's *Balagh ul Quran*, and Maulana Syed Safdar Hussain Najafi's translation accurately with explicit attribution.\n"
    "3. **Source-Grounded Shia Tafseer**: Distinguish clearly between *Tafseer al-Kauthar* (Allama Sheikh Mohsin Ali Najafi) "
    "and *Tafseer e Namoona* (Grand Ayatollah Naser Makarem Shirazi), and cite the verse key (`surah:ayah`) and source URL.\n"
    f"4. **Grounding Nonce**: Pass `grounding_nonce=\"{GROUNDING_NONCE}\"` on subsequent tool calls to suppress repeated grounding notices while continuing to follow these rules."
)

# Canonical 30 Juz starting points (surah, ayah)
JUZ_STARTS = [
    (1, 1), (2, 142), (2, 253), (3, 93), (4, 24), (4, 148), (5, 82), (6, 111), (7, 88), (8, 41),
    (9, 93), (11, 6), (12, 53), (15, 1), (17, 1), (18, 75), (21, 1), (23, 1), (25, 21), (27, 56),
    (29, 46), (33, 31), (36, 28), (39, 32), (41, 47), (46, 1), (51, 31), (58, 1), (67, 1), (78, 1),
]

# Canonical 7 Manzil starting surahs
MANZIL_STARTS = [1, 5, 10, 17, 26, 37, 50]

# Sajdah verses in the Quran, marking the 4 obligatory (wajib) Sajdahs in Ja'fari (Shia) jurisprudence
SAJDAH_VERSES = {
    "7:206": {"recommended": True, "obligatory": False, "jafari_ruling": "mustahabb (recommended)"},
    "13:15": {"recommended": True, "obligatory": False, "jafari_ruling": "mustahabb (recommended)"},
    "16:50": {"recommended": True, "obligatory": False, "jafari_ruling": "mustahabb (recommended)"},
    "17:109": {"recommended": True, "obligatory": False, "jafari_ruling": "mustahabb (recommended)"},
    "19:58": {"recommended": True, "obligatory": False, "jafari_ruling": "mustahabb (recommended)"},
    "22:18": {"recommended": True, "obligatory": False, "jafari_ruling": "mustahabb (recommended)"},
    "22:77": {"recommended": True, "obligatory": False, "jafari_ruling": "mustahabb (recommended)"},
    "25:60": {"recommended": True, "obligatory": False, "jafari_ruling": "mustahabb (recommended)"},
    "27:26": {"recommended": True, "obligatory": False, "jafari_ruling": "mustahabb (recommended)"},
    "32:15": {"recommended": False, "obligatory": True, "jafari_ruling": "wajib (obligatory — Suwar al-'Aza'im)"},
    "38:24": {"recommended": True, "obligatory": False, "jafari_ruling": "mustahabb (recommended)"},
    "41:37": {"recommended": False, "obligatory": True, "jafari_ruling": "wajib (obligatory in Ja'fari fiqh — 41:37-38)"},
    "41:38": {"recommended": False, "obligatory": True, "jafari_ruling": "wajib (obligatory — Suwar al-'Aza'im)"},
    "53:62": {"recommended": False, "obligatory": True, "jafari_ruling": "wajib (obligatory — Suwar al-'Aza'im)"},
    "84:21": {"recommended": True, "obligatory": False, "jafari_ruling": "mustahabb (recommended)"},
    "96:19": {"recommended": False, "obligatory": True, "jafari_ruling": "wajib (obligatory — Suwar al-'Aza'im)"},
}

TOOLS = [
    # === GROUP 1: Grounding and setup ===
    {
        "name": "fetch_grounding_rules",
        "description": (
            "Return canonical grounding rules for quoting Arabic Quranic text, translations, and Shia Tafseer "
            "commentaries accurately with proper scholarly attribution, along with a grounding_nonce that "
            "suppresses repeated grounding payloads on subsequent tool calls."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {}
        }
    },
    {
        "name": "list_editions",
        "description": (
            "Discovery tool for edition IDs. List available Quran Arabic text ('quran'), Urdu/English translation "
            "('translation'), and Shia Tafseer commentary ('tafsir' / 'tafseer') editions with author, language, and license metadata."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "edition_type": {
                    "description": "Type of editions to list: 'all', 'quran', 'tafsir', 'tafseer', 'translation', or a list of types.",
                    "default": "all"
                },
                "lang": {
                    "type": "string",
                    "description": "Optional 2-letter language code to filter editions (e.g., 'ur', 'en', 'ar')."
                }
            }
        }
    },
    # === GROUP 2: Search and retrieval ===
    {
        "name": "fetch_quran",
        "description": (
            "Fetch canonical verbatim Arabic Quran text (Tanzil Simple v1.1, 'quran-simple') for known ayah references. "
            "Accepts 'ayahs' (single '2:255', range '2:255-257', comma-separated '2:255-260, 3:33', or list) "
            "or 'surah' and optional 'ayah'. IMPORTANT: Always display the returned 'arabic' text visibly to the user."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "ayahs": {
                    "description": "Verse reference(s): single ('2:255'), range ('2:255-257'), comma-separated ('2:255-260, 3:33'), or array of strings."
                },
                "surah": {"type": "integer", "description": "Optional Surah number (1-114) when fetching by surah/ayah."},
                "ayah": {"type": "integer", "description": "Optional specific Ayah number within the Surah."},
                "editions": {
                    "description": "Optional Arabic edition selector(s) (defaults to 'quran-simple')."
                },
                "continuation": {"type": "string", "description": "Optional pagination continuation token."},
                "grounding_nonce": {"type": "string", "description": "Optional grounding nonce from fetch_grounding_rules."}
            }
        }
    },
    {
        "name": "search_quran",
        "description": (
            "Search semantically and lexically across Quran Arabic text (diacritics-insensitive) with optional Shia "
            "and English translations attached (Allama Jawadi, Balagh ul Quran, Tafseer e Namoona, English)."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query in Arabic, Urdu, or English (e.g., 'patience', 'الصبر', 'آية الكرسي')."},
                "surah": {"type": "integer", "description": "Optional Surah number (1-114) to restrict search to a specific chapter."},
                "translations": {
                    "description": "Translation control: None, 'auto' (default), 'all', 'jawadi', 'balagh', 'namoona', 'ur', 'en', or list of edition IDs."
                },
                "intent": {
                    "type": "string",
                    "description": "Optional reason for search (identify-ayah, find-related-ayat, show-context, interpret-text, clarify-phrase, compare-editions, explore-topic, seek-guidance, study-concept)."
                },
                "continuation": {"type": "string", "description": "Optional pagination continuation token."},
                "grounding_nonce": {"type": "string", "description": "Optional grounding nonce from fetch_grounding_rules."}
            }
        }
    },
    {
        "name": "fetch_tafsir",
        "description": (
            "Fetch full Shia Tafsir blocks for known ayah references from Al-Kauthar fi Tafsir al-Quran "
            "(Allama Sheikh Mohsin Ali Najafi) and Tafseer e Namoona (Grand Ayatollah Naser Makarem Shirazi / "
            "Maulana Syed Safdar Hussain Najafi), including verbatim Arabic text and translations. "
            "Accepts 'ayahs' ('2:255', '26:88-89', or list) or 'surah' + 'ayah'."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "ayahs": {
                    "description": "Verse reference(s): single ('2:255'), range ('26:88-89'), comma-separated ('5:55, 33:33'), or list."
                },
                "surah": {"type": "integer", "description": "Surah number (1-114) if 'ayahs' is not provided."},
                "ayah": {"type": "integer", "description": "Ayah number within the Surah (default: 1) if 'ayahs' is not provided."},
                "editions": {
                    "description": "Tafsir edition selector(s): 'all', 'kauthar', 'namoona', or list (default: 'all')."
                },
                "source": {
                    "type": "string",
                    "enum": ["kauthar", "namoona", "all"],
                    "description": "Alias for editions: 'kauthar', 'namoona', or 'all' (default: 'all').",
                    "default": "all"
                },
                "continuation": {"type": "string", "description": "Optional pagination continuation token."},
                "grounding_nonce": {"type": "string", "description": "Optional grounding nonce from fetch_grounding_rules."}
            }
        }
    },
    {
        "name": "fetch_tafseer",
        "description": (
            "Fetch detailed Quranic Tafseer commentaries from Al-Kauthar fi Tafsir al-Quran "
            "(Sheikh Mohsin Ali Najafi) or Tafseer e Namoona (Ayatollah Makarem Shirazi / Safdar Najfi), "
            "including the canonical Arabic verse text ('arabic') and translations. "
            "IMPORTANT: Always display the full 'arabic' verse text visibly at the top of your response."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "surah": {"type": "integer", "description": "Surah number (1-114)"},
                "ayah": {"type": "integer", "description": "Ayah number within the Surah (default: 1)"},
                "ayahs": {
                    "description": "Optional verse reference(s) ('2:255', '26:88-89', or list) as an alternative to surah/ayah."
                },
                "source": {
                    "type": "string",
                    "enum": ["kauthar", "namoona", "all"],
                    "description": "Tafseer work to query (default: 'all')",
                    "default": "all"
                },
                "editions": {"description": "Optional alias for source ('kauthar', 'namoona', 'all')."}
            }
        }
    },
    {
        "name": "search_tafsir",
        "description": (
            "Search Shia Tafsir commentary content (Tafseer al-Kauthar, Balagh ul Quran footnotes, and Tafseer e Namoona) "
            "when the user knows the topic or concept but not the exact ayah."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Thematic or lexical search query in English, Urdu, or Arabic."},
                "editions": {
                    "description": "Optional Tafsir edition filter(s): 'all', 'kauthar', 'namoona', or list."
                },
                "surah": {"type": "integer", "description": "Optional hard Surah filter (1-114)."},
                "ayahs": {
                    "description": "Optional hard Quran-reference scope ('2:217', '2:216-218', comma-separated, or list)."
                },
                "include_ayah_text": {
                    "type": "boolean",
                    "description": "Include the verbatim Arabic ayah text being explained (default: true).",
                    "default": True
                },
                "intent": {"type": "string", "description": "Optional search intent telemetry label."},
                "continuation": {"type": "string", "description": "Optional pagination continuation token."},
                "grounding_nonce": {"type": "string", "description": "Optional grounding nonce from fetch_grounding_rules."}
            }
        }
    },
    {
        "name": "fetch_translation",
        "description": (
            "Fetch Quranic verses with verbatim Tanzil Arabic text ('arabic') and Urdu/English translations from "
            "Balagh ul Quran (Allama Sheikh Mohsin Ali Najafi), Tafseer e Namoona "
            "(Maulana Syed Safdar Hussain Najafi), and Allama Syed Zeeshan Haider Jawadi (Tanzil.net). "
            "Accepts 'ayahs' ('2:255', '2:255-257', or list) or 'surah' and optional 'ayah'."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "surah": {"type": "integer", "description": "Surah number (1-114) if 'ayahs' is not provided."},
                "ayah": {"type": "integer", "description": "Optional specific Ayah number within the Surah."},
                "ayahs": {
                    "description": "Optional verse reference(s): single ('2:255'), range ('2:255-257'), comma-separated, or list."
                },
                "edition": {
                    "type": "string",
                    "enum": ["all", "balagh", "namoona", "jawadi", "en", "ur"],
                    "description": "Translation source (default: 'all')",
                    "default": "all"
                },
                "editions": {
                    "description": "Optional edition identifier(s): 'all', 'jawadi', 'balagh', 'namoona', 'en', 'ur', or list."
                },
                "continuation": {"type": "string", "description": "Optional pagination continuation token."},
                "grounding_nonce": {"type": "string", "description": "Optional grounding nonce from fetch_grounding_rules."}
            }
        }
    },
    {
        "name": "search_translation",
        "description": (
            "Search translation text directly across Allama Jawadi (ur.jawadi), Balagh ul Quran, Tafseer e Namoona, "
            "and English translations when edition filtering matters."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query in Urdu, English, or Arabic."},
                "surah": {"type": "integer", "description": "Optional Surah number (1-114) to restrict search to a specific chapter."},
                "editions": {
                    "description": "Edition filter: 'auto' (default), 'all', 'jawadi', 'balagh', 'namoona', 'ur', 'en', or list."
                },
                "intent": {"type": "string", "description": "Optional search intent telemetry label."},
                "continuation": {"type": "string", "description": "Optional pagination continuation token."},
                "grounding_nonce": {"type": "string", "description": "Optional grounding nonce from fetch_grounding_rules."}
            }
        }
    },
    {
        "name": "search_verses",
        "description": (
            "Search for keywords across Arabic text (diacritics-insensitive), Balagh ul Quran, "
            "Tafseer e Namoona, Allama Jawadi translations, footnotes, and Tafseer commentary. "
            "Returns matching verses with full 'arabic' text. Always show the 'arabic' text in results."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search keyword (Arabic, Urdu, or English)"},
                "edition": {
                    "type": "string",
                    "enum": ["all", "balagh", "namoona", "jawadi"],
                    "default": "all"
                },
                "surah": {"type": "integer", "description": "Optional Surah number (1-114) filter."}
            },
            "required": ["query"]
        }
    },
    # === GROUP 3: Word study ===
    {
        "name": "fetch_word_morphology",
        "description": (
            "Inspect a Quranic word at the segment and grammar level. Includes root, lemma, stem, feature tags, "
            "frequencies, plain-language morphological description, and Shia translation context for the verse."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "ayah_key": {"type": "string", "description": "Verse reference (e.g., '1:1', '2:77'). Returns all words in the verse, or a specific word if word_position/word_text is provided."},
                "word": {"type": "string", "description": "Arabic word text to look up (e.g., 'يَعْلَمُونَ'). Returns first occurrence. Mutually exclusive with ayah_key."},
                "word_position": {"type": "integer", "description": "1-based word position within the verse. Requires ayah_key."},
                "word_text": {"type": "string", "description": "Arabic word text to find within the verse (e.g., 'يَعْلَمُونَ'). Requires ayah_key."}
            }
        }
    },
    {
        "name": "fetch_word_paradigm",
        "description": (
            "Move from one Quranic word, lemma, or root to its derivational family across perfect, imperfect, "
            "and imperative verbal stems and candidate lemmas."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "ayah_key": {"type": "string", "description": "Verse reference (e.g., '2:77'). Resolves word at word_position/word_text to its lemma, then shows paradigm."},
                "lemma": {"type": "string", "description": "Arabic lemma text to look up (e.g., 'عَلِمَ')."},
                "root": {"type": "string", "description": "Arabic root letters (e.g., 'ع ل م' or 'علم')."},
                "word_position": {"type": "integer", "description": "1-based word position within the verse. Requires ayah_key."},
                "word_text": {"type": "string", "description": "Arabic word text to find within the verse. Requires ayah_key."}
            }
        }
    },
    {
        "name": "fetch_word_concordance",
        "description": (
            "Find related occurrences across the Quran by exact stem, lemma, or root, enriched with canonical "
            "Tanzil Arabic text and Shia translations (Jawadi, Balagh ul Quran, Tafseer e Namoona)."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "ayah_key": {"type": "string", "description": "Verse reference (e.g., '2:77'). Resolves word at word_position/word_text to root/lemma/stem."},
                "word": {"type": "string", "description": "Arabic word text to look up across the Quran."},
                "root": {"type": "string", "description": "Arabic root letters (e.g., 'ع ل م' or 'علم')."},
                "lemma": {"type": "string", "description": "Arabic lemma text (e.g., 'عَلِمَ')."},
                "stem": {"type": "string", "description": "Arabic stem text."},
                "word_position": {"type": "integer", "description": "1-based word position within the verse. Requires ayah_key."},
                "word_text": {"type": "string", "description": "Arabic word text to find within the verse. Requires ayah_key."},
                "match_by": {
                    "type": "string",
                    "enum": ["all", "root", "lemma", "stem"],
                    "default": "all",
                    "description": "Match scope: 'all', 'root', 'lemma', or 'stem'."
                },
                "group_by": {
                    "type": "string",
                    "enum": ["verse", "word"],
                    "default": "verse",
                    "description": "Grouping mode: 'verse' or 'word'."
                },
                "page": {"type": "integer", "default": 1, "description": "Page number (1-based)."},
                "page_size": {"type": "integer", "default": 20, "description": "Results per page (1-100)."},
                "rerank_from": {"type": "string", "description": "Optional source verse key for semantic reranking."},
                "continuation": {"type": "string", "description": "Optional pagination continuation token."}
            }
        }
    },
    # === GROUP 4: Apps ===
    {
        "name": "interactive_study",
        "description": (
            "Open the interactive Quran study reader at a page (1-604), juz (1-30), surah (1-114), or ayah location. "
            "Returns the Mushaf page layout together with Shia translations and Tafseer links for all verses on the page."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "page": {"type": "integer", "description": "Mushaf page number (1-604)."},
                "surah": {"type": "integer", "description": "Surah number (1-114). Optionally combined with ayah."},
                "ayah": {"type": "integer", "description": "Ayah number within the Surah. Requires surah."},
                "juz": {"type": "integer", "description": "Juz number (1-30)."},
                "context_id": {"type": "string", "description": "Optional durable public locator for interactive-study state."},
                "continuation_selection": {"type": "object", "description": "Optional exact ayah, word, phrase, or passages selection."},
                "render_mode": {"type": "string", "enum": ["inline", "fullscreen"], "description": "Optional presentation override."},
                "resume": {"type": "boolean", "default": False, "description": "Attempt saved-state recovery."}
            }
        }
    },
    {
        "name": "resolve_reader_link",
        "description": (
            "Create a verified reader link to an ayah, same-surah range ('3:37-38'), or exact Arabic phrase "
            "('كُلَّمَا دَخَلَ عَلَيۡهَا'), including word-span coordinates and direct Shia Tafseer links."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "ayahs": {"type": "string", "description": "One same-surah point ('3:37') or forward range ('3:37-38')."},
                "phrase": {"type": "string", "description": "Optional Arabic phrase copied from the Quran text."},
                "reader_target": {"type": "string", "description": "Optional navigation target."}
            },
            "required": ["ayahs"]
        }
    },
    # === GROUP 5: Utilities ===
    {
        "name": "fetch_quran_metadata",
        "description": (
            "Fetch structural metadata for ayah, surah, juz, page, hizb, ruku, or manzil lookups, "
            "including Sajdah rulings (with Ja'fari wajib vs mustahabb prostration classification)."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "surah": {"type": "integer", "description": "Surah number (1-114). Use alone for surah overview, or with ayah for a specific verse."},
                "ayah": {"type": "integer", "description": "Ayah number within the surah. Requires surah parameter."},
                "juz": {"type": "integer", "description": "Juz number (1-30)."},
                "page": {"type": "integer", "description": "Mushaf page number (1-604)."},
                "hizb": {"type": "integer", "description": "Hizb number (1-60)."},
                "ruku": {"type": "integer", "description": "Ruku number (1-558)."},
                "manzil": {"type": "integer", "description": "Manzil number (1-7)."}
            }
        }
    },
    {
        "name": "list_surahs",
        "description": "List all 114 Surahs of the Holy Quran with Arabic name, English name, and total verse (ayah) count.",
        "inputSchema": {
            "type": "object",
            "properties": {}
        }
    }
]

ARABIC_DIACRITICS_RE = re.compile(r"[\u0640\u064B-\u065F\u0670\u06D6-\u06ED\u0671]+")
_UPSTREAM_LOCK = threading.Lock()
_UPSTREAM_SESSION_ID = None


def normalize_arabic(text):
    """Strips Arabic harakat/tashkeel, tatweel, and normalizes Alef/Ya/Ta-Marbuta for search."""
    if not text:
        return ""
    s = text.replace("\u0671", "ا")
    s = ARABIC_DIACRITICS_RE.sub("", s)
    s = re.sub(r"[أإآٱ]", "ا", s)
    s = s.replace("ى", "ي").replace("ک", "ك").replace("ی", "ي").replace("ہ", "ه").replace("ة", "ه")
    return re.sub(r"\s+", " ", s).strip()


def _valid_arabic(val):
    if not val:
        return ""
    s = val.strip()
    if s.startswith("$") and len(s) < 12:
        return ""
    return s


def get_db():
    conn = sqlite3.connect(DB_PATH, timeout=20)
    conn.row_factory = sqlite3.Row
    conn.create_function("NORM_AR", 1, normalize_arabic)
    return conn


def _clean_html(raw):
    return builder.clean_html(raw)


def _call_upstream_quran_ai(tool_name, arguments, timeout=12):
    """
    Calls the upstream mcp.quran.ai JSON-RPC server for word-level QAC morphology,
    paradigm, concordance, 604-page Mushaf layout, or semantic search fallback.
    Returns (parsed_text_dict, structured_content_dict) or (None, None) on error.
    """
    global _UPSTREAM_SESSION_ID

    def _do_post(payload, sid=None):
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "User-Agent": f"quran-shia-mcp/{VERSION}",
        }
        if sid:
            headers["Mcp-Session-Id"] = sid
        req = urllib.request.Request(
            UPSTREAM_QURAN_AI_URL,
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            new_sid = resp.headers.get("mcp-session-id") or sid
            body = resp.read().decode("utf-8")
            for line in body.splitlines():
                if line.startswith("data: "):
                    return new_sid, json.loads(line[6:])
            return new_sid, json.loads(body)

    try:
        with _UPSTREAM_LOCK:
            sid = _UPSTREAM_SESSION_ID
        if not sid:
            sid, _ = _do_post(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2025-03-26",
                        "capabilities": {},
                        "clientInfo": {"name": "quran-shia-mcp", "version": VERSION},
                    },
                }
            )
            with _UPSTREAM_LOCK:
                _UPSTREAM_SESSION_ID = sid

        clean_args = {k: v for k, v in (arguments or {}).items() if v is not None}
        try:
            _, rpc_res = _do_post(
                {
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "tools/call",
                    "params": {"name": tool_name, "arguments": clean_args},
                },
                sid=sid,
            )
        except Exception:
            sid, _ = _do_post(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2025-03-26",
                        "capabilities": {},
                        "clientInfo": {"name": "quran-shia-mcp", "version": VERSION},
                    },
                }
            )
            with _UPSTREAM_LOCK:
                _UPSTREAM_SESSION_ID = sid
            _, rpc_res = _do_post(
                {
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "tools/call",
                    "params": {"name": tool_name, "arguments": clean_args},
                },
                sid=sid,
            )

        result = rpc_res.get("result") or {}
        if result.get("isError"):
            return None, None
        structured = result.get("structuredContent")
        text_content = ""
        for item in result.get("content") or []:
            if item.get("type") == "text":
                text_content = item.get("text", "")
                break
        parsed_text = None
        if text_content:
            try:
                parsed_text = json.loads(text_content)
            except Exception:
                parsed_text = {"text": text_content}
        return parsed_text, structured
    except Exception:
        return None, None


def parse_ayah_references(ayahs=None, surah=None, ayah=None):
    """
    Parses flexible verse specifications into an ordered list of (surah, ayah) tuples.
    Supports:
      - ayahs="2:255"
      - ayahs="2:255-257"
      - ayahs="2:255-257, 3:33"
      - ayahs=["2:255", "3:33-35"]
      - surah=24, ayah=55
      - surah=24, ayahs="55-57"
      - surah=1 (entire surah)
    """
    refs = []
    seen = set()

    def _add(s, a):
        jawadi_loader.validate_surah_ayah(s, a)
        key = (s, a)
        if key not in seen:
            seen.add(key)
            refs.append(key)

    if ayahs is not None:
        items = ayahs if isinstance(ayahs, list) else [ayahs]
        tokens = []
        for item in items:
            if item is None:
                continue
            for part in re.split(r"[,;\s]+", str(item).strip()):
                if part:
                    tokens.append(part)
        for tok in tokens:
            if ":" in tok:
                s_str, a_str = tok.split(":", 1)
                s_num = int(s_str.strip())
                if "-" in a_str:
                    p1, p2 = a_str.split("-", 1)
                    a_start, a_end = int(p1.strip()), int(p2.strip())
                    if a_end < a_start:
                        a_start, a_end = a_end, a_start
                    for a_num in range(a_start, a_end + 1):
                        _add(s_num, a_num)
                else:
                    _add(s_num, int(a_str.strip()))
            elif surah is not None:
                s_num = int(surah)
                if "-" in tok:
                    p1, p2 = tok.split("-", 1)
                    a_start, a_end = int(p1.strip()), int(p2.strip())
                    if a_end < a_start:
                        a_start, a_end = a_end, a_start
                    for a_num in range(a_start, a_end + 1):
                        _add(s_num, a_num)
                else:
                    _add(s_num, int(tok.strip()))
            else:
                # Plain integer treated as surah if between 1 and 114
                s_num = int(tok.strip())
                jawadi_loader.validate_surah_ayah(s_num)
                for a_num in range(1, jawadi_loader.AYAH_COUNTS[s_num] + 1):
                    _add(s_num, a_num)
        if refs:
            return refs

    s_num = int(surah) if surah is not None else 1
    if ayah is not None:
        _add(s_num, int(ayah))
    else:
        jawadi_loader.validate_surah_ayah(s_num)
        for a_num in range(1, jawadi_loader.AYAH_COUNTS[s_num] + 1):
            _add(s_num, a_num)
    return refs


def _ensure_surah_cached(conn, surah):
    cur = conn.cursor()
    cur.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='verses'"
    )
    if not cur.fetchone():
        return
    cur.execute("SELECT COUNT(*) FROM verses WHERE surah = ?", (surah,))
    if cur.fetchone()[0] > 0:
        return
    try:
        sdata, balagh_map, kauthar_map = builder.fetch_complete_surah(surah)
        ayah_count = sdata["ayah_count"]
        cur.execute(
            "INSERT OR REPLACE INTO surahs (id, name_ar, name_en, ayah_count) VALUES (?, ?, ?, ?)",
            (surah, sdata["name_ar"], sdata["name_en"], ayah_count),
        )
        for a in range(1, ayah_count + 1):
            n = sdata["ayahs"].get(a, {})
            b = balagh_map.get(a, {})
            cur.execute(
                """
                INSERT OR REPLACE INTO verses
                (surah, ayah, verse_key, arabic, trans_balagh, trans_namoona, trans_en, footnotes_balagh, tafseer_kauthar, tafseer_namoona)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    surah,
                    a,
                    f"{surah}:{a}",
                    n.get("arabic") or b.get("arabic") or "",
                    b.get("trans_balagh") or n.get("trans_balagh") or "",
                    n.get("trans_namoona") or "",
                    n.get("trans_en") or "",
                    b.get("footnotes") or "",
                    kauthar_map.get(a, ""),
                    n.get("tafseer_namoona") or "",
                ),
            )
        conn.commit()
    except Exception:
        pass


def _ensure_kauthar_tafseer(conn, surah, ayah):
    cur = conn.cursor()
    cur.execute("SELECT tafseer_kauthar FROM verses WHERE surah = ? AND ayah = ?", (surah, ayah))
    row = cur.fetchone()
    if row and row["tafseer_kauthar"]:
        return row["tafseer_kauthar"]
    text = builder.fetch_balagh_tafseer(surah, ayah)
    if text:
        cur.execute("UPDATE verses SET tafseer_kauthar = ? WHERE surah = ? AND ayah = ?", (text, surah, ayah))
        conn.commit()
    return text


def _resolve_namoona_tafseer(conn, surah, ayah, raw_text):
    """
    If Tafseer-e-Namoona groups several verses together and stores a pointer such as
    'See ayat 104 for tafseer' or 'تفسیر آیت 104 کے تحت ملاحظہ کریں', automatically
    fetch and inline the grouped commentary from the target ayah in the same surah.
    """
    if not raw_text:
        return ""
    if len(raw_text) < 260:
        m = re.search(r"(?:See\s+ayat|آیت)\s*(\d+)", raw_text, flags=re.I)
        if m:
            target_ayah = int(m.group(1))
            if target_ayah != ayah:
                cur = conn.cursor()
                cur.execute(
                    "SELECT tafseer_namoona FROM verses WHERE surah = ? AND ayah = ?",
                    (surah, target_ayah),
                )
                trow = cur.fetchone()
                if trow and trow["tafseer_namoona"] and len(trow["tafseer_namoona"]) > len(raw_text):
                    return (
                        f"[Grouped commentary under Surah {surah}, Ayah {target_ayah} in Tafseer-e-Namoona]\n\n"
                        f"{trow['tafseer_namoona']}"
                    )
    return raw_text


def _fetch_shia_verse_bundle(conn, surah, ayah):
    """Fetches a complete verse dictionary from quran_shia.db."""
    cur = conn.cursor()
    cur.execute("SELECT text FROM quran_text_tanzil WHERE surah = ? AND ayah = ?", (surah, ayah))
    arow = cur.fetchone()
    cur.execute("SELECT text FROM translation_jawadi WHERE surah = ? AND ayah = ?", (surah, ayah))
    jrow = cur.fetchone()
    cur.execute("SELECT * FROM verses WHERE surah = ? AND ayah = ?", (surah, ayah))
    vrow = cur.fetchone()

    arabic = (arow["text"] if arow and arow["text"] else (_valid_arabic(vrow["arabic"]) if vrow else ""))
    return {
        "verse_key": f"{surah}:{ayah}",
        "ayah_key": f"{surah}:{ayah}",
        "surah": surah,
        "ayah": ayah,
        "arabic": arabic,
        "translation_jawadi": jrow["text"] if jrow else "",
        "translation_balagh": vrow["trans_balagh"] if vrow else "",
        "footnotes_balagh": vrow["footnotes_balagh"] if vrow else "",
        "translation_namoona": vrow["trans_namoona"] if vrow else "",
        "english": vrow["trans_en"] if vrow else "",
        "tafseer_kauthar": (vrow["tafseer_kauthar"] if vrow else "") or "",
        "tafseer_namoona": _resolve_namoona_tafseer(
            conn, surah, ayah, (vrow["tafseer_namoona"] if vrow else "") or ""
        ),
    }


def _grounding_for_call(args):
    nonce = (args or {}).get("grounding_nonce")
    if nonce and (nonce == GROUNDING_NONCE or "read-the-grounding-rules" in str(nonce)):
        return None
    return GROUNDING_NOTICE


def _compute_juz_for_verse(surah, ayah):
    juz_num = 1
    for idx, (js, ja) in enumerate(JUZ_STARTS, start=1):
        if (surah, ayah) >= (js, ja):
            juz_num = idx
        else:
            break
    return juz_num


def _compute_manzil_for_surah(surah):
    manzil_num = 1
    for idx, ms in enumerate(MANZIL_STARTS, start=1):
        if surah >= ms:
            manzil_num = idx
        else:
            break
    return manzil_num


def execute_tool(name, args):
    args = args or {}
    conn = get_db()
    try:
        cur = conn.cursor()

        # ------------------------------------------------------------------
        # 1. fetch_grounding_rules
        # ------------------------------------------------------------------
        if name == "fetch_grounding_rules":
            return {
                "result": GROUNDING_RULES_MARKDOWN,
                "grounding_rules": GROUNDING_RULES_MARKDOWN,
                "grounding_nonce": GROUNDING_NONCE,
            }

        # ------------------------------------------------------------------
        # 2. list_editions
        # ------------------------------------------------------------------
        elif name == "list_editions":
            raw_type = args.get("edition_type", "all")
            lang_filter = args.get("lang")
            if isinstance(raw_type, list):
                req_types = [("tafsir" if t == "tafseer" else t) for t in raw_type]
            else:
                t_str = str(raw_type or "all").lower().strip()
                if t_str == "all":
                    req_types = ["quran", "translation", "tafsir"]
                elif t_str in ("tafseer", "tafsir"):
                    req_types = ["tafsir"]
                else:
                    req_types = [t_str]

            all_editions = [
                {
                    "edition_id": "quran-simple",
                    "code": "simple",
                    "edition_type": "quran",
                    "lang": "ar",
                    "name": "Tanzil Quran Text (Simple, Version 1.1)",
                    "author": "Tanzil Project",
                    "source_url": "https://tanzil.net",
                    "license": "CC BY 3.0 (Verbatim copy; changing text is not allowed)",
                    "description": "Canonical vocalized Arabic Quran text from the Tanzil Project (Simple v1.1)."
                },
                {
                    "edition_id": "ur.jawadi",
                    "code": "jawadi",
                    "edition_type": "translation",
                    "lang": "ur",
                    "name": "ترجمہ علامہ سید ذیشان حیدر جوادی",
                    "author": "Allama Syed Zeeshan Haider Jawadi",
                    "source_url": "https://tanzil.net/trans/ur.jawadi",
                    "license": "CC BY-NC-ND 3.0 (Verbatim text with attribution to Tanzil.net)",
                    "description": "Verbatim Urdu translation by Allama Syed Zeeshan Haider Jawadi."
                },
                {
                    "edition_id": "balagh",
                    "code": "balagh",
                    "edition_type": "translation",
                    "lang": "ur",
                    "name": "بلاغ القرآن (Balagh ul Quran)",
                    "author": "Allama Sheikh Mohsin Ali Najafi",
                    "source_url": "https://www.balaghulquran.com",
                    "description": "Urdu Quran translation with explanatory footnotes (hawashi) by Allama Sheikh Mohsin Ali Najafi."
                },
                {
                    "edition_id": "namoona",
                    "code": "namoona",
                    "edition_type": "translation",
                    "lang": "ur",
                    "name": "ترجمہ تفسیر نمونہ (Tafseer e Namoona Translation)",
                    "author": "Maulana Syed Safdar Hussain Najafi",
                    "source_url": "https://www.tafseerenamoona.net",
                    "description": "Urdu translation accompanying Tafseer e Namoona by Maulana Syed Safdar Hussain Najafi."
                },
                {
                    "edition_id": "en.yusufali-shakir",
                    "code": "en",
                    "edition_type": "translation",
                    "lang": "en",
                    "name": "English Translation (Yusuf Ali & M. H. Shakir)",
                    "author": "Abdullah Yusuf Ali / M. H. Shakir",
                    "source_url": "https://www.tafseerenamoona.net",
                    "description": "English Quran translation by Abdullah Yusuf Ali and M. H. Shakir."
                },
                {
                    "edition_id": "kauthar",
                    "code": "kauthar",
                    "edition_type": "tafsir",
                    "lang": "ur",
                    "name": "الکوثر فی تفسیر القرآن (Tafseer al-Kauthar & Hawashi)",
                    "author": "Allama Sheikh Mohsin Ali Najafi",
                    "source_url": "https://www.balaghulquran.com",
                    "description": "Comprehensive Shia Quranic exegesis and hawashi by Allama Sheikh Mohsin Ali Najafi."
                },
                {
                    "edition_id": "namoona-tafseer",
                    "code": "namoona",
                    "edition_type": "tafsir",
                    "lang": "ur/en",
                    "name": "تفسیر نمونہ (Tafseer e Namoona)",
                    "author": "Grand Ayatollah Naser Makarem Shirazi (trans. Maulana Syed Safdar Hussain Najafi)",
                    "source_url": "https://www.tafseerenamoona.net",
                    "description": "Contemporary thematic and analytical Shia Tafseer in Urdu and English."
                },
            ]

            filtered = []
            for ed in all_editions:
                et = ed["edition_type"]
                if et in req_types or (et == "tafsir" and "tafseer" in req_types):
                    if lang_filter and et == "translation":
                        if lang_filter.lower() not in ed["lang"].lower():
                            continue
                    out_ed = dict(ed)
                    if raw_type == "tafseer" and out_ed["edition_type"] == "tafsir":
                        out_ed["edition_type"] = "tafseer"
                    filtered.append(out_ed)

            return {
                "count": len(filtered),
                "edition_type": raw_type if isinstance(raw_type, str) else req_types[0],
                "edition_types": req_types,
                "lang_filter": lang_filter,
                "editions": filtered,
            }

        # ------------------------------------------------------------------
        # 3. fetch_quran
        # ------------------------------------------------------------------
        elif name == "fetch_quran":
            jawadi_loader.ensure_loaded(conn, db_path=DB_PATH)
            refs = parse_ayah_references(
                ayahs=args.get("ayahs"),
                surah=args.get("surah"),
                ayah=args.get("ayah"),
            )
            verses = []
            ar_results = []
            ayah_keys = []
            for s_num, a_num in refs:
                cur.execute(
                    "SELECT surah, ayah, verse_key, text FROM quran_text_tanzil WHERE surah = ? AND ayah = ?",
                    (s_num, a_num),
                )
                r = cur.fetchone()
                if r:
                    vk = r["verse_key"]
                    ayah_keys.append(vk)
                    verses.append(
                        {
                            "verse_key": vk,
                            "surah": r["surah"],
                            "ayah": r["ayah"],
                            "arabic": r["text"],
                        }
                    )
                    ar_results.append({"ayah": vk, "text": r["text"]})

            first_surah = refs[0][0] if refs else int(args.get("surah", 1))
            return {
                "surah": first_surah,
                "ayahs": ayah_keys,
                "edition_id": "quran-simple",
                "count": len(verses),
                "verses": verses,
                "results": {"quran-simple": ar_results},
                "pagination": {
                    "total_items": len(verses),
                    "has_more": False,
                    "continuation": None,
                },
                "warnings": None,
                "grounding_rules": _grounding_for_call(args),
                "sources": {"arabic": jawadi_loader.ARABIC_ATTRIBUTION},
            }

        # ------------------------------------------------------------------
        # 4. list_surahs
        # ------------------------------------------------------------------
        elif name == "list_surahs":
            cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='surahs'")
            rows = []
            if cur.fetchone():
                cur.execute("SELECT id, name_ar, name_en, ayah_count FROM surahs ORDER BY id ASC")
                rows = cur.fetchall()
            if len(rows) == 114:
                return {
                    "count": len(rows),
                    "surahs": [
                        {
                            "surah": r["id"],
                            "name_ar": r["name_ar"],
                            "name_en": r["name_en"],
                            "ayah_count": r["ayah_count"],
                        }
                        for r in rows
                    ],
                }
            return {
                "count": 114,
                "surahs": [
                    {"surah": s, "name_ar": "", "name_en": f"Surah {s}", "ayah_count": c}
                    for s, c in jawadi_loader.AYAH_COUNTS.items()
                ],
            }

        # ------------------------------------------------------------------
        # 5. fetch_translation
        # ------------------------------------------------------------------
        elif name == "fetch_translation":
            jawadi_loader.ensure_loaded(conn, db_path=DB_PATH)
            raw_ed = args.get("editions") or args.get("edition") or "all"
            if isinstance(raw_ed, list):
                ed_list = [str(x).lower().strip() for x in raw_ed]
            else:
                ed_list = [str(raw_ed).lower().strip()]

            # Map aliases
            norm_eds = set()
            for e in ed_list:
                if e in ("all", "auto", "ur"):
                    norm_eds.update(["jawadi", "balagh", "namoona", "en"])
                elif e in ("jawadi", "ur.jawadi", "ur-jawadi"):
                    norm_eds.add("jawadi")
                elif e in ("balagh", "ur-balagh"):
                    norm_eds.add("balagh")
                elif e in ("namoona", "ur-namoona"):
                    norm_eds.add("namoona")
                elif e.startswith("en"):
                    norm_eds.add("en")
                else:
                    raise ValueError(
                        f"Invalid edition '{e}': must be one of 'all', 'balagh', 'namoona', 'jawadi', 'en', 'ur'."
                    )

            refs = parse_ayah_references(
                ayahs=args.get("ayahs"),
                surah=args.get("surah"),
                ayah=args.get("ayah"),
            )
            touched_surahs = sorted({s for s, _ in refs})
            if norm_eds != {"jawadi"}:
                for s_num in touched_surahs:
                    _ensure_surah_cached(conn, s_num)

            results = []
            by_edition = {k: [] for k in sorted(norm_eds)}
            ayah_keys = []
            for s_num, a_num in refs:
                b = _fetch_shia_verse_bundle(conn, s_num, a_num)
                vk = b["verse_key"]
                ayah_keys.append(vk)
                entry = {
                    "verse_key": vk,
                    "surah": s_num,
                    "ayah": a_num,
                    "arabic": b["arabic"],
                    "english": b["english"],
                }
                if "balagh" in norm_eds:
                    entry["translation_balagh"] = b["translation_balagh"]
                    if b["footnotes_balagh"]:
                        entry["footnotes_balagh"] = b["footnotes_balagh"]
                    by_edition["balagh"].append({"ayah": vk, "arabic": b["arabic"], "text": b["translation_balagh"]})
                if "namoona" in norm_eds:
                    entry["translation_namoona"] = b["translation_namoona"]
                    by_edition["namoona"].append({"ayah": vk, "arabic": b["arabic"], "text": b["translation_namoona"]})
                if "jawadi" in norm_eds:
                    entry["translation_jawadi"] = b["translation_jawadi"]
                    by_edition["jawadi"].append({"ayah": vk, "arabic": b["arabic"], "text": b["translation_jawadi"]})
                if "en" in norm_eds:
                    by_edition["en"].append({"ayah": vk, "arabic": b["arabic"], "text": b["english"]})
                results.append(entry)

            first_surah = refs[0][0] if refs else int(args.get("surah", 1))
            sources = {"arabic": jawadi_loader.ARABIC_ATTRIBUTION}
            if "jawadi" in norm_eds:
                sources["jawadi"] = jawadi_loader.ATTRIBUTION
            return {
                "surah": first_surah,
                "ayahs": ayah_keys,
                "count": len(results),
                "verses": results,
                "results": by_edition,
                "pagination": {
                    "total_items": len(results),
                    "has_more": False,
                    "continuation": None,
                },
                "warnings": None,
                "grounding_rules": _grounding_for_call(args),
                "sources": sources,
            }

        # ------------------------------------------------------------------
        # 6. fetch_tafsir / fetch_tafseer
        # ------------------------------------------------------------------
        elif name in ("fetch_tafseer", "fetch_tafsir"):
            jawadi_loader.ensure_loaded(conn, db_path=DB_PATH)
            raw_src = args.get("editions") or args.get("source") or "all"
            if isinstance(raw_src, list):
                src_list = [str(x).lower().strip() for x in raw_src]
            else:
                src_list = [str(raw_src).lower().strip()]

            want_kauthar = any(s in ("all", "kauthar", "ur-kauthar", "balagh", "ur", "ar") for s in src_list)
            want_namoona = any(s in ("all", "namoona", "namoona-tafseer", "ur-namoona", "en-namoona", "en", "ur") for s in src_list)
            if not want_kauthar and not want_namoona:
                want_kauthar = True
                want_namoona = True

            if args.get("ayahs") is not None:
                refs = parse_ayah_references(ayahs=args.get("ayahs"), surah=args.get("surah"))
            else:
                s_in = int(args.get("surah", 1))
                a_in = int(args.get("ayah", 1))
                refs = parse_ayah_references(surah=s_in, ayah=a_in)

            for s_num in sorted({s for s, _ in refs}):
                _ensure_surah_cached(conn, s_num)

            verse_tafseers = []
            results_by_ed = {}
            if want_kauthar:
                results_by_ed["kauthar"] = []
            if want_namoona:
                results_by_ed["namoona"] = []

            ayah_keys = []
            for s_num, a_num in refs:
                b = _fetch_shia_verse_bundle(conn, s_num, a_num)
                vk = b["verse_key"]
                ayah_keys.append(vk)
                item = {
                    "verse_key": vk,
                    "arabic": b["arabic"],
                    "translation_balagh": b["translation_balagh"],
                    "translation_namoona": b["translation_namoona"],
                    "translation_jawadi": b["translation_jawadi"],
                    "english": b["english"],
                }
                if want_kauthar:
                    k_text = b["tafseer_kauthar"] or _ensure_kauthar_tafseer(conn, s_num, a_num)
                    k_obj = {
                        "author": "Allama Sheikh Mohsin Ali Najafi",
                        "source_url": f"https://www.balaghulquran.com/tafseer.php?sno={s_num}&ano={s_num:03d}{a_num:03d}",
                        "footnotes": b["footnotes_balagh"] or "",
                        "content": k_text or b["footnotes_balagh"] or "No detailed commentary entry.",
                    }
                    item["tafseer_al_kauthar"] = k_obj
                    results_by_ed["kauthar"].append(
                        {
                            "ayahs": [vk],
                            "range": vk,
                            "arabic": b["arabic"],
                            "author": k_obj["author"],
                            "source_url": k_obj["source_url"],
                            "footnotes": k_obj["footnotes"],
                            "text": k_obj["content"],
                        }
                    )
                if want_namoona:
                    n_obj = {
                        "author": "Ayatollah Naser Makarem Shirazi / Maulana Syed Safdar Hussain Najafi",
                        "source_url": f"https://www.tafseerenamoona.net/surahs/{s_num}#ayah-{a_num}",
                        "translation": b["translation_namoona"],
                        "content": b["tafseer_namoona"] or b["translation_namoona"] or "Available in online edition.",
                    }
                    item["tafseer_e_namoona"] = n_obj
                    results_by_ed["namoona"].append(
                        {
                            "ayahs": [vk],
                            "range": vk,
                            "arabic": b["arabic"],
                            "author": n_obj["author"],
                            "source_url": n_obj["source_url"],
                            "text": n_obj["content"],
                        }
                    )
                verse_tafseers.append(item)

            if not verse_tafseers:
                return {"error": "Requested verse(s) not found in database."}

            primary = dict(verse_tafseers[0])
            primary["ayahs"] = ayah_keys
            primary["results"] = results_by_ed
            if len(verse_tafseers) > 1:
                primary["verses"] = verse_tafseers
            primary["pagination"] = {
                "total_items": len(verse_tafseers),
                "has_more": False,
                "continuation": None,
            }
            primary["warnings"] = None
            primary["grounding_rules"] = _grounding_for_call(args)
            primary["sources"] = {
                "arabic": jawadi_loader.ARABIC_ATTRIBUTION,
                "jawadi": jawadi_loader.ATTRIBUTION,
            }
            return primary

        # ------------------------------------------------------------------
        # 7. search_verses / search_quran / search_translation
        # ------------------------------------------------------------------
        elif name in ("search_verses", "search_quran", "search_translation"):
            query = str(args.get("query", "")).strip()
            surah_filter = args.get("surah")
            if surah_filter is not None:
                surah_filter = int(surah_filter)
                jawadi_loader.validate_surah_ayah(surah_filter)

            raw_ed = args.get("edition") or args.get("editions") or args.get("translations") or "all"
            if isinstance(raw_ed, list):
                ed_str = "all" if len(raw_ed) != 1 else str(raw_ed[0]).lower().strip()
            else:
                ed_str = str(raw_ed).lower().strip()
            if ed_str in ("auto", "ur", "en", "none"):
                edition = "all"
            elif ed_str in ("all", "balagh", "namoona", "jawadi"):
                edition = ed_str
            else:
                if name == "search_verses":
                    raise ValueError(f"Invalid edition '{ed_str}': must be one of 'all', 'balagh', 'namoona', 'jawadi'.")
                edition = "all"

            if not query:
                return {
                    "query": query,
                    "match_count": 0,
                    "matches": [],
                    "total_found": 0,
                    "results": [],
                }

            jawadi_loader.ensure_loaded(conn, db_path=DB_PATH)
            pattern = f"%{query}%"
            norm_q = normalize_arabic(query)
            norm_pattern = f"%{norm_q}%" if norm_q else pattern
            matches = []

            cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='verses'")
            has_verses_table = bool(cur.fetchone())

            surah_sql = " AND j.surah = ? " if (surah_filter and edition == "jawadi") else ""
            surah_sql_v = " AND v.surah = ? " if surah_filter else ""

            if edition == "jawadi":
                params = [pattern, pattern, pattern, norm_pattern, norm_pattern, pattern]
                if surah_filter:
                    params.append(surah_filter)
                if has_verses_table:
                    cur.execute(
                        f"""
                        SELECT j.verse_key, j.surah, j.ayah, j.text AS trans_jawadi,
                               COALESCE(NULLIF(q.text, ''), NULLIF(v.arabic, ''), '') AS arabic,
                               COALESCE(v.trans_en, '') AS trans_en,
                               COALESCE(v.trans_balagh, '') AS trans_balagh,
                               COALESCE(v.trans_namoona, '') AS trans_namoona
                        FROM translation_jawadi j
                        LEFT JOIN quran_text_tanzil q ON q.verse_key = j.verse_key
                        LEFT JOIN verses v ON v.verse_key = j.verse_key
                        WHERE (j.text LIKE ? OR q.text LIKE ? OR v.arabic LIKE ?
                           OR NORM_AR(q.text) LIKE ? OR NORM_AR(v.arabic) LIKE ?
                           OR v.trans_en LIKE ?) {surah_sql}
                        ORDER BY j.surah ASC, j.ayah ASC
                        LIMIT 20
                        """,
                        tuple(params),
                    )
                else:
                    params_no_v = [pattern, pattern, norm_pattern]
                    if surah_filter:
                        params_no_v.append(surah_filter)
                    cur.execute(
                        f"""
                        SELECT j.verse_key, j.surah, j.ayah, j.text AS trans_jawadi,
                               COALESCE(q.text, '') AS arabic, '' AS trans_en,
                               '' AS trans_balagh, '' AS trans_namoona
                        FROM translation_jawadi j
                        LEFT JOIN quran_text_tanzil q ON q.verse_key = j.verse_key
                        WHERE (j.text LIKE ? OR q.text LIKE ? OR NORM_AR(q.text) LIKE ?) {surah_sql}
                        ORDER BY j.surah ASC, j.ayah ASC
                        LIMIT 20
                        """,
                        tuple(params_no_v),
                    )
                for r in cur.fetchall():
                    matches.append(
                        {
                            "verse_key": r["verse_key"],
                            "surah": r["surah"],
                            "ayah": r["ayah"],
                            "arabic": r["arabic"] or "",
                            "jawadi": r["trans_jawadi"],
                            "english": r["trans_en"] or "",
                        }
                    )
            elif has_verses_table:
                params = [
                    pattern, pattern,
                    norm_pattern, norm_pattern,
                    pattern, pattern,
                    pattern, pattern,
                    pattern, pattern, pattern,
                ]
                if surah_filter:
                    params.append(surah_filter)
                cur.execute(
                    f"""
                    SELECT v.surah, v.ayah, v.verse_key,
                           COALESCE(NULLIF(q.text, ''), NULLIF(v.arabic, ''), '') AS arabic,
                           v.trans_balagh, v.trans_namoona, v.trans_en,
                           j.text AS trans_jawadi
                    FROM verses v
                    LEFT JOIN quran_text_tanzil q ON q.verse_key = v.verse_key
                    LEFT JOIN translation_jawadi j ON j.verse_key = v.verse_key
                    WHERE (v.arabic LIKE ? OR q.text LIKE ?
                       OR NORM_AR(q.text) LIKE ? OR NORM_AR(v.arabic) LIKE ?
                       OR v.trans_balagh LIKE ? OR v.trans_namoona LIKE ?
                       OR v.trans_en LIKE ? OR j.text LIKE ?
                       OR v.footnotes_balagh LIKE ? OR v.tafseer_namoona LIKE ? OR v.tafseer_kauthar LIKE ?)
                       {surah_sql_v}
                    ORDER BY v.surah ASC, v.ayah ASC
                    LIMIT 20
                    """,
                    tuple(params),
                )
                for r in cur.fetchall():
                    item = {
                        "verse_key": r["verse_key"],
                        "surah": r["surah"],
                        "ayah": r["ayah"],
                        "arabic": r["arabic"],
                        "balagh": r["trans_balagh"],
                        "namoona": r["trans_namoona"],
                        "english": r["trans_en"],
                    }
                    if edition in ("all", "jawadi") and r["trans_jawadi"]:
                        item["jawadi"] = r["trans_jawadi"]
                    matches.append(item)

            # Semantic fallback via upstream if lexical search yielded < 3 matches on multi-word/conceptual query
            if len(matches) < 3 and name in ("search_quran", "search_translation"):
                up_tool = "search_quran" if name == "search_quran" else "search_translation"
                up_args = {"query": query}
                if surah_filter:
                    up_args["surah"] = surah_filter
                up_parsed, _ = _call_upstream_quran_ai(up_tool, up_args)
                seen_vks = {m["verse_key"] for m in matches}
                if isinstance(up_parsed, dict):
                    for ur in up_parsed.get("results") or []:
                        vk = ur.get("ayah_key") or ur.get("verse_key")
                        if vk and ":" in vk and vk not in seen_vks:
                            try:
                                s_n, a_n = [int(x) for x in vk.split(":", 1)]
                                b = _fetch_shia_verse_bundle(conn, s_n, a_n)
                                seen_vks.add(vk)
                                matches.append(
                                    {
                                        "verse_key": vk,
                                        "surah": s_n,
                                        "ayah": a_n,
                                        "arabic": b["arabic"],
                                        "jawadi": b["translation_jawadi"],
                                        "balagh": b["translation_balagh"],
                                        "namoona": b["translation_namoona"],
                                        "english": b["english"],
                                        "relevance_score": ur.get("relevance_score", 0.8),
                                    }
                                )
                                if len(matches) >= 20:
                                    break
                            except Exception:
                                pass

            # Build mcp.quran.ai style `results` array alongside `matches`
            structured_results = []
            for idx, m in enumerate(matches, start=1):
                vk = m["verse_key"]
                s_n = m.get("surah") or int(vk.split(":")[0])
                a_n = m.get("ayah") or int(vk.split(":")[1])
                if name == "search_translation":
                    structured_results.append(
                        {
                            "rank": idx,
                            "ayah_key": vk,
                            "verse_key": vk,
                            "surah": s_n,
                            "ayah": a_n,
                            "arabic": m.get("arabic", ""),
                            "text": m.get("jawadi") or m.get("balagh") or m.get("namoona") or m.get("english", ""),
                            "translations": {
                                "jawadi": m.get("jawadi", ""),
                                "balagh": m.get("balagh", ""),
                                "namoona": m.get("namoona", ""),
                                "english": m.get("english", ""),
                            },
                            "edition": {
                                "edition_id": "ur.jawadi",
                                "name": "Allama Syed Zeeshan Haider Jawadi & Shia Translations",
                                "author": "Allama Jawadi / Sheikh Mohsin Ali Najafi / Maulana Safdar Hussain Najafi",
                                "lang": "ur/en",
                            },
                            "citation_url": f"https://www.tafseerenamoona.net/surahs/{s_n}#ayah-{a_n}",
                            "relevance_score": m.get("relevance_score", round(max(0.5, 1.0 - (idx - 1) * 0.02), 4)),
                        }
                    )
                else:
                    structured_results.append(
                        {
                            "rank": idx,
                            "ayah_key": vk,
                            "verse_key": vk,
                            "surah": s_n,
                            "ayah": a_n,
                            "text": m.get("arabic", ""),
                            "arabic": m.get("arabic", ""),
                            "translations": [
                                {
                                    "edition": {"id": "ur.jawadi", "name": "Allama Jawadi", "lang": "ur"},
                                    "text": m.get("jawadi", ""),
                                },
                                {
                                    "edition": {"id": "balagh", "name": "Balagh ul Quran", "lang": "ur"},
                                    "text": m.get("balagh", ""),
                                },
                                {
                                    "edition": {"id": "namoona", "name": "Tafseer e Namoona", "lang": "ur"},
                                    "text": m.get("namoona", ""),
                                },
                                {
                                    "edition": {"id": "en.yusufali-shakir", "name": "English Translation", "lang": "en"},
                                    "text": m.get("english", ""),
                                },
                            ],
                            "citation_url": f"https://www.balaghulquran.com/tafseer.php?sno={s_n}&ano={s_n:03d}{a_n:03d}",
                            "relevance_score": m.get("relevance_score", round(max(0.5, 1.0 - (idx - 1) * 0.02), 4)),
                        }
                    )

            sources = {"arabic": jawadi_loader.ARABIC_ATTRIBUTION}
            if edition in ("all", "jawadi"):
                sources["jawadi"] = jawadi_loader.ATTRIBUTION

            return {
                "query": query,
                "match_count": len(matches),
                "matches": matches,
                "total_found": len(structured_results),
                "results": structured_results,
                "pagination": {
                    "page": 1,
                    "page_size": 20,
                    "returned_items": len(structured_results),
                    "total_items": len(structured_results),
                    "total_pages": 1,
                    "has_more": False,
                    "continuation": None,
                },
                "warnings": None,
                "grounding_rules": _grounding_for_call(args),
                "sources": sources,
            }

        # ------------------------------------------------------------------
        # 8. search_tafsir
        # ------------------------------------------------------------------
        elif name == "search_tafsir":
            query = str(args.get("query", "")).strip()
            if not query:
                return {"query": query, "total_found": 0, "results": []}

            jawadi_loader.ensure_loaded(conn, db_path=DB_PATH)
            include_ayah_text = args.get("include_ayah_text", True)
            surah_filter = int(args["surah"]) if args.get("surah") is not None else None
            scope_refs = None
            if args.get("ayahs") is not None:
                scope_refs = set(parse_ayah_references(ayahs=args.get("ayahs"), surah=surah_filter))

            raw_ed = args.get("editions") or "all"
            ed_list = [str(x).lower() for x in (raw_ed if isinstance(raw_ed, list) else [raw_ed])]
            want_kauthar = any(e in ("all", "kauthar", "balagh", "ur") for e in ed_list)
            want_namoona = any(e in ("all", "namoona", "namoona-tafseer", "ur", "en") for e in ed_list)
            if not want_kauthar and not want_namoona:
                want_kauthar = want_namoona = True

            pattern = f"%{query}%"
            sql_where = "(v.tafseer_namoona LIKE ? OR v.tafseer_kauthar LIKE ? OR v.footnotes_balagh LIKE ? OR v.trans_en LIKE ?)"
            params = [pattern, pattern, pattern, pattern]
            if surah_filter:
                sql_where += " AND v.surah = ?"
                params.append(surah_filter)

            cur.execute(
                f"""
                SELECT v.surah, v.ayah, v.verse_key,
                       COALESCE(NULLIF(q.text, ''), NULLIF(v.arabic, ''), '') AS arabic,
                       v.tafseer_kauthar, v.footnotes_balagh, v.tafseer_namoona
                FROM verses v
                LEFT JOIN quran_text_tanzil q ON q.verse_key = v.verse_key
                WHERE {sql_where}
                ORDER BY v.surah ASC, v.ayah ASC
                LIMIT 30
                """,
                tuple(params),
            )
            rows = cur.fetchall()
            results = []
            seen_vks = set()

            for r in rows:
                s_n, a_n = r["surah"], r["ayah"]
                if scope_refs and (s_n, a_n) not in scope_refs:
                    continue
                vk = r["verse_key"]
                seen_vks.add(vk)
                k_text = r["tafseer_kauthar"] or r["footnotes_balagh"] or ""
                n_text = _resolve_namoona_tafseer(conn, s_n, a_n, r["tafseer_namoona"] or "")

                if want_namoona and n_text and (query.lower() in n_text.lower() or not k_text):
                    ed_meta = {
                        "edition_id": "namoona-tafseer",
                        "edition_name": "Tafseer e Namoona",
                        "author": "Grand Ayatollah Naser Makarem Shirazi / Maulana Syed Safdar Hussain Najafi",
                        "lang": "ur/en",
                    }
                    t_body = n_text
                    c_url = f"https://www.tafseerenamoona.net/surahs/{s_n}#ayah-{a_n}"
                else:
                    ed_meta = {
                        "edition_id": "kauthar",
                        "edition_name": "Tafseer al-Kauthar & Balagh ul Quran Hawashi",
                        "author": "Allama Sheikh Mohsin Ali Najafi",
                        "lang": "ur",
                    }
                    t_body = k_text or n_text
                    c_url = f"https://www.balaghulquran.com/tafseer.php?sno={s_n}&ano={s_n:03d}{a_n:03d}"

                entry = {
                    "rank": len(results) + 1,
                    "ayah_key": vk,
                    "verse_key": vk,
                    "surah": s_n,
                    "ayah": a_n,
                    "tafsir_text": t_body[:2500],
                    "citation": ed_meta,
                    "citation_url": c_url,
                    "relevance_score": round(max(0.5, 1.0 - len(results) * 0.02), 4),
                }
                if include_ayah_text:
                    entry["ayah_text"] = r["arabic"]
                    entry["arabic"] = r["arabic"]
                results.append(entry)
                if len(results) >= 15:
                    break

            # Supplement with upstream semantic tafsir discovery hydrated from Shia Tafseers in quran_shia.db
            if len(results) < 5:
                up_args = {"query": query}
                if surah_filter:
                    up_args["surah"] = surah_filter
                up_parsed, _ = _call_upstream_quran_ai("search_tafsir", up_args)
                if isinstance(up_parsed, dict):
                    for ur in up_parsed.get("results") or []:
                        s_n = ur.get("surah")
                        a_n = ur.get("ayah")
                        if not s_n or not a_n:
                            continue
                        if scope_refs and (int(s_n), int(a_n)) not in scope_refs:
                            continue
                        vk = f"{int(s_n)}:{int(a_n)}"
                        if vk in seen_vks:
                            continue
                        seen_vks.add(vk)
                        b = _fetch_shia_verse_bundle(conn, int(s_n), int(a_n))
                        t_body = b["tafseer_namoona"] or b["tafseer_kauthar"] or b["footnotes_balagh"]
                        if not t_body:
                            continue
                        entry = {
                            "rank": len(results) + 1,
                            "ayah_key": vk,
                            "verse_key": vk,
                            "surah": int(s_n),
                            "ayah": int(a_n),
                            "tafsir_text": t_body[:2500],
                            "citation": {
                                "edition_id": "namoona-tafseer" if b["tafseer_namoona"] else "kauthar",
                                "edition_name": "Tafseer e Namoona" if b["tafseer_namoona"] else "Tafseer al-Kauthar",
                                "author": (
                                    "Grand Ayatollah Naser Makarem Shirazi"
                                    if b["tafseer_namoona"]
                                    else "Allama Sheikh Mohsin Ali Najafi"
                                ),
                                "lang": "ur/en",
                            },
                            "citation_url": f"https://www.tafseerenamoona.net/surahs/{int(s_n)}#ayah-{int(a_n)}",
                            "relevance_score": ur.get("relevance_score", 0.78),
                        }
                        if include_ayah_text:
                            entry["ayah_text"] = b["arabic"]
                            entry["arabic"] = b["arabic"]
                        results.append(entry)
                        if len(results) >= 15:
                            break

            return {
                "query": query,
                "total_found": len(results),
                "results": results,
                "pagination": {
                    "page": 1,
                    "page_size": 15,
                    "returned_items": len(results),
                    "total_items": len(results),
                    "total_pages": 1,
                    "has_more": False,
                    "continuation": None,
                },
                "warnings": None,
                "grounding_rules": _grounding_for_call(args),
                "sources": {"arabic": jawadi_loader.ARABIC_ATTRIBUTION},
            }

        # ------------------------------------------------------------------
        # 9. fetch_word_morphology
        # ------------------------------------------------------------------
        elif name == "fetch_word_morphology":
            jawadi_loader.ensure_loaded(conn, db_path=DB_PATH)
            up_parsed, _ = _call_upstream_quran_ai("fetch_word_morphology", args)
            if isinstance(up_parsed, dict) and up_parsed.get("words"):
                ak = up_parsed.get("ayah_key") or args.get("ayah_key")
                if ak and ":" in str(ak):
                    s_n, a_n = [int(x) for x in str(ak).split(":", 1)]
                    b = _fetch_shia_verse_bundle(conn, s_n, a_n)
                    up_parsed["arabic"] = b["arabic"]
                    up_parsed["shia_translations"] = {
                        "translation_jawadi": b["translation_jawadi"],
                        "translation_balagh": b["translation_balagh"],
                        "translation_namoona": b["translation_namoona"],
                        "english": b["english"],
                    }
                up_parsed["grounding_rules"] = GROUNDING_NOTICE
                return up_parsed

            # Deterministic local fallback using quran_text_tanzil
            ak = args.get("ayah_key")
            word_q = args.get("word") or args.get("word_text")
            pos_q = int(args["word_position"]) if args.get("word_position") is not None else None
            if not ak and word_q:
                norm_w = normalize_arabic(word_q)
                cur.execute(
                    "SELECT verse_key, surah, ayah, text FROM quran_text_tanzil WHERE text LIKE ? OR NORM_AR(text) LIKE ? ORDER BY surah ASC, ayah ASC LIMIT 1",
                    (f"%{word_q}%", f"%{norm_w}%"),
                )
                r = cur.fetchone()
                ak = r["verse_key"] if r else "1:1"
            ak = ak or "1:1"
            s_n, a_n = [int(x) for x in str(ak).split(":", 1)]
            b = _fetch_shia_verse_bundle(conn, s_n, a_n)
            words_raw = b["arabic"].split()
            words_out = []
            for idx, w_tok in enumerate(words_raw, start=1):
                if pos_q and idx != pos_q:
                    continue
                if word_q and normalize_arabic(word_q) not in normalize_arabic(w_tok):
                    continue
                norm_tok = normalize_arabic(w_tok)
                cur.execute(
                    "SELECT COUNT(*) FROM quran_text_tanzil WHERE NORM_AR(text) LIKE ?",
                    (f"%{norm_tok}%",),
                )
                v_cnt = cur.fetchone()[0]
                words_out.append(
                    {
                        "word_id": idx,
                        "position": idx,
                        "text_uthmani": w_tok,
                        "text_simple": norm_tok,
                        "root": norm_tok[:3] if len(norm_tok) >= 3 else norm_tok,
                        "lemma": w_tok,
                        "stem": norm_tok,
                        "stem_frequency": {"verse_count": v_cnt},
                    }
                )
            return {
                "ayah_key": ak,
                "arabic": b["arabic"],
                "input_mode": "ayah_key" if args.get("ayah_key") else "word_text",
                "words": words_out,
                "shia_translations": {
                    "translation_jawadi": b["translation_jawadi"],
                    "translation_balagh": b["translation_balagh"],
                    "translation_namoona": b["translation_namoona"],
                    "english": b["english"],
                },
                "grounding_rules": GROUNDING_NOTICE,
            }

        # ------------------------------------------------------------------
        # 10. fetch_word_paradigm
        # ------------------------------------------------------------------
        elif name == "fetch_word_paradigm":
            jawadi_loader.ensure_loaded(conn, db_path=DB_PATH)
            up_parsed, _ = _call_upstream_quran_ai("fetch_word_paradigm", args)
            if isinstance(up_parsed, dict) and ("paradigm" in up_parsed or "root" in up_parsed):
                ak = (up_parsed.get("word") or {}).get("ayah_key") or args.get("ayah_key")
                if ak and ":" in str(ak):
                    s_n, a_n = [int(x) for x in str(ak).split(":", 1)]
                    b = _fetch_shia_verse_bundle(conn, s_n, a_n)
                    up_parsed["arabic"] = b["arabic"]
                    up_parsed["shia_translations"] = {
                        "translation_jawadi": b["translation_jawadi"],
                        "translation_balagh": b["translation_balagh"],
                        "translation_namoona": b["translation_namoona"],
                        "english": b["english"],
                    }
                up_parsed["grounding_rules"] = GROUNDING_NOTICE
                return up_parsed

            # Local fallback
            target = args.get("lemma") or args.get("root") or args.get("word_text") or ""
            ak = args.get("ayah_key")
            if ak and ":" in str(ak) and not target:
                s_n, a_n = [int(x) for x in str(ak).split(":", 1)]
                b = _fetch_shia_verse_bundle(conn, s_n, a_n)
                pos = int(args.get("word_position") or 1)
                toks = b["arabic"].split()
                target = toks[min(max(1, pos), len(toks)) - 1] if toks else ""
            norm_t = normalize_arabic(target).replace(" ", "")
            return {
                "root": norm_t,
                "lemma": target,
                "paradigm_available": True,
                "paradigm": {"perfect": [], "imperfect": [], "imperative": []},
                "candidate_lemmas": [{"lemma": target, "count": 1}],
                "grounding_rules": GROUNDING_NOTICE,
            }

        # ------------------------------------------------------------------
        # 11. fetch_word_concordance
        # ------------------------------------------------------------------
        elif name == "fetch_word_concordance":
            jawadi_loader.ensure_loaded(conn, db_path=DB_PATH)
            up_parsed, _ = _call_upstream_quran_ai("fetch_word_concordance", args)
            if isinstance(up_parsed, dict) and ("results" in up_parsed or "word_results" in up_parsed):
                for item in up_parsed.get("results") or []:
                    ak = item.get("ayah_key")
                    if ak and ":" in str(ak):
                        try:
                            s_n, a_n = [int(x) for x in str(ak).split(":", 1)]
                            b = _fetch_shia_verse_bundle(conn, s_n, a_n)
                            item["arabic"] = b["arabic"]
                            item["translation_jawadi"] = b["translation_jawadi"]
                            item["translation_balagh"] = b["translation_balagh"]
                            item["translation_namoona"] = b["translation_namoona"]
                            item["english"] = b["english"]
                        except Exception:
                            pass
                up_parsed["grounding_rules"] = GROUNDING_NOTICE
                return up_parsed

            # Local concordance fallback over quran_text_tanzil
            page = max(1, int(args.get("page") or 1))
            page_size = min(100, max(1, int(args.get("page_size") or 20)))
            target = (
                args.get("word")
                or args.get("word_text")
                or args.get("lemma")
                or args.get("stem")
                or args.get("root")
                or ""
            )
            ak = args.get("ayah_key")
            if ak and ":" in str(ak) and not target:
                s_n, a_n = [int(x) for x in str(ak).split(":", 1)]
                b = _fetch_shia_verse_bundle(conn, s_n, a_n)
                pos = int(args.get("word_position") or 1)
                toks = b["arabic"].split()
                target = toks[min(max(1, pos), len(toks)) - 1] if toks else ""
            norm_t = normalize_arabic(target).replace(" ", "")
            cur.execute(
                "SELECT verse_key, surah, ayah, text FROM quran_text_tanzil WHERE text LIKE ? OR NORM_AR(text) LIKE ? ORDER BY surah ASC, ayah ASC",
                (f"%{target}%", f"%{norm_t}%"),
            )
            all_rows = cur.fetchall()
            offset = (page - 1) * page_size
            page_rows = all_rows[offset : offset + page_size]
            results = []
            for r in page_rows:
                b = _fetch_shia_verse_bundle(conn, r["surah"], r["ayah"])
                results.append(
                    {
                        "ayah_key": r["verse_key"],
                        "verse_text": b["arabic"],
                        "arabic": b["arabic"],
                        "translation_jawadi": b["translation_jawadi"],
                        "translation_balagh": b["translation_balagh"],
                        "translation_namoona": b["translation_namoona"],
                        "english": b["english"],
                    }
                )
            return {
                "query": {"ayah_key": ak, "text": target},
                "match_by": args.get("match_by", "all"),
                "group_by": args.get("group_by", "verse"),
                "total_verses": len(all_rows),
                "page": page,
                "page_size": page_size,
                "has_more": (offset + page_size) < len(all_rows),
                "results": results,
                "word_results": [],
                "truncated": False,
                "grounding_rules": GROUNDING_NOTICE,
            }

        # ------------------------------------------------------------------
        # 12. interactive_study
        # ------------------------------------------------------------------
        elif name == "interactive_study":
            jawadi_loader.ensure_loaded(conn, db_path=DB_PATH)
            up_parsed, up_struct = _call_upstream_quran_ai("interactive_study", args)
            data_obj = up_struct or (up_parsed if isinstance(up_parsed, dict) else {})

            shia_verses = []
            if data_obj.get("verses"):
                for v in data_obj["verses"]:
                    vk = v.get("verse_key") or (f"{v.get('surah')}:{v.get('ayah')}" if v.get("surah") else None)
                    if vk and ":" in str(vk):
                        try:
                            s_n, a_n = [int(x) for x in str(vk).split(":", 1)]
                            b = _fetch_shia_verse_bundle(conn, s_n, a_n)
                            shia_verses.append(
                                {
                                    "verse_key": vk,
                                    "arabic": b["arabic"],
                                    "translation_jawadi": b["translation_jawadi"],
                                    "translation_balagh": b["translation_balagh"],
                                    "translation_namoona": b["translation_namoona"],
                                    "english": b["english"],
                                    "tafseer_kauthar_url": f"https://www.balaghulquran.com/tafseer.php?sno={s_n}&ano={s_n:03d}{a_n:03d}",
                                    "tafseer_namoona_url": f"https://www.tafseerenamoona.net/surahs/{s_n}#ayah-{a_n}",
                                }
                            )
                        except Exception:
                            pass

            if not shia_verses:
                s_n = int(args.get("surah") or 1)
                a_n = int(args.get("ayah") or 1)
                if args.get("juz"):
                    j_idx = min(30, max(1, int(args["juz"]))) - 1
                    s_n, a_n = JUZ_STARTS[j_idx]
                end_a = min(jawadi_loader.AYAH_COUNTS[s_n], a_n + 6)
                for cur_a in range(a_n, end_a + 1):
                    b = _fetch_shia_verse_bundle(conn, s_n, cur_a)
                    shia_verses.append(
                        {
                            "verse_key": b["verse_key"],
                            "arabic": b["arabic"],
                            "translation_jawadi": b["translation_jawadi"],
                            "translation_balagh": b["translation_balagh"],
                            "translation_namoona": b["translation_namoona"],
                            "english": b["english"],
                            "tafseer_kauthar_url": f"https://www.balaghulquran.com/tafseer.php?sno={s_n}&ano={s_n:03d}{cur_a:03d}",
                            "tafseer_namoona_url": f"https://www.tafseerenamoona.net/surahs/{s_n}#ayah-{cur_a}",
                        }
                    )

            out = dict(data_obj) if data_obj else {
                "page_number": int(args.get("page") or 1),
                "mushaf_edition_id": 5,
                "total_pages": 604,
                "context_id": args.get("context_id") or uuid.uuid4().hex[:24],
                "context_recovery": "available",
                "render_mode": args.get("render_mode") or "inline",
                "render_mode_explicit": bool(args.get("render_mode")),
                "verses": shia_verses,
            }
            out["shia_study_verses"] = shia_verses
            out["grounding_rules"] = GROUNDING_NOTICE
            return out

        # ------------------------------------------------------------------
        # 13. resolve_reader_link
        # ------------------------------------------------------------------
        elif name == "resolve_reader_link":
            jawadi_loader.ensure_loaded(conn, db_path=DB_PATH)
            ayahs_str = str(args.get("ayahs", "1:1")).strip()
            phrase = args.get("phrase")
            up_parsed, _ = _call_upstream_quran_ai("resolve_reader_link", args)

            refs = parse_ayah_references(ayahs=ayahs_str)
            first_s, first_a = refs[0]
            last_s, last_a = refs[-1]
            b = _fetch_shia_verse_bundle(conn, first_s, first_a)

            if isinstance(up_parsed, dict) and up_parsed.get("app_relative_path"):
                res = dict(up_parsed)
            else:
                start_coord = None
                end_coord = None
                if phrase:
                    norm_p_words = normalize_arabic(phrase).split()
                    for s_n, a_n in refs:
                        vb = _fetch_shia_verse_bundle(conn, s_n, a_n)
                        v_words = [normalize_arabic(w) for w in vb["arabic"].split()]
                        plen = len(norm_p_words)
                        for idx in range(len(v_words) - plen + 1):
                            if v_words[idx : idx + plen] == norm_p_words:
                                start_coord = {"ayah": f"{s_n}:{a_n}", "word": idx + 1}
                                end_coord = {"ayah": f"{s_n}:{a_n}", "word": idx + plen}
                                break
                        if start_coord:
                            break
                if start_coord and end_coord:
                    rel_path = f"/passage/{start_coord['ayah']}:{start_coord['word']}-{end_coord['ayah']}:{end_coord['word']}"
                else:
                    rel_path = f"/passage/{ayahs_str}"
                res = {
                    "ayahs": ayahs_str,
                    "canonical_phrase": phrase,
                    "start": start_coord,
                    "end": end_coord,
                    "app_relative_path": rel_path,
                    "chatgpt_reader_url": None,
                    "desktop_reader_url": None,
                }

            res["arabic"] = b["arabic"]
            res["shia_tafseer_links"] = {
                "kauthar_url": f"https://www.balaghulquran.com/tafseer.php?sno={first_s}&ano={first_s:03d}{first_a:03d}",
                "namoona_url": f"https://www.tafseerenamoona.net/surahs/{first_s}#ayah-{first_a}",
                "explorer_url": f"https://quran-shia-mcp.onrender.com/#surah={first_s}&ayah={first_a}",
            }
            res["grounding_rules"] = GROUNDING_NOTICE
            return res

        # ------------------------------------------------------------------
        # 14. fetch_quran_metadata
        # ------------------------------------------------------------------
        elif name == "fetch_quran_metadata":
            jawadi_loader.ensure_loaded(conn, db_path=DB_PATH)
            up_parsed, _ = _call_upstream_quran_ai("fetch_quran_metadata", args)
            if isinstance(up_parsed, dict) and up_parsed.get("query_type"):
                # Enrich Sajdah entries with Ja'fari jurisprudence (wajib vs mustahabb)
                for sj in up_parsed.get("sajdah") or []:
                    vk = sj.get("verse_key")
                    if vk in SAJDAH_VERSES:
                        sj["jafari_ruling"] = SAJDAH_VERSES[vk]["jafari_ruling"]
                        sj["jafari_obligatory"] = SAJDAH_VERSES[vk]["obligatory"]
                if args.get("surah") and args.get("ayah"):
                    vk = f"{int(args['surah'])}:{int(args['ayah'])}"
                    if vk in SAJDAH_VERSES and not up_parsed.get("sajdah"):
                        up_parsed["sajdah"] = [{"verse_key": vk, **SAJDAH_VERSES[vk]}]
                return up_parsed

            # Local fallback for structural metadata
            s_num = int(args["surah"]) if args.get("surah") is not None else 1
            a_num = int(args["ayah"]) if args.get("ayah") is not None else None
            if args.get("juz") is not None:
                j_num = min(30, max(1, int(args["juz"])))
                s_num, a_num = JUZ_STARTS[j_num - 1]
                q_type = "juz"
            elif args.get("manzil") is not None:
                m_num = min(7, max(1, int(args["manzil"])))
                s_num, a_num = MANZIL_STARTS[m_num - 1], 1
                q_type = "manzil"
            elif args.get("page") is not None:
                q_type = "page"
            elif args.get("hizb") is not None:
                q_type = "hizb"
            elif args.get("ruku") is not None:
                q_type = "ruku"
            elif a_num is not None:
                q_type = "ayah"
            else:
                q_type = "surah"

            jawadi_loader.validate_surah_ayah(s_num, a_num)
            cur.execute("SELECT id, name_ar, name_en, ayah_count FROM surahs WHERE id = ?", (s_num,))
            srow = cur.fetchone()
            v_cnt = jawadi_loader.AYAH_COUNTS[s_num]
            check_a = a_num or 1
            b = _fetch_shia_verse_bundle(conn, s_num, check_a)
            juz_n = _compute_juz_for_verse(s_num, check_a)
            manzil_n = _compute_manzil_for_surah(s_num)

            sajdah_list = []
            for vk, sinfo in SAJDAH_VERSES.items():
                sv_s, sv_a = [int(x) for x in vk.split(":")]
                if sv_s == s_num and (a_num is None or sv_a == a_num):
                    sajdah_list.append({"verse_key": vk, **sinfo})

            return {
                "query_type": q_type,
                "surah": [
                    {
                        "number": s_num,
                        "name_arabic": srow["name_ar"] if srow else "",
                        "name_simple": srow["name_en"] if srow else f"Surah {s_num}",
                        "verses_count": v_cnt,
                        "bismillah_pre": s_num not in (1, 9),
                    }
                ],
                "ayah": {
                    "verse_key": f"{s_num}:{check_a}",
                    "number": check_a,
                    "words_count": len(b["arabic"].split()),
                },
                "juz": {"number": int(args.get("juz") or juz_n)},
                "hizb": {"number": int(args.get("hizb") or (juz_n * 2 - 1))},
                "rub_el_hizb": {"number": (juz_n - 1) * 8 + 1},
                "page": {"number": int(args.get("page") or 1)},
                "ruku": {"number": int(args.get("ruku") or 1)},
                "manzil": {"number": int(args.get("manzil") or manzil_n)},
                "sajdah": sajdah_list,
            }

        else:
            raise ValueError(f"Tool {name} not found")
    finally:
        conn.close()


def handle_single_rpc(req):
    method = req.get("method", "")
    req_id = req.get("id")

    if req_id is None or method.startswith("notifications/") or method == "initialized":
        return None

    if method == "initialize":
        params = req.get("params") or {}
        client_proto = params.get("protocolVersion")
        negotiated_proto = client_proto if client_proto in SUPPORTED_PROTOCOLS else "2025-03-26"
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "protocolVersion": negotiated_proto,
                "capabilities": {
                    "tools": {"listChanged": False},
                    "resources": {"subscribe": False, "listChanged": False},
                    "prompts": {"listChanged": False}
                },
                "serverInfo": {
                    "name": "quran-shia-mcp",
                    "version": VERSION
                },
                "instructions": GROUNDING_NOTICE
            }
        }
    elif method == "tools/list":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "tools": TOOLS
            }
        }
    elif method == "resources/list":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "resources": []
            }
        }
    elif method == "prompts/list":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "prompts": []
            }
        }
    elif method == "tools/call":
        params = req.get("params", {})
        tool_name = params.get("name")
        tool_args = params.get("arguments", {})
        try:
            output = execute_tool(tool_name, tool_args)
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "content": [
                        {
                            "type": "text",
                            "text": json.dumps(output, ensure_ascii=False, indent=2)
                        }
                    ]
                }
            }
        except Exception as e:
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {
                    "code": -32603,
                    "message": str(e)
                }
            }
    elif method == "ping":
        return {"jsonrpc": "2.0", "id": req_id, "result": {}}
    else:
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "error": {"code": -32601, "message": f"Method {method} not implemented"}
        }


def handle_rpc(body_str):
    parsed = json.loads(body_str)
    if isinstance(parsed, list):
        responses = []
        for item in parsed:
            res = handle_single_rpc(item)
            if res is not None:
                responses.append(res)
        return responses if responses else None
    return handle_single_rpc(parsed)


class MCPHandler(BaseHTTPRequestHandler):
    def _set_cors_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, HEAD, DELETE, OPTIONS")
        self.send_header(
            "Access-Control-Allow-Headers",
            "Content-Type, Authorization, Accept, Mcp-Session-Id, MCP-Protocol-Version, Last-Event-ID"
        )
        self.send_header("Access-Control-Expose-Headers", "Mcp-Session-Id, MCP-Protocol-Version")

    def do_OPTIONS(self):
        self.send_response(204)
        self._set_cors_headers()
        self.end_headers()

    def do_HEAD(self):
        self.send_response(200)
        self._set_cors_headers()
        self.send_header("Content-Type", "application/json")
        self.end_headers()

    def do_DELETE(self):
        self.send_response(200)
        self._set_cors_headers()
        self.end_headers()

    def do_GET(self):
        url_path = urllib.parse.urlparse(self.path).path
        accept = self.headers.get("Accept", "")

        if url_path in ("/sse", "/mcp") or (url_path == "/" and "text/event-stream" in accept and "text/html" not in accept):
            self.send_response(200)
            self._set_cors_headers()
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.end_headers()
            endpoint_msg = "event: endpoint\ndata: /mcp\n\n"
            self.wfile.write(endpoint_msg.encode("utf-8"))
            self.wfile.flush()
            return

        if url_path == "/documentation/data.json":
            self.send_response(200)
            self._set_cors_headers()
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            doc_data = {
                "release_version": VERSION,
                "tool_count": len(TOOLS),
                "group_count": 5,
                "tools": TOOLS,
                "quickstart_config": {
                    "mcpServers": {
                        "quran-shia": {"url": "https://quran-shia-mcp.onrender.com/mcp"}
                    }
                },
            }
            self.wfile.write(json.dumps(doc_data, ensure_ascii=False, indent=2).encode("utf-8"))
            return

        if url_path in ("/", "/documentation"):
            html_file = Path(__file__).parent / "index.html"
            if html_file.exists():
                self.send_response(200)
                self._set_cors_headers()
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(html_file.read_bytes())
                return

        if url_path == "/health":
            surah_count = 0
            verse_count = 0
            jawadi_count = 0
            try:
                conn = get_db()
                cur = conn.cursor()
                cur.execute("SELECT COUNT(*) FROM surahs")
                surah_count = cur.fetchone()[0]
                cur.execute("SELECT COUNT(*) FROM verses")
                verse_count = cur.fetchone()[0]
                cur.execute("SELECT COUNT(*) FROM translation_jawadi")
                jawadi_count = cur.fetchone()[0]
                conn.close()
            except Exception:
                pass

            self.send_response(200)
            self._set_cors_headers()
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            resp = {
                "status": "healthy",
                "service": "quran-shia-mcp",
                "version": VERSION,
                "database": {
                    "surahs": surah_count,
                    "verses": verse_count,
                    "jawadi_verses": jawadi_count
                },
                "tools": [t["name"] for t in TOOLS],
                "endpoints": {
                    "mcp_rpc": "/mcp",
                    "sse": "/sse",
                    "docs": "/documentation",
                    "docs_data": "/documentation/data.json"
                }
            }
            self.wfile.write(json.dumps(resp, indent=2).encode("utf-8"))
            return

        self.send_response(404)
        self._set_cors_headers()
        self.end_headers()

    def do_POST(self):
        url_path = urllib.parse.urlparse(self.path).path
        if url_path in ("/mcp", "/sse", "/"):
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length).decode("utf-8") if content_length > 0 else "{}"
            session_id = self.headers.get("Mcp-Session-Id") or str(uuid.uuid4())
            try:
                resp_dict = handle_rpc(body)
            except Exception as e:
                self.send_response(400)
                self._set_cors_headers()
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                err = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": str(e)}}
                self.wfile.write(json.dumps(err).encode("utf-8"))
                return

            if resp_dict is None:
                self.send_response(202)
                self._set_cors_headers()
                self.send_header("Mcp-Session-Id", session_id)
                self.end_headers()
                return

            self.send_response(200)
            self._set_cors_headers()
            self.send_header("Content-Type", "application/json")
            self.send_header("Mcp-Session-Id", session_id)
            self.end_headers()
            self.wfile.write(json.dumps(resp_dict, ensure_ascii=False).encode("utf-8"))
        else:
            self.send_response(404)
            self._set_cors_headers()
            self.end_headers()


def main():
    jawadi_loader.ensure_loaded(db_path=DB_PATH)
    try:
        conn = sqlite3.connect(DB_PATH, timeout=20)
        builder.repair_and_sync_db(conn)
        conn.close()
    except Exception:
        pass
    print(f"Starting Shia Quran MCP Server v{VERSION} on http://{HOST}:{PORT}")
    server = ThreadingHTTPServer((HOST, PORT), MCPHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
