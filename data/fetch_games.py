#!/usr/bin/env python3
"""Fetch retro game lists from Wikipedia and write client/games.json.

Run once: python3 data/fetch_games.py
Raw API responses are cached in data/cache/ for 7 days.
"""

from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from html.parser import HTMLParser
from pathlib import Path

ROOT_DIR  = Path(__file__).resolve().parent.parent
CLIENT_DIR = ROOT_DIR / "client"
CACHE_DIR  = Path(__file__).resolve().parent / "cache"
CACHE_TTL_DAYS = 7

CONSOLES = [
    {"id": "atari2600",  "label": "Atari 2600",    "articles": ["List of Atari 2600 games"]},
    {"id": "atari7800",  "label": "Atari 7800",     "articles": ["List of Atari 7800 games"]},
    {"id": "nes",        "label": "NES",            "articles": ["List of Nintendo Entertainment System games"]},
    {"id": "sms",        "label": "SMS",            "articles": ["List of Sega Master System games"]},
    {"id": "tg16",       "label": "TurboGrafx-16",  "articles": ["List of TurboGrafx-16 games"]},
    {"id": "gb",         "label": "Game Boy",       "articles": ["List of Game Boy games"]},
    {"id": "genesis",    "label": "Genesis",        "articles": ["List of Sega Genesis games"]},
    {"id": "snes",       "label": "SNES",           "articles": ["List of Super Nintendo Entertainment System games"]},
    {"id": "neogeo",     "label": "Neo Geo",        "articles": ["List of Neo Geo games"]},
    {"id": "segacd",     "label": "Sega CD",        "articles": ["List of Sega CD games"]},
    {"id": "3do",        "label": "3DO",            "articles": ["List of 3DO Interactive Multiplayer games"]},
    {"id": "32x",        "label": "32X",            "articles": ["List of Sega 32X games"]},
    {"id": "ps1",        "label": "PlayStation",    "articles": ["List of PlayStation games (A–L)", "List of PlayStation games (M–Z)"]},
    {"id": "saturn",     "label": "Saturn",         "articles": ["List of Sega Saturn games"]},
    {"id": "n64",        "label": "N64",            "articles": ["List of Nintendo 64 games"]},
    {"id": "gbc",        "label": "Game Boy Color", "articles": ["List of Game Boy Color games"]},
    {"id": "dreamcast",  "label": "Dreamcast",      "articles": ["List of Dreamcast games"]},
]

DATE_FORMATS = [
    "%B %d, %Y",
    "%B %Y",
    "%Y-%m-%d",
    "%Y",
]

CUTOFF = "2001-01-01"

# Ordered by preference: specific region names first, then generic date labels
NA_HEADER_PATTERNS = [
    "north america",
    "na",
    "us release",
    "us",
    "release date",
    "release",
    "released",
    "year",           # Atari 2600 uses "Year" as the single date column
]

JP_HEADER_PATTERNS = [
    "japan",
    "jp",
    "jpn",
]

PAL_HEADER_PATTERNS = [
    "pal region",
    "pal/au",
    "pal",
    "europe",
    "eu",
    "aus",
    "australia",
]

REGION_COLUMN_MAP = [
    ("NA", NA_HEADER_PATTERNS),
    ("JP", JP_HEADER_PATTERNS),
    ("PAL", PAL_HEADER_PATTERNS),
]

TITLE_HEADER_PATTERNS = [
    "title",
    "name",
    "game",
]

TRAILING_HEADER_PATTERNS = [
    "ref",
    "note",
    "notes",
    "comment",
    "references",
    "source",
]

# Region codes used in sub-header rows
REGION_WORDS = frozenset([
    "jp", "japan", "na", "north america", "pal", "pal region",
    "eu", "europe", "other", "br", "brazil", "kr", "korea",
    "tw", "taiwan", "au", "australia",
])


def slugify(text: str) -> str:
    text = text.lower()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_]+", "-", text)
    text = re.sub(r"-+", "-", text)
    return text.strip("-")


