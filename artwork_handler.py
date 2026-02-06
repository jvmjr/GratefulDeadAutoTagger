#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Artwork detection and copying for show folders.

Checks for existing artwork (embedded or in folder), then searches
a supplied directory for matching artwork files to copy.

Features:
- Detects embedded artwork in FLAC files
- Finds image files in show folders
- Checks if artwork is approximately square
- Searches multiple directories for matching artwork by date
- Copies artwork with smart renaming to avoid overwrites
"""

import re
import shutil
from pathlib import Path
from typing import Optional, List, Tuple

from mutagen.flac import FLAC

from config import SQUARE_TOLERANCE

# Supported image extensions
IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp', '.tiff'}


def get_image_dimensions(image_path: Path) -> Optional[Tuple[int, int]]:
    """
    Get width and height of an image file.
    
    Uses PIL/Pillow if available, falls back to header parsing for
    common formats (PNG, JPEG).
    
    Args:
        image_path: Path to the image file
        
    Returns:
        Tuple of (width, height) or None if unable to read
    """
    try:
        # Try using PIL/Pillow if available
        from PIL import Image
        with Image.open(image_path) as img:
            return img.size
    except ImportError:
        pass
    except Exception:
        pass
    
    # Fallback: try to read image header manually for common formats
    try:
        with open(image_path, 'rb') as f:
            header = f.read(32)
            
            # PNG: width/height at bytes 16-24
            if header[:8] == b'\x89PNG\r\n\x1a\n':
                import struct
                width = struct.unpack('>I', header[16:20])[0]
                height = struct.unpack('>I', header[20:24])[0]
                return (width, height)
            
            # JPEG: need to parse markers
            if header[:2] == b'\xff\xd8':
                f.seek(0)
                data = f.read()
                i = 2
                while i < len(data) - 8:
                    if data[i] != 0xFF:
                        i += 1
                        continue
                    marker = data[i+1]
                    if marker in (0xC0, 0xC1, 0xC2):  # SOF markers
                        height = (data[i+5] << 8) | data[i+6]
                        width = (data[i+7] << 8) | data[i+8]
                        return (width, height)
                    if marker == 0xD9:  # EOI
                        break
                    length = (data[i+2] << 8) | data[i+3]
                    i += 2 + length
    except Exception:
        pass
    
    return None


def is_approximately_square(image_path: Path) -> bool:
    """
    Check if an image is approximately square (within tolerance).
    
    Args:
        image_path: Path to the image file
        
    Returns:
        True if image is square or approximately square (within configured tolerance)
    """
    dimensions = get_image_dimensions(image_path)
    if dimensions is None:
        # If we can't read dimensions, assume it's okay
        return True
    
    width, height = dimensions
    if width == 0 or height == 0:
        return True
    
    ratio = width / height
    # Check if ratio is within tolerance of 1.0
    return abs(ratio - 1.0) <= SQUARE_TOLERANCE


def has_embedded_artwork(folder_path: Path) -> bool:
    """
    Check if any FLAC file in the folder has embedded artwork.
    
    Args:
        folder_path: Path to the show folder
        
    Returns:
        True if any FLAC has embedded pictures
    """
    flac_files = list(folder_path.glob('*.flac'))
    
    for flac_path in flac_files:
        try:
            audio = FLAC(str(flac_path))
            if audio.pictures:
                return True
        except Exception:
            continue
    
    return False


def has_folder_artwork(folder_path: Path, require_square: bool = True) -> bool:
    """
    Check if the folder contains any image files.
    
    Args:
        folder_path: Path to the show folder
        require_square: If True, only count square/approximately square images
        
    Returns:
        True if folder contains (square) image files
    """
    images = get_folder_artwork_files(folder_path)
    
    if not images:
        return False
    
    if not require_square:
        return True
    
    # Check if any image is approximately square
    for img in images:
        if is_approximately_square(img):
            return True
    
    return False


def get_folder_artwork_files(folder_path: Path) -> List[Path]:
    """
    Get list of image files in the folder.
    
    Args:
        folder_path: Path to the show folder
        
    Returns:
        List of image file paths
    """
    images = []
    for ext in IMAGE_EXTENSIONS:
        images.extend(folder_path.glob(f'*{ext}'))
        images.extend(folder_path.glob(f'*{ext.upper()}'))
    return images


def extract_band_and_date(folder_name: str) -> Optional[tuple]:
    """
    Extract band prefix and date from folder name.
    
    Args:
        folder_name: Name of the show folder (e.g., 'gd1977-05-26.matrix.tobin.flac16')
        
    Returns:
        Tuple of (band, year_2digit, month, day) or None if not parseable
    """
    # Pattern for band prefix + date (2 or 4 digit year)
    # Examples: gd77-05-26, gd1977-05-26, jgb74-02-15, jgb1974-02-15
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


def find_matching_artwork(folder_name: str, artwork_dir: Path) -> Optional[Path]:
    """
    Find artwork file matching the show date in the artwork directory.
    
    Searches the directory and subdirectories for matching artwork.
    Supports multiple naming patterns:
    - gd77-05-26.* (band + 2-digit year)
    - 1977-05-26.* (4-digit year, no band prefix)
    
    Args:
        folder_name: Name of the show folder
        artwork_dir: Path to directory containing artwork files
        
    Returns:
        Path to matching artwork file, or None if not found
    """
    if not artwork_dir.exists():
        return None
    
    parsed = extract_band_and_date(folder_name)
    if not parsed:
        return None
    
    band, year_2digit, month, day = parsed
    
    # Calculate 4-digit year
    year_4digit = f"19{year_2digit}" if int(year_2digit) >= 60 else f"20{year_2digit}"
    
    # Build search patterns
    search_patterns = [
        f"{band}{year_2digit}-{month}-{day}",  # gd77-05-26
        f"{year_4digit}-{month}-{day}",         # 1977-05-26
        f"{band}{year_4digit}-{month}-{day}",   # gd1977-05-26
    ]
    
    # Search in main directory and subdirectories (including year folders)
    search_dirs = [artwork_dir]
    
    # Add year subdirectory if it exists
    year_subdir = artwork_dir / year_4digit
    if year_subdir.exists():
        search_dirs.append(year_subdir)
    
    # Also check for any subdirectories that might contain artwork
    for subdir in artwork_dir.iterdir():
        if subdir.is_dir() and subdir not in search_dirs:
            search_dirs.append(subdir)
    
    # Search each directory with each pattern
    for search_dir in search_dirs:
        for prefix in search_patterns:
            for ext in IMAGE_EXTENSIONS:
                # Try lowercase extension
                pattern = f"{prefix}*{ext}"
                matches = list(search_dir.glob(pattern))
                if matches:
                    return matches[0]
                
                # Try uppercase extension
                pattern = f"{prefix}*{ext.upper()}"
                matches = list(search_dir.glob(pattern))
                if matches:
                    return matches[0]
    
    return None


def copy_artwork_to_folder(artwork_path: Path, dest_folder: Path) -> Optional[str]:
    """
    Copy artwork file to destination folder.
    
    If a file with the same name exists, rename the new file to avoid overwriting.
    
    Args:
        artwork_path: Path to source artwork file
        dest_folder: Path to destination folder
        
    Returns:
        Name of the copied file, or None if failed
    """
    try:
        dest_name = artwork_path.name
        dest_path = dest_folder / dest_name
        
        # If file exists, find a unique name
        if dest_path.exists():
            stem = artwork_path.stem
            suffix = artwork_path.suffix
            counter = 1
            while dest_path.exists():
                dest_name = f"{stem}_cover{counter}{suffix}"
                dest_path = dest_folder / dest_name
                counter += 1
        
        shutil.copy2(artwork_path, dest_path)
        return dest_name
    except Exception as e:
        print(f"  Error copying artwork: {e}")
        return None


def find_artwork_dir_in_parent(folder_path: Path) -> Optional[Path]:
    """
    Look for an artwork directory in the parent folder.
    
    Searches for subdirectories that appear to be artwork folders based on naming.
    Avoids matching show folders that happen to contain 'art' in their names.
    
    Args:
        folder_path: Path to the show folder
        
    Returns:
        Path to artwork directory if found, None otherwise
    """
    parent = folder_path.parent
    
    if not parent.exists():
        return None
    
    # Look for directories that are likely artwork folders
    # Check each subdirectory in parent
    for subdir in parent.iterdir():
        if not subdir.is_dir() or subdir == folder_path:
            continue
        
        name_lower = subdir.name.lower()
        
        # Skip if this looks like a show folder (contains date pattern)
        if re.search(r'\d{2,4}-\d{2}-\d{2}', subdir.name):
            continue
        
        # Check for artwork-related names
        # Be specific: look for 'cover' or 'artwork' as words, not just substrings
        is_artwork_dir = False
        
        # Check for common artwork folder patterns
        if 'cover' in name_lower:  # Covers, Dead_Covers-78, etc.
            is_artwork_dir = True
        elif 'artwork' in name_lower:  # artwork, Artwork
            is_artwork_dir = True
        elif name_lower in ('art', 'arts', 'images', 'pics', 'pictures'):
            # Exact matches for short common names
            is_artwork_dir = True
        
        if is_artwork_dir:
            # Verify it contains image files
            for ext in IMAGE_EXTENSIONS:
                if list(subdir.glob(f'*{ext}')) or list(subdir.glob(f'*{ext.upper()}')):
                    return subdir
    
    return None


def process_folder_artwork(folder_path: Path, artwork_dir: Optional[Path] = None, 
                          trial: bool = False, artwork_primary: bool = False) -> str:
    """
    Process artwork for a show folder.
    
    Checks for existing artwork first, then searches artwork directories.
    If existing artwork is not square, searches for replacement.
    
    Args:
        folder_path: Path to the show folder
        artwork_dir: Optional path to artwork source directory
        trial: If True, don't actually copy files
        artwork_primary: If True, CLI artwork_dir is checked before parent folder.
                        If False (default), parent folder is checked first, CLI dir is backup.
        
    Returns:
        Status string describing what was found/done
    """
    folder_name = folder_path.name
    
    # Check for embedded artwork
    if has_embedded_artwork(folder_path):
        return "embedded (skipped)"
    
    # Check for folder artwork (square only)
    folder_images = get_folder_artwork_files(folder_path)
    has_square = False
    non_square_images = []
    
    for img in folder_images:
        if is_approximately_square(img):
            has_square = True
            break
        else:
            non_square_images.append(img)
    
    if has_square:
        # Find the first square image for display
        for img in folder_images:
            if is_approximately_square(img):
                return f"found in folder: {img.name} (skipped)"
    
    # If we have non-square images, we'll look for replacement
    needs_replacement = len(non_square_images) > 0
    
    # Build list of artwork directories to search in order
    search_dirs = []
    parent_artwork_dir = find_artwork_dir_in_parent(folder_path)
    
    if artwork_primary:
        # CLI artwork_dir first, then parent folder
        if artwork_dir:
            search_dirs.append(artwork_dir)
        if parent_artwork_dir:
            search_dirs.append(parent_artwork_dir)
    else:
        # Parent folder first, then CLI artwork_dir as backup
        if parent_artwork_dir:
            search_dirs.append(parent_artwork_dir)
        if artwork_dir:
            search_dirs.append(artwork_dir)
    
    if not search_dirs:
        if needs_replacement:
            return f"non-square: {non_square_images[0].name} (no replacement found)"
        return "not found (no artwork directory)"
    
    # Search each directory in order
    matching_artwork = None
    for search_dir in search_dirs:
        matching_artwork = find_matching_artwork(folder_name, search_dir)
        if matching_artwork:
            break
    
    if matching_artwork:
        if trial:
            if needs_replacement:
                return f"non-square: {non_square_images[0].name}, would copy {matching_artwork.name}"
            return f"would copy {matching_artwork.name}"
        else:
            copied_name = copy_artwork_to_folder(matching_artwork, folder_path)
            if copied_name:
                if needs_replacement:
                    return f"non-square replaced: copied {copied_name}"
                return f"copied {copied_name}"
            else:
                return f"failed to copy {matching_artwork.name}"
    
    if needs_replacement:
        return f"non-square: {non_square_images[0].name} (no replacement found)"
    return "not found in artwork directory"
