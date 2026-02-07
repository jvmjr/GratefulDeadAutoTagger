#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Main auto-tagger CLI script.

Runs the full tagging pipeline:
1. Normalize song titles (fuzzy matching, corrections)
2. Set Album, Artist, AlbumArtist, Genre, Date
3. Assign DISCNUMBER based on musical sets
4. Renumber TRACKNUMBER within each set
5. Set DISCTOTAL and TRACKTOTAL
6. Copy artwork if missing

Usage:
    python tagger.py /path/to/shows --gd 1
    python tagger.py /path/to/jg/shows --gd 0 --pad 2
    python tagger.py /path/to/single/show --trial  # Preview without writing
    python tagger.py /path/to/shows --artwork-dir /path/to/covers
"""

import argparse
import csv
from pathlib import Path
from typing import List, Dict, Optional
from dataclasses import dataclass

from mutagen.flac import FLAC

from config import (
    ensure_dirs, DEFAULT_DB_PATH, REVIEW_MATCHES_PATH, 
    UNMATCHED_SONGS_PATH, SEGUE_LOG_PATH, LOGS_DIR, AUTO_APPLY_THRESHOLD
)
from song_matcher import SongMatcher, MatchResult, get_final_title
from album_tagger import AlbumTagger, AlbumInfo
from set_tagger import SetTagger, TrackAssignment, assign_extras_to_encore
from txt_parser import TxtParser, get_title_from_txt
from artwork_handler import process_folder_artwork


@dataclass
class FileTagUpdate:
    """Represents all tag updates for a single file."""
    file_path: Path
    title: str
    artist: str
    album_artist: str
    album: str
    genre: str
    date: str
    version: str  # Folder name - tracks which recording version
    disc_number: int
    disc_total: int
    track_number: int
    track_total: int
    has_segue: bool
    match_source: str
    needs_review: bool


class AutoTagger:
    """
    Main auto-tagger class that orchestrates the tagging pipeline.
    
    Coordinates between song matching, album tagging, set assignment,
    and artwork handling to fully process show folders.
    """
    
    def __init__(self, db_path: Path = DEFAULT_DB_PATH, trial_mode: bool = False,
                 artwork_dir: Optional[Path] = None, artwork_primary: bool = False,
                 trust_txt: bool = False):
        """
        Initialize the auto-tagger.
        
        Args:
            db_path: Path to JerryBase.db database
            trial_mode: If True, preview changes without writing
            artwork_dir: Optional directory to search for artwork
            artwork_primary: If True, artwork_dir is searched before parent folder
            trust_txt: If True, prioritize txt file over existing FLAC tags
        """
        self.db_path = db_path
        self.trial_mode = trial_mode
        self.artwork_dir = artwork_dir
        self.artwork_primary = artwork_primary
        self.trust_txt = trust_txt
        
        self.matcher = SongMatcher(db_path)
        self.album_tagger = AlbumTagger(db_path)
        self.set_tagger = SetTagger(self.matcher)
        self.txt_parser = TxtParser()
        
        self.review_matches: List[Dict] = []
        self.unmatched_songs: List[Dict] = []
        self.segue_discrepancies: List[Dict] = []
        self.duplicate_warnings: List[Dict] = []
        self.processed_count = 0
        self.skipped_count = 0
        self.artwork_copied = 0
        self.artwork_not_found = 0
    
    def process_folder(self, folder_path: Path, is_gd: int = 1, 
                       num_pad_chars: int = 2) -> List[FileTagUpdate]:
        """
        Process a single show folder.
        
        Args:
            folder_path: Path to the show folder
            is_gd: 1 for Grateful Dead, 0 for Jerry Garcia
            num_pad_chars: Number of prefix chars before date in folder name
            
        Returns:
            List of FileTagUpdate objects
        """
        folder_name = folder_path.name
        print(f"\nProcessing: {folder_name}")
        
        # Get album info
        album_info = self.album_tagger.get_album_info(folder_path, num_pad_chars, is_gd)
        
        if not album_info:
            print(f"  Warning: Could not get album info for {folder_name}")
            # Create minimal album info
            album_info = AlbumInfo(
                artist="Grateful Dead" if is_gd else "Jerry Garcia",
                album=folder_name,
                genre="GD",
                date=""
            )
        
        # Get FLAC files sorted by name (actual files only, not directories)
        flac_files = sorted([f for f in folder_path.glob('*.flac') if f.is_file()])
        
        if not flac_files:
            print(f"  No FLAC files found in {folder_name}")
            return []
        
        # Parse date for setlist lookup
        date_tuple = self.album_tagger.parse_date_from_folder(folder_name, num_pad_chars)
        
        setlist = []
        set_info = []
        
        if date_tuple:
            year, month, day = date_tuple
            early_late = self.album_tagger.detect_early_late(folder_name)
            
            setlist = self.matcher.get_songs_for_date(year, month, day, is_gd, early_late)
            set_info = self.matcher.get_set_info_for_date(year, month, day, is_gd, early_late)
            
            print(f"  Date: {year}-{month:02d}-{day:02d}, Songs in setlist: {len(setlist)}, Sets: {len(set_info)}")
        
        # Get song mappings from txt file (for files with missing/generic titles)
        txt_mappings = self.txt_parser.get_all_songs_from_folder(folder_path)
        
        # Validate: check if txt file track count matches FLAC file count
        if txt_mappings and self.trust_txt:
            should_skip = self._validate_txt_file_coverage(flac_files, txt_mappings, 
                                                           folder_name, setlist)
            if should_skip:
                print(f"  ⛔ SKIPPING FOLDER - txt file mismatch detected")
                print(f"  → Fix the txt file or run without --trust-txt flag")
                return []
        
        # Process each file
        updates = []
        file_results: List[MatchResult] = []
        
        for flac_file in flac_files:
            result = self._process_file(flac_file, txt_mappings, setlist)
            file_results.append(result)
        
        # Merge segue info from JerryBase and txt file.
        # If EITHER source indicates a segue, we apply it.
        # Discrepancies are logged but neither source is altered.
        db_segues = {s['song_name'].lower(): s['segue'] for s in setlist}
        
        for flac_file, result in zip(flac_files, file_results):
            if not result.matched_title:
                continue
            
            # JerryBase segue flag
            db_segue = db_segues.get(result.matched_title.lower(), False)
            
            # Txt file segue marker (parse from raw txt title if available)
            txt_segue = False
            txt_title_raw = txt_mappings.get(flac_file.name)
            if txt_title_raw:
                _, txt_segue = self.matcher.clean_title(txt_title_raw)
            
            # Segue already detected from the FLAC tag itself
            tag_segue = result.has_segue
            
            # OR logic: apply segue if any source says so
            final_segue = db_segue or tag_segue or txt_segue
            
            # Log discrepancy when sources disagree
            if db_segue != txt_segue and txt_title_raw is not None:
                self.segue_discrepancies.append({
                    'file_path': str(flac_file),
                    'song': result.matched_title,
                    'db_segue': db_segue,
                    'txt_segue': txt_segue,
                    'tag_segue': tag_segue,
                    'applied': final_segue,
                })
            
            result.has_segue = final_segue
        
        # Assign discs based on setlist, using pre-matched results
        assignments = self.set_tagger.assign_discs(flac_files, setlist, set_info, file_results)
        
        # Move extras after last song to encore disc
        if set_info:
            assignments = assign_extras_to_encore(assignments, set_info)
            # Renumber after moving
            assignments = self.set_tagger._renumber_tracks(assignments)
        
        # Calculate totals
        disc_total, track_totals = self.set_tagger.get_totals(assignments)
        
        # Build update objects
        for i, (flac_file, result, assignment) in enumerate(zip(flac_files, file_results, assignments)):
            track_total = track_totals.get(assignment.disc_number, len(flac_files))
            
            final_title = get_final_title(result)
            
            update = FileTagUpdate(
                file_path=flac_file,
                title=final_title,
                artist=album_info.artist,
                album_artist=album_info.artist,
                album=album_info.album,
                genre=album_info.genre,
                date=album_info.date,
                version=folder_name,  # Folder name to track recording version
                disc_number=assignment.disc_number,
                disc_total=disc_total,
                track_number=assignment.track_number,
                track_total=track_total,
                has_segue=result.has_segue,
                match_source=result.match_source,
                needs_review=result.needs_review
            )
            
            updates.append(update)
            
            # Track review/unmatched
            if result.needs_review:
                self.review_matches.append({
                    'file_path': str(flac_file),
                    'original_title': result.original_title,
                    'suggested_match': result.matched_title,
                    'confidence': result.confidence,
                    'action': ''
                })
            elif result.match_source == 'unmatched':
                self.unmatched_songs.append({
                    'file_path': str(flac_file),
                    'original_title': result.original_title,
                    'cleaned_title': result.cleaned_title
                })
        
        # Check for unexpected duplicate titles
        self._check_for_duplicate_titles(updates, setlist, txt_mappings, folder_name)
        
        return updates
    
    def _process_file(self, flac_file: Path, txt_mappings: Dict[str, str], 
                       setlist: List[Dict] = None) -> MatchResult:
        """
        Process a single FLAC file to get matched title.
        
        Cross-validates against the show's setlist from JerryBase. If the existing
        tag doesn't match a song in this show's setlist, checks the txt file.
        Uses JerryBase canonical naming.
        
        Priority order (when trust_txt=True):
        1. Txt file (if available)
        2. Existing FLAC tag
        
        Priority order (when trust_txt=False, default):
        1. High-confidence existing FLAC tag match (>= 85%)
        2. Txt file (if available and existing tag is low confidence or suspicious)
        3. Existing FLAC tag (any confidence)
        """
        try:
            audio = FLAC(str(flac_file))
            raw_title = audio.get('TITLE', [''])[0] if audio.get('TITLE') else ''
        except Exception as e:
            print(f"  Error reading {flac_file.name}: {e}")
            raw_title = ''
        
        # Build set of canonical song names for this show (lowercase for comparison)
        setlist_songs = {}
        if setlist:
            for song in setlist:
                setlist_songs[song['song_name'].lower()] = song['song_name']
        
        # If trust_txt flag is set, prioritize txt file
        if self.trust_txt:
            txt_title = txt_mappings.get(flac_file.name)
            if txt_title:
                txt_result = self.matcher.match(txt_title)
                txt_matched_lower = txt_result.matched_title.lower() if txt_result.matched_title else ''
                
                # Check if txt file's match is in the setlist
                if txt_matched_lower in setlist_songs:
                    return MatchResult(
                        original_title=raw_title,  # Keep original for reference
                        cleaned_title=txt_result.cleaned_title,
                        matched_title=setlist_songs[txt_matched_lower],
                        confidence=txt_result.confidence,
                        match_source='txt_setlist',
                        has_segue=txt_result.has_segue,
                        needs_review=False
                    )
                # Even if not in setlist, use txt result
                return txt_result
            else:
                # trust_txt is enabled but file has NO txt mapping
                # Mark as unmatched to prevent using potentially wrong existing tags
                return MatchResult(
                    original_title=raw_title,
                    cleaned_title=raw_title,
                    matched_title=None,
                    confidence=0,
                    match_source='no_txt_mapping',
                    has_segue=False,
                    needs_review=True
                )
        
        # Standard logic: try existing tag first
        if raw_title and setlist_songs:
            result = self.matcher.match(raw_title)
            matched_lower = result.matched_title.lower() if result.matched_title else ''
            
            # Detect suspicious tags that should prefer txt file
            is_suspicious = (
                raw_title.count('>') > 2 or  # Multiple segues suggests compound title
                ('jam' in raw_title.lower() and len(raw_title) > 40) or  # Long jam description
                result.needs_review  # Low confidence match
            )
            
            # Check if the matched song is in this show's setlist
            if matched_lower in setlist_songs:
                # Only trust high-confidence matches or non-suspicious tags
                if result.confidence >= AUTO_APPLY_THRESHOLD or not is_suspicious:
                    # Use the JerryBase canonical name from the setlist
                    return MatchResult(
                        original_title=result.original_title,
                        cleaned_title=result.cleaned_title,
                        matched_title=setlist_songs[matched_lower],
                        confidence=result.confidence,
                        match_source=result.match_source,
                        has_segue=result.has_segue,
                        needs_review=result.needs_review
                    )
                # Low confidence or suspicious - check txt file first
                txt_title = txt_mappings.get(flac_file.name)
                if txt_title:
                    txt_result = self.matcher.match(txt_title)
                    txt_matched_lower = txt_result.matched_title.lower() if txt_result.matched_title else ''
                    
                    if txt_matched_lower in setlist_songs:
                        return MatchResult(
                            original_title=raw_title,
                            cleaned_title=txt_result.cleaned_title,
                            matched_title=setlist_songs[txt_matched_lower],
                            confidence=txt_result.confidence,
                            match_source='txt_setlist',
                            has_segue=txt_result.has_segue,
                            needs_review=False
                        )
                # No txt file or txt doesn't match - use original low-confidence result
                return MatchResult(
                    original_title=result.original_title,
                    cleaned_title=result.cleaned_title,
                    matched_title=setlist_songs[matched_lower],
                    confidence=result.confidence,
                    match_source=result.match_source,
                    has_segue=result.has_segue,
                    needs_review=result.needs_review
                )
            
            # Matched song is NOT in this show's setlist - try txt file
            txt_title = txt_mappings.get(flac_file.name)
            if txt_title:
                txt_result = self.matcher.match(txt_title)
                txt_matched_lower = txt_result.matched_title.lower() if txt_result.matched_title else ''
                
                # Check if txt file's match is in the setlist
                if txt_matched_lower in setlist_songs:
                    # Use the JerryBase canonical name from the setlist
                    return MatchResult(
                        original_title=raw_title,  # Keep original for reference
                        cleaned_title=txt_result.cleaned_title,
                        matched_title=setlist_songs[txt_matched_lower],
                        confidence=txt_result.confidence,
                        match_source='txt_setlist',  # New source type
                        has_segue=txt_result.has_segue,
                        needs_review=False
                    )
        
        # Fallback: no setlist or no match - use original logic
        # If no title or generic title, try txt file
        if not raw_title or raw_title.lower().startswith('d') or raw_title.lower().startswith('t'):
            txt_title = txt_mappings.get(flac_file.name)
            if txt_title:
                raw_title = txt_title
        
        # Match the title
        return self.matcher.match(raw_title)
    
    def apply_updates(self, updates: List[FileTagUpdate]):
        """Apply tag updates to files."""
        for update in updates:
            if self.trial_mode:
                self._print_update(update)
            else:
                self._write_tags(update)
                self.processed_count += 1
    
    def _write_tags(self, update: FileTagUpdate):
        """Write tags to a FLAC file using mutagen."""
        try:
            audio = FLAC(str(update.file_path))
            
            # Set all tags
            audio['TITLE'] = update.title
            audio['ARTIST'] = update.artist
            audio['ALBUMARTIST'] = update.album_artist
            audio['ALBUM'] = update.album
            audio['GENRE'] = update.genre
            audio['VERSION'] = update.version  # Folder name to track recording version
            
            if update.date:
                audio['DATE'] = update.date
            
            audio['DISCNUMBER'] = str(update.disc_number)
            audio['DISCTOTAL'] = str(update.disc_total)
            audio['TRACKNUMBER'] = str(update.track_number)
            audio['TRACKTOTAL'] = str(update.track_total)
            
            # Remove legacy "Album Artist" tag if present (keep ALBUMARTIST)
            if 'ALBUM ARTIST' in audio:
                del audio['ALBUM ARTIST']
            
            audio.save()
            
        except Exception as e:
            print(f"  Error writing tags to {update.file_path.name}: {e}")
            self.skipped_count += 1
    
    def _safe_print(self, text: str) -> str:
        """Safely encode text for printing, replacing non-ASCII chars."""
        if not text:
            return ''
        return text.encode('ascii', 'replace').decode('ascii')
    
    def _print_update(self, update: FileTagUpdate):
        """Print what would be written (trial mode)."""
        print(f"  {self._safe_print(update.file_path.name)}")
        print(f"    TITLE: {self._safe_print(update.title)}")
        print(f"    ARTIST: {self._safe_print(update.artist)}")
        print(f"    ALBUM: {self._safe_print(update.album)}")
        print(f"    VERSION: {update.version}")
        print(f"    DISC: {update.disc_number}/{update.disc_total}")
        print(f"    TRACK: {update.track_number}/{update.track_total}")
        print(f"    Match: {update.match_source}" + (" [REVIEW]" if update.needs_review else ""))
    
    def _check_for_duplicate_titles(self, updates: List[FileTagUpdate], 
                                     setlist: List[Dict], txt_mappings: Dict[str, str],
                                     folder_name: str):
        """
        Check for unexpected duplicate song titles.
        
        Only warns if duplicates appear that are NOT in the JerryBase setlist
        or txt file. Legitimate duplicates (like 'Dark Star >' and 'Dark Star')
        are expected and not flagged.
        
        Args:
            updates: List of file tag updates
            setlist: JerryBase setlist for this show
            txt_mappings: Txt file mappings
            folder_name: Name of the show folder
        """
        # Count occurrences of each title (without segue marker for comparison)
        title_counts = {}
        title_files = {}
        for update in updates:
            # Normalize title by removing segue marker for counting
            base_title = update.title.rstrip(' >').strip()
            if base_title not in title_counts:
                title_counts[base_title] = 0
                title_files[base_title] = []
            title_counts[base_title] += 1
            title_files[base_title].append(update.file_path.name)
        
        # Get expected duplicates from setlist
        setlist_counts = {}
        if setlist:
            for song in setlist:
                base_song = song['song_name'].rstrip(' >').strip()
                setlist_counts[base_song] = setlist_counts.get(base_song, 0) + 1
        
        # Get expected duplicates from txt file
        txt_counts = {}
        for txt_title in txt_mappings.values():
            # Clean and normalize txt title
            base_txt = txt_title.rstrip(' >').strip()
            txt_counts[base_txt] = txt_counts.get(base_txt, 0) + 1
        
        # Check for unexpected duplicates
        for title, count in title_counts.items():
            if count > 1:
                # Check if this duplicate is expected
                expected_in_setlist = setlist_counts.get(title, 0) >= count
                expected_in_txt = txt_counts.get(title, 0) >= count
                
                if not expected_in_setlist and not expected_in_txt:
                    # This is an unexpected duplicate!
                    self.duplicate_warnings.append({
                        'folder': folder_name,
                        'song': title,
                        'count': count,
                        'files': title_files[title],
                        'setlist_count': setlist_counts.get(title, 0),
                        'txt_count': txt_counts.get(title, 0)
                    })
                    print(f"  WARNING: Unexpected duplicate song '{title}' appears {count} times")
                    print(f"    Expected in setlist: {setlist_counts.get(title, 0)} times")
                    print(f"    Expected in txt: {txt_counts.get(title, 0)} times")
                    print(f"    Files: {', '.join(title_files[title])}")
    
    def _validate_txt_file_coverage(self, flac_files: List[Path], 
                                      txt_mappings: Dict[str, str], folder_name: str,
                                      setlist: List[Dict] = None) -> bool:
        """
        Validate that txt file has mappings for all FLAC files.
        
        When --trust-txt is enabled, checks if the number of txt mappings
        matches the number of FLAC files. If not, the folder should be skipped
        to prevent cascading errors from incorrect mappings.
        
        Exception: If FLAC count exactly matches JerryBase setlist count,
        allow processing but still warn (could tag from JerryBase instead).
        
        Args:
            flac_files: List of FLAC files in the folder
            txt_mappings: Dict of filename -> song title from txt file
            folder_name: Name of the folder being processed
            setlist: JerryBase setlist for this show (if available)
            
        Returns:
            True if folder should be skipped, False if processing can continue
        """
        num_flac_files = len(flac_files)
        num_txt_mappings = len(txt_mappings)
        
        if num_flac_files == num_txt_mappings:
            # Perfect match - no issues
            return False
        
        # Mismatch detected
        print(f"  ⚠️  WARNING: Txt file track count mismatch!")
        print(f"    FLAC files in folder: {num_flac_files}")
        print(f"    Txt file mappings: {num_txt_mappings}")
        print(f"    Difference: {abs(num_flac_files - num_txt_mappings)} file(s)")
        
        # Find which files are missing txt mappings
        unmapped_files = [f.name for f in flac_files if f.name not in txt_mappings]
        if unmapped_files:
            print(f"    Files without txt mappings: {', '.join(unmapped_files)}")
        
        # Find txt mappings that don't have corresponding files
        missing_files = [fname for fname in txt_mappings.keys() 
                       if not any(f.name == fname for f in flac_files)]
        if missing_files:
            print(f"    Txt mappings without files: {', '.join(missing_files)}")
        
        print(f"    → This may indicate:")
        print(f"       - Missing tracks in txt file (extra songs, jam segments)")
        print(f"       - Txt file is for a different version/retracking")
        print(f"       - Numbering mismatch causing offset errors")
        
        # Check exception: does FLAC count match JerryBase setlist count?
        if setlist and len(setlist) == num_flac_files:
            print(f"    ⚠️  EXCEPTION: FLAC count ({num_flac_files}) matches JerryBase setlist count ({len(setlist)})")
            print(f"    → Allowing processing - will use JerryBase for matching")
            print(f"    → CAUTION: This match could be coincidental - please review results!")
            return False  # Don't skip - allow processing with JerryBase
        
        # No exception applies - must skip
        print(f"    ⛔ RESULT: Folder will be SKIPPED with --trust-txt enabled")
        print(f"    → Txt file mappings cannot be trusted")
        print(f"    → Incorrect mappings would cause cascading tagging errors")
        print(f"    → Fix txt file or run without --trust-txt to use fuzzy matching")
        
        return True  # Skip this folder
    
    def _process_artwork(self, folder_path: Path):
        """Process artwork for a show folder."""
        status = process_folder_artwork(folder_path, self.artwork_dir, self.trial_mode,
                                        self.artwork_primary)
        print(f"  Artwork: {status}")
        
        # Track stats
        if 'copied' in status:
            self.artwork_copied += 1
        elif 'not found' in status:
            self.artwork_not_found += 1
    
    def process_directory(self, root_path: Path, is_gd: int = 1,
                          num_pad_chars: int = 2, recursive: bool = True):
        """
        Process a directory of shows.
        
        Args:
            root_path: Root directory containing show folders
            is_gd: 1 for Grateful Dead, 0 for Jerry Garcia
            num_pad_chars: Number of prefix chars before date
            recursive: If True, process subdirectories
        """
        if not root_path.is_dir():
            print(f"Error: {root_path} is not a directory")
            return
        
        # Check if this is a show folder (contains FLAC files, not directories)
        flac_files = [f for f in root_path.glob('*.flac') if f.is_file()]
        
        if flac_files:
            # This is a show folder
            updates = self.process_folder(root_path, is_gd, num_pad_chars)
            self.apply_updates(updates)
            self._process_artwork(root_path)
        elif recursive:
            # Process subdirectories
            for subdir in sorted(root_path.iterdir()):
                if subdir.is_dir() and not subdir.name.startswith('.'):
                    # Check if subdir is a show folder (contains FLAC files, not directories)
                    if [f for f in subdir.glob('*.flac') if f.is_file()]:
                        updates = self.process_folder(subdir, is_gd, num_pad_chars)
                        self.apply_updates(updates)
                        self._process_artwork(subdir)
                    else:
                        # Recurse into year folders, etc.
                        self.process_directory(subdir, is_gd, num_pad_chars, recursive)
    
    def save_review_files(self):
        """Save review and unmatched files."""
        ensure_dirs()
        
        if self.review_matches:
            with open(REVIEW_MATCHES_PATH, 'w', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(f, fieldnames=['file_path', 'original_title', 
                                                       'suggested_match', 'confidence', 'action'])
                writer.writeheader()
                writer.writerows(self.review_matches)
            print(f"\nWrote {len(self.review_matches)} matches for review to {REVIEW_MATCHES_PATH}")
        
        if self.unmatched_songs:
            with open(UNMATCHED_SONGS_PATH, 'w', encoding='utf-8') as f:
                for item in self.unmatched_songs:
                    f.write(f"{item['file_path']}|{item['original_title']}|{item['cleaned_title']}\n")
            print(f"Wrote {len(self.unmatched_songs)} unmatched songs to {UNMATCHED_SONGS_PATH}")
        
        if self.segue_discrepancies:
            with open(SEGUE_LOG_PATH, 'w', encoding='utf-8') as f:
                f.write("Segue Discrepancies (JerryBase vs txt file)\n")
                f.write("=" * 60 + "\n")
                f.write("Segue applied if EITHER source indicates one.\n\n")
                for item in self.segue_discrepancies:
                    db_flag = '>' if item['db_segue'] else '(none)'
                    txt_flag = '>' if item['txt_segue'] else '(none)'
                    applied = '> applied' if item['applied'] else 'no segue'
                    f.write(f"{item['song']}\n")
                    f.write(f"  File:     {item['file_path']}\n")
                    f.write(f"  JerryBase: {db_flag}  |  Txt file: {txt_flag}  |  Result: {applied}\n\n")
            print(f"Wrote {len(self.segue_discrepancies)} segue discrepancies to {SEGUE_LOG_PATH}")
    
    def print_summary(self):
        """Print processing summary."""
        print(f"\n{'='*60}")
        print("SUMMARY")
        print(f"{'='*60}")
        if self.trial_mode:
            print("TRIAL MODE - No files were modified")
        else:
            print(f"Files processed: {self.processed_count}")
            print(f"Files skipped (errors): {self.skipped_count}")
        
        print(f"Matches needing review: {len(self.review_matches)}")
        print(f"Unmatched songs: {len(self.unmatched_songs)}")
        print(f"Segue discrepancies: {len(self.segue_discrepancies)}")
        print(f"Duplicate warnings: {len(self.duplicate_warnings)}")
        print(f"Artwork copied: {self.artwork_copied}")
        print(f"Artwork not found: {self.artwork_not_found}")


def main():
    parser = argparse.ArgumentParser(
        description='Auto-tag Grateful Dead and Jerry Garcia show recordings',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  Tag all Grateful Dead shows in a directory:
    python tagger.py /path/to/gd/shows --gd 1

  Tag Jerry Garcia shows:
    python tagger.py /path/to/jg/shows --gd 0

  Preview changes without writing (trial mode):
    python tagger.py /path/to/shows --trial

  Process a single show folder:
    python tagger.py /path/to/gd1977-05-08.sbd.miller.flac16 --gd 1

  Include artwork copying:
    python tagger.py /path/to/shows --artwork-dir /path/to/covers

  Trust txt file over existing FLAC tags (for retracked shows):
    python tagger.py /path/to/shows --trust-txt
        """
    )
    
    parser.add_argument('path', type=Path, help='Path to show folder or directory of shows')
    parser.add_argument('--gd', type=int, default=1, choices=[0, 1],
                        help='1 for Grateful Dead, 0 for Jerry Garcia (default: 1)')
    parser.add_argument('--pad', type=int, default=2,
                        help='Number of prefix chars before date in folder name (default: 2)')
    parser.add_argument('--db', type=Path, default=DEFAULT_DB_PATH,
                        help=f'Path to JerryBase.db (default: {DEFAULT_DB_PATH})')
    parser.add_argument('--trial', action='store_true',
                        help='Trial mode - preview changes without writing')
    parser.add_argument('--no-recursive', action='store_true',
                        help='Do not process subdirectories')
    parser.add_argument('--artwork-dir', type=Path, default=None,
                        help='Directory containing artwork files to copy if missing')
    parser.add_argument('--artwork-primary', action='store_true',
                        help='Use --artwork-dir as primary source (before parent folder). '
                             'Default is to use parent folder first, --artwork-dir as backup.')
    parser.add_argument('--trust-txt', action='store_true',
                        help='Prioritize txt file over existing FLAC tags. Use for retracked '
                             'shows where txt file is the source of truth.')
    
    args = parser.parse_args()
    
    if not args.path.exists():
        print(f"Error: Path does not exist: {args.path}")
        return 1
    
    if not args.db.exists():
        print(f"Warning: Database not found: {args.db}")
        print("Song matching will use fuzzy matching only")
    
    print("Auto-Tagger")
    print(f"{'='*60}")
    print(f"Path: {args.path}")
    print(f"Mode: {'Grateful Dead' if args.gd else 'Jerry Garcia'}")
    print(f"Database: {args.db}")
    print(f"Trial mode: {args.trial}")
    print(f"Trust txt file: {args.trust_txt}")
    if args.artwork_dir:
        priority = "primary" if args.artwork_primary else "backup"
        print(f"Artwork directory: {args.artwork_dir} ({priority})")
    print(f"{'='*60}")
    
    tagger = AutoTagger(db_path=args.db, trial_mode=args.trial, artwork_dir=args.artwork_dir,
                        artwork_primary=args.artwork_primary, trust_txt=args.trust_txt)
    tagger.process_directory(args.path, is_gd=args.gd, num_pad_chars=args.pad,
                             recursive=not args.no_recursive)
    tagger.save_review_files()
    tagger.print_summary()
    
    return 0


if __name__ == '__main__':
    exit(main())
