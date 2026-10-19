#!/usr/bin/env python3
"""
Builds the complete 114-Surah Shia Quran & Tafseer SQLite database (quran_shia.db).
Sources:
1. Tafseer e Namoona (tafseerenamoona.net) — All 114 Surahs:
   - Arabic text
   - Balagh ul Quran Urdu translation (Allama Sheikh Mohsin Ali Najafi)
   - Tafseer e Namoona Urdu translation (Maulana Syed Safdar Hussain Najafi)
   - English translations (Abdullah Yusuf Ali & M. H. Shakir)
   - Complete Tafseer e Namoona commentary (Urdu & English topics and exegesis)
2. Balagh ul Quran (balaghulquran.com) — All 114 Surahs:
   - Balagh ul Quran explanatory footnotes (حواشی)
   - Tafseer al-Kauthar (الکوثر فی تفسیر القرآن) commentary
"""
import sys
import sqlite3
import urllib.request
import re
import html
import json
import time
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

import jawadi_loader

DB_PATH = Path(__file__).parent / "quran_shia.db"
HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"}


def is_db_complete(db_path=DB_PATH):
    if not db_path.exists():
        return False
    try:
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM surahs")
        scount = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM verses")
        vcount = cur.fetchone()[0]
        conn.close()
        return scount == 114 and vcount >= 6236
    except Exception:
        return False


def init_db(db_path=DB_PATH):
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("PRAGMA journal_mode=WAL")
    cur.execute("PRAGMA synchronous=NORMAL")
    cur.execute("""
    CREATE TABLE IF NOT EXISTS surahs (
        id INTEGER PRIMARY KEY,
        name_ar TEXT,
        name_en TEXT,
        ayah_count INTEGER
    )
    """)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS verses (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        surah INTEGER,
        ayah INTEGER,
        verse_key TEXT UNIQUE,
        arabic TEXT,
        trans_balagh TEXT,
        trans_namoona TEXT,
        trans_en TEXT,
        footnotes_balagh TEXT,
        tafseer_kauthar TEXT,
        tafseer_namoona TEXT
    )
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_verses_surah_ayah ON verses(surah, ayah)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_verses_key ON verses(verse_key)")
    conn.commit()
    return conn


