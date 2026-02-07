#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Set/Disc tagging module.

Assigns DISCNUMBER based on musical sets from JerryBase and renumbers tracks.
- Set 1 -> DISCNUMBER 1
- Set 2 -> DISCNUMBER 2
- Encore (+ extras between last song and encore) -> Final DISCNUMBER

Also sets TRACKTOTAL per disc and DISCTOTAL for the show.
"""

from pathlib import Path
from typing import Optional, List, Dict, Tuple
from dataclasses import dataclass

from mutagen.flac import FLAC

from song_matcher import SongMatcher, MatchResult
from config import is_extra_track


@dataclass
class TrackAssignment:
    """Track assignment with disc and track numbers."""
    file_path: Path
    disc_number: int
    track_number: int
    title: str
    is_extra: bool
    matched_song: Optional[str] = None


class SetTagger:
    """
    Assigns set/disc numbers and renumbers tracks based on JerryBase setlist.
    
    Maps songs to their musical sets (Set 1, Set 2, Encore) and assigns
    DISCNUMBER accordingly. Extra tracks (tuning, crowd noise) are grouped
    with the set they appear in.
    """
    
    def __init__(self, matcher: SongMatcher):
        """
        Initialize the set tagger.
        
        Args:
            matcher: SongMatcher instance for title matching
        """
        self.matcher = matcher
    
    def get_set_for_song(self, song_name: str, setlist: List[Dict]) -> Optional[int]:
        """
        Find which set a song belongs to.
        
        Args:
            song_name: Canonical song name
            setlist: List of song dicts from matcher.get_songs_for_date()
            
        Returns:
            Set sequence number or None if not found
        """
        song_lower = song_name.lower()
        
        for song in setlist:
            if song['song_name'].lower() == song_lower:
                return song['set_seq']
        
        return None
    
    def assign_discs(self, files: List[Path], setlist: List[Dict], 
                     set_info: List[Dict], match_results: List = None) -> List[TrackAssignment]:
        """
        Assign disc numbers to files based on setlist.
        
        Args:
            files: List of FLAC file paths in the show folder (sorted)
            setlist: List of song dicts from matcher.get_songs_for_date()
            set_info: List of set dicts from matcher.get_set_info_for_date()
            match_results: Optional pre-matched results from tagger._process_file()
                          If provided, uses these instead of doing its own matching
            
        Returns:
            List of TrackAssignment objects
        """
        if not set_info:
            # No setlist - fall back to single disc
            return self._assign_single_disc(files, match_results)
        
        # Build set structure
        num_sets = len(set_info)
        encore_set = None
        
        for info in set_info:
            if info['encore']:
                encore_set = info['set_seq']
                break
        
        # If no encore set, the last set is the encore
        if encore_set is None and set_info:
            encore_set = set_info[-1]['set_seq']
        
        # Build song-to-set mapping
        song_to_set = {}
        for song in setlist:
            song_to_set[song['song_name'].lower()] = song['set_seq']
        
        # First pass: gather all track info and identify real songs vs extras
        track_info = []
        for i, file_path in enumerate(files):
            # Use pre-matched results if available, otherwise do our own matching
            if match_results and i < len(match_results):
                result = match_results[i]
                matched_title = result.matched_title if result.matched_title else result.cleaned_title
                raw_title = result.original_title
                is_extra = result.match_source == 'extra'
            else:
                # Fallback: read from file and match
                try:
                    audio = FLAC(str(file_path))
                    raw_title = audio.get('TITLE', [''])[0] if audio.get('TITLE') else ''
                except:
                    raw_title = ''
                
                result = self.matcher.match(raw_title)
                matched_title = result.matched_title if result.matched_title else result.cleaned_title
                is_extra = is_extra_track(raw_title) or result.match_source == 'extra'
            
            # Find which set this song belongs to (None for extras/unknowns)
            song_set = None
            if matched_title and matched_title.lower() in song_to_set:
                song_set = song_to_set[matched_title.lower()]
            
            track_info.append({
                'file_path': file_path,
                'matched_title': matched_title,
                'raw_title': raw_title,
                'is_extra': is_extra,
                'song_set': song_set,
                'matched_song': result.matched_title if hasattr(result, 'matched_title') else matched_title
            })
        
        # Second pass: assign disc numbers
        # Extra tracks attach to the NEXT real song's set (look ahead)
        assignments = []
        
        for i, info in enumerate(track_info):
            if info['song_set'] is not None:
                # Real song with known set
                disc_number = info['song_set']
            elif info['is_extra']:
                # Extra track - look ahead for next real song's set
                disc_number = self._find_next_song_set(track_info, i, song_to_set)
                if disc_number is None:
                    # No next song found - fall back to previous song's set
                    disc_number = self._find_prev_song_set(track_info, i, song_to_set)
                if disc_number is None:
                    disc_number = 1  # Ultimate fallback
            else:
                # Unknown song (not extra, not in setlist) - use previous song's set
                disc_number = self._find_prev_song_set(track_info, i, song_to_set)
                if disc_number is None:
                    disc_number = 1
            
            assignments.append(TrackAssignment(
                file_path=info['file_path'],
                disc_number=disc_number,
                track_number=0,  # Will be assigned later
                title=info['matched_title'] or info['raw_title'],
                is_extra=info['is_extra'],
                matched_song=info['matched_song']
            ))
        
        # Renumber tracks within each disc
        assignments = self._renumber_tracks(assignments)
        
        return assignments
    
    def _find_next_song_set(self, track_info: List[Dict], current_idx: int,
                            song_to_set: Dict[str, int]) -> Optional[int]:
        """
        Look ahead to find the next real song's set.
        
        Args:
            track_info: List of track info dicts
            current_idx: Current position in the list
            song_to_set: Mapping of song names to set numbers
            
        Returns:
            Set number of next real song, or None if not found
        """
        for i in range(current_idx + 1, len(track_info)):
            if track_info[i]['song_set'] is not None:
                return track_info[i]['song_set']
        return None
    
    def _find_prev_song_set(self, track_info: List[Dict], current_idx: int,
                            song_to_set: Dict[str, int]) -> Optional[int]:
        """
        Look back to find the previous real song's set.
        
        Args:
            track_info: List of track info dicts
            current_idx: Current position in the list
            song_to_set: Mapping of song names to set numbers
            
        Returns:
            Set number of previous real song, or None if not found
        """
        for i in range(current_idx - 1, -1, -1):
            if track_info[i]['song_set'] is not None:
                return track_info[i]['song_set']
        return None
    
    def _assign_single_disc(self, files: List[Path], match_results: List = None) -> List[TrackAssignment]:
        """Fallback: assign all files to disc 1."""
        assignments = []
        
        for i, file_path in enumerate(files, 1):
            # Use pre-matched results if available
            if match_results and (i-1) < len(match_results):
                result = match_results[i-1]
                matched_title = result.matched_title if result.matched_title else result.cleaned_title
                raw_title = result.original_title
                is_extra = result.match_source == 'extra'
            else:
                try:
                    audio = FLAC(str(file_path))
                    raw_title = audio.get('TITLE', [''])[0] if audio.get('TITLE') else ''
                except:
                    raw_title = ''
                
                result = self.matcher.match(raw_title)
                matched_title = result.matched_title if result.matched_title else result.cleaned_title
                is_extra = is_extra_track(raw_title)
            
            assignments.append(TrackAssignment(
                file_path=file_path,
                disc_number=1,
                track_number=i,
                title=matched_title or raw_title,
                is_extra=is_extra,
                matched_song=result.matched_title if hasattr(result, 'matched_title') else matched_title
            ))
        
        return assignments
    
    def _renumber_tracks(self, assignments: List[TrackAssignment]) -> List[TrackAssignment]:
        """
        Renumber tracks sequentially within each disc while preserving file order.
        
        The assignments list is assumed to be in physical file order. This method
        assigns track numbers within each disc based on that order, ensuring that
        files maintain their physical sequence.
        """
        # Track the next track number for each disc
        disc_track_numbers: Dict[int, int] = {}
        
        # Process in the order given (which should be file order)
        for assign in assignments:
            disc_num = assign.disc_number
            
            # Initialize or increment track number for this disc
            if disc_num not in disc_track_numbers:
                disc_track_numbers[disc_num] = 1
            else:
                disc_track_numbers[disc_num] += 1
            
            assign.track_number = disc_track_numbers[disc_num]
        
        return assignments
    
    def get_totals(self, assignments: List[TrackAssignment]) -> Tuple[int, Dict[int, int]]:
        """
        Calculate disc total and track totals.
        
        Args:
            assignments: List of track assignments
        
        Returns:
            Tuple of (disc_total, {disc_number: track_total})
        """
        disc_track_counts: Dict[int, int] = {}
        
        for assign in assignments:
            disc_num = assign.disc_number
            if disc_num not in disc_track_counts:
                disc_track_counts[disc_num] = 0
            disc_track_counts[disc_num] += 1
        
        disc_total = len(disc_track_counts)
        
        return (disc_total, disc_track_counts)


def assign_extras_to_encore(assignments: List[TrackAssignment], 
                            set_info: List[Dict]) -> List[TrackAssignment]:
    """
    Move extras that occur after the last non-encore song to the encore disc.
    
    This handles crowd noise, encore break, etc. between set closer and encore.
    
    Args:
        assignments: List of track assignments
        set_info: Set information from database
        
    Returns:
        Updated list of track assignments
    """
    if not set_info:
        return assignments
    
    # Find the encore set number
    encore_set = None
    non_encore_sets = []
    
    for info in set_info:
        if info['encore']:
            encore_set = info['set_seq']
        else:
            non_encore_sets.append(info['set_seq'])
    
    if encore_set is None:
        return assignments
    
    # Find the last non-encore song
    last_non_encore_idx = -1
    
    for i, assign in enumerate(assignments):
        if not assign.is_extra and assign.disc_number in non_encore_sets:
            last_non_encore_idx = i
    
    # Move extras after last non-encore song to encore disc
    if last_non_encore_idx >= 0:
        for i in range(last_non_encore_idx + 1, len(assignments)):
            if assignments[i].is_extra:
                assignments[i].disc_number = encore_set
    
    return assignments
