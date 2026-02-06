#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Album, Artist, and Genre tagging module.

Sets album metadata from JerryBase database:
- ARTIST / ALBUMARTIST: Band name (Grateful Dead, Jerry Garcia Band, etc.)
- ALBUM: YYYY-MM-DD (Early/Late)  Venue, City, ST
- GENRE: GD
- DATE: Full date (YYYY-MM-DD)
"""

import sqlite3
import re
from pathlib import Path
from typing import Optional, Tuple
from dataclasses import dataclass
from dateutil.parser import parse as parse_date

from config import DEFAULT_DB_PATH, SOURCE_PATTERNS, DEFAULT_GENRE


@dataclass
class ShowInfo:
    """Information about a show from JerryBase."""
    artist: str
    venue: str
    city: str
    state: str
    country: str
    year: int
    month: int
    day: int
    early_late: Optional[str] = None


@dataclass
class AlbumInfo:
    """Computed album information for tagging."""
    artist: str
    album: str
    genre: str
    date: str  # Full date in YYYY-MM-DD format


class AlbumTagger:
    """
    Generates album and artist metadata from folder names and database.
    
    Parses folder names to extract date and source information,
    then looks up venue and artist details from JerryBase.
    """
    
    def __init__(self, db_path: Path = DEFAULT_DB_PATH):
        """
        Initialize the album tagger.
        
        Args:
            db_path: Path to JerryBase.db database
        """
        self.db_path = db_path
    
    def parse_date_from_folder(self, folder_name: str, num_pad_chars: int = 2) -> Optional[Tuple[int, int, int]]:
        """
        Extract date from folder name.
        
        Args:
            folder_name: e.g., "gd1977-05-08.12345.sbd.miller.flac16" or "gd83-09-04..."
            num_pad_chars: Number of prefix chars before date (e.g., 2 for "gd")
            
        Returns:
            Tuple of (year, month, day) or None if not found
        """
        # Try 4-digit year pattern first: YYYY-MM-DD
        match = re.search(r'(\d{4})-(\d{2})-(\d{2})', folder_name)
        if match:
            return (int(match.group(1)), int(match.group(2)), int(match.group(3)))
        
        # Try 2-digit year pattern: YY-MM-DD
        match = re.search(r'(\d{2})-(\d{2})-(\d{2})', folder_name)
        if match:
            year_2digit = int(match.group(1))
            month = int(match.group(2))
            day = int(match.group(3))
            # Convert 2-digit year to 4-digit (assume 1900s for GD/JG shows)
            # 65-95 -> 1965-1995, 00-64 would be 2000-2064 but unlikely for this use case
            if year_2digit >= 60:
                year = 1900 + year_2digit
            else:
                year = 2000 + year_2digit
            return (year, month, day)
        
        # Fallback to dateutil parsing
        try:
            date_str = folder_name[num_pad_chars:num_pad_chars + 10]
            dt = parse_date(date_str, fuzzy=True)
            return (dt.year, dt.month, dt.day)
        except:
            return None
    
    def parse_shnid_from_folder(self, folder_name: str) -> Optional[str]:
        """
        Extract SHNID from folder name.
        
        Args:
            folder_name: Folder name containing SHNID
            
        Returns:
            SHNID as string or None if not found
        """
        parts = folder_name.split('.')
        for part in parts:
            try:
                shnid = int(part)
                if shnid > 1000:  # SHNIDs are typically large numbers
                    return str(shnid)
            except ValueError:
                continue
        return None
    
    def detect_source_type(self, folder_name: str) -> Optional[str]:
        """
        Detect recording source type from folder name.
        
        Args:
            folder_name: Folder name to analyze
            
        Returns:
            Source type (sbd, aud, fm, etc.) or None
        """
        folder_lower = folder_name.lower()
        
        for source_type, patterns in SOURCE_PATTERNS.items():
            for pattern in patterns:
                if pattern in folder_lower:
                    return source_type
        
        return None
    
    def has_miller(self, folder_name: str) -> bool:
        """Check if this is a Charlie Miller mix."""
        return 'miller' in folder_name.lower()
    
    def detect_early_late(self, folder_name: str) -> Optional[str]:
        """
        Detect early/late show designation.
        
        Args:
            folder_name: Folder name to analyze
            
        Returns:
            'EARLY', 'LATE', or None
        """
        folder_lower = folder_name.lower()
        
        if 'early' in folder_lower and 'late' in folder_lower:
            return None  # Ambiguous, skip
        elif 'early' in folder_lower:
            return 'EARLY'
        elif 'late' in folder_lower:
            return 'LATE'
        
        return None
    
    def get_show_info(self, year: int, month: int, day: int, is_gd: int = 1,
                      early_late: Optional[str] = None) -> Optional[ShowInfo]:
        """
        Get show information from JerryBase database.
        
        Args:
            year, month, day: Date of the show
            is_gd: 1 for Grateful Dead, 0 for Jerry Garcia
            early_late: 'EARLY', 'LATE', or None
            
        Returns:
            ShowInfo or None if not found
        """
        if not self.db_path.exists():
            return None
        
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()
        
        sql = """
            SELECT a.name, v.name, v.city, v.state, v.country, e.early_late
            FROM events e
            JOIN acts a ON e.act_id = a.id
            JOIN venues v ON e.venue_id = v.id
            WHERE e.year = ? AND e.month = ? AND e.day = ?
            AND a.gd = ? AND e.canceled = 0
        """
        
        cursor.execute(sql, (year, month, day, is_gd))
        results = cursor.fetchall()
        conn.close()
        
        if not results:
            return None
        
        # If multiple results (early/late shows), try to find the right one
        if len(results) > 1 and early_late:
            for row in results:
                if row[5] == early_late:
                    return ShowInfo(
                        artist=row[0] or '',
                        venue=row[1] or '',
                        city=row[2] or '',
                        state=row[3] or '',
                        country=row[4] or '',
                        year=year, month=month, day=day,
                        early_late=early_late
                    )
        
        # Return first result
        row = results[0]
        return ShowInfo(
            artist=row[0] or '',
            venue=row[1] or '',
            city=row[2] or '',
            state=row[3] or '',
            country=row[4] or '',
            year=year, month=month, day=day,
            early_late=row[5]
        )
    
    def build_album_name(self, show: ShowInfo, folder_name: str) -> str:
        """
        Build album name from show info and folder name.
        
        Format: 
        - Normal: YYYY-MM-DD  Venue, City, ST (2 spaces after date)
        - Early/Late: YYYY-MM-DD (Early)  Venue, City, ST (1 space, indicator, 2 spaces)
        
        Args:
            show: ShowInfo from database
            folder_name: Original folder name (for early/late detection)
            
        Returns:
            Formatted album name
        """
        # Date
        date_str = f"{show.year}-{show.month:02d}-{show.day:02d}"
        
        # Early/Late indicator
        early_late = self.detect_early_late(folder_name)
        if early_late == 'EARLY':
            early_late_str = " (Early)"  # 1 space before (Early)
        elif early_late == 'LATE':
            early_late_str = " (Late)"   # 1 space before (Late)
        else:
            early_late_str = ""
        
        # Location - prefer state, fall back to country for international
        location = show.state if show.state else show.country
        
        # Build final album name with proper spacing
        # 2 spaces before venue in all cases
        album = f"{date_str}{early_late_str}  {show.venue}, {show.city}, {location}"
        
        return album.strip()
    
    def get_album_info(self, folder_path: Path, num_pad_chars: int = 2,
                       is_gd: int = 1) -> Optional[AlbumInfo]:
        """
        Get complete album info for a show folder.
        
        Args:
            folder_path: Path to the show folder
            num_pad_chars: Number of prefix chars before date in folder name
            is_gd: 1 for Grateful Dead, 0 for Jerry Garcia
            
        Returns:
            AlbumInfo or None if date/show not found
        """
        folder_name = folder_path.name
        
        # Parse date from folder
        date_tuple = self.parse_date_from_folder(folder_name, num_pad_chars)
        if not date_tuple:
            return None
        
        year, month, day = date_tuple
        
        # Detect early/late
        early_late = self.detect_early_late(folder_name)
        
        # Get show info from database
        show = self.get_show_info(year, month, day, is_gd, early_late)
        if not show:
            return None
        
        # Build album name
        album = self.build_album_name(show, folder_name)
        
        # Full date in YYYY-MM-DD format
        full_date = f"{year}-{month:02d}-{day:02d}"
        
        return AlbumInfo(
            artist=show.artist,
            album=album,
            genre=DEFAULT_GENRE,
            date=full_date
        )
    
    def get_album_info_from_folder_name(self, folder_name: str, num_pad_chars: int = 2,
                                         is_gd: int = 1) -> Optional[AlbumInfo]:
        """
        Get album info using just folder name (for when Path not available).
        
        Args:
            folder_name: Name of the folder
            num_pad_chars: Number of prefix chars before date
            is_gd: 1 for Grateful Dead, 0 for Jerry Garcia
            
        Returns:
            AlbumInfo or None
        """
        return self.get_album_info(Path(folder_name), num_pad_chars, is_gd)
