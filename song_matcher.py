#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Multi-tier song title matching engine.

Matching tiers:
1. Exact match (case-insensitive) against JerryBase songs table
2. Corrections map lookup (previously corrected titles)
3. Extra songs map for non-song tracks (tuning, crowd, etc.)
4. Fuzzy match with confidence scoring

The fuzzy matching uses rapidfuzz for high-performance string similarity.
Auto-applies high-confidence matches and saves them for future use.
"""

import sqlite3
import csv
import re
from pathlib import Path
from typing import Optional, Tuple, Dict, List
from dataclasses import dataclass

try:
    from rapidfuzz import fuzz, process
    RAPIDFUZZ_AVAILABLE = True
except ImportError:
    RAPIDFUZZ_AVAILABLE = False
    print("Warning: rapidfuzz not installed. Fuzzy matching disabled.")
    print("Install with: pip install rapidfuzz")

from config import (
    DEFAULT_DB_PATH, CORRECTIONS_MAP_PATH, EXTRA_SONGS_PATH,
    AUTO_APPLY_THRESHOLD, REVIEW_THRESHOLD, SEGUE_MARKERS, TAPE_MARKERS,
    is_extra_track
)


# Words that should stay lowercase in titles (unless first word)
LOWERCASE_WORDS = {'a', 'an', 'the', 'and', 'but', 'or', 'for', 'nor', 'on', 
                   'at', 'to', 'from', 'by', 'of', 'in', 'with', 'vs'}


def title_case(text: str) -> str:
    """
    Convert text to proper Title Case for song titles.
    
    - Capitalizes first letter of each word
    - Keeps small words (a, an, the, and, etc.) lowercase unless first word
    - Preserves existing all-caps words (acronyms like "USA", "II", "IV")
    - Handles contractions properly (I'm, You're, etc.)
    
    Args:
        text: The text to convert
        
    Returns:
        Title-cased text
    """
    if not text:
        return text
    
    words = text.split()
    result = []
    
    for i, word in enumerate(words):
        # Preserve all-caps words (likely acronyms or Roman numerals)
        if word.isupper() and len(word) > 1:
            result.append(word)
            continue
        
        # Check if it's a small word (but always capitalize first word)
        word_lower = word.lower()
        if i > 0 and word_lower in LOWERCASE_WORDS:
            result.append(word_lower)
            continue
        
        # Handle hyphenated words (capitalize each part)
        if "-" in word:
            parts = word.split("-")
            capitalized_parts = [p.capitalize() for p in parts]
            result.append('-'.join(capitalized_parts))
            continue
        
        # Handle contractions - only capitalize the first part
        # e.g., "he's" -> "He's", not "He'S"
        if "'" in word:
            result.append(word.capitalize())
            continue
        
        # Standard capitalization
        result.append(word.capitalize())
    
    return ' '.join(result)


@dataclass
class MatchResult:
    """Result of a song title match attempt."""
    original_title: str
    cleaned_title: str
    matched_title: Optional[str]
    confidence: int
    match_source: str  # 'exact', 'corrections', 'fuzzy', 'extra', 'unmatched'
    has_segue: bool
    needs_review: bool = False


class SongMatcher:
    """
    Multi-tier song title matching engine.
    
    Uses a hierarchy of matching strategies to normalize song titles
    from various recording sources to canonical names.
    """
    
    def __init__(self, db_path: Path = DEFAULT_DB_PATH):
        """
        Initialize the song matcher.
        
        Args:
            db_path: Path to JerryBase_BCEversion.db database
        """
        self.db_path = db_path
        self.songs_cache: Dict[str, str] = {}  # lowercase -> canonical
        self.corrections_cache: Dict[str, str] = {}  # lowercase -> canonical
        self.extra_songs_cache: Dict[str, str] = {}  # lowercase -> canonical
        
        self._load_songs_from_db()
        self._load_corrections_map()
        self._load_extra_songs()
    
    def _load_songs_from_db(self):
        """Load all song names from JerryBase database."""
        if not self.db_path.exists():
            print(f"Warning: Database not found at {self.db_path}")
            return
        
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM songs WHERE name IS NOT NULL")
        
        for (name,) in cursor.fetchall():
            self.songs_cache[name.lower().strip()] = name
        
        conn.close()
        print(f"Loaded {len(self.songs_cache)} songs from database")
    
    def _load_corrections_map(self):
        """Load previously corrected title mappings (pipe-delimited)."""
        if not CORRECTIONS_MAP_PATH.exists():
            return
        
        with open(CORRECTIONS_MAP_PATH, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f, delimiter='|')
            for row in reader:
                original = row.get('original_title', '').lower().strip()
                canonical = row.get('canonical_title', '').strip()
                if original and canonical:
                    self.corrections_cache[original] = canonical
        
        print(f"Loaded {len(self.corrections_cache)} corrections from map")
    
    def _load_extra_songs(self):
        """Load extra songs map (tuning, crowd, etc.) - pipe-delimited."""
        if not EXTRA_SONGS_PATH.exists():
            return
        
        with open(EXTRA_SONGS_PATH, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f, delimiter='|')
            for row in reader:
                original = row.get('original_title', '').lower().strip()
                canonical = row.get('canonical_title', '').strip()
                if original and canonical:
                    self.extra_songs_cache[original] = canonical
        
        print(f"Loaded {len(self.extra_songs_cache)} extra song mappings")
    
    def clean_title(self, raw_title: str) -> Tuple[str, bool]:
        """
        Clean and normalize a song title.
        
        Removes various artifacts commonly found in live recording metadata:
        - Duration timestamps
        - Tape markers
        - Take numbers
        - Segue indicators
        - File extensions
        - Hash suffixes
        
        Args:
            raw_title: The raw title from file metadata
            
        Returns:
            Tuple of (cleaned_title, has_segue)
        """
        if not raw_title:
            return ('', False)
        
        title = str(raw_title).strip()
        has_segue = False
        
        # Strip double quotes (they're typically not part of song titles)
        title = title.replace('"', '')
        
        # Remove hash suffixes like ":e0129245cbbe36646809993036a6e6a7"
        title = re.sub(r':[a-f0-9]{32}$', '', title)
        
        # Remove .flac extension if present at end
        if title.lower().endswith('.flac'):
            title = title[:-5]
        
        # Remove tape markers FIRST (before other patterns that check end of string)
        for marker in TAPE_MARKERS:
            title = title.replace(marker, '')
        
        # Remove embedded durations like "05:09" or "11:57" at end of title
        # Matches patterns like "SONG NAME  05:09" or "SONG NAME\t07:03"
        title = re.sub(r'[\s\t]+\d{1,2}:\d{2}\s*$', '', title)
        
        # Remove colon-prefixed duration like ":10:27" at end
        title = re.sub(r'\s*:\d{1,2}:\d{2}\s*$', '', title)
        
        # Remove bracketed timing info like [0:41], [ 7:22], [10:57] anywhere in title
        # Note: handles optional space after bracket
        title = re.sub(r'\s*\[\s*\d{1,2}:\d{2}[#]?\]\s*', ' ', title)
        
        # Remove curly-brace timing info like {7:56.21}, {9:21.24}
        title = re.sub(r'\s*\{\s*\d{1,2}:\d{2}(\.\d+)?\s*\}\s*', ' ', title)
        
        # Remove parenthesized durations like (5:20), (14:42) at end of title
        title = re.sub(r'\s*\(\s*\d{1,2}:\d{2}\s*\)\s*$', '', title)
        
        # Remove timing/breakdown info after = sign (studio outtakes)
        # e.g., "Lovelight take 1  [0:41] = [0:22] ; Lovelight [0:17]"
        title = re.sub(r'\s*=\s*.*$', '', title)
        
        # Keep take numbers - they're meaningful for outtakes/rehearsals
        
        # Normalize multiple spaces to single space
        title = re.sub(r'\s+', ' ', title)
        
        # Detect and remove segue markers
        for marker in SEGUE_MARKERS:
            if title.endswith(marker):
                has_segue = True
                title = title[:-len(marker)].strip()
                break
        
        # Also check for standalone '>' at end
        if title.endswith('>'):
            has_segue = True
            title = title.rstrip('>').strip()
        
        # Remove leading/trailing markers that might remain
        title = title.strip('/->')
        title = title.strip()
        
        return (title, has_segue)
    
    def match(self, raw_title: str) -> MatchResult:
        """
        Attempt to match a song title using all available tiers.
        
        Args:
            raw_title: The raw song title from the FLAC metadata
            
        Returns:
            MatchResult with match details
        """
        cleaned, has_segue = self.clean_title(raw_title)
        cleaned_lower = cleaned.lower()
        
        # Tier 1: Exact match
        if cleaned_lower in self.songs_cache:
            return MatchResult(
                original_title=raw_title,
                cleaned_title=cleaned,
                matched_title=self.songs_cache[cleaned_lower],
                confidence=100,
                match_source='exact',
                has_segue=has_segue
            )
        
        # Tier 2: Corrections map
        if cleaned_lower in self.corrections_cache:
            return MatchResult(
                original_title=raw_title,
                cleaned_title=cleaned,
                matched_title=self.corrections_cache[cleaned_lower],
                confidence=100,
                match_source='corrections',
                has_segue=has_segue
            )
        
        # Tier 3: Extra songs map (tuning, crowd, etc.)
        if cleaned_lower in self.extra_songs_cache:
            return MatchResult(
                original_title=raw_title,
                cleaned_title=cleaned,
                matched_title=self.extra_songs_cache[cleaned_lower],
                confidence=100,
                match_source='extra',
                has_segue=has_segue
            )
        
        # Check if it's an extra track pattern
        if is_extra_track(cleaned):
            # Try to find a match in extra songs
            for pattern, canonical in self.extra_songs_cache.items():
                if pattern in cleaned_lower:
                    return MatchResult(
                        original_title=raw_title,
                        cleaned_title=cleaned,
                        matched_title=canonical,
                        confidence=90,
                        match_source='extra',
                        has_segue=has_segue
                    )
            
            # Return as-is with title case normalization
            return MatchResult(
                original_title=raw_title,
                cleaned_title=cleaned,
                matched_title=cleaned.title(),
                confidence=80,
                match_source='extra',
                has_segue=has_segue
            )
        
        # Tier 4: Fuzzy match
        if RAPIDFUZZ_AVAILABLE and self.songs_cache:
            song_names = list(self.songs_cache.keys())
            result = process.extractOne(
                cleaned_lower,
                song_names,
                scorer=fuzz.ratio
            )
            
            if result:
                matched_lower, score, _ = result
                matched_canonical = self.songs_cache[matched_lower]
                
                if score >= AUTO_APPLY_THRESHOLD:
                    # Auto-apply and add to corrections
                    self.add_correction(cleaned_lower, matched_canonical, 'fuzzy_auto')
                    return MatchResult(
                        original_title=raw_title,
                        cleaned_title=cleaned,
                        matched_title=matched_canonical,
                        confidence=score,
                        match_source='fuzzy',
                        has_segue=has_segue
                    )
                elif score >= REVIEW_THRESHOLD:
                    # Needs review
                    return MatchResult(
                        original_title=raw_title,
                        cleaned_title=cleaned,
                        matched_title=matched_canonical,
                        confidence=score,
                        match_source='fuzzy',
                        has_segue=has_segue,
                        needs_review=True
                    )
        
        # No match found
        return MatchResult(
            original_title=raw_title,
            cleaned_title=cleaned,
            matched_title=None,
            confidence=0,
            match_source='unmatched',
            has_segue=has_segue
        )
    
    def add_correction(self, original_lower: str, canonical: str, source: str = 'manual'):
        """
        Add a correction to the map and save.
        
        Args:
            original_lower: Lowercase version of the original title
            canonical: The correct canonical title
            source: Source of the correction (manual, fuzzy_auto, etc.)
        """
        self.corrections_cache[original_lower] = canonical
        self._save_corrections_map()
    
    def _save_corrections_map(self):
        """Save corrections map to pipe-delimited file."""
        with open(CORRECTIONS_MAP_PATH, 'w', encoding='utf-8', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=['original_title', 'canonical_title', 'source'],
                                    delimiter='|')
            writer.writeheader()
            for original, canonical in sorted(self.corrections_cache.items()):
                writer.writerow({
                    'original_title': original,
                    'canonical_title': canonical,
                    'source': 'learned'
                })
    
    def get_songs_for_date(self, year: int, month: int, day: int, is_gd: int = 1,
                           early_late: Optional[str] = None) -> List[Dict]:
        """
        Get the setlist for a specific date from the database.
        
        Args:
            year, month, day: Date of the show
            is_gd: 1 for Grateful Dead, 0 for Jerry Garcia
            early_late: 'EARLY', 'LATE', or None
        
        Returns:
            List of dicts with: song_name, set_seq, set_name, song_seq, segue, encore
        """
        if not self.db_path.exists():
            return []
        
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()
        
        if early_late:
            sql = """
                SELECT s.name, es.seq_no, es.name, ev_s.seq_no, ev_s.segue, es.encore
                FROM events e
                JOIN event_sets es ON e.id = es.event_id
                JOIN event_songs ev_s ON es.id = ev_s.event_set_id
                JOIN songs s ON ev_s.song_id = s.id
                JOIN acts a ON e.act_id = a.id
                WHERE e.year = ? AND e.month = ? AND e.day = ?
                AND a.gd = ? AND es.soundcheck = 0 AND e.early_late = ?
                ORDER BY es.seq_no, ev_s.seq_no
            """
            cursor.execute(sql, (year, month, day, is_gd, early_late))
        else:
            sql = """
                SELECT s.name, es.seq_no, es.name, ev_s.seq_no, ev_s.segue, es.encore
                FROM events e
                JOIN event_sets es ON e.id = es.event_id
                JOIN event_songs ev_s ON es.id = ev_s.event_set_id
                JOIN songs s ON ev_s.song_id = s.id
                JOIN acts a ON e.act_id = a.id
                WHERE e.year = ? AND e.month = ? AND e.day = ?
                AND a.gd = ? AND es.soundcheck = 0
                ORDER BY es.seq_no, ev_s.seq_no
            """
            cursor.execute(sql, (year, month, day, is_gd))
        
        results = []
        for row in cursor.fetchall():
            results.append({
                'song_name': row[0],
                'set_seq': row[1],
                'set_name': row[2],
                'song_seq': row[3],
                'segue': row[4] == 1,
                'encore': row[5] == 1
            })
        
        conn.close()
        return results
    
    def get_set_info_for_date(self, year: int, month: int, day: int, is_gd: int = 1,
                              early_late: Optional[str] = None) -> List[Dict]:
        """
        Get set structure for a specific date.
        
        Args:
            year, month, day: Date of the show
            is_gd: 1 for Grateful Dead, 0 for Jerry Garcia
            early_late: 'EARLY', 'LATE', or None
        
        Returns:
            List of dicts with: set_seq, set_name, encore, song_count
        """
        if not self.db_path.exists():
            return []
        
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()
        
        if early_late:
            sql = """
                SELECT es.seq_no, es.name, es.encore, COUNT(ev_s.id) as song_count
                FROM events e
                JOIN event_sets es ON e.id = es.event_id
                JOIN event_songs ev_s ON es.id = ev_s.event_set_id
                JOIN acts a ON e.act_id = a.id
                WHERE e.year = ? AND e.month = ? AND e.day = ?
                AND a.gd = ? AND es.soundcheck = 0 AND e.early_late = ?
                GROUP BY es.id
                ORDER BY es.seq_no
            """
            cursor.execute(sql, (year, month, day, is_gd, early_late))
        else:
            sql = """
                SELECT es.seq_no, es.name, es.encore, COUNT(ev_s.id) as song_count
                FROM events e
                JOIN event_sets es ON e.id = es.event_id
                JOIN event_songs ev_s ON es.id = ev_s.event_set_id
                JOIN acts a ON e.act_id = a.id
                WHERE e.year = ? AND e.month = ? AND e.day = ?
                AND a.gd = ? AND es.soundcheck = 0
                GROUP BY es.id
                ORDER BY es.seq_no
            """
            cursor.execute(sql, (year, month, day, is_gd))
        
        results = []
        for row in cursor.fetchall():
            results.append({
                'set_seq': row[0],
                'set_name': row[1],
                'encore': row[2] == 1,
                'song_count': row[3]
            })
        
        conn.close()
        return results


def get_final_title(result: MatchResult) -> str:
    """
    Get the final title string including segue marker if present.
    
    For matched songs, uses the canonical title from JerryBase.
    For unmatched songs, applies Title Case normalization.
    
    Args:
        result: The match result to extract the title from
        
    Returns:
        Final title with segue marker appended if applicable
    """
    if result.matched_title:
        title = result.matched_title
    else:
        # Apply Title Case normalization for unmatched songs
        title = title_case(result.cleaned_title)
    
    if result.has_segue:
        title = title + " >"
    
    return title
