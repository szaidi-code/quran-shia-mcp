#!/usr/bin/env python3
"""
Shia Quran & Tafseer HTTP / SSE MCP Server
Supports both JSON-RPC via HTTP POST (Streamable HTTP) and Server-Sent Events (SSE).
Zero external dependencies (uses standard library http.server and sqlite3).
Ready for Render, Fly.io, and Kubernetes.
"""
import sys
import json
import sqlite3
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
VERSION = "1.2.0"
SUPPORTED_PROTOCOLS = ("2025-06-18", "2025-03-26", "2024-11-05")

TOOLS = [
    {
        "name": "fetch_translation",
        "description": (
            "Fetch Quranic verses with Arabic text and Urdu/English translations from "
            "Balagh ul Quran (Allama Sheikh Mohsin Ali Najafi), Tafseer e Namoona "
            "(Maulana Syed Safdar Hussain Najafi), and Allama Syed Zeeshan Haider Jawadi (Tanzil.net)."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "surah": {"type": "integer", "description": "Surah number (1-114)"},
                "ayah": {"type": "integer", "description": "Optional specific Ayah number"},
                "edition": {
                    "type": "string",
                    "enum": ["all", "balagh", "namoona", "jawadi"],
                    "description": "Translation source (default: 'all')",
                    "default": "all"
                }
            },
            "required": ["surah"]
        }
    },
    {
        "name": "fetch_tafseer",
        "description": "Fetch detailed Quranic Tafseer commentaries from Al-Kauthar fi Tafsir al-Quran (Sheikh Mohsin Ali Najafi) or Tafseer e Namoona (Ayatollah Makarem Shirazi / Safdar Najfi).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "surah": {"type": "integer", "description": "Surah number (1-114)"},
                "ayah": {"type": "integer", "description": "Ayah number within the Surah (default: 1)"},
                "source": {
                    "type": "string",
                    "enum": ["kauthar", "namoona", "all"],
                    "description": "Tafseer work to query (default: 'all')",
                    "default": "all"
                }
            },
            "required": ["surah", "ayah"]
        }
    },
    {
        "name": "search_verses",
        "description": "Search for keywords across Arabic text, Balagh ul Quran, Tafseer e Namoona, Allama Jawadi translations, footnotes, and Tafseer commentary.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search keyword (Arabic, Urdu, or English)"},
                "edition": {
                    "type": "string",
                    "enum": ["all", "balagh", "namoona", "jawadi"],
                    "default": "all"
                }
            },
            "required": ["query"]
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


def get_db():
    conn = sqlite3.connect(DB_PATH, timeout=20)
    conn.row_factory = sqlite3.Row
    return conn


def _clean_html(raw):
    return builder.clean_html(raw)


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


