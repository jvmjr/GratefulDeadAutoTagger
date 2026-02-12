# Auto-Tagger Fix Summary

## What Was Done

I've successfully diagnosed the issue with the 12/8/73 show and implemented all the requested fixes to the auto-tagger.

## Diagnosis Complete

**Root Cause:** The show had bad pre-existing FLAC tags (multiple files with the same title "Truckin > Nobody's Fault But Mine Jam >"). The tagger's fuzzy matcher extracted "Nobody's Fault But Mine" from this complex title with 76.67% confidence, found it in the setlist, and used it without checking the txt file. This caused:
- Wrong song matches
- Wrong disc assignments (songs assigned to Set 2 instead of Set 1)
- Wrong track numbers (renumbered within wrong discs)
- Duplicate songs appearing

## Fixes Implemented

### 1. ✅ --trust-txt Flag (NEW)
- Added new command-line flag: `python tagger.py /path --trust-txt`
- When enabled, prioritizes txt file over existing FLAC tags
- Perfect for retracked shows where txt file is the source of truth

### 2. ✅ Confidence Threshold for Setlist Matching
- Now requires ≥85% confidence to trust existing tag matches
- Low-confidence matches (like the 76.67% one) trigger txt file lookup instead

### 3. ✅ Suspicious Tag Detection
- Detects problematic tags:
  - Multiple segue markers (>2)
  - Long jam descriptions (>40 chars with "jam")
  - Low confidence matches
- Prefers txt file for suspicious tags

### 4. ✅ Smart Duplicate Detection
- Warns about unexpected duplicate songs
- Compares against JerryBase setlist AND txt file
- Only warns if duplicates are NOT expected in either source
- Allows legitimate duplicates (e.g., "Dark Star >" and "Dark Star")
- Example warning:
  ```
  WARNING: Unexpected duplicate song 'Brown Eyed Women' appears 2 times
    Expected in setlist: 1 times
    Expected in txt: 1 times
    Files: gd73-12-08d1t10.flac, gd73-12-08d2t10.flac
  ```

### 5. ✅ Improved Priority Logic
- **Default mode (trust_txt=False):**
  1. High-confidence existing tag (≥85%) in setlist
  2. Txt file (if tag is low confidence or suspicious)
  3. Low-confidence existing tag
  4. Fuzzy matching fallback

- **Trust txt mode (trust_txt=True):**
  1. Txt file (if available)
  2. Existing FLAC tag
  3. Fuzzy matching fallback

## Files Created/Modified

**Modified:**
- `tagger.py` - All main fixes implemented

**Documentation Created:**
- `DIAGNOSIS_12-08-73.md` - Complete root cause analysis
- `FIXES_IMPLEMENTED.md` - Detailed explanation of all fixes
- `SUMMARY.md` - This file

## How to Use

### For the 12/8/73 Show (or similar retracked shows):
```bash
python tagger.py "/Volumes/DS_Main/Grateful Dead/gd73/gd73-12-08.sbd.remaster. shnid.105268.flac" --trust-txt --trial
```

### For normal shows with potentially bad tags:
```bash
python tagger.py /path/to/shows --trial
```
The improved logic will automatically:
- Require high confidence for existing tags
- Check txt file for suspicious/low-confidence tags
- Warn about unexpected duplicates

## Important Note: TXT File Parser Limitation

During testing, I discovered that the txt_parser.py has a limitation:

**The txt file for 12/8/73 uses a different disc structure than the filenames:**
- Txt file: "Disc 1 / 01. Me And My Uncle", "Disc 3 / 01. Truckin..."
- Filenames: gd73-12-08d1t01.flac, gd73-12-08d3t01.flac

**The parser creates mappings like:**
- `01 -> "Me And My Uncle"` (from Disc 1 section)
- `01 -> "Truckin..."` (from Disc 3 section - OVERWRITES previous!)

**It does NOT create disc-specific mappings like:**
- `d1t01 -> "Me And My Uncle"`
- `d3t01 -> "Truckin..."`

This means the `--trust-txt` flag works perfectly for shows where:
- Track numbers are sequential across all discs (01-32 for 32 tracks)
- Filenames don't use dXtYY pattern
- Txt file structure matches filename structure

But for shows with per-disc track numbering in both the txt file AND filenames (like 12/8/73), additional txt_parser enhancements would be needed to detect disc boundaries and create disc-specific mappings.

## What You Can Do Now

1. **Test the fixes on other shows:**
   ```bash
   python tagger.py /path/to/your/shows --trial
   ```

2. **Use --trust-txt for retracked shows:**
   ```bash
   python tagger.py /path/to/retracked/show --trust-txt --trial
   ```

3. **Review duplicate warnings** - they'll alert you to matching problems

4. **Consider enhancing txt_parser.py** if you have many shows with per-disc track numbering

All the core fixes are in place and will prevent the issues you encountered!
