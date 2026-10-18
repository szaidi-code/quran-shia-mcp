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
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
import urllib.parse
import urllib.request
import re
import html
import uuid
import os

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
    conn = sqlite3.connect(DB_PATH, timeout=15)
    conn.row_factory = sqlite3.Row
    return conn

def _clean_html(raw):
    if not raw:
        return ""
    return html.unescape(re.sub(r"<[^>]+>", "", raw)).strip()

def _ensure_surah_cached(conn, surah):
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM verses WHERE surah = ?", (surah,))
    if cur.fetchone()[0] > 0:
        return
    try:
        url_b = f"https://www.balaghulquran.com/index.php?sno={surah}"
        req_b = urllib.request.Request(url_b, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req_b, timeout=15) as resp:
            content_b = resp.read().decode("utf-8", errors="replace")
        blocks = re.split(r'<div class="row mb-lg-6" id="(\d{6})">', content_b)
        balagh_data = {}
        for i in range(1, len(blocks), 2):
            vid = blocks[i]
            chunk = blocks[i + 1].split("<footer")[0]
            ar_m = re.search(r'<p[^>]*class="[^"]*txtArabicQuran[^"]*"[^>]*>(.*?)</p>', chunk, re.S)
            ur_m = re.search(r'<p[^>]*class="[^"]*txtUrduQuran\b[^"]*"[^>]*>(.*?)</p>', chunk, re.S)
            notes = re.findall(r'<p[^>]*class="[^"]*txtUrdu fu-medium-lh[^"]*"[^>]*>(.*?)</p>', chunk, re.S)
            ayah_num = int(vid[3:])
            balagh_data[ayah_num] = {
                "arabic": _clean_html(ar_m.group(1)) if ar_m else "",
                "trans_balagh": _clean_html(ur_m.group(1)) if ur_m else "",
                "footnotes": "\n".join([_clean_html(n) for n in notes if _clean_html(n)])
            }
    except Exception:
        balagh_data = {}

    try:
        url_n = f"https://www.tafseerenamoona.net/surahs/{surah}"
        req_n = urllib.request.Request(url_n, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req_n, timeout=15) as resp:
            page_n = resp.read().decode("utf-8", errors="replace")
        safdars = re.findall(r'translation_safdar_najfi\\":\\"(.*?)\\"', page_n)
        yusufs = re.findall(r'translation_en\\":\\"(.*?)\\"', page_n)
        namoona_data = {}
        for i, s in enumerate(safdars):
            namoona_data[i + 1] = {
                "trans_namoona": html.unescape(s.strip()),
                "trans_en": html.unescape(yusufs[i].strip()) if i < len(yusufs) else ""
            }
    except Exception:
        namoona_data = {}

    max_ayah = max(list(balagh_data.keys()) + list(namoona_data.keys()) + [0])
    for a in range(1, max_ayah + 1):
        b = balagh_data.get(a, {})
        n = namoona_data.get(a, {})
        cur.execute("""
        INSERT OR IGNORE INTO verses
        (surah, ayah, verse_key, arabic, trans_balagh, trans_namoona, trans_en, footnotes_balagh, tafseer_kauthar, tafseer_namoona)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            surah, a, f"{surah}:{a}",
            b.get("arabic", ""),
            b.get("trans_balagh", ""),
            n.get("trans_namoona", ""),
            n.get("trans_en", ""),
            b.get("footnotes", ""),
            "",
            ""
        ))
    conn.commit()

def _ensure_kauthar_tafseer(conn, surah, ayah):
    cur = conn.cursor()
    cur.execute("SELECT tafseer_kauthar FROM verses WHERE surah = ? AND ayah = ?", (surah, ayah))
    row = cur.fetchone()
    if row and row["tafseer_kauthar"]:
        return row["tafseer_kauthar"]
    ano = f"{surah:03d}{ayah:03d}"
    url = f"https://www.balaghulquran.com/tafseer.php?sno={surah}&ano={ano}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            content = resp.read().decode("utf-8", errors="replace")
        paras = re.findall(r'<p class="lead fu-medium">(.*?)</p>', content, re.S)
        text = "\n\n".join([_clean_html(p) for p in paras if _clean_html(p)])
        if text:
            cur.execute("UPDATE verses SET tafseer_kauthar = ? WHERE surah = ? AND ayah = ?", (text, surah, ayah))
            conn.commit()
        return text
    except Exception:
        return ""

def execute_tool(name, args):
    conn = get_db()
    try:
        cur = conn.cursor()

        if name == "fetch_translation":
            surah = int(args.get("surah", 1))
            ayah = args.get("ayah")
            edition = args.get("edition", "all")

            _ensure_surah_cached(conn, surah)

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

            _ensure_surah_cached(conn, surah)
            cur.execute("SELECT * FROM verses WHERE surah = ? AND ayah = ?", (surah, ayah))
            row = cur.fetchone()
            if not row:
                return {"error": f"Verse {surah}:{ayah} not found in database."}

            res = {
                "verse_key": f"{surah}:{ayah}",
                "arabic": row["arabic"]
            }
            if source in ("all", "kauthar"):
                k_text = _ensure_kauthar_tafseer(conn, surah, ayah)
                res["tafseer_al_kauthar"] = {
                    "author": "Allama Sheikh Mohsin Ali Najafi",
                    "source_url": f"https://www.balaghulquran.com/tafseer.php?sno={surah}&ano={surah:03d}{ayah:03d}",
                    "content": k_text or row["footnotes_balagh"] or "No detailed commentary entry."
                }
            if source in ("all", "namoona"):
                res["tafseer_e_namoona"] = {
                    "author": "Ayatollah Naser Makarem Shirazi / Maulana Syed Safdar Hussain Najafi",
                    "translation": row["trans_namoona"],
                    "content": row["tafseer_namoona"] or row["trans_namoona"] or "Available in online edition."
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
    finally:
        conn.close()

def handle_single_rpc(req):
    method = req.get("method", "")
    req_id = req.get("id")

    # JSON-RPC notifications (e.g. notifications/initialized) do not have an id
    # and must not return a JSON-RPC response object.
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
                    "version": "1.1.0"
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

        # If an MCP client sends GET with Accept: text/event-stream to /, /mcp, or /sse
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
            self.send_response(200)
            self._set_cors_headers()
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            resp = {
                "status": "healthy",
                "service": "quran-shia-mcp",
                "version": "1.1.0",
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
                # Notification (such as notifications/initialized): return 202 Accepted
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
    print(f"Starting Shia Quran MCP Server on http://{HOST}:{PORT}")
    server = ThreadingHTTPServer((HOST, PORT), MCPHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass

if __name__ == "__main__":
    main()