def execute_tool(name, args):
    conn = get_db()
    try:
        cur = conn.cursor()

        if name == "list_surahs":
            cur.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='surahs'"
            )
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
                            "ayah_count": r["ayah_count"]
                        }
                        for r in rows
                    ]
                }
            return {
                "count": 114,
                "surahs": [
                    {"surah": s, "name_ar": "", "name_en": f"Surah {s}", "ayah_count": c}
                    for s, c in jawadi_loader.AYAH_COUNTS.items()
                ]
            }

        elif name == "fetch_translation":
            surah = int(args.get("surah", 1))
            ayah_raw = args.get("ayah")
            ayah = int(ayah_raw) if ayah_raw is not None else None
            edition = args.get("edition", "all")
            if edition not in ("all", "balagh", "namoona", "jawadi"):
                raise ValueError(f"Invalid edition '{edition}': must be one of 'all', 'balagh', 'namoona', 'jawadi'.")

            jawadi_loader.validate_surah_ayah(surah, ayah)
            jawadi_loader.ensure_loaded(conn, db_path=DB_PATH)

            # edition == "jawadi" intentionally skips live scraping
            if edition != "jawadi":
                _ensure_surah_cached(conn, surah)

            cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='verses'")
            has_verses_table = bool(cur.fetchone())
            cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='quran_text_tanzil'")
            has_arabic_table = bool(cur.fetchone())

            arabic_map = {}
            if has_arabic_table:
                if ayah is not None:
                    cur.execute(
                        "SELECT ayah, text FROM quran_text_tanzil WHERE surah = ? AND ayah = ?",
                        (surah, ayah),
                    )
                else:
                    cur.execute(
                        "SELECT ayah, text FROM quran_text_tanzil WHERE surah = ? ORDER BY ayah ASC",
                        (surah,),
                    )
                for arow in cur.fetchall():
                    arabic_map[arow["ayah"]] = arow["text"]

            jawadi_map = {}
            if edition in ("all", "jawadi"):
                if ayah is not None:
                    cur.execute(
                        "SELECT ayah, text FROM translation_jawadi WHERE surah = ? AND ayah = ?",
                        (surah, ayah),
                    )
                else:
                    cur.execute(
                        "SELECT ayah, text FROM translation_jawadi WHERE surah = ? ORDER BY ayah ASC",
                        (surah,),
                    )
                for jrow in cur.fetchall():
                    jawadi_map[jrow["ayah"]] = jrow["text"]

            v_map = {}
            if has_verses_table:
                if ayah is not None:
                    cur.execute("SELECT * FROM verses WHERE surah = ? AND ayah = ?", (surah, ayah))
                else:
                    cur.execute("SELECT * FROM verses WHERE surah = ? ORDER BY ayah ASC", (surah,))
                for r in cur.fetchall():
                    v_map[r["ayah"]] = r

            if edition == "jawadi":
                ayah_nums = sorted(jawadi_map.keys())
            elif edition == "all":
                ayah_nums = sorted(set(v_map.keys()) | set(jawadi_map.keys()) | set(arabic_map.keys()))
            else:
                ayah_nums = sorted(v_map.keys())

            results = []
            for a in ayah_nums:
                r = v_map.get(a)
                entry = {
                    "verse_key": f"{surah}:{a}",
                    "surah": surah,
                    "ayah": a,
                    "arabic": (r["arabic"] if (r and r["arabic"]) else arabic_map.get(a, "")),
                    "english": r["trans_en"] if r else ""
                }
                if edition in ("all", "balagh") and r:
                    entry["translation_balagh"] = r["trans_balagh"]
                    if r["footnotes_balagh"]:
                        entry["footnotes_balagh"] = r["footnotes_balagh"]
                if edition in ("all", "namoona") and r:
                    entry["translation_namoona"] = r["trans_namoona"]
                if edition in ("all", "jawadi") and a in jawadi_map:
                    entry["translation_jawadi"] = jawadi_map[a]
                results.append(entry)

            resp = {
                "surah": surah,
                "count": len(results),
                "verses": results
            }
            sources = {}
            if has_arabic_table:
                sources["arabic"] = jawadi_loader.ARABIC_ATTRIBUTION
            if edition in ("all", "jawadi"):
                sources["jawadi"] = jawadi_loader.ATTRIBUTION
            if sources:
                resp["sources"] = sources
            return resp

        elif name == "fetch_tafseer":
            surah = int(args.get("surah", 1))
            ayah = int(args.get("ayah", 1))
            source = args.get("source", "kauthar")

            jawadi_loader.validate_surah_ayah(surah, ayah)
            jawadi_loader.ensure_loaded(conn, db_path=DB_PATH)
            _ensure_surah_cached(conn, surah)

            cur.execute("SELECT * FROM verses WHERE surah = ? AND ayah = ?", (surah, ayah))
            row = cur.fetchone()
            if not row:
                return {"error": f"Verse {surah}:{ayah} not found in database."}

            cur.execute(
                "SELECT text FROM translation_jawadi WHERE surah = ? AND ayah = ?",
                (surah, ayah),
            )
            jrow = cur.fetchone()

            cur.execute(
                "SELECT text FROM quran_text_tanzil WHERE surah = ? AND ayah = ?",
                (surah, ayah),
            )
            arow = cur.fetchone()

            res = {
                "verse_key": f"{surah}:{ayah}",
                "arabic": row["arabic"] or (arow["text"] if arow else ""),
                "translation_balagh": row["trans_balagh"],
                "translation_namoona": row["trans_namoona"],
                "translation_jawadi": jrow["text"] if jrow else "",
                "english": row["trans_en"]
            }
            if source in ("all", "kauthar"):
                k_text = _ensure_kauthar_tafseer(conn, surah, ayah)
                res["tafseer_al_kauthar"] = {
                    "author": "Allama Sheikh Mohsin Ali Najafi",
                    "source_url": f"https://www.balaghulquran.com/tafseer.php?sno={surah}&ano={surah:03d}{ayah:03d}",
                    "footnotes": row["footnotes_balagh"] or "",
                    "content": k_text or row["footnotes_balagh"] or "No detailed commentary entry."
                }
            if source in ("all", "namoona"):
                res["tafseer_e_namoona"] = {
                    "author": "Ayatollah Naser Makarem Shirazi / Maulana Syed Safdar Hussain Najafi",
                    "source_url": f"https://www.tafseerenamoona.net/surahs/{surah}#ayah-{ayah}",
                    "translation": row["trans_namoona"],
                    "content": row["tafseer_namoona"] or row["trans_namoona"] or "Available in online edition."
                }
            sources = {"arabic": jawadi_loader.ARABIC_ATTRIBUTION}
            if jrow:
                sources["jawadi"] = jawadi_loader.ATTRIBUTION
            res["sources"] = sources
            return res

        elif name == "search_verses":
            query = args.get("query", "").strip()
            edition = args.get("edition", "all")
            if edition not in ("all", "balagh", "namoona", "jawadi"):
                raise ValueError(f"Invalid edition '{edition}': must be one of 'all', 'balagh', 'namoona', 'jawadi'.")

            if not query:
                return {"query": query, "match_count": 0, "matches": []}

            jawadi_loader.ensure_loaded(conn, db_path=DB_PATH)

            pattern = f"%{query}%"
            matches = []

            cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='verses'")
            has_verses_table = bool(cur.fetchone())

            if edition == "jawadi":
                if has_verses_table:
                    cur.execute(
                        """
                        SELECT j.verse_key, j.surah, j.ayah, j.text AS trans_jawadi,
                               COALESCE(NULLIF(v.arabic, ''), q.text, '') AS arabic,
                               COALESCE(v.trans_en, '') AS trans_en
                        FROM translation_jawadi j
                        LEFT JOIN quran_text_tanzil q ON q.verse_key = j.verse_key
                        LEFT JOIN verses v ON v.verse_key = j.verse_key
                        WHERE j.text LIKE ? OR q.text LIKE ? OR v.arabic LIKE ? OR v.trans_en LIKE ?
                        ORDER BY j.surah ASC, j.ayah ASC
                        LIMIT 20
                        """,
                        (pattern, pattern, pattern, pattern),
                    )
                else:
                    cur.execute(
                        """
                        SELECT j.verse_key, j.surah, j.ayah, j.text AS trans_jawadi,
                               COALESCE(q.text, '') AS arabic, '' AS trans_en
                        FROM translation_jawadi j
                        LEFT JOIN quran_text_tanzil q ON q.verse_key = j.verse_key
                        WHERE j.text LIKE ? OR q.text LIKE ?
                        ORDER BY j.surah ASC, j.ayah ASC
                        LIMIT 20
                        """,
                        (pattern, pattern),
                    )
                for r in cur.fetchall():
                    matches.append({
                        "verse_key": r["verse_key"],
                        "arabic": r["arabic"] or "",
                        "jawadi": r["trans_jawadi"],
                        "english": r["trans_en"] or ""
                    })
            elif has_verses_table:
                cur.execute(
                    """
                    SELECT v.surah, v.ayah, v.verse_key,
                           COALESCE(NULLIF(v.arabic, ''), q.text, '') AS arabic,
                           v.trans_balagh, v.trans_namoona, v.trans_en,
                           j.text AS trans_jawadi
                    FROM verses v
                    LEFT JOIN quran_text_tanzil q ON q.verse_key = v.verse_key
                    LEFT JOIN translation_jawadi j ON j.verse_key = v.verse_key
                    WHERE v.arabic LIKE ? OR q.text LIKE ? OR v.trans_balagh LIKE ? OR v.trans_namoona LIKE ?
                       OR v.trans_en LIKE ? OR j.text LIKE ?
                       OR v.footnotes_balagh LIKE ? OR v.tafseer_namoona LIKE ? OR v.tafseer_kauthar LIKE ?
                    ORDER BY v.surah ASC, v.ayah ASC
                    LIMIT 20
                    """,
                    (pattern, pattern, pattern, pattern, pattern, pattern, pattern, pattern, pattern),
                )
                for r in cur.fetchall():
                    item = {
                        "verse_key": r["verse_key"],
                        "arabic": r["arabic"],
                        "balagh": r["trans_balagh"],
                        "namoona": r["trans_namoona"],
                        "english": r["trans_en"]
                    }
                    if edition in ("all", "jawadi") and r["trans_jawadi"]:
                        item["jawadi"] = r["trans_jawadi"]
                    matches.append(item)

            resp = {
                "query": query,
                "match_count": len(matches),
                "matches": matches
            }
            sources = {"arabic": jawadi_loader.ARABIC_ATTRIBUTION}
            if edition in ("all", "jawadi"):
                sources["jawadi"] = jawadi_loader.ATTRIBUTION
            resp["sources"] = sources
            return resp

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
                }
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
                    "docs": "/documentation"
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
    print(f"Starting Shia Quran MCP Server v{VERSION} on http://{HOST}:{PORT}")
    server = ThreadingHTTPServer((HOST, PORT), MCPHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