def fetch_article_html(article_title: str, cache_key: str) -> str:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_file = CACHE_DIR / f"{cache_key}.json"

    if cache_file.exists():
        age = datetime.now() - datetime.fromtimestamp(cache_file.stat().st_mtime)
        if age < timedelta(days=CACHE_TTL_DAYS):
            data = json.loads(cache_file.read_text(encoding="utf-8"))
            return data.get("html", "")

    params = urllib.parse.urlencode({
        "action": "parse",
        "page": article_title,
        "prop": "text",
        "format": "json",
        "redirects": "1",
    })
    url = f"https://en.wikipedia.org/w/api.php?{params}"
    req = urllib.request.Request(url, headers={"User-Agent": "chronoGamer/1.0 (data fetcher)"})

    print(f"  Fetching: {article_title}")
    for attempt in range(5):
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
            break
        except urllib.error.HTTPError as e:
            if e.code == 429:
                wait = 10 * (2 ** attempt)
                print(f"  Rate limited (429), waiting {wait}s…")
                time.sleep(wait)
            else:
                raise
    else:
        raise RuntimeError(f"Failed to fetch {article_title} after 5 retries")

    html = payload.get("parse", {}).get("text", {}).get("*", "")
    cache_file.write_text(json.dumps({"html": html}), encoding="utf-8")
    time.sleep(1.5)
    return html


def parse_date(text: str) -> str | None:
    text = re.sub(r"\[.*?\]", "", text).strip()
    text = re.sub(r"\s+", " ", text)
    if not text or text.lower() in ("unreleased", "n/a", "tba", "tbd", "—", "-", "?"):
        return None

    patterns = [
        r"\b([A-Z][a-z]+ \d{1,2},? \d{4})\b",
        r"\b([A-Z][a-z]+ \d{4})\b",
        r"\b(\d{4}-\d{2}-\d{2})\b",
        r"\b(\d{4})\b",
    ]
    for pat in patterns:
        m = re.search(pat, text)
        if m:
            candidate = m.group(1).replace(",", "").strip()
            for fmt in DATE_FORMATS:
                try:
                    dt = datetime.strptime(candidate, fmt)
                    if fmt in ("%B %Y", "%Y"):
                        return dt.strftime("%Y-%m-01")
                    return dt.strftime("%Y-%m-%d")
                except ValueError:
                    continue
    return None


class TableParser(HTMLParser):
    """Extracts wikitable rows from rendered Wikipedia HTML."""

    def __init__(self) -> None:
        super().__init__()
        self.tables: list[list[list[str]]] = []
        self._in_table = 0       # nesting depth
        self._in_wikitable = False
        self._current_table: list[list[str]] = []
        self._current_row: list[str] = []
        self._current_cell: list[str] = []
        self._in_cell = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr_dict = dict(attrs)

        if tag == "table":
            self._in_table += 1
            if self._in_table == 1:
                classes = attr_dict.get("class") or ""
                self._in_wikitable = "wikitable" in classes
                if self._in_wikitable:
                    self._current_table = []
            return

        if not self._in_wikitable or self._in_table > 1:
            return

        if tag in ("th", "td"):
            self._in_cell = True
            self._current_cell = []

    def handle_endtag(self, tag: str) -> None:
        if tag == "table":
            if self._in_wikitable and self._in_table == 1:
                if self._current_row:
                    self._current_table.append(self._current_row)
                if self._current_table:
                    self.tables.append(self._current_table)
                self._current_table = []
                self._current_row = []
                self._in_wikitable = False
            self._in_table = max(0, self._in_table - 1)
            return

        if not self._in_wikitable or self._in_table > 1:
            return

        if tag in ("th", "td") and self._in_cell:
            self._current_row.append("".join(self._current_cell).strip())
            self._in_cell = False
            self._current_cell = []

        elif tag == "tr":
            if self._current_row:
                self._current_table.append(self._current_row)
            self._current_row = []

    def handle_data(self, data: str) -> None:
        if self._in_cell and self._in_table == 1:
            self._current_cell.append(data)

    def handle_entityref(self, name: str) -> None:
        entities = {"amp": "&", "lt": "<", "gt": ">", "quot": '"', "nbsp": " "}
        if self._in_cell and self._in_table == 1:
            self._current_cell.append(entities.get(name, ""))

    def handle_charref(self, name: str) -> None:
        if self._in_cell and self._in_table == 1:
            try:
                ch = chr(int(name[1:], 16) if name.startswith("x") else int(name))
                self._current_cell.append(ch)
            except (ValueError, OverflowError):
                pass


def clean_header(text: str) -> str:
    """Strip footnote markers and whitespace from header text."""
    return re.sub(r"\[.*?\]|\s+", " ", text).lower().strip()


def is_subheader_row(row: list[str]) -> bool:
    """True if every non-empty cell in the row is a known region code."""
    cells = [c.strip() for c in row if c.strip()]
    if not cells:
        return False
    return all(clean_header(c) in REGION_WORDS for c in cells)


def find_col_index(headers: list[str], patterns: list[str]) -> int:
    for i, h in enumerate(headers):
        norm = clean_header(h)
        for pat in patterns:
            if pat in norm:
                return i
    return -1