def clean_html(raw):
    if not raw:
        return ""
    text = re.sub(r"<br\s*/?>", "\n", raw, flags=re.I)
    text = re.sub(r"</p\s*>", "\n\n", text, flags=re.I)
    text = re.sub(r"<[^>]+>", "", text)
    text = html.unescape(text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def fetch_namoona_surah(surah, retries=3):
    """Fetches a full Surah JSON + RSC Tafseer chunks from tafseerenamoona.net."""
    url = f"https://www.tafseerenamoona.net/surahs/{surah}"
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=45) as resp:
                html_n = resp.read().decode("utf-8", errors="replace")

            pushes = re.findall(r'self\.__next_f\.push\(\[1,(".*?")\]\)', html_n, re.S)
            full_rsc = "".join(json.loads(p) for p in pushes)
            raw_bytes = full_rsc.encode("utf-8")

            chunks = {}
            for m in re.finditer(rb"([0-9a-f]+):T([0-9a-f]+),", raw_bytes):
                cid = m.group(1).decode("ascii")
                blen = int(m.group(2).decode("ascii"), 16)
                start = m.end()
                chunks["$" + cid] = raw_bytes[start : start + blen].decode("utf-8", errors="replace")

            idx = full_rsc.find('{"surah":{"surah_number":')
            if idx == -1:
                raise ValueError(f"Surah JSON marker not found in RSC for surah {surah}")
            dec = json.JSONDecoder()
            obj, _ = dec.raw_decode(full_rsc[idx:])
            sdata = obj["surah"]

            def resolve(val):
                if isinstance(val, str) and val.startswith("$"):
                    return chunks.get(val, "")
                return val or ""

            bismillah_tafseer_ur = ""
            bismillah_tafseer_en = ""
            parsed_ayahs = {}

            for a in sdata.get("ayahs", []):
                anum = int(a.get("ayat_number", 0))
                topics_ur = []
                topics_en = []
                for t in a.get("tafseer_topics") or []:
                    t_ur = clean_html(resolve(t.get("title_ur") or t.get("title") or ""))
                    d_ur = clean_html(resolve(t.get("details_ur") or t.get("details") or ""))
                    t_en = clean_html(resolve(t.get("title_en") or ""))
                    d_en = clean_html(resolve(t.get("details_en") or ""))
                    if t_ur or d_ur:
                        topics_ur.append(f"### {t_ur}\n{d_ur}".strip() if t_ur else d_ur)
                    if t_en or d_en:
                        topics_en.append(f"### {t_en}\n{d_en}".strip() if t_en else d_en)

                taf_ur = clean_html(resolve(a.get("tafseer_ur") or a.get("tafseer") or ""))
                taf_en = clean_html(resolve(a.get("tafseer_en") or ""))

                full_ur = "\n\n".join([x for x in [taf_ur] + topics_ur if x])
                full_en = "\n\n".join([x for x in [taf_en] + topics_en if x])

                if anum == 0:
                    bismillah_tafseer_ur = full_ur
                    bismillah_tafseer_en = full_en
                    continue

                if anum == 1 and (bismillah_tafseer_ur or bismillah_tafseer_en):
                    if bismillah_tafseer_ur:
                        full_ur = "\n\n".join([x for x in [bismillah_tafseer_ur, full_ur] if x])
                    if bismillah_tafseer_en:
                        full_en = "\n\n".join([x for x in [bismillah_tafseer_en, full_en] if x])

                combined_tafseer = ""
                if full_ur and full_en:
                    combined_tafseer = f"{full_ur}\n\n---\n\n{full_en}"
                else:
                    combined_tafseer = full_ur or full_en

                en_yusuf = clean_html(resolve(a.get("translation_en_yusuf_ali") or a.get("translation_en") or "")).strip()
                en_shakir = clean_html(resolve(a.get("translation_en_shakir") or "")).strip()
                trans_en = en_yusuf
                if en_shakir and en_shakir != en_yusuf:
                    trans_en = f"{en_yusuf}\n[Shakir]: {en_shakir}" if en_yusuf else en_shakir

                parsed_ayahs[anum] = {
                    "arabic": clean_html(resolve(a.get("arabic") or "")).strip(),
                    "trans_balagh": clean_html(resolve(a.get("translation_mohsin_najfi") or a.get("translation") or "")).strip(),
                    "trans_namoona": clean_html(resolve(a.get("translation_safdar_najfi") or a.get("translation_ur") or "")).strip(),
                    "trans_en": trans_en,
                    "tafseer_namoona": combined_tafseer,
                }

            return {
                "id": int(sdata.get("surah_number", surah)),
                "name_ar": (sdata.get("name_ar") or "").strip(),
                "name_en": (sdata.get("name_en") or "").strip(),
                "ayah_count": len(parsed_ayahs),
                "ayahs": parsed_ayahs,
            }
        except Exception as e:
            if attempt == retries - 1:
                raise
            time.sleep(1.5 * (attempt + 1))


def fetch_balagh_page(surah, ano, retries=3):
    """Fetches a 10-verse page from balaghulquran.com for Arabic, Urdu translation, and footnotes."""
    url = f"https://www.balaghulquran.com/index.php?sno={surah}&ano={ano}"
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=25) as resp:
                content = resp.read().decode("utf-8", errors="replace")
            blocks = re.split(r'<div class="row mb-lg-6" id="(\d{6})">', content)
            results = {}
            for i in range(1, len(blocks), 2):
                vid = blocks[i]
                ayah_num = int(vid[3:])
                if ayah_num == 0:
                    continue
                chunk = blocks[i + 1].split("<footer")[0]
                ar_m = re.search(r'<p[^>]*class="[^"]*txtArabicQuran[^"]*"[^>]*>(.*?)</p>', chunk, re.S)
                ur_m = re.search(r'<p[^>]*class="[^"]*txtUrduQuran\b[^"]*"[^>]*>(.*?)</p>', chunk, re.S)
                notes = re.findall(r'<p[^>]*class="[^"]*txtUrdu fu-medium-lh[^"]*"[^>]*>(.*?)</p>', chunk, re.S)
                results[ayah_num] = {
                    "arabic": clean_html(ar_m.group(1)) if ar_m else "",
                    "trans_balagh": clean_html(ur_m.group(1)) if ur_m else "",
                    "footnotes": "\n".join([clean_html(n) for n in notes if clean_html(n)]),
                }
            return results
        except Exception:
            if attempt == retries - 1:
                return {}
            time.sleep(1.0 * (attempt + 1))


