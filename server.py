#!/usr/bin/env python3
"""
Shia Quran & Tafseer HTTP / SSE MCP Server
Supports both JSON-RPC via HTTP POST and Server-Sent Events (SSE).
Zero external dependencies (uses standard library http.server and sqlite3).
Ready for Render, Fly.io, and Kubernetes.
"""
import sys
import json
import sqlite3
from pathlib import Path
from http.server import HTTPServer, BaseHTTPRequestHandler
import urllib.parse
import os

DB_PATH = Path(os.environ.get("DB_PATH", Path(__file__).parent / "quran_shia.db"))
PORT = int(os.environ.get("PORT", 8080))
HOST = os.environ.get("HOST", "0.0.0.0")

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
                    "description": "Tafseer work to query (default: 'kauthar')",
                    "default": "kauthar"
                }
            },
            "required": ["surah", "ayah"]
        }
    },
    {
        "name": "search_verses",
        "description": "Search for keywords across Arabic text, Balagh ul Quran, or Tafseer e Namoona translations.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search keyword (Arabic, Urdu, or English)"},
                "edition": {"type": "string", "enum": ["all", "balagh", "namoona"], "default": "all"}
            },
            "required": ["query"]
        }
    }
]

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def execute_tool(name, args):
    conn = get_db()
    cur = conn.cursor()

    if name == "fetch_translation":
        surah = int(args.get("surah", 1))
        ayah = args.get("ayah")
        edition = args.get("edition", "all")

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
            "count": len(results),
            "verses": results
        }

    elif name == "fetch_tafseer":
        surah = int(args.get("surah", 1))
        ayah = int(args.get("ayah", 1))
        source = args.get("source", "kauthar")

        cur.execute("SELECT * FROM verses WHERE surah = ? AND ayah = ?", (surah, ayah))
        row = cur.fetchone()
        if not row:
            return {"error": f"Verse {surah}:{ayah} not found in database."}

        res = {
            "verse_key": f"{surah}:{ayah}",
            "arabic": row["arabic"]
        }
        if source in ("all", "kauthar"):
            res["tafseer_al_kauthar"] = {
                "author": "Allama Sheikh Mohsin Ali Najafi",
                "content": row["tafseer_kauthar"] or "No detailed commentary entry."
            }
        if source in ("all", "namoona"):
            res["tafseer_e_namoona"] = {
                "author": "Ayatollah Naser Makarem Shirazi / Maulana Syed Safdar Hussain Najafi",
                "content": row["tafseer_namoona"] or "Available in online edition."
            }
        return res

    elif name == "search_verses":
        query = args.get("query", "").strip()
        edition = args.get("edition", "all")
        pattern = f"%{query}%"

        cur.execute("""
        SELECT surah, ayah, verse_key, arabic, trans_balagh, trans_namoona, trans_en
        FROM verses
        WHERE arabic LIKE ? OR trans_balagh LIKE ? OR trans_namoona LIKE ? OR trans_en LIKE ?
        LIMIT 20
        """, (pattern, pattern, pattern, pattern))

        rows = cur.fetchall()
        matches = []
        for r in rows:
            matches.append({
                "verse_key": r["verse_key"],
                "arabic": r["arabic"],
                "balagh": r["trans_balagh"],
                "namoona": r["trans_namoona"],
                "english": r["trans_en"]
            })
        return {
            "query": query,
            "match_count": len(matches),
            "matches": matches
        }

    else:
        raise ValueError(f"Tool {name} not found")

def handle_rpc(body_str):
    req = json.loads(body_str)
    method = req.get("method")
    req_id = req.get("id")

    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {
                    "tools": {}
                },
                "serverInfo": {
                    "name": "quran-shia-mcp",
                    "version": "1.0.0"
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

class MCPHandler(BaseHTTPRequestHandler):
    def _set_cors_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")

    def do_OPTIONS(self):
        self.send_response(204)
        self._set_cors_headers()
        self.end_headers()

    def do_GET(self):
        url_path = urllib.parse.urlparse(self.path).path
        if url_path == "/" or url_path == "/health":
            self.send_response(200)
            self._set_cors_headers()
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            resp = {
                "status": "healthy",
                "service": "quran-shia-mcp",
                "version": "1.0.0",
                "tools": [t["name"] for t in TOOLS],
                "endpoints": {
                    "mcp_rpc": "/mcp",
                    "sse": "/sse"
                }
            }
            self.wfile.write(json.dumps(resp, indent=2).encode("utf-8"))

        elif url_path == "/sse":
            # Server-Sent Events endpoint
            self.send_response(200)
            self._set_cors_headers()
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.end_headers()
            # Send initial endpoint event as specified by MCP SSE transport
            endpoint_msg = f"event: endpoint\ndata: /mcp\n\n"
            self.wfile.write(endpoint_msg.encode("utf-8"))
            self.wfile.flush()

        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        url_path = urllib.parse.urlparse(self.path).path
        if url_path in ("/mcp", "/"):
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length).decode("utf-8")
            resp_dict = handle_rpc(body)
            self.send_response(200)
            self._set_cors_headers()
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(resp_dict, ensure_ascii=False).encode("utf-8"))
        else:
            self.send_response(404)
            self.end_headers()

def main():
    print(f"Starting Shia Quran MCP Server on http://{HOST}:{PORT}")
    server = HTTPServer((HOST, PORT), MCPHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass

if __name__ == "__main__":
    main()
