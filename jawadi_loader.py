#!/usr/bin/env python3
"""
Loader and validator for:
1. Allama Syed Zeeshan Haider Jawadi's Urdu Quran translation (data/tanzil/ur.jawadi.txt)
2. Tanzil Simple Arabic Quran Text v1.1 (data/tanzil/quran-simple.sql)

Licensing & Attribution:
- Jawadi Translation: Tanzil.net (https://tanzil.net/trans/ur.jawadi), CC BY-NC-ND 3.0
- Arabic Quran Text: Tanzil Project (https://tanzil.net), CC BY 3.0
- Verbatim text only; no modifications allowed.
"""
import re
import sqlite3
from pathlib import Path

BASE_DIR = Path(__file__).parent
DB_PATH = BASE_DIR / "quran_shia.db"
DATA_PATH = BASE_DIR / "data" / "tanzil" / "ur.jawadi.txt"
ARABIC_SQL_PATH = BASE_DIR / "data" / "tanzil" / "quran-simple.sql"

ATTRIBUTION = {
    "id": "ur.jawadi",
    "name": "علامہ جوادی",
    "translator": "Syed Zeeshan Haider Jawadi",
    "language": "ur",
    "source": "Tanzil.net",
    "source_url": "https://tanzil.net/trans/ur.jawadi",
    "terms_url": "https://tanzil.net/trans/",
    "license": "CC BY-NC-ND 3.0 (Non-commercial only; verbatim text with attribution to Tanzil.net)",
}

ARABIC_ATTRIBUTION = {
    "id": "quran-simple",
    "name": "Tanzil Quran Text (Simple, Version 1.1)",
    "source": "Tanzil Project",
    "source_url": "https://tanzil.net",
    "updates_url": "http://tanzil.net/updates/",
    "license": "Creative Commons Attribution 3.0 (Verbatim copy; changing text is not allowed)",
}

AYAH_COUNTS = {
    1: 7, 2: 286, 3: 200, 4: 176, 5: 120, 6: 165, 7: 206, 8: 75, 9: 129, 10: 109,
    11: 123, 12: 111, 13: 43, 14: 52, 15: 99, 16: 128, 17: 111, 18: 110, 19: 98, 20: 135,
    21: 112, 22: 78, 23: 118, 24: 64, 25: 77, 26: 227, 27: 93, 28: 88, 29: 69, 30: 60,
    31: 34, 32: 30, 33: 73, 34: 54, 35: 45, 36: 83, 37: 182, 38: 88, 39: 75, 40: 85,
    41: 54, 42: 53, 43: 89, 44: 59, 45: 37, 46: 35, 47: 38, 48: 29, 49: 18, 50: 45,
    51: 60, 52: 49, 53: 62, 54: 55, 55: 78, 56: 96, 57: 29, 58: 22, 59: 24, 60: 13,
    61: 14, 62: 11, 63: 11, 64: 18, 65: 12, 66: 12, 67: 30, 68: 52, 69: 52, 70: 44,
    71: 28, 72: 28, 73: 20, 74: 56, 75: 40, 76: 31, 77: 50, 78: 40, 79: 46, 80: 42,
    81: 29, 82: 19, 83: 36, 84: 25, 85: 22, 86: 17, 87: 19, 88: 26, 89: 30, 90: 20,
    91: 15, 92: 21, 93: 11, 94: 8, 95: 8, 96: 19, 97: 5, 98: 8, 99: 8, 100: 11,
    101: 11, 102: 8, 103: 3, 104: 9, 105: 5, 106: 4, 107: 7, 108: 3, 109: 6, 110: 3,
    111: 5, 112: 4, 113: 5, 114: 6,
}

TOTAL_AYAHS = sum(AYAH_COUNTS.values())  # 6236


def validate_surah_ayah(surah, ayah=None):
    """Validates surah (1-114) and optional ayah against canonical counts."""
    if not isinstance(surah, int) or surah < 1 or surah > 114:
        raise ValueError(f"Invalid surah {surah}: must be between 1 and 114.")
    max_ayah = AYAH_COUNTS[surah]
    if ayah is not None:
        if not isinstance(ayah, int) or ayah < 1 or ayah > max_ayah:
            raise ValueError(
                f"Invalid ayah {ayah} for surah {surah}: must be between 1 and {max_ayah}."
            )


def parse_and_validate(data_path=DATA_PATH):
    """
    Parses data/tanzil/ur.jawadi.txt verbatim and validates that all 6,236 ayahs
    across surahs 1..114 are present.
    """
    path = Path(data_path)
    if not path.exists():
        raise FileNotFoundError(f"Tanzil Jawadi translation file not found: {path}")

    raw_content = path.read_text(encoding="utf-8")
    rows = []
    seen = set()

    for line_no, line in enumerate(raw_content.splitlines(), start=1):
        if not line or line.startswith("#"):
            continue
        parts = line.split("|", 2)
        if len(parts) != 3:
            raise ValueError(f"Malformed line {line_no} in {path}: {line!r}")
        try:
            surah = int(parts[0])
            ayah = int(parts[1])
        except ValueError as exc:
            raise ValueError(f"Invalid surah/ayah numbers at line {line_no}: {line!r}") from exc

        text = parts[2]
        if not text:
            raise ValueError(f"Empty translation text at {surah}:{ayah} (line {line_no})")

        validate_surah_ayah(surah, ayah)
        verse_key = f"{surah}:{ayah}"
        if verse_key in seen:
            raise ValueError(f"Duplicate verse {verse_key} at line {line_no}")
        seen.add(verse_key)
        rows.append((verse_key, surah, ayah, text))

    if len(rows) != TOTAL_AYAHS:
        raise ValueError(f"Expected {TOTAL_AYAHS} ayahs in {path}, found {len(rows)}")

    for s, count in AYAH_COUNTS.items():
        for a in range(1, count + 1):
            vk = f"{s}:{a}"
            if vk not in seen:
                raise ValueError(f"Missing expected verse {vk} in {path}")

    return rows