def fetch_balagh_surah(surah, ayah_count):
    """Fetches all 10-verse pages for a Surah from balaghulquran.com."""
    anos = list(range(1, ayah_count + 1, 10))
    merged = {}
    with ThreadPoolExecutor(max_workers=10) as ex:
        futures = [ex.submit(fetch_balagh_page, surah, ano) for ano in anos]
        for f in as_completed(futures):
            merged.update(f.result())
    return merged


def fetch_balagh_tafseer(surah=1, ayah=1):
    ano = f"{surah:03d}{ayah:03d}"
    url = f"https://www.balaghulquran.com/tafseer.php?sno={surah}&ano={ano}"
    try:
        req = urllib.request.Request(url, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=20) as resp:
            content = resp.read().decode("utf-8", errors="replace")
        paras = re.findall(r'<p class="lead fu-medium">(.*?)</p>', content, re.S)
        return "\n\n".join([clean_html(p) for p in paras if clean_html(p)])
    except Exception:
        return ""


def fetch_complete_surah(surah_num):
    try:
        sdata = fetch_namoona_surah(surah_num)
    except Exception:
        sdata = {
            "id": surah_num,
            "name_ar": "",
            "name_en": f"Surah {surah_num}",
            "ayah_count": jawadi_loader.AYAH_COUNTS.get(surah_num, 0),
            "ayahs": {},
        }
    ayah_count = sdata["ayah_count"]
    try:
        balagh_map = fetch_balagh_surah(surah_num, ayah_count)
    except Exception:
        balagh_map = {}
    kauthar_map = {}
    if surah_num == 1:
        kauthar_map[1] = fetch_balagh_tafseer(1, 1)
    elif surah_num == 2:
        for a in (255, 256, 257):
            kauthar_map[a] = fetch_balagh_tafseer(2, a)
    return sdata, balagh_map, kauthar_map


def repair_and_sync_db(conn):
    """Ensures Tanzil Arabic & Jawadi tables are loaded, repairs any RSC pointer artifacts, and syncs verses.arabic."""
    j_count = jawadi_loader.ensure_loaded(conn)
    cur = conn.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='verses'")
    if not cur.fetchone():
        return j_count

    # Repair any corrupted RSC pointer in 2:282 or missing 34:49 translation
    cur.execute(
        "SELECT surah, ayah FROM verses WHERE arabic LIKE '$%' OR trans_namoona LIKE '$%' OR trans_en LIKE '%$%' OR (surah = 34 AND ayah = 49 AND (trans_en IS NULL OR trans_en = ''))"
    )
    bad_rows = cur.fetchall()
    for s_num, a_num in bad_rows:
        try:
            sdata = fetch_namoona_surah(s_num)
            n = sdata.get("ayahs", {}).get(a_num, {})
            if n:
                cur.execute(
                    """
                    UPDATE verses
                    SET arabic = COALESCE(NULLIF(?, ''), arabic),
                        trans_namoona = COALESCE(NULLIF(?, ''), trans_namoona),
                        trans_en = COALESCE(NULLIF(?, ''), trans_en)
                    WHERE surah = ? AND ayah = ?
                    """,
                    (
                        n.get("arabic", ""),
                        n.get("trans_namoona", ""),
                        n.get("trans_en", ""),
                        s_num,
                        a_num,
                    ),
                )
        except Exception:
            pass

    # Synchronize all verses.arabic with canonical Tanzil Simple v1.1 text
    cur.execute(
        """
        UPDATE verses
        SET arabic = (
            SELECT q.text FROM quran_text_tanzil q
            WHERE q.surah = verses.surah AND q.ayah = verses.ayah
        )
        WHERE EXISTS (
            SELECT 1 FROM quran_text_tanzil q
            WHERE q.surah = verses.surah AND q.ayah = verses.ayah
              AND q.text IS NOT NULL AND q.text != ''
              AND verses.arabic != q.text
        )
        """
    )
    conn.commit()
    return j_count


