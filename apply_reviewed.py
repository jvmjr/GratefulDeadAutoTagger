#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Apply reviewed matches from the review CSV file.

After running tagger.py, review_matches.csv contains lower-confidence
matches that need manual review. Edit that file to approve or correct
matches, then run this script to apply them.

Usage:
    python apply_reviewed.py
    python apply_reviewed.py --file /path/to/review_matches.csv
    python apply_reviewed.py --dry-run  # Preview without applying
"""

import argparse
import csv
from pathlib import Path

from mutagen.flac import FLAC

from config import REVIEW_MATCHES_PATH, CORRECTIONS_MAP_PATH


def load_corrections_map() -> dict:
    """Load existing corrections map (pipe-delimited)."""
    corrections = {}
    
    if CORRECTIONS_MAP_PATH.exists():
        with open(CORRECTIONS_MAP_PATH, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f, delimiter='|')
            for row in reader:
                original = row.get('original_title', '').lower().strip()
                canonical = row.get('canonical_title', '').strip()
                if original and canonical:
                    corrections[original] = canonical
    
    return corrections


def save_corrections_map(corrections: dict):
    """Save corrections map (pipe-delimited)."""
    with open(CORRECTIONS_MAP_PATH, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=['original_title', 'canonical_title', 'source'],
                                delimiter='|')
        writer.writeheader()
        for original, canonical in sorted(corrections.items()):
            writer.writerow({
                'original_title': original,
                'canonical_title': canonical,
                'source': 'reviewed'
            })


def apply_reviewed(review_path: Path, dry_run: bool = False):
    """
    Apply reviewed matches from CSV file.
    
    The 'action' column should contain:
    - Empty or 'y': Accept the suggested match
    - 'n': Reject (skip this file)
    - Any other text: Use as the custom title
    
    Args:
        review_path: Path to the review CSV file
        dry_run: If True, preview changes without applying
    """
    if not review_path.exists():
        print(f"Error: Review file not found: {review_path}")
        return
    
    corrections = load_corrections_map()
    applied = 0
    skipped = 0
    added_corrections = 0
    
    with open(review_path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        rows = list(reader)
    
    for row in rows:
        file_path = Path(row['file_path'])
        original_title = row['original_title']
        suggested_match = row['suggested_match']
        action = row.get('action', '').strip()
        
        if not file_path.exists():
            print(f"  File not found: {file_path}")
            skipped += 1
            continue
        
        # Determine final title
        if action.lower() == 'n':
            print(f"  Skipped: {file_path.name}")
            skipped += 1
            continue
        elif action == '' or action.lower() == 'y':
            final_title = suggested_match
        else:
            final_title = action  # Custom title
        
        if not final_title:
            print(f"  No title for: {file_path.name}")
            skipped += 1
            continue
        
        # Add to corrections map
        original_lower = original_title.lower().strip()
        if original_lower and original_lower not in corrections:
            corrections[original_lower] = final_title
            added_corrections += 1
        
        if dry_run:
            print(f"  Would set: {file_path.name} -> {final_title}")
        else:
            try:
                audio = FLAC(str(file_path))
                audio['TITLE'] = final_title
                audio.save()
                print(f"  Applied: {file_path.name} -> {final_title}")
                applied += 1
            except Exception as e:
                print(f"  Error: {file_path.name}: {e}")
                skipped += 1
    
    # Save updated corrections map
    if not dry_run and added_corrections > 0:
        save_corrections_map(corrections)
        print(f"\nAdded {added_corrections} new corrections to map")
    
    print(f"\nApplied: {applied}, Skipped: {skipped}")


def main():
    parser = argparse.ArgumentParser(
        description='Apply reviewed song title matches',
        epilog="""
Edit review_matches.csv before running:
- Leave 'action' empty or 'y' to accept suggested match
- Set 'action' to 'n' to skip the file
- Set 'action' to a custom title to use that instead
        """
    )
    
    parser.add_argument('--file', type=Path, default=REVIEW_MATCHES_PATH,
                        help=f'Path to review CSV (default: {REVIEW_MATCHES_PATH})')
    parser.add_argument('--dry-run', action='store_true',
                        help='Preview changes without applying')
    
    args = parser.parse_args()
    
    print(f"Applying reviewed matches from: {args.file}")
    if args.dry_run:
        print("DRY RUN - No files will be modified")
    print()
    
    apply_reviewed(args.file, dry_run=args.dry_run)


if __name__ == '__main__':
    main()
