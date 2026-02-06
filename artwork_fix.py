#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Fix incorrectly-added artwork by replacing with correct source.

This script identifies artwork that was incorrectly copied from one source
(e.g., dp-project) and replaces it with artwork from the correct source
(e.g., Dead_Covers-78).

Only replaces artwork if:
1. The folder has artwork that matches the "wrong source" (by file hash)
2. A matching file exists in the "correct source"

Usage:
    python artwork_fix.py /path/to/gd78 \\
        --wrong-source /path/to/dp-project/covers \\
        --correct-source /path/to/Dead_Covers-78

    # Preview without making changes
    python artwork_fix.py /path/to/gd78 \\
        --wrong-source /path/to/dp-project/covers \\
        --correct-source /path/to/Dead_Covers-78 \\
        --trial
"""

import argparse
import hashlib
import os
import re
import shutil
from pathlib import Path
from typing import Optional, List, Tuple, Dict

# Supported image extensions
IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp', '.tiff'}


def get_file_hash(file_path: Path) -> str:
    """Calculate MD5 hash of a file."""
    hasher = hashlib.md5()
    with open(file_path, 'rb') as f:
        for chunk in iter(lambda: f.read(8192), b''):
            hasher.update(chunk)
    return hasher.hexdigest()


def get_image_files(folder: Path) -> List[Path]:
    """Get all image files in a folder."""
    images = []
    for ext in IMAGE_EXTENSIONS:
        images.extend(folder.glob(f'*{ext}'))
        images.extend(folder.glob(f'*{ext.upper()}'))
    return images


def extract_date_from_folder(folder_name: str) -> Optional[Tuple[str, str, str, str]]:
    """
    Extract band prefix and date from folder name.
    
    Returns (band, year_2digit, month, day) or None.
    """
    # Pattern for band prefix + date (2 or 4 digit year)
    pattern = r'^([a-zA-Z]{2,4})(\d{2,4})-(\d{2})-(\d{2})'
    
    match = re.match(pattern, folder_name)
    if not match:
        return None
    
    band = match.group(1).lower()
    year = match.group(2)
    month = match.group(3)
    day = match.group(4)
    
    # Convert to 2-digit year
    if len(year) == 4:
        year_2digit = year[2:]
    else:
        year_2digit = year
    
    return (band, year_2digit, month, day)


def find_matching_artwork_in_source(folder_name: str, source_dir: Path) -> Optional[Path]:
    """
    Find artwork matching the show date in a source directory.
    
    Searches subdirectories as well.
    """
    if not source_dir.exists():
        return None
    
    parsed = extract_date_from_folder(folder_name)
    if not parsed:
        return None
    
    band, year_2digit, month, day = parsed
    year_4digit = f"19{year_2digit}" if int(year_2digit) >= 60 else f"20{year_2digit}"
    
    # Search patterns
    search_patterns = [
        f"{band}{year_2digit}-{month}-{day}",   # gd78-12-13
        f"{year_4digit}-{month}-{day}",          # 1978-12-13
        f"{band}{year_4digit}-{month}-{day}",    # gd1978-12-13
    ]
    
    # Build list of directories to search
    search_dirs = [source_dir]
    
    # Add subdirectories
    for subdir in source_dir.iterdir():
        if subdir.is_dir():
            search_dirs.append(subdir)
    
    # Search
    for search_dir in search_dirs:
        for prefix in search_patterns:
            for ext in IMAGE_EXTENSIONS:
                pattern = f"{prefix}*{ext}"
                matches = list(search_dir.glob(pattern))
                if matches:
                    return matches[0]
                
                pattern = f"{prefix}*{ext.upper()}"
                matches = list(search_dir.glob(pattern))
                if matches:
                    return matches[0]
    
    return None


def process_folder(show_folder: Path, wrong_source: Path, correct_source: Path,
                   trial: bool = False) -> Tuple[str, Optional[str]]:
    """
    Process a single show folder.
    
    Returns (status, details) tuple.
    """
    folder_name = show_folder.name
    
    # Get artwork in the show folder
    folder_images = get_image_files(show_folder)
    
    if not folder_images:
        return ("no_artwork", None)
    
    # Find matching artwork in wrong source (dp-project)
    wrong_artwork = find_matching_artwork_in_source(folder_name, wrong_source)
    
    if not wrong_artwork:
        return ("no_wrong_source_match", None)
    
    # Calculate hash of wrong source artwork
    wrong_hash = get_file_hash(wrong_artwork)
    
    # Check if any folder artwork matches the wrong source
    matching_folder_image = None
    for folder_image in folder_images:
        folder_hash = get_file_hash(folder_image)
        if folder_hash == wrong_hash:
            matching_folder_image = folder_image
            break
    
    if not matching_folder_image:
        return ("original_artwork", f"artwork doesn't match wrong source")
    
    # Found artwork that matches wrong source - look for replacement
    correct_artwork = find_matching_artwork_in_source(folder_name, correct_source)
    
    if not correct_artwork:
        return ("no_correct_source", f"has wrong artwork but no replacement found")
    
    # Replace the artwork
    if trial:
        return ("would_replace", f"{matching_folder_image.name} -> {correct_artwork.name}")
    else:
        try:
            # Remove the wrong artwork
            matching_folder_image.unlink()
            
            # Copy the correct artwork (keep original filename from correct source)
            dest_path = show_folder / correct_artwork.name
            
            # Handle name collision
            if dest_path.exists():
                stem = correct_artwork.stem
                suffix = correct_artwork.suffix
                counter = 1
                while dest_path.exists():
                    dest_path = show_folder / f"{stem}_{counter}{suffix}"
                    counter += 1
            
            shutil.copy2(correct_artwork, dest_path)
            return ("replaced", f"{matching_folder_image.name} -> {dest_path.name}")
        except Exception as e:
            return ("error", str(e))


def main():
    parser = argparse.ArgumentParser(
        description='Fix incorrectly-added artwork by replacing with correct source',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Example:
    python artwork_fix.py /Volumes/DS_Main/Grateful\\ Dead/gd78 \\
        --wrong-source /Users/johnmulvaney/Projects/dp-project/covers \\
        --correct-source /Volumes/DS_Main/Grateful\\ Dead/gd78/Dead_Covers-78 \\
        --trial
        """
    )
    
    parser.add_argument('path', type=Path,
                        help='Path to directory containing show folders')
    parser.add_argument('--wrong-source', type=Path, required=True,
                        help='Path to the incorrectly-used artwork source (e.g., dp-project/covers)')
    parser.add_argument('--correct-source', type=Path, required=True,
                        help='Path to the correct artwork source (e.g., Dead_Covers-78)')
    parser.add_argument('--trial', action='store_true',
                        help='Preview changes without making them')
    
    args = parser.parse_args()
    
    if not args.path.exists():
        print(f"Error: Path does not exist: {args.path}")
        return 1
    
    if not args.wrong_source.exists():
        print(f"Error: Wrong source does not exist: {args.wrong_source}")
        return 1
    
    if not args.correct_source.exists():
        print(f"Error: Correct source does not exist: {args.correct_source}")
        return 1
    
    print("Artwork Fix")
    print("=" * 60)
    print(f"Show directory: {args.path}")
    print(f"Wrong source: {args.wrong_source}")
    print(f"Correct source: {args.correct_source}")
    print(f"Trial mode: {args.trial}")
    print("=" * 60)
    
    # Collect stats
    stats = {
        'no_artwork': 0,
        'no_wrong_source_match': 0,
        'original_artwork': 0,
        'no_correct_source': 0,
        'would_replace': 0,
        'replaced': 0,
        'error': 0,
    }
    
    # Process each show folder
    show_folders = []
    
    # Check if path itself contains FLAC files (single show)
    # Must be actual files, not directories ending in .flac
    flac_files = [f for f in args.path.glob('*.flac') if f.is_file()]
    if flac_files:
        show_folders = [args.path]
    else:
        # Get all subdirectories that look like show folders
        for subdir in sorted(args.path.iterdir()):
            if subdir.is_dir() and not subdir.name.startswith('.'):
                # Check for date pattern in name
                if re.search(r'\d{2,4}-\d{2}-\d{2}', subdir.name):
                    show_folders.append(subdir)
    
    print(f"\nProcessing {len(show_folders)} show folders...\n")
    
    for show_folder in show_folders:
        status, details = process_folder(
            show_folder, args.wrong_source, args.correct_source, args.trial
        )
        
        stats[status] += 1
        
        # Print interesting cases
        if status in ('would_replace', 'replaced', 'no_correct_source', 'error'):
            print(f"{show_folder.name}: {status}")
            if details:
                print(f"  {details}")
    
    # Print summary
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"Folders with no artwork: {stats['no_artwork']}")
    print(f"Original artwork (kept): {stats['original_artwork']}")
    print(f"No match in wrong source: {stats['no_wrong_source_match']}")
    print(f"Wrong artwork, no replacement: {stats['no_correct_source']}")
    if args.trial:
        print(f"Would replace: {stats['would_replace']}")
    else:
        print(f"Replaced: {stats['replaced']}")
    print(f"Errors: {stats['error']}")
    
    return 0


if __name__ == '__main__':
    exit(main())