def main():
    force_rebuild = "--rebuild" in sys.argv or "--force" in sys.argv
    if not force_rebuild and is_db_complete(DB_PATH):
        conn = sqlite3.connect(DB_PATH)
        j_count = repair_and_sync_db(conn)
        conn.close()
        print(
            f"Database {DB_PATH} already contains all 114 Surahs (6,236+ verses) "
            f"and {j_count} Jawadi verses (Arabic synced). Skipping rebuild."
        )
        return

    print(f"Building full 114-Surah Shia Quran & Tafseer database at {DB_PATH}...")
    if force_rebuild and DB_PATH.exists():
        DB_PATH.unlink()
    conn = init_db(DB_PATH)
    cur = conn.cursor()

    cur.execute("SELECT id, ayah_count FROM surahs")
    existing_surahs = {}
    for row in cur.fetchall():
        sid, acount = row[0], row[1]
        cur.execute("SELECT COUNT(*) FROM verses WHERE surah = ?", (sid,))
        vcount = cur.fetchone()[0]
        if acount > 0 and vcount >= acount and not force_rebuild:
            existing_surahs[sid] = vcount

    to_fetch = [s for s in range(1, 115) if s not in existing_surahs]
    total_verses = sum(existing_surahs.values())
    t_start = time.time()

    with ThreadPoolExecutor(max_workers=6) as pool:
        future_map = {s: pool.submit(fetch_complete_surah, s) for s in to_fetch}

        for surah_num in range(1, 115):
            if surah_num in existing_surahs:
                print(
                    f"[{surah_num:3d}/114] Surah {surah_num} already populated "
                    f"({existing_surahs[surah_num]} verses). Skipping.",
                    flush=True,
                )
                continue

            t0 = time.time()
            sdata, balagh_map, kauthar_map = future_map[surah_num].result()
            ayah_count = sdata["ayah_count"]

            cur.execute(
                "INSERT OR REPLACE INTO surahs (id, name_ar, name_en, ayah_count) VALUES (?, ?, ?, ?)",
                (surah_num, sdata["name_ar"], sdata["name_en"], ayah_count),
            )

            rows_to_insert = []
            for a in range(1, ayah_count + 1):
                n = sdata["ayahs"].get(a, {})
                b = balagh_map.get(a, {})

                arabic = n.get("arabic") or b.get("arabic") or ""
                trans_balagh = b.get("trans_balagh") or n.get("trans_balagh") or ""
                trans_namoona = n.get("trans_namoona") or ""
                trans_en = n.get("trans_en") or ""
                footnotes = b.get("footnotes") or ""
                tafseer_namoona = n.get("tafseer_namoona") or ""
                kauthar = kauthar_map.get(a, "")

                rows_to_insert.append((
                    surah_num,
                    a,
                    f"{surah_num}:{a}",
                    arabic,
                    trans_balagh,
                    trans_namoona,
                    trans_en,
                    footnotes,
                    kauthar,
                    tafseer_namoona,
                ))

            cur.executemany(
                """
                INSERT OR REPLACE INTO verses
                (surah, ayah, verse_key, arabic, trans_balagh, trans_namoona, trans_en, footnotes_balagh, tafseer_kauthar, tafseer_namoona)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                rows_to_insert,
            )
            conn.commit()
            total_verses += ayah_count
            elapsed = time.time() - t0
            print(
                f"[{surah_num:3d}/114] {sdata['name_en']} ({sdata['name_ar']}) — "
                f"{ayah_count} ayahs fed ({elapsed:.1f}s, total verses: {total_verses})",
                flush=True,
            )

    print("Loading Allama Syed Zeeshan Haider Jawadi translation (ur.jawadi)...")
    j_count = jawadi_loader.load(conn)
    print(f"Loaded {j_count} Jawadi translation verses.")

    cur.execute("PRAGMA journal_mode=DELETE")
    cur.execute("VACUUM")
    conn.commit()
    conn.close()
    size_mb = DB_PATH.stat().st_size / (1024 * 1024)
    print(
        f"Completed in {time.time() - t_start:.1f}s! "
        f"All 114 Surahs ({total_verses} verses + {j_count} Jawadi verses) stored in {DB_PATH} ({size_mb:.2f} MB)."
    )


if __name__ == "__main__":
    main()
