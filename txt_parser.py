#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Parser for show .txt files that accompany recordings.

These files typically contain track listings that can be used
to identify songs when the FLAC metadata is missing or generic.

Supports multiple track listing formats:
- d1t01 - Song Name
- 01. Song Name
- 01   Song Name
- Track 01: Song Name
- t01 Song Name
"""

import re
from pathlib import Path
from typing import Optional, Dict, List

# Word-boundary patterns for short tokens that could appear as substrings of
# legitimate content (e.g. "flac24" must not match "flac2496").
_SKIP_WORD_RES = [
    re.compile(r'\b' + p + r'\b', re.IGNORECASE)
    for p in ('ffp', 'md5', 'sha256', 'sha1', 'flac16', 'flac24')
]


class TxtParser:
    """
    Parse show .txt files to extract track-to-song mappings.
    
    Handles various track listing formats found in live show archives.
    Intelligently skips fingerprint and checksum files.
    """
    
    def __init__(self):
        """Initialize the parser with common track listing patterns."""
        # Common patterns for track listings in txt files
        self.track_patterns = [
            # "d1t01 - Song Name" (requires the dash separator to avoid matching fingerprint section)
            re.compile(r'd(\d+)t(\d+)\s+-\s+(.+?)(?:\s*$)', re.IGNORECASE | re.MULTILINE),
            
            # "01. Song Name" or "01 - Song Name"
            re.compile(r'^(\d{1,2})[.\-\)]\s*(.+)', re.MULTILINE),
            
            # "01   Song Name" (track number followed by spaces only - common format)
            re.compile(r'^(\d{2})\s{2,}(\S.+)$', re.MULTILINE),
            
            # "Track 01: Song Name"
            re.compile(r'track\s*(\d+)\s*[:\-]\s*(.+)', re.IGNORECASE),
            
            # "t01 Song Name"
            re.compile(r't(\d+)\s+(.+)', re.IGNORECASE),
        ]
    
    def find_txt_file(self, folder_path: Path) -> Optional[Path]:
        """
        Find the .txt file in a show folder.
        
        Returns the first .txt file found, or None.
        Skips fingerprint/checksum files.
        
        Args:
            folder_path: Path to the show folder
            
        Returns:
            Path to the txt file, or None if not found
        """
        txt_files = list(folder_path.glob('*.txt'))
        
        if not txt_files:
            return None
        
        # Skip fingerprint/checksum/technical files
        skip_substr = ['fingerprint', 'checksum', 'shntool', 'shninfo']
        txt_files = [
            f for f in txt_files
            if not any(p in f.name.lower() for p in skip_substr)
            and not f.name.lower().endswith(('.ffp', '.md5', '.sha', '.sha1', '.sha256'))
            and not any(pat.search(f.name) for pat in _SKIP_WORD_RES)
        ]
        
        if not txt_files:
            return None
        
        # Prefer files with common naming patterns
        preferred_patterns = ['info', 'track', 'list', 'set']
        
        for pattern in preferred_patterns:
            for txt_file in txt_files:
                if pattern in txt_file.name.lower():
                    return txt_file
        
        # Return the first one
        return txt_files[0]
    
    def parse_txt_file(self, txt_path: Path) -> Dict[str, str]:
        """
        Parse a .txt file to extract track-to-song mappings.
        
        Args:
            txt_path: Path to the txt file
        
        Returns:
            Dict mapping track identifiers to song names
            Keys can be: "d1t01", "01", "t01", etc.
        """
        mappings = {}
        
        try:
            with open(txt_path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
        except Exception as e:
            print(f"Warning: Could not read {txt_path}: {e}")
            return mappings
        
        # Try each pattern
        for pattern in self.track_patterns:
            matches = pattern.findall(content)
            
            if matches:
                for match in matches:
                    if len(match) == 3:  # d1t01 pattern
                        disc, track, song = match
                        key = f"d{disc}t{track.zfill(2)}"
                        mappings[key] = song.strip()
                    elif len(match) == 2:  # Simple track pattern
                        track, song = match
                        # Store with various key formats
                        key_num = track.zfill(2)
                        mappings[key_num] = song.strip()
                        mappings[f"t{key_num}"] = song.strip()
        
        # Also parse line-by-line for simple formats
        lines = content.split('\n')
        in_tracklist = False
        track_num = 0
        
        for line in lines:
            line = line.strip()
            
            # Skip empty lines and common headers
            if not line or line.lower().startswith(('set', 'encore', '---', '===')):
                if 'set' in line.lower() or 'encore' in line.lower():
                    in_tracklist = True
                continue
            
            # Look for numbered lines
            # Standard: "01. Song" or "01) Song"
            match = re.match(r'^(\d{1,2})[.\)]\s*(.+)', line)
            
            # Fallback: "01 Song" (single space) — only inside a set/encore
            # section to avoid matching technical metadata in headers
            if not match and in_tracklist:
                match = re.match(r'^(\d{1,2})\s+([A-Za-z/].+)', line)
            
            if match:
                track_num = int(match.group(1))
                song = match.group(2).strip()
                # Skip lines that are filenames or contain hashes (FFP section)
                if '.flac' in song.lower() or '.shn' in song.lower():
                    continue
                if re.search(r':[a-f0-9]{32}', song):
                    continue
                # Remove common suffixes
                song = re.sub(r'\s*[\[\(][^\]\)]*[\]\)]$', '', song)
                mappings[str(track_num).zfill(2)] = song
        
        return mappings
    
    def get_song_for_filename(self, filename: str, txt_path: Path) -> Optional[str]:
        """
        Get song name for a specific file based on the .txt file.
        
        Args:
            filename: Name of the FLAC file (e.g., "gd1977-05-08d1t03.flac")
            txt_path: Path to the .txt file
            
        Returns:
            Song name or None if not found
        """
        mappings = self.parse_txt_file(txt_path)
        
        if not mappings:
            return None
        
        # Extract track identifier from filename
        # Pattern: d#t##, d#t#, t##, t#, or just ##
        
        # Try d#t## pattern
        match = re.search(r'd(\d+)t(\d+)', filename, re.IGNORECASE)
        if match:
            key = f"d{match.group(1)}t{match.group(2).zfill(2)}"
            if key in mappings:
                return mappings[key]
        
        # Try t## pattern
        match = re.search(r't(\d+)', filename, re.IGNORECASE)
        if match:
            key = f"t{match.group(1).zfill(2)}"
            if key in mappings:
                return mappings[key]
            # Also try just the number
            key = match.group(1).zfill(2)
            if key in mappings:
                return mappings[key]
        
        # Try leading number: "01 Song Name.flac" or "01. Song.flac"
        match = re.match(r'^(\d{1,2})\s', filename)
        if match:
            key = match.group(1).zfill(2)
            if key in mappings:
                return mappings[key]
        
        return None
    
    def get_all_songs_from_folder(self, folder_path: Path) -> Dict[str, str]:
        """
        Get all song mappings for a folder from its .txt file.
        
        Args:
            folder_path: Path to the show folder
        
        Returns:
            Dict mapping filenames to song names
        """
        result = {}
        
        txt_path = self.find_txt_file(folder_path)
        if not txt_path:
            return result
        
        # Get all FLAC files
        flac_files = list(folder_path.glob('*.flac'))
        
        for flac_file in flac_files:
            song = self.get_song_for_filename(flac_file.name, txt_path)
            if song:
                result[flac_file.name] = song
        
        return result


def get_title_from_txt(file_path: Path) -> Optional[str]:
    """
    Convenience function to get song title from accompanying .txt file.
    
    Args:
        file_path: Path to the FLAC file
        
    Returns:
        Song title from .txt file or None if not found
    """
    parser = TxtParser()
    folder = file_path.parent
    txt_path = parser.find_txt_file(folder)
    
    if txt_path:
        return parser.get_song_for_filename(file_path.name, txt_path)
    
    return None