def count_trailing_cols(main_header: list[str]) -> int:
    count = 0
    for h in reversed(main_header):
        norm = clean_header(h)
        if any(pat in norm for pat in TRAILING_HEADER_PATTERNS):
            count += 1
        else:
            break
    return count


def resolve_region_columns(table_rows: list[list[str]]) -> tuple[int, dict[str, int]]:
    """Return (title_col, {region: col_index}).  title_col=-1 on failure."""
    if not table_rows:
        return -1, {}

    main_header = table_rows[0]
    title_col = find_col_index(main_header, TITLE_HEADER_PATTERNS)
    if title_col == -1:
        return -1, {}

    region_cols: dict[str, int] = {}

    sub_row = table_rows[1] if len(table_rows) > 1 else []
    if is_subheader_row(sub_row):
        trailing = count_trailing_cols(main_header)
        data_row = next(
            (r for r in table_rows[2:] if len(r) > len(sub_row) and not is_subheader_row(r)),
            None,
        )
        if data_row is None:
            return title_col, {}

        sub_start = len(data_row) - len(sub_row) - trailing
        for region, patterns in REGION_COLUMN_MAP:
            pos = find_col_index(sub_row, patterns)
            if pos != -1:
                region_cols[region] = sub_start + pos
    else:
        # Single-level header: look for any region columns, fall back to generic date → NA
        for region, patterns in REGION_COLUMN_MAP:
            col = find_col_index(main_header, patterns)
            if col != -1:
                region_cols[region] = col
        if not region_cols:
            # Generic single date column — treat as NA
            col = find_col_index(main_header, NA_HEADER_PATTERNS)
            if col != -1:
                region_cols["NA"] = col

    return title_col, region_cols


def parse_games_from_html(html: str, console_label: str) -> list[dict]:
    parser = TableParser()
    parser.feed(html)

    games = []
    for table in parser.tables:
        if len(table) < 3:
            continue

        title_col, region_cols = resolve_region_columns(table)
        if title_col == -1 or not region_cols:
            continue

        data_start = 1
        while data_start < len(table) and (
            data_start == 0 or is_subheader_row(table[data_start])
        ):
            data_start += 1

        max_col = max(title_col, *region_cols.values())
        for row in table[data_start:]:
            if len(row) <= max_col:
                continue

            raw_title = row[title_col].strip()
            if not raw_title:
                continue

            title = re.sub(r"\[.*?\]", "", raw_title).strip()
            if not title or clean_header(title) in ("title", "name", "game"):
                continue

            # Extract a valid date per region; collect which regions are present
            region_dates: dict[str, str] = {}
            for region, col in region_cols.items():
                if col < len(row):
                    d = parse_date(row[col].strip())
                    if d and d < CUTOFF:
                        region_dates[region] = d

            if not region_dates:
                continue

            # Primary release date: NA first, then JP, then PAL
            release_date = (
                region_dates.get("NA")
                or region_dates.get("JP")
                or next(iter(region_dates.values()))
            )

            games.append({
                "title":       title,
                "console":     console_label,
                "releaseDate": release_date,
                "regions":     sorted(region_dates.keys()),
                "coverUrl":    None,
            })

    return games


def make_id(console_id: str, title: str, seen: set[str]) -> str:
    base = f"{console_id}-{slugify(title)}"
    candidate = base
    n = 1
    while candidate in seen:
        candidate = f"{base}-{n}"
        n += 1
    seen.add(candidate)
    return candidate


def main() -> None:
    all_games: list[dict] = []
    seen_ids: set[str] = set()

    for console in CONSOLES:
        print(f"\n[{console['label']}]")
        console_games: list[dict] = []

        for i, article in enumerate(console["articles"]):
            cache_key = f"{console['id']}-{i}"
            html = fetch_article_html(article, cache_key)
            found = parse_games_from_html(html, console["label"])
            console_games.extend(found)
            print(f"  Parsed {len(found)} games from '{article}'")

        # Deduplicate within console by title (case-insensitive)
        seen_titles: set[str] = set()
        unique: list[dict] = []
        for g in console_games:
            key = g["title"].lower()
            if key not in seen_titles:
                seen_titles.add(key)
                unique.append(g)

        for g in unique:
            g["id"] = make_id(console["id"], g["title"], seen_ids)

        all_games.extend(unique)
        print(f"  Total after dedup: {len(unique)}")

    all_games.sort(key=lambda g: (g["releaseDate"], g["title"].lower()))

    output_path = CLIENT_DIR / "games.json"
    output_path.write_text(json.dumps(all_games, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nWrote {len(all_games)} games to {output_path}")


if __name__ == "__main__":
    main()
