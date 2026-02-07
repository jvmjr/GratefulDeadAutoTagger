#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Discrepancy Scanner for Grateful Dead / Jerry Garcia show archives.

Scans show folders to find discrepancies between:
- JerryBase.db setlist/venue data
- Accompanying .txt files (in the folder, parent dir, or adjacent txt/text folders)
- Multiple txt files for the same show (cross-referencing)

READ-ONLY: Does not modify txt files, the database, FLAC tags, or folder names.

Usage:
    python discrepancy_scanner.py /path/to/shows [options]

Output:
    CSV file with one row per discrepancy found.
"""

import argparse
import csv
import re
import sys
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Tuple, Set

from album_tagger import AlbumTagger
from song_matcher import SongMatcher
from config import DEFAULT_DB_PATH, SEGUE_MARKERS, is_extra_track


# ──────────────────────────────────────────────────────────────────────────────
# Constants
# ──────────────────────────────────────────────────────────────────────────────

# Simple substring patterns for technical txt files
_SKIP_SUBSTR = [
    'fingerprint', 'checksum', 'shntool', 'shninfo',
]

# Patterns that must appear as whole "tokens" (not as a substring of a longer
# word).  E.g. 'flac24' should match "show.flac24.txt" but NOT
# "show.flac2496.txt".  We compile them with word-boundary anchors.
_SKIP_WORD_RES = [
    re.compile(r'\b' + p + r'\b', re.IGNORECASE)
    for p in ('ffp', 'md5', 'sha256', 'sha1', 'flac16', 'flac24')
]

# Regex for detecting set header lines in txt files
SET_HEADER_RE = re.compile(
    r'^\s*(?:'
    r'set\s*[#:]?\s*(\d+|[ivxIVX]+)'       # "Set 1", "Set I", "Set #2"
    r'|'
    r'(first|second|third)\s+set'            # "First Set", "Second Set"
    r'|'
    r'(encore)\s*:?\s*(\d*)'                 # "Encore", "Encore:", "Encore 1"
    r'|'
    r'e\s*:\s*$'                              # "E:" on its own line
    r')\s*:?\s*$',
    re.IGNORECASE
)

ROMAN_MAP = {'i': 1, 'ii': 2, 'iii': 3, 'iv': 4, 'v': 5}
ORDINAL_MAP = {'first': 1, 'second': 2, 'third': 3}

# Band name substrings to filter from header lines when extracting venue
BAND_NAME_PATTERNS = [
    'grateful dead', 'jerry garcia', 'garcia', 'jgb',
    'jerry garcia band', 'legion of mary', 'reconstruction',
    'old and in the way', 'robert hunter', 'bob weir',
    'mickey hart', 'phil lesh', 'merl saunders',
]

# Regex to detect date-like strings in header lines
DATE_PATTERN = re.compile(
    r'\b(?:'
    r'\d{4}[-/]\d{1,2}[-/]\d{1,2}'                              # 1977-05-08
    r'|\d{1,2}[-/]\d{1,2}[-/]\d{2,4}'                           # 05/08/77
    r'|(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\w*'
    r'\s+\d{1,2},?\s+\d{4}'                                      # May 8, 1977
    r')\b',
    re.IGNORECASE
)


# ──────────────────────────────────────────────────────────────────────────────
# Data Classes
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class TxtSongEntry:
    """A single song entry parsed from a txt file."""
    title: str              # Raw song title from txt (after cleaning artifacts)
    set_number: int         # Sequential set number (1, 2, 3, ...)
    set_is_encore: bool     # Whether this set was labeled "Encore"
    position: int           # 1-based position within its set
    has_segue: bool         # Segue marker detected on this line
    is_extra: bool          # Recognized as an extra/non-song track


@dataclass
class TxtSetlistData:
    """Structured data parsed from a single txt file."""
    file_path: Path
    venue_text: Optional[str]                           # Venue/location from header
    songs: List[TxtSongEntry] = field(default_factory=list)
    raw_header_lines: List[str] = field(default_factory=list)


@dataclass
class Discrepancy:
    """A single discrepancy row for the CSV report."""
    folder_name: str
    date: str
    txt_files_found: str
    discrepancy_type: str
    source_a: str
    source_b: str
    details: str


# ──────────────────────────────────────────────────────────────────────────────
# Read-Only Song Matcher (never writes corrections to disk)
# ──────────────────────────────────────────────────────────────────────────────

class ReadOnlySongMatcher(SongMatcher):
    """SongMatcher that caches corrections in memory only."""

    def add_correction(self, original_lower: str, canonical: str,
                       source: str = 'manual'):
        """Cache in memory but never persist to corrections_map.csv."""
        self.corrections_cache[original_lower] = canonical


# ──────────────────────────────────────────────────────────────────────────────
# Enhanced Txt File Finder
# ──────────────────────────────────────────────────────────────────────────────

def is_technical_txt(filename: str) -> bool:
    """Return True if *filename* looks like a fingerprint / checksum file."""
    name_lower = filename.lower()

    # Check for file extensions that are always technical
    if name_lower.endswith(('.ffp', '.md5', '.sha', '.sha1', '.sha256')):
        return True

    # Substring checks (long, unambiguous strings)
    if any(p in name_lower for p in _SKIP_SUBSTR):
        return True

    # Word-boundary checks (short tokens that could be substrings of
    # legitimate content, e.g. "flac24" vs "flac2496")
    if any(pat.search(name_lower) for pat in _SKIP_WORD_RES):
        return True

    return False


def find_all_txt_files(folder_path: Path, date_str: str,
                       shnid: Optional[str]) -> List[Path]:
    """
    Find ALL matching, non-technical txt files for a show across:

    1. The show folder itself  (include every non-technical .txt)
    2. The parent folder       (match by date + SHNID in filename)
    3. Adjacent sibling dirs whose name contains "txt" or "text"
       (match by date + SHNID in filename)

    Returns a deduplicated list of Path objects.
    """
    found: List[Path] = []

    # --- 1. Inside the show folder (all non-technical txt) ---
    if folder_path.is_dir():
        for txt in folder_path.glob('*.txt'):
            if not is_technical_txt(txt.name):
                found.append(txt)

    # Build date variants for matching in parent / sibling folders
    date_variants: List[str] = []
    if date_str:
        date_variants.append(date_str)                     # "1977-05-08"
        if len(date_str) == 10:                             # YYYY-MM-DD
            date_variants.append(date_str[2:])              # "77-05-08"

    parent = folder_path.parent

    # --- 2. Parent folder ---
    if parent.exists() and parent != folder_path:
        for txt in parent.glob('*.txt'):
            if is_technical_txt(txt.name):
                continue
            if _matches_show(txt.name, date_variants, shnid):
                found.append(txt)

    # --- 3. Sibling dirs with "txt" or "text" in name ---
    if parent.exists():
        for sibling in parent.iterdir():
            if not sibling.is_dir() or sibling.resolve() == folder_path.resolve():
                continue
            sib_lower = sibling.name.lower()
            if 'txt' in sib_lower or 'text' in sib_lower:
                for txt in sibling.glob('*.txt'):
                    if is_technical_txt(txt.name):
                        continue
                    if _matches_show(txt.name, date_variants, shnid):
                        found.append(txt)

    # Deduplicate by resolved path
    seen: Set[Path] = set()
    unique: List[Path] = []
    for f in found:
        resolved = f.resolve()
        if resolved not in seen:
            seen.add(resolved)
            unique.append(f)

    return unique


def _matches_show(filename: str, date_variants: List[str],
                  shnid: Optional[str]) -> bool:
    """True if *filename* contains the show date AND the SHNID (when known)."""
    name_lower = filename.lower()

    if not any(d.lower() in name_lower for d in date_variants):
        return False                       # Must contain the date

    if shnid and shnid not in filename:    # SHNID is numeric, case-insensitive OK
        return False

    return True


# ──────────────────────────────────────────────────────────────────────────────
# Enhanced Txt File Parser  (set-aware)
# ──────────────────────────────────────────────────────────────────────────────

class SetlistTxtParser:
    """
    Parse a show txt file into structured setlist data:
    songs grouped by set, venue info from the header, segue markers.
    """

    # Patterns that extract a song title from a numbered track line.
    # Order matters: more specific patterns first.
    TRACK_LINE_PATTERNS = [
        # "d1t01 - Song Name"
        re.compile(r'^d\d+t\d+\s*[-–—]\s*(.+)', re.IGNORECASE),
        # "01. Song Name"  or  "01) Song Name"  or  "01 - Song Name"
        re.compile(r'^\d{1,2}\s*[.)\-–—]\s*(.+)'),
        # "01   Song Name"  (number + 2+ spaces)
        re.compile(r'^\d{1,2}\s{2,}(\S.+)'),
        # "01 Song Name"  (number + single space + letter)
        re.compile(r'^\d{1,2}\s+([A-Za-z/].+)'),
        # "Track 01: Song Name"
        re.compile(r'^track\s*\d+\s*[:\-–—]\s*(.+)', re.IGNORECASE),
        # "t01 Song Name"
        re.compile(r'^t\d+\s+(.+)', re.IGNORECASE),
    ]

    # Lines to skip unconditionally (metadata, technical info, etc.)
    SKIP_LINE_RES = [
        re.compile(r'^[-=~*_]{3,}'),                       # horizontal rules
        re.compile(r'^\s*$'),                                # blank
        re.compile(r'^source\s*:', re.IGNORECASE),
        re.compile(r'^taper\s*:', re.IGNORECASE),
        re.compile(r'^transfer', re.IGNORECASE),
        re.compile(r'^lineage\s*:', re.IGNORECASE),
        re.compile(r'^notes?\s*:', re.IGNORECASE),
        re.compile(r'^recorded\b', re.IGNORECASE),
        re.compile(r'^location\s*:', re.IGNORECASE),
        re.compile(r'^gen(eration)?\s*:', re.IGNORECASE),
        re.compile(r'^shn\b', re.IGNORECASE),
        re.compile(r'^flac\b', re.IGNORECASE),
        re.compile(r'^disc\s*\d', re.IGNORECASE),           # "Disc 1"
        re.compile(r'^cd\s*\d', re.IGNORECASE),             # "CD 1"
        re.compile(r'^d\d+\s*$', re.IGNORECASE),            # bare "d1"
        re.compile(r'^total\s+time', re.IGNORECASE),
        re.compile(r'^\d+:\d+:\d+'),                        # total timestamps
        re.compile(r'^runtime', re.IGNORECASE),
        re.compile(r'^archive\.org', re.IGNORECASE),
        re.compile(r'^etree\b', re.IGNORECASE),
        re.compile(r'^shnid', re.IGNORECASE),
        re.compile(r'^https?://', re.IGNORECASE),
        re.compile(r'^www\.', re.IGNORECASE),
        re.compile(r'^equipment\s*:', re.IGNORECASE),
        re.compile(r'^patch(ed)?\s*:', re.IGNORECASE),
        re.compile(r'^seeded\b', re.IGNORECASE),
        re.compile(r'^\(?\s*\d{1,3}\.\d\s*MB\s*\)?', re.IGNORECASE),  # file sizes
        # shntool / technical report lines
        re.compile(r'\.flac\b', re.IGNORECASE),             # any line with .flac
        re.compile(r'\.shn\b', re.IGNORECASE),              # any line with .shn
        re.compile(r'\.mp3\b', re.IGNORECASE),              # any line with .mp3
        re.compile(r'^[0-9a-f]{32}\s', re.IGNORECASE),      # MD5 hash lines
        re.compile(r'\*\d{2}\s', re.IGNORECASE),            # md5sum format "*01 file"
        re.compile(r'\b\d+\s+B\b'),                         # byte counts "12345 B"
        re.compile(r'\bcdr\b.*\bflac\b', re.IGNORECASE),    # shntool columns
        re.compile(r'^\*\*.+\*\*'),                          # **marker** lines
        re.compile(r'\blength\b.*\bexpanded\b.*\bsize\b', re.IGNORECASE),  # shntool header
        re.compile(r'^\(\d+\s+files?\)', re.IGNORECASE),    # "(28 files)"
        re.compile(r'^\d+\s+bit\b', re.IGNORECASE),         # "24 bit 96 kHz..."
        re.compile(r'\bbit\s+\d+\s*k[Hh]z', re.IGNORECASE), # "bit 96 kHz"
        re.compile(r'^setbreak\s*$', re.IGNORECASE),         # bare "Setbreak"
        re.compile(r'^set\s*break\s*$', re.IGNORECASE),      # bare "Set break"
        re.compile(r'^\s*\d{1,2}:\d{2}\.\d+\s+\d', re.IGNORECASE),  # shntool timing lines "1:27.960  50665004"
    ]

    # ------------------------------------------------------------------ public

    def parse(self, txt_path: Path) -> Optional[TxtSetlistData]:
        """Parse *txt_path* and return structured setlist data, or None."""
        try:
            with open(txt_path, 'r', encoding='utf-8', errors='ignore') as fh:
                content = fh.read()
        except Exception as exc:
            print(f"  Warning: Could not read {txt_path}: {exc}")
            return None

        lines = content.split('\n')

        # Locate the first set-header line
        first_set_idx = self._find_first_set_header(lines)

        if first_set_idx is None:
            # No set markers — look for the first numbered-track line instead
            first_set_idx = self._find_first_track_line(lines)

        if first_set_idx is None:
            return None            # file doesn't appear to be a setlist

        # Header = non-blank lines before the first set / track line
        header_lines = [l.strip() for l in lines[:first_set_idx] if l.strip()]

        venue_text = self._extract_venue(header_lines)
        has_set_headers = self._find_first_set_header(lines) is not None
        songs = self._parse_songs(lines, first_set_idx, has_set_headers)

        return TxtSetlistData(
            file_path=txt_path,
            venue_text=venue_text,
            songs=songs,
            raw_header_lines=header_lines,
        )

    # --------------------------------------------------------------- internal

    def _find_first_set_header(self, lines: List[str]) -> Optional[int]:
        for i, line in enumerate(lines):
            if self._parse_set_header(line.strip()) is not None:
                return i
        return None

    def _find_first_track_line(self, lines: List[str]) -> Optional[int]:
        for i, line in enumerate(lines):
            stripped = line.strip()
            for pat in self.TRACK_LINE_PATTERNS:
                if pat.match(stripped):
                    return i
        return None

    def _parse_set_header(self, line: str) -> Optional[Tuple[int, bool]]:
        """Return ``(set_number, is_encore)`` or *None*."""
        if not line:
            return None
        m = SET_HEADER_RE.match(line)
        if not m:
            return None

        set_num_str = m.group(1)        # "1" / "II" / …
        ordinal     = m.group(2)        # "first" / "second" / …
        encore      = m.group(3)        # "encore" or None

        if encore:
            return (0, True)            # 0 = placeholder, assigned later

        if ordinal:
            return (ORDINAL_MAP.get(ordinal.lower(), 1), False)

        if set_num_str:
            try:
                return (int(set_num_str), False)
            except ValueError:
                roman = set_num_str.lower()
                if roman in ROMAN_MAP:
                    return (ROMAN_MAP[roman], False)

        return None

    # ──────────────────────────────── song extraction ─────────────────────────

    def _parse_songs(self, lines: List[str], start_idx: int,
                     has_set_headers: bool) -> List[TxtSongEntry]:
        """Walk *lines* from *start_idx*, track set changes, yield songs."""
        songs: List[TxtSongEntry] = []
        current_set = 1
        current_is_encore = False
        max_non_encore_set = 0
        position_in_set = 0

        for i in range(start_idx, len(lines)):
            stripped = lines[i].strip()
            if not stripped:
                continue

            # ── check for set header ──
            hdr = self._parse_set_header(stripped)
            if hdr is not None:
                set_num, is_encore = hdr
                if is_encore:
                    current_is_encore = True
                    current_set = max(max_non_encore_set, current_set) + 1
                else:
                    current_is_encore = False
                    current_set = set_num
                    max_non_encore_set = max(max_non_encore_set, set_num)
                position_in_set = 0
                continue

            # ── skip metadata / technical lines ──
            if self._is_skip_line(stripped):
                continue

            # ── try to extract a song title ──
            title = self._extract_song_title(stripped, has_set_headers)
            if title is None:
                continue

            # Detect / strip segue markers
            has_segue = False
            for marker in [' -->', ' ->', '>>', ' >']:
                if title.rstrip().endswith(marker.strip()):
                    has_segue = True
                    title = title.rstrip()[:-len(marker.strip())].rstrip()
                    break
            if not has_segue and title.rstrip().endswith('>'):
                has_segue = True
                title = title.rstrip().rstrip('>').rstrip()

            title = self._clean_song_title(title)
            if not title:
                continue

            is_extra = is_extra_track(title)
            position_in_set += 1

            songs.append(TxtSongEntry(
                title=title,
                set_number=current_set if current_set > 0 else 1,
                set_is_encore=current_is_encore,
                position=position_in_set,
                has_segue=has_segue,
                is_extra=is_extra,
            ))

        # If no set headers were ever found, make sure everything is Set 1
        if max_non_encore_set == 0 and not current_is_encore:
            for s in songs:
                s.set_number = 1

        return songs

    def _is_skip_line(self, line: str) -> bool:
        for pat in self.SKIP_LINE_RES:
            if pat.search(line):          # search (not match) — some patterns
                return True               # are non-anchored and must scan the
        return False                      # full line (e.g. \.flac\b)

    def _extract_song_title(self, line: str,
                            has_set_headers: bool) -> Optional[str]:
        """Return the song title embedded in *line*, or *None*."""
        # Try structured (numbered) patterns first
        for pat in self.TRACK_LINE_PATTERNS:
            m = pat.match(line)
            if m:
                return m.group(1).strip()

        # Bare-text fallback — only if we're inside a file that has real
        # set headers, the line contains letters, and is short enough to
        # plausibly be a song title.
        if (has_set_headers
                and re.search(r'[a-zA-Z]', line)
                and len(line) < 150
                and not re.match(r'^[A-Z][a-z]+\s*:', line)):
            return line.strip()

        return None

    def _clean_song_title(self, title: str) -> str:
        """Strip timing info, hashes, extensions, and normalise whitespace."""
        # Trailing "  05:32"
        title = re.sub(r'\s+\d{1,2}:\d{2}(?:\.\d+)?\s*$', '', title)
        # Bracketed timing  [5:32]
        title = re.sub(r'\s*\[\s*\d{1,2}:\d{2}[#]?\]\s*', ' ', title)
        # Paren timing  (5:32)  at end
        title = re.sub(r'\s*\(\s*\d{1,2}:\d{2}\s*\)\s*$', '', title)
        # Curly-brace timing  {5:32.21}
        title = re.sub(r'\s*\{\s*\d{1,2}:\d{2}(?:\.\d+)?\s*\}\s*', ' ', title)
        # Trailing MD5-style hash  :e012…
        title = re.sub(r':[a-f0-9]{32}$', '', title)
        # .flac extension
        if title.lower().endswith('.flac'):
            title = title[:-5]
        # Tape-cut markers
        for marker in ('////', '///', '//'):
            title = title.replace(marker, '')
        title = title.strip().strip('-').strip()
        title = re.sub(r'\s+', ' ', title)
        return title

    # ──────────────────────────────── venue extraction ────────────────────────

    def _extract_venue(self, header_lines: List[str]) -> Optional[str]:
        """Best-effort venue / location text from the header section."""
        venue_parts: List[str] = []

        for line in header_lines:
            low = line.lower().strip()

            # Skip band names
            if any(b in low for b in BAND_NAME_PATTERNS):
                continue
            # Skip dates
            if DATE_PATTERN.search(line):
                continue
            # Skip source / technical metadata
            if any(kw in low for kw in (
                'source:', 'taper:', 'transfer', 'lineage:', 'recording',
                'sbd', 'aud', 'matrix', 'shn', 'flac', 'archive.org',
                'etree', 'http', 'www.', '.flac', '.shn', 'cd-r',
                'dat', 'cassette', 'reel', 'pre-fm', 'fm broadcast',
                'equipment', 'patch', 'generation',
            )):
                continue
            # Skip pure numbers / slashes
            if re.match(r'^[\d\s\-/]+$', line):
                continue

            if line.strip():
                venue_parts.append(line.strip())

        return '; '.join(venue_parts) if venue_parts else None


# ──────────────────────────────────────────────────────────────────────────────
# Comparison Engine
# ──────────────────────────────────────────────────────────────────────────────

class ComparisonEngine:
    """Run all comparison types: txt-vs-DB and txt-vs-txt."""

    def __init__(self, matcher: ReadOnlySongMatcher):
        self.matcher = matcher

    # ─────────────────────── helpers ──────────────────────────────────────────

    def _normalize_songs(self, songs: List[TxtSongEntry]) -> List[Dict]:
        """Run each TxtSongEntry through the matcher, return enriched dicts."""
        out: List[Dict] = []
        for song in songs:
            result = self.matcher.match(song.title)
            canonical = result.matched_title
            out.append({
                'entry': song,
                'match_result': result,
                'canonical': canonical,
                'canonical_lower': canonical.lower() if canonical else None,
                'is_extra': song.is_extra or result.match_source == 'extra',
            })
        return out

    @staticmethod
    def _fuzzy_venue_match(db_venue: str, txt_venue: str) -> bool:
        """True when the venue string from JerryBase roughly matches the txt."""
        txt_lower = txt_venue.lower()
        db_parts = db_venue.split(',')

        # Check if significant words of the venue name appear in the txt
        if db_parts:
            venue_name = db_parts[0].strip().lower()
            venue_words = [w for w in venue_name.split() if len(w) > 3]
            if venue_words:
                hits = sum(1 for w in venue_words if w in txt_lower)
                if hits >= max(1, len(venue_words) // 2):
                    return True

        # Check city
        if len(db_parts) > 1:
            city = db_parts[1].strip().lower()
            if city and len(city) > 2 and city in txt_lower:
                return True

        return False

    # ──────────────────── txt vs JerryBase ────────────────────────────────────

    def compare_txt_vs_db(
        self,
        txt_data: TxtSetlistData,
        setlist: List[Dict],
        show_info,                       # ShowInfo | None
        folder_name: str,
        date_str: str,
        txt_files_str: str,
    ) -> List[Discrepancy]:
        discs: List[Discrepancy] = []
        txt_name = txt_data.file_path.name

        # ── normalise txt songs ──
        norm_txt = self._normalize_songs(txt_data.songs)

        # ── build DB lookup structures ──
        db_songs: List[Dict] = []
        for s in setlist:
            db_songs.append({
                'song_name': s['song_name'],
                'set_seq':   s['set_seq'],
                'song_seq':  s['song_seq'],
                'segue':     s['segue'],
                'encore':    s['encore'],
            })
        db_names_lower: Set[str] = {d['song_name'].lower() for d in db_songs}

        # canonical non-extra titles found in the txt
        txt_canon_lower: Set[str] = {
            t['canonical_lower'] for t in norm_txt
            if t['canonical_lower'] and not t['is_extra']
        }

        # ── songs in DB but missing from txt ──
        for d in db_songs:
            if d['song_name'].lower() not in txt_canon_lower:
                discs.append(Discrepancy(
                    folder_name=folder_name, date=date_str,
                    txt_files_found=txt_files_str,
                    discrepancy_type='song_missing_from_txt',
                    source_a='JerryBase', source_b=txt_name,
                    details=(f"Song in JerryBase but not in txt: "
                             f"{d['song_name']} (Set {d['set_seq']})"),
                ))

        # ── songs in txt but missing from DB ──
        for t in norm_txt:
            if t['is_extra']:
                continue
            canon = t['canonical']
            if canon and canon.lower() in db_names_lower:
                continue
            raw = t['entry'].title
            if canon and canon.lower() not in db_names_lower:
                discs.append(Discrepancy(
                    folder_name=folder_name, date=date_str,
                    txt_files_found=txt_files_str,
                    discrepancy_type='song_missing_from_db',
                    source_a=txt_name, source_b='JerryBase',
                    details=(f"Song in txt but not in JerryBase setlist: "
                             f"'{raw}' (matched as '{canon}', "
                             f"Set {t['entry'].set_number})"),
                ))
            elif canon is None:
                discs.append(Discrepancy(
                    folder_name=folder_name, date=date_str,
                    txt_files_found=txt_files_str,
                    discrepancy_type='song_missing_from_db',
                    source_a=txt_name, source_b='JerryBase',
                    details=(f"Song in txt but not in JerryBase setlist "
                             f"(unmatched): '{raw}' "
                             f"(Set {t['entry'].set_number})"),
                ))

        # ── song-name differences (fuzzy matches) ──
        for t in norm_txt:
            if t['is_extra']:
                continue
            res = t['match_result']
            if res.match_source == 'fuzzy' and res.confidence < 100:
                discs.append(Discrepancy(
                    folder_name=folder_name, date=date_str,
                    txt_files_found=txt_files_str,
                    discrepancy_type='song_name_diff',
                    source_a=txt_name, source_b='JerryBase',
                    details=(f"Fuzzy match ({res.confidence}%): txt "
                             f"'{t['entry'].title}' -> JerryBase "
                             f"'{res.matched_title}'"),
                ))

        # ── set-assignment differences ──
        db_song_set: Dict[str, int] = {
            d['song_name'].lower(): d['set_seq'] for d in db_songs
        }
        for t in norm_txt:
            if t['is_extra'] or not t['canonical']:
                continue
            cl = t['canonical_lower']
            if cl in db_song_set:
                db_set = db_song_set[cl]
                txt_set = t['entry'].set_number
                if db_set != txt_set:
                    discs.append(Discrepancy(
                        folder_name=folder_name, date=date_str,
                        txt_files_found=txt_files_str,
                        discrepancy_type='set_assignment',
                        source_a=txt_name, source_b='JerryBase',
                        details=(f"'{t['canonical']}': txt says Set "
                                 f"{txt_set}, JerryBase says Set {db_set}"),
                    ))

        # ── song order within shared sets ──
        db_by_set: Dict[int, List[str]] = {}
        for d in db_songs:
            db_by_set.setdefault(d['set_seq'], []).append(d['song_name'].lower())

        txt_by_set: Dict[int, List[str]] = {}
        for t in norm_txt:
            if t['is_extra'] or not t['canonical_lower']:
                continue
            txt_by_set.setdefault(
                t['entry'].set_number, []).append(t['canonical_lower'])

        for set_num in set(db_by_set) & set(txt_by_set):
            db_order  = db_by_set[set_num]
            txt_order = txt_by_set[set_num]
            common_db  = [s for s in db_order  if s in set(txt_order)]
            common_txt = [s for s in txt_order if s in set(db_order)]
            if common_db and common_txt and common_db != common_txt:
                # readable names
                canon_map = {t['canonical_lower']: t['canonical']
                             for t in norm_txt if t['canonical']}
                db_readable  = [canon_map.get(n, n) for n in common_db]
                txt_readable = [canon_map.get(n, n) for n in common_txt]
                limit = 6
                db_str  = ' / '.join(db_readable[:limit])
                txt_str = ' / '.join(txt_readable[:limit])
                if len(db_readable)  > limit: db_str  += '...'
                if len(txt_readable) > limit: txt_str += '...'
                discs.append(Discrepancy(
                    folder_name=folder_name, date=date_str,
                    txt_files_found=txt_files_str,
                    discrepancy_type='song_order',
                    source_a=txt_name, source_b='JerryBase',
                    details=(f"Set {set_num} order differs. "
                             f"Txt: {txt_str} | DB: {db_str}"),
                ))

        # ── segue differences ──
        db_segues: Dict[str, bool] = {
            d['song_name'].lower(): d['segue'] for d in db_songs
        }
        for t in norm_txt:
            if t['is_extra'] or not t['canonical_lower']:
                continue
            cl = t['canonical_lower']
            if cl in db_segues:
                db_seg  = db_segues[cl]
                txt_seg = t['entry'].has_segue
                if db_seg != txt_seg:
                    discs.append(Discrepancy(
                        folder_name=folder_name, date=date_str,
                        txt_files_found=txt_files_str,
                        discrepancy_type='segue_mismatch',
                        source_a=txt_name, source_b='JerryBase',
                        details=(f"'{t['canonical']}': txt "
                                 f"{'>' if txt_seg else '(no segue)'}, "
                                 f"JerryBase "
                                 f"{'>' if db_seg else '(no segue)'}"),
                    ))

        # ── venue mismatch ──
        if txt_data.venue_text and show_info:
            db_venue = (f"{show_info.venue}, {show_info.city}, "
                        f"{show_info.state or show_info.country}")
            if not self._fuzzy_venue_match(db_venue, txt_data.venue_text):
                discs.append(Discrepancy(
                    folder_name=folder_name, date=date_str,
                    txt_files_found=txt_files_str,
                    discrepancy_type='venue_mismatch',
                    source_a=txt_name, source_b='JerryBase',
                    details=(f"Venue mismatch: txt='{txt_data.venue_text}' "
                             f"vs JerryBase='{db_venue}'"),
                ))

        return discs

    # ──────────────────── txt vs txt ──────────────────────────────────────────

    def compare_txt_vs_txt(
        self,
        txt_a: TxtSetlistData,
        txt_b: TxtSetlistData,
        folder_name: str,
        date_str: str,
        txt_files_str: str,
    ) -> List[Discrepancy]:
        discs: List[Discrepancy] = []
        name_a = txt_a.file_path.name
        name_b = txt_b.file_path.name

        norm_a = self._normalize_songs(txt_a.songs)
        norm_b = self._normalize_songs(txt_b.songs)

        non_extra_a = {t['canonical_lower'] for t in norm_a
                       if t['canonical_lower'] and not t['is_extra']}
        non_extra_b = {t['canonical_lower'] for t in norm_b
                       if t['canonical_lower'] and not t['is_extra']}

        # ── song-list differences (non-extras) ──
        for name in non_extra_a - non_extra_b:
            raw = next((t['entry'].title for t in norm_a
                        if t['canonical_lower'] == name), name)
            discs.append(Discrepancy(
                folder_name=folder_name, date=date_str,
                txt_files_found=txt_files_str,
                discrepancy_type='txt_disagreement',
                source_a=name_a, source_b=name_b,
                details=f"Song in {name_a} but not in {name_b}: '{raw}'",
            ))
        for name in non_extra_b - non_extra_a:
            raw = next((t['entry'].title for t in norm_b
                        if t['canonical_lower'] == name), name)
            discs.append(Discrepancy(
                folder_name=folder_name, date=date_str,
                txt_files_found=txt_files_str,
                discrepancy_type='txt_disagreement',
                source_a=name_a, source_b=name_b,
                details=f"Song in {name_b} but not in {name_a}: '{raw}'",
            ))

        # ── extra-song disagreements ──
        extras_a = {t['canonical_lower'] for t in norm_a
                    if t['canonical_lower'] and t['is_extra']}
        extras_b = {t['canonical_lower'] for t in norm_b
                    if t['canonical_lower'] and t['is_extra']}
        for name in extras_a - extras_b:
            raw = next((t['entry'].title for t in norm_a
                        if t['canonical_lower'] == name), name)
            discs.append(Discrepancy(
                folder_name=folder_name, date=date_str,
                txt_files_found=txt_files_str,
                discrepancy_type='txt_disagreement',
                source_a=name_a, source_b=name_b,
                details=f"Extra track in {name_a} but not {name_b}: '{raw}'",
            ))
        for name in extras_b - extras_a:
            raw = next((t['entry'].title for t in norm_b
                        if t['canonical_lower'] == name), name)
            discs.append(Discrepancy(
                folder_name=folder_name, date=date_str,
                txt_files_found=txt_files_str,
                discrepancy_type='txt_disagreement',
                source_a=name_a, source_b=name_b,
                details=f"Extra track in {name_b} but not {name_a}: '{raw}'",
            ))

        # ── set-assignment disagreements (common non-extras) ──
        common = non_extra_a & non_extra_b
        set_a = {t['canonical_lower']: t['entry'].set_number
                 for t in norm_a if t['canonical_lower'] and not t['is_extra']}
        set_b = {t['canonical_lower']: t['entry'].set_number
                 for t in norm_b if t['canonical_lower'] and not t['is_extra']}

        for name in common:
            if set_a.get(name) != set_b.get(name):
                canon = next((t['canonical'] for t in norm_a
                              if t['canonical_lower'] == name), name)
                discs.append(Discrepancy(
                    folder_name=folder_name, date=date_str,
                    txt_files_found=txt_files_str,
                    discrepancy_type='txt_disagreement',
                    source_a=name_a, source_b=name_b,
                    details=(f"Set differs for '{canon}': "
                             f"{name_a}=Set {set_a[name]}, "
                             f"{name_b}=Set {set_b[name]}"),
                ))

        # ── song order within shared sets ──
        all_sets = {t['entry'].set_number for t in norm_a
                    if not t['is_extra']}
        all_sets |= {t['entry'].set_number for t in norm_b
                     if not t['is_extra']}
        for sn in sorted(all_sets):
            order_a = [t['canonical_lower'] for t in norm_a
                       if not t['is_extra'] and t['entry'].set_number == sn
                       and t['canonical_lower']]
            order_b = [t['canonical_lower'] for t in norm_b
                       if not t['is_extra'] and t['entry'].set_number == sn
                       and t['canonical_lower']]
            common_a = [s for s in order_a if s in set(order_b)]
            common_b = [s for s in order_b if s in set(order_a)]
            if common_a and common_b and common_a != common_b:
                discs.append(Discrepancy(
                    folder_name=folder_name, date=date_str,
                    txt_files_found=txt_files_str,
                    discrepancy_type='txt_disagreement',
                    source_a=name_a, source_b=name_b,
                    details=f"Set {sn} song order differs between txt files",
                ))

        # ── segue differences ──
        seg_a = {t['canonical_lower']: t['entry'].has_segue
                 for t in norm_a if t['canonical_lower']}
        seg_b = {t['canonical_lower']: t['entry'].has_segue
                 for t in norm_b if t['canonical_lower']}
        for name in set(seg_a) & set(seg_b):
            if seg_a[name] != seg_b[name]:
                canon = next((t['canonical'] for t in norm_a
                              if t['canonical_lower'] == name), name)
                discs.append(Discrepancy(
                    folder_name=folder_name, date=date_str,
                    txt_files_found=txt_files_str,
                    discrepancy_type='txt_disagreement',
                    source_a=name_a, source_b=name_b,
                    details=(f"Segue for '{canon}': "
                             f"{name_a} {'>' if seg_a[name] else '(none)'}, "
                             f"{name_b} {'>' if seg_b[name] else '(none)'}"),
                ))

        # ── venue text differences ──
        if txt_a.venue_text and txt_b.venue_text:
            if txt_a.venue_text.lower().strip() != txt_b.venue_text.lower().strip():
                discs.append(Discrepancy(
                    folder_name=folder_name, date=date_str,
                    txt_files_found=txt_files_str,
                    discrepancy_type='txt_disagreement',
                    source_a=name_a, source_b=name_b,
                    details=(f"Venue text differs: "
                             f"{name_a}='{txt_a.venue_text}' vs "
                             f"{name_b}='{txt_b.venue_text}'"),
                ))

        return discs


# ──────────────────────────────────────────────────────────────────────────────
# CSV Report Writer
# ──────────────────────────────────────────────────────────────────────────────

REPORT_FIELDS = [
    'folder_name', 'date', 'txt_files_found', 'discrepancy_type',
    'source_a', 'source_b', 'details',
]


def write_report(discrepancies: List[Discrepancy], output_path: Path):
    """Write the full discrepancy report to a CSV file."""
    with open(output_path, 'w', newline='', encoding='utf-8') as fh:
        writer = csv.DictWriter(fh, fieldnames=REPORT_FIELDS)
        writer.writeheader()
        for d in discrepancies:
            writer.writerow({
                'folder_name':     d.folder_name,
                'date':            d.date,
                'txt_files_found': d.txt_files_found,
                'discrepancy_type': d.discrepancy_type,
                'source_a':        d.source_a,
                'source_b':        d.source_b,
                'details':         d.details,
            })


# ──────────────────────────────────────────────────────────────────────────────
# Main Scanner
# ──────────────────────────────────────────────────────────────────────────────

class DiscrepancyScanner:
    """Orchestrates the full discrepancy-detection pipeline."""

    def __init__(self, db_path: Path = DEFAULT_DB_PATH, is_gd: int = 1,
                 num_pad_chars: int = 2, verbose: bool = False):
        self.is_gd = is_gd
        self.num_pad_chars = num_pad_chars
        self.verbose = verbose

        self.album_tagger = AlbumTagger(db_path)
        self.matcher = ReadOnlySongMatcher(db_path)
        self.txt_parser = SetlistTxtParser()
        self.engine = ComparisonEngine(self.matcher)

        self.all_discrepancies: List[Discrepancy] = []
        self.folders_scanned = 0
        self.folders_with_issues = 0

    # ──────────────────────────────────────────────────────────────────────────

    def scan_directory(self, root_path: Path):
        """Recursively scan *root_path* for show folders."""
        if not root_path.is_dir():
            print(f"Error: {root_path} is not a directory")
            return

        # If root itself is a show folder…
        if list(root_path.glob('*.flac')):
            self._scan_folder(root_path)
            return

        for child in sorted(root_path.iterdir()):
            if not child.is_dir() or child.name.startswith('.'):
                continue
            if list(child.glob('*.flac')):
                self._scan_folder(child)
            else:
                self.scan_directory(child)        # recurse into year dirs etc.

    # ──────────────────────────────────────────────────────────────────────────

    def _scan_folder(self, folder_path: Path):
        folder_name = folder_path.name
        self.folders_scanned += 1

        if self.verbose:
            print(f"Scanning: {folder_name}")

        # ── parse date / SHNID ──
        date_tuple = self.album_tagger.parse_date_from_folder(
            folder_name, self.num_pad_chars)
        if not date_tuple:
            if self.verbose:
                print(f"  Warning: could not parse date from {folder_name}")
            return

        year, month, day = date_tuple
        date_str = f"{year}-{month:02d}-{day:02d}"
        shnid = self.album_tagger.parse_shnid_from_folder(folder_name)
        early_late = self.album_tagger.detect_early_late(folder_name)

        # ── find all txt files ──
        txt_files = find_all_txt_files(folder_path, date_str, shnid)

        # Build a display string of relative paths
        txt_files_str = '; '.join(
            self._relative_name(f, folder_path) for f in txt_files
        )

        if self.verbose:
            print(f"  Date: {date_str}, SHNID: {shnid or 'N/A'}, "
                  f"Txt files: {len(txt_files)}")

        # ── missing txt ──
        if not txt_files:
            self.all_discrepancies.append(Discrepancy(
                folder_name=folder_name, date=date_str,
                txt_files_found='',
                discrepancy_type='missing_txt',
                source_a=folder_name, source_b='',
                details='No txt file found for this show',
            ))
            self.folders_with_issues += 1

        # ── parse each txt file ──
        parsed_txts: List[TxtSetlistData] = []
        for txt_path in txt_files:
            parsed = self.txt_parser.parse(txt_path)
            if parsed and parsed.songs:
                parsed_txts.append(parsed)
            elif self.verbose:
                print(f"  Could not parse setlist from {txt_path.name}")

        # ── JerryBase data ──
        setlist = self.matcher.get_songs_for_date(
            year, month, day, self.is_gd, early_late)
        show_info = self.album_tagger.get_show_info(
            year, month, day, self.is_gd, early_late)

        if self.verbose:
            venue = show_info.venue if show_info else 'N/A'
            print(f"  JerryBase: {len(setlist)} songs, Venue: {venue}")

        folder_discs: List[Discrepancy] = []

        # ── txt vs JerryBase ──
        if setlist:
            for td in parsed_txts:
                folder_discs.extend(
                    self.engine.compare_txt_vs_db(
                        td, setlist, show_info,
                        folder_name, date_str, txt_files_str))

        # ── txt vs txt (pairwise) ──
        for i in range(len(parsed_txts)):
            for j in range(i + 1, len(parsed_txts)):
                folder_discs.extend(
                    self.engine.compare_txt_vs_txt(
                        parsed_txts[i], parsed_txts[j],
                        folder_name, date_str, txt_files_str))

        if folder_discs:
            self.folders_with_issues += 1
            self.all_discrepancies.extend(folder_discs)
            if self.verbose:
                print(f"  Found {len(folder_discs)} discrepancies")

    # ──────────────────────────────────────────────────────────────────────────

    @staticmethod
    def _relative_name(txt_path: Path, folder_path: Path) -> str:
        """Best-effort short display name for a txt file."""
        try:
            return str(txt_path.relative_to(folder_path.parent))
        except ValueError:
            return txt_path.name


# ──────────────────────────────────────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description=('Scan show folders for discrepancies between txt files '
                     'and JerryBase.db'),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  Scan Grateful Dead shows:
    python discrepancy_scanner.py /path/to/gd/shows --gd 1

  Scan Jerry Garcia shows:
    python discrepancy_scanner.py /path/to/jg/shows --gd 0

  Custom output and verbose:
    python discrepancy_scanner.py /path/to/shows -o report.csv --verbose
        """,
    )

    parser.add_argument('path', type=Path,
                        help='Path to show folder or directory of shows')
    parser.add_argument('--gd', type=int, default=1, choices=[0, 1],
                        help='1 for Grateful Dead, 0 for Jerry Garcia '
                             '(default: 1)')
    parser.add_argument('--pad', type=int, default=2,
                        help='Prefix chars before date in folder name '
                             '(default: 2)')
    parser.add_argument('--db', type=Path, default=DEFAULT_DB_PATH,
                        help=f'Path to JerryBase.db '
                             f'(default: {DEFAULT_DB_PATH})')
    parser.add_argument('-o', '--output', type=Path,
                        default=Path('discrepancy_report.csv'),
                        help='Output CSV path '
                             '(default: discrepancy_report.csv)')
    parser.add_argument('--verbose', action='store_true',
                        help='Print progress to stdout')

    args = parser.parse_args()

    if not args.path.exists():
        print(f"Error: path does not exist: {args.path}")
        return 1
    if not args.db.exists():
        print(f"Error: database not found: {args.db}")
        return 1

    print("Discrepancy Scanner")
    print(f"{'=' * 60}")
    print(f"Path:     {args.path}")
    print(f"Mode:     {'Grateful Dead' if args.gd else 'Jerry Garcia'}")
    print(f"Database: {args.db}")
    print(f"Output:   {args.output}")
    print(f"{'=' * 60}\n")

    scanner = DiscrepancyScanner(
        db_path=args.db,
        is_gd=args.gd,
        num_pad_chars=args.pad,
        verbose=args.verbose,
    )
    scanner.scan_directory(args.path)

    write_report(scanner.all_discrepancies, args.output)

    # ── summary ──
    print(f"\n{'=' * 60}")
    print("SUMMARY")
    print(f"{'=' * 60}")
    print(f"Folders scanned:            {scanner.folders_scanned}")
    print(f"Folders with discrepancies: {scanner.folders_with_issues}")
    print(f"Total discrepancies:        {len(scanner.all_discrepancies)}")
    print(f"Report written to:          {args.output}")

    type_counts: Dict[str, int] = {}
    for d in scanner.all_discrepancies:
        type_counts[d.discrepancy_type] = (
            type_counts.get(d.discrepancy_type, 0) + 1)
    if type_counts:
        print("\nBreakdown by type:")
        for dtype, count in sorted(type_counts.items()):
            print(f"  {dtype}: {count}")

    return 0


if __name__ == '__main__':
    sys.exit(main())
