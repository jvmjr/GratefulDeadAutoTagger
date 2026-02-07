"""
Shared configuration and constants for the auto_tagger module.

This module centralizes all configurable settings including:
- File paths for data and logs
- Fuzzy matching thresholds
- Pattern definitions for segues, tape markers, and source types
"""

from pathlib import Path

# Base paths
AUTO_TAGGER_DIR = Path(__file__).parent

# Database
DEFAULT_DB_PATH = AUTO_TAGGER_DIR / "JerryBase.db"

# Log files
LOGS_DIR = AUTO_TAGGER_DIR / "logs"

# Data files
CORRECTIONS_MAP_PATH = AUTO_TAGGER_DIR / "corrections_map.csv"
EXTRA_SONGS_PATH = AUTO_TAGGER_DIR / "extra_songs.csv"
REVIEW_MATCHES_PATH = AUTO_TAGGER_DIR / "review_matches.csv"
UNMATCHED_SONGS_PATH = LOGS_DIR / "unmatched_songs.txt"
SEGUE_LOG_PATH = LOGS_DIR / "segue_discrepancies.log"

# Fuzzy matching thresholds
AUTO_APPLY_THRESHOLD = 85  # Auto-apply matches at or above this confidence
REVIEW_THRESHOLD = 75      # Write to review file at or above this confidence
                           # Below this, check extra songs or mark as unmatched

# Artwork settings
SQUARE_TOLERANCE = 0.05    # 5% tolerance for "approximately square" images

# Segue markers to detect and strip
SEGUE_MARKERS = [' ->', ' -->', '>>', ' >']

# Tape cut markers to strip
TAPE_MARKERS = ['//', '///', '////']

# Source type detection patterns (for album naming)
SOURCE_PATTERNS = {
    'sbd': ['sbd'],
    'aud': ['aud', 'nak', 'sony', 'akg', 'senn'],
    'fm': ['fm'],
    'tv': ['tv'],
    'fob': ['fob'],
    'studio': ['studio'],
    'gmb': ['gmb'],
    'pa': ['.pa.', '-pa-', '_pa_', 'pa.'],
    'mtx': ['mtx', 'matrix'],
}

# Genre to set for all files
DEFAULT_GENRE = "GD"

# Extra track patterns (non-songs that should be kept but normalized)
EXTRA_TRACK_PATTERNS = [
    'tuning', 'crowd', 'banter', 'applause', 'introduction', 'intro',
    'stage banter', 'band introductions', 'band intros', 'announcements',
    'soundcheck', 'warmup', 'fade in', 'fade out', 'cut', 'tape flip',
    'tape cut', 'unknown', 'encore break', 'technical', 'set break',
    'd1t', 'd2t', 'd3t', 'd4t',  # Track number patterns
]


def ensure_dirs():
    """Create necessary directories if they don't exist."""
    LOGS_DIR.mkdir(parents=True, exist_ok=True)


def is_extra_track(title: str) -> bool:
    """
    Check if a title represents a non-song extra track.
    
    Args:
        title: The song title to check
        
    Returns:
        True if this appears to be a non-song track (tuning, crowd, etc.)
    """
    title_lower = title.lower().strip()
    
    # Check for track number patterns like "d1t07"
    if len(title_lower) >= 4 and title_lower[0] == 'd' and title_lower[2] == 't':
        try:
            int(title_lower[1])
            int(title_lower[3:5])
            return True
        except (ValueError, IndexError):
            pass
    
    for pattern in EXTRA_TRACK_PATTERNS:
        if pattern in title_lower:
            return True
    
    return False
