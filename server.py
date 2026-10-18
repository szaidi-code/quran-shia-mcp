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

DB_PATH = Path(os.environ.get("DB_PATH", Path(__file__).parent / "quran_shia.db"))
PORT = int(os.environ.get("PORT", 8080))
HOST = os.environ.get("HOST", "0.0.0.0")
SUPPORTED_PROTOCOLS = ("2025-06-18", "2025-03-26", "2024-11-05")

TOOLS = [
    {
        "name": "fetch_translation",
        "description": "Fetch Quranic verses with Arabic text and Urdu/English translations from Balagh ul Quran (Allama Sheikh Mohsin Ali Najafi) and Tafseer e Namoona (Maulana Syed Safdar Hussain Najafi).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "surah": {"type": "integer", "description": "Surah number (1-114)"},
                "ayah": {"type": "integer", "description": "Optional specific Ayah number"},
                "edition": {
                    "type": "string",
                    "enum": ["all", "balagh", "namoona"],
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
        "description": "Search for keywords across Arabic text, Balagh ul Quran, Tafseer e Namoona translations, footnotes, and Tafseer commentary.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search keyword (Arabic, Urdu, or English)"},
                "edition": {"type": "string", "enum": ["all", "balagh", "namoona"], "default": "all"}
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
            cur.execute("SELECT id, name_ar, name_en, ayah_count FROM surahs ORDER BY id ASC")
            rows = cur.fetchall()
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

        elif name == "fetch_translation":
            surah = int(args.get("surah", 1))
            ayah = args.get("ayah")
            edition = args.get("edition", "all")

            _ensure_surah_cached(conn, surah)

            cur.execute("SELECT name_ar, name_en, ayah_count FROM surahs WHERE id = ?", (surah,))
            srow = cur.fetchone()

            if ayah is not None:
                cur.execute("SELECT * FROM verses WHERE surah = ? AND ayah = ?", (surah, int(ayah)))
            else:
                cur.execute("SELECT * FROM verses WHERE surah = ? ORDER BY ayah ASC", (surah,))

            rows = cur.fetchall()
            results = []
            for r in rows:
                entry = {
                    "verse_key": r["verse_key"],
                    "surah": r["surah"],
                    "ayah": r["ayah"],
                    "arabic": r["arabic"],
                    "english": r["trans_en"]
                }
                if edition in ("all", "balagh"):
                    entry["translation_balagh"] = r["trans_balagh"]
                    if r["footnotes_balagh"]:
                        entry["footnotes_balagh"] = r["footnotes_balagh"]
                if edition in ("all", "namoona"):
                    entry["translation_namoona"] = r["trans_namoona"]
                results.append(entry)

            return {
                "surah": surah,
                "name_ar": srow["name_ar"] if srow else "",
                "name_en": srow["name_en"] if srow else "",
                "count": len(results),
                "verses": results
            }

        elif name == "fetch_tafseer":
            surah = int(args.get("surah", 1))
            ayah = int(args.get("ayah", 1))
            source = args.get("source", "all")

            _ensure_surah_cached(conn, surah)
            cur.execute("SELECT * FROM verses WHERE surah = ? AND ayah = ?", (surah, ayah))
            row = cur.fetchone()
            if not row:
                return {"error": f"Verse {surah}:{ayah} not found in database."}

            res = {
                "verse_key": f"{surah}:{ayah}",
                "arabic": row["arabic"],
                "translation_balagh": row["trans_balagh"],
                "translation_namoona": row["trans_namoona"],
                "english": row["trans_en"]
            }
            if source in ("all", "kauthar"):
                k_text = _ensure_kauthar_tafseer(conn, surah, ayah)
                res["tafseer_al_kauthar"] = {
                    "author": "Allama Sheikh Mohsin Ali Najafi",
                    "source_url": f"https://www.balaghulquran.com/tafseer.php?sno={surah}&ano={surah:03d}{ayah:03d}",
                    "footnotes": row["footnotes_balagh"] or "",
                    "content": k_text or row["footnotes_balagh"] or "No separate extended entry; see translation and footnotes."
                }
            if source in ("all", "namoona"):
                res["tafseer_e_namoona"] = {
                    "author": "Grand Ayatollah Naser Makarem Shirazi / Maulana Syed Safdar Hussain Najafi",
                    "source_url": f"https://www.tafseerenamoona.net/surahs/{surah}#ayah-{ayah}",
                    "translation": row["trans_namoona"],
                    "content": row["tafseer_namoona"] or row["trans_namoona"] or "Available in online edition."
                }
            return res

        elif name == "search_verses":
            query = args.get("query", "").strip()
            edition = args.get("edition", "all")
            pattern = f"%{query}%"

            cur.execute(
                """
                SELECT surah, ayah, verse_key, arabic, trans_balagh, trans_namoona, trans_en, footnotes_balagh
                FROM verses
                WHERE arabic LIKE ? OR trans_balagh LIKE ? OR trans_namoona LIKE ? OR trans_en LIKE ?
                   OR footnotes_balagh LIKE ? OR tafseer_namoona LIKE ? OR tafseer_kauthar LIKE ?
                ORDER BY surah ASC, ayah ASC
                LIMIT 25
                """,
                (pattern, pattern, pattern, pattern, pattern, pattern, pattern),
            )

            rows = cur.fetchall()
            matches = []
            for r in rows:
                item = {
                    "verse_key": r["verse_key"],
                    "arabic": r["arabic"],
                    "english": r["trans_en"]
                }
                if edition in ("all", "balagh"):
                    item["balagh"] = r["trans_balagh"]
                    if r["footnotes_balagh"]:
                        item["footnotes_balagh"] = r["footnotes_balagh"]
                if edition in ("all", "namoona"):
                    item["namoona"] = r["trans_namoona"]
                matches.append(item)
            return {
                "query": query,
                "match_count": len(matches),
                "matches": matches
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
                    "version": "2.0.0"
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
            try:
                conn = get_db()
                cur = conn.cursor()
                cur.execute("SELECT COUNT(*) FROM surahs")
                surah_count = cur.fetchone()[0]
                cur.execute("SELECT COUNT(*) FROM verses")
                verse_count = cur.fetchone()[0]
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
                "version": "2.0.0",
                "database": {
                    "surahs": surah_count,
                    "verses": verse_count
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
    print(f"Starting Shia Quran MCP Server v2.0.0 on http://{HOST}:{PORT}")
    server = ThreadingHTTPServer((HOST, PORT), MCPHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