def parse_and_validate_arabic_sql(sql_path=ARABIC_SQL_PATH):
    """
    Parses data/tanzil/quran-simple.sql verbatim and validates that all 6,236 Arabic
    verses across surahs 1..114 are present without modification.
    """
    path = Path(sql_path)
    if not path.exists():
        raise FileNotFoundError(f"Tanzil Arabic SQL file not found: {path}")

    raw_content = path.read_text(encoding="utf-8")
    rows = []
    seen = set()

    for m in re.finditer(r"\((\d+),\s*(\d+),\s*(\d+),\s*'([^']*)'\)", raw_content):
        surah = int(m.group(2))
        ayah = int(m.group(3))
        text = m.group(4)
        if not text:
            raise ValueError(f"Empty Arabic text at {surah}:{ayah}")
        validate_surah_ayah(surah, ayah)
        verse_key = f"{surah}:{ayah}"
        if verse_key in seen:
            raise ValueError(f"Duplicate Arabic verse {verse_key} in {path}")
        seen.add(verse_key)
        rows.append((verse_key, surah, ayah, text))

    if len(rows) != TOTAL_AYAHS:
        raise ValueError(f"Expected {TOTAL_AYAHS} Arabic ayahs in {path}, found {len(rows)}")

    for s, count in AYAH_COUNTS.items():
        for a in range(1, count + 1):
            vk = f"{s}:{a}"
            if vk not in seen:
                raise ValueError(f"Missing expected Arabic verse {vk} in {path}")

    return rows


def load_arabic(conn=None, db_path=DB_PATH, sql_path=ARABIC_SQL_PATH):
    """
    Validates quran-simple.sql and (re)creates the quran_text_tanzil table.
    Returns the number of loaded rows (6236).
    """
    if not Path(sql_path).exists():
        return 0
    rows = parse_and_validate_arabic_sql(sql_path)
    own_conn = False
    if conn is None:
        conn = sqlite3.connect(db_path)
        own_conn = True

    try:
        cur = conn.cursor()
        cur.execute("DROP TABLE IF EXISTS quran_text_tanzil")
        cur.execute(
            """
            CREATE TABLE quran_text_tanzil (
                verse_key TEXT PRIMARY KEY,
                surah INTEGER NOT NULL,
                ayah INTEGER NOT NULL,
                text TEXT NOT NULL
            )
            """
        )
        cur.execute(
            "CREATE INDEX idx_quran_text_tanzil_surah_ayah ON quran_text_tanzil(surah, ayah)"
        )
        cur.executemany(
            "INSERT INTO quran_text_tanzil (verse_key, surah, ayah, text) VALUES (?, ?, ?, ?)",
            rows,
        )
        conn.commit()
        return len(rows)
    finally:
        if own_conn:
            conn.close()


def load(conn=None, db_path=DB_PATH, data_path=DATA_PATH):
    """
    Validates ur.jawadi.txt (and quran-simple.sql if present) and (re)creates
    the translation_jawadi (and quran_text_tanzil) tables.
    Returns the number of loaded Jawadi rows (6236).
    """
    rows = parse_and_validate(data_path)
    own_conn = False
    if conn is None:
        conn = sqlite3.connect(db_path)
        own_conn = True

    try:
        cur = conn.cursor()
        cur.execute("DROP TABLE IF EXISTS translation_jawadi")
        cur.execute(
            """
            CREATE TABLE translation_jawadi (
                verse_key TEXT PRIMARY KEY,
                surah INTEGER NOT NULL,
                ayah INTEGER NOT NULL,
                text TEXT NOT NULL
            )
            """
        )
        cur.execute(
            "CREATE INDEX idx_translation_jawadi_surah_ayah ON translation_jawadi(surah, ayah)"
        )
        cur.executemany(
            "INSERT INTO translation_jawadi (verse_key, surah, ayah, text) VALUES (?, ?, ?, ?)",
            rows,
        )
        conn.commit()
        load_arabic(conn=conn, db_path=db_path)
        return len(rows)
    finally:
        if own_conn:
            conn.close()


def ensure_loaded(conn=None, db_path=DB_PATH, data_path=DATA_PATH):
    """
    Ensures translation_jawadi and quran_text_tanzil exist and contain all 6,236 verses;
    loads from data/tanzil/ if missing or incomplete.
    """
    own_conn = False
    if conn is None:
        conn = sqlite3.connect(db_path)
        own_conn = True

    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='quran_text_tanzil'"
        )
        has_ar = False
        if cur.fetchone():
            cur.execute("SELECT COUNT(*) FROM quran_text_tanzil")
            has_ar = cur.fetchone()[0] == TOTAL_AYAHS
        if not has_ar and ARABIC_SQL_PATH.exists():
            load_arabic(conn=conn, db_path=db_path)

        cur.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='translation_jawadi'"
        )
        if cur.fetchone():
            cur.execute("SELECT COUNT(*) FROM translation_jawadi")
            count = cur.fetchone()[0]
            if count == TOTAL_AYAHS:
                return count
        return load(conn=conn, db_path=db_path, data_path=data_path)
    finally:
        if own_conn:
            conn.close()


if __name__ == "__main__":
    loaded = load()
    print(f"Loaded {loaded} verses into translation_jawadi and quran_text_tanzil.")
