#!/usr/bin/env python3
"""
Scrapes Surah Al-Fatihah from:
- Balagh ul Quran (balaghulquran.com)
- Tafseer e Namoona (tafseerenamoona.net)

Stores clean UTF-8 relational data into SQLite (quran_shia.db).
"""
import sqlite3
import urllib.request
import re
import html
from pathlib import Path

DB_PATH = Path(__file__).parent / "quran_shia.db"

def init_db(db_path=DB_PATH):
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("DROP TABLE IF EXISTS surahs")
    cur.execute("DROP TABLE IF EXISTS verses")
    cur.execute("""
    CREATE TABLE surahs (
        id INTEGER PRIMARY KEY,
        name_ar TEXT,
        name_en TEXT,
        ayah_count INTEGER
    )
    """)
    cur.execute("""
    CREATE TABLE verses (
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
    conn.commit()
    return conn

def fetch_balagh(surah=1):
    url = f"https://www.balaghulquran.com/index.php?sno={surah}"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        content = resp.read().decode("utf-8", errors="replace")

    blocks = re.split(r'<div class="row mb-lg-6" id="(\d{6})">', content)
    results = {}
    for i in range(1, len(blocks), 2):
        vid = blocks[i]
        chunk = blocks[i + 1].split("<footer")[0]
        ar_m = re.search(r'<p[^>]*class="[^"]*txtArabicQuran[^"]*"[^>]*>(.*?)</p>', chunk, re.S)
        ur_m = re.search(r'<p[^>]*class="[^"]*txtUrduQuran\b[^"]*"[^>]*>(.*?)</p>', chunk, re.S)
        notes = re.findall(r'<p[^>]*class="[^"]*txtUrdu fu-medium-lh[^"]*"[^>]*>(.*?)</p>', chunk, re.S)

        clean = lambda s: html.unescape(re.sub(r'<[^>]+>', '', s or '')).strip()
        ayah_num = int(vid[3:])
        results[ayah_num] = {
            "arabic": clean(ar_m.group(1)) if ar_m else "",
            "trans_balagh": clean(ur_m.group(1)) if ur_m else "",
            "footnotes": "\n".join([clean(n) for n in notes if clean(n)])
        }
    return results

def fetch_namoona(surah=1):
    url = f"https://www.tafseerenamoona.net/surahs/{surah}"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        page = resp.read().decode("utf-8", errors="replace")

    safdars = re.findall(r'translation_safdar_najfi\\":\\"(.*?)\\"', page)
    yusufs = re.findall(r'translation_en\\":\\"(.*?)\\"', page)

    results = {}
    for i, s in enumerate(safdars):
        ayah_num = i + 1
        results[ayah_num] = {
            "trans_namoona": html.unescape(s.strip()),
            "trans_en": html.unescape(yusufs[i].strip()) if i < len(yusufs) else ""
        }
    return results

def fetch_balagh_tafseer(surah=1, ayah=1):
    ano = f"{surah:03d}{ayah:03d}"
    url = f"https://www.balaghulquran.com/tafseer.php?sno={surah}&ano={ano}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=20) as resp:
            content = resp.read().decode("utf-8", errors="replace")
        paras = re.findall(r'<p class="lead fu-medium">(.*?)</p>', content, re.S)
        clean = lambda s: html.unescape(re.sub(r'<[^>]+>', '', s or '')).strip()
        return "\n\n".join([clean(p) for p in paras if clean(p)])
    except Exception as e:
        return ""

def main():
    print("Re-initializing database...")
    conn = init_db()
    cur = conn.cursor()

    cur.execute("INSERT OR REPLACE INTO surahs (id, name_ar, name_en, ayah_count) VALUES (1, 'الفاتحة', 'Al-Fatihah', 7)")
    conn.commit()

    print("Fetching Balagh ul Quran data...")
    balagh_data = fetch_balagh(surah=1)

    print("Fetching Tafseer e Namoona data...")
    namoona_data = fetch_namoona(surah=1)

    print("Fetching Tafseer al-Kauthar for Surah 1:1...")
    kauthar_1_1 = fetch_balagh_tafseer(surah=1, ayah=1)

    print("Populating verses table...")
    for a in range(1, 8):
        b = balagh_data.get(a, {})
        n = namoona_data.get(a, {})
        k = kauthar_1_1 if a == 1 else ""
        cur.execute("""
        INSERT INTO verses 
        (surah, ayah, verse_key, arabic, trans_balagh, trans_namoona, trans_en, footnotes_balagh, tafseer_kauthar, tafseer_namoona)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            1, a, f"1:{a}",
            b.get("arabic", ""),
            b.get("trans_balagh", ""),
            n.get("trans_namoona", ""),
            n.get("trans_en", ""),
            b.get("footnotes", ""),
            k,
            ""
        ))
    conn.commit()
    print("Database built successfully at:", DB_PATH)

if __name__ == "__main__":
    main()
