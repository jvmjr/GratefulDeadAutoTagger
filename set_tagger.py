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
                     set_info: List[Dict]) -> List[TrackAssignment]:
        """
        Assign disc numbers to files based on setlist.
        
        Args:
            files: List of FLAC file paths in the show folder (sorted)
            setlist: List of song dicts from matcher.get_songs_for_date()
            set_info: List of set dicts from matcher.get_set_info_for_date()
            
        Returns:
            List of TrackAssignment objects
        """
        if not set_info:
            # No setlist - fall back to single disc
            return self._assign_single_disc(files)
        
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
        
        assignments = []
        current_set = 1
        last_known_set = 1
        
        # Build song-to-set mapping
        song_to_set = {}
        for song in setlist:
            song_to_set[song['song_name'].lower()] = song['set_seq']
        
        for file_path in files:
            # Get title from file (we'll match it later in the main tagger)
            try:
                audio = FLAC(str(file_path))
                raw_title = audio.get('TITLE', [''])[0] if audio.get('TITLE') else ''
            except:
                raw_title = ''
            
            # Match the title
            result = self.matcher.match(raw_title)
            matched_title = result.matched_title if result.matched_title else result.cleaned_title
            
            # Determine if this is an extra track
            is_extra = is_extra_track(raw_title) or result.match_source == 'extra'
            
            # Find which set this song belongs to
            if matched_title and matched_title.lower() in song_to_set:
                current_set = song_to_set[matched_title.lower()]
                last_known_set = current_set
            elif is_extra:
                # Extra tracks stay with the current/last known set
                current_set = last_known_set
            else:
                # Unknown song - keep in current set
                current_set = last_known_set
            
            assignments.append(TrackAssignment(
                file_path=file_path,
                disc_number=current_set,
                track_number=0,  # Will be assigned later
                title=matched_title or raw_title,
                is_extra=is_extra,
                matched_song=result.matched_title
            ))
        
        # Renumber tracks within each disc
        assignments = self._renumber_tracks(assignments)
        
        return assignments
    
    def _assign_single_disc(self, files: List[Path]) -> List[TrackAssignment]:
        """Fallback: assign all files to disc 1."""
        assignments = []
        
        for i, file_path in enumerate(files, 1):
            try:
                audio = FLAC(str(file_path))
                raw_title = audio.get('TITLE', [''])[0] if audio.get('TITLE') else ''
            except:
                raw_title = ''
            
            result = self.matcher.match(raw_title)
            matched_title = result.matched_title if result.matched_title else result.cleaned_title
            
            assignments.append(TrackAssignment(
                file_path=file_path,
                disc_number=1,
                track_number=i,
                title=matched_title or raw_title,
                is_extra=is_extra_track(raw_title),
                matched_song=result.matched_title
            ))
        
        return assignments
    
    def _renumber_tracks(self, assignments: List[TrackAssignment]) -> List[TrackAssignment]:
        """Renumber tracks sequentially within each disc."""
        # Group by disc
        disc_tracks: Dict[int, List[TrackAssignment]] = {}
        
        for assign in assignments:
            if assign.disc_number not in disc_tracks:
                disc_tracks[assign.disc_number] = []
            disc_tracks[assign.disc_number].append(assign)
        
        # Renumber within each disc
        for disc_num, tracks in disc_tracks.items():
            for i, track in enumerate(tracks, 1):
                track.track_number = i
        
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
