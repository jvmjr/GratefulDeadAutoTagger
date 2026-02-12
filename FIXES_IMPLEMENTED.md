# Fixes Implemented for Auto-Tagger

**Date:** February 7, 2026  
**Issue:** Songs tagged with wrong titles, wrong disc numbers, and wrong track numbers

---

## Summary of Changes

The auto-tagger has been enhanced with five major improvements to prevent mismatching issues like the one that occurred with the 12/8/73 show:

### 1. **--trust-txt Flag** (NEW)

Added a new command-line flag `--trust-txt` that prioritizes the txt file over existing FLAC tags.

**Usage:**
```bash
python tagger.py /path/to/shows --trust-txt
```

**When to use:**
- Retracked shows where the txt file reflects the actual disc structure
- Shows with bad or incorrect pre-existing FLAC tags
- When you want the txt file to be the source of truth

**How it works:**
- When `--trust-txt` is set, the tagger checks the txt file FIRST
- Only if the txt file doesn't have a mapping does it fall back to the existing FLAC tag
- This prevents bad existing tags from overriding correct txt file information

### 2. **Confidence Threshold for Setlist Matching**

The tagger now requires HIGH confidence (≥85%) to trust an existing FLAC tag match, even if the song is in the setlist.

**What changed:**
- Old behavior: If fuzzy match found a song in the setlist, use it (even at 76% confidence)
- New behavior: Only trust matches ≥85% confidence OR non-suspicious tags

**Impact:**
- Low-confidence matches (like "Truckin > Nobody's Fault But Mine Jam >" → "Nobody's Fault But Mine" at 76%) now trigger txt file lookup instead of being used

### 3. **Suspicious Tag Detection**

The tagger now detects "suspicious" tags that are likely to be wrong and prefers the txt file:

**Suspicious indicators:**
- Multiple segue markers (more than 2 `>` symbols) - suggests compound title
- Long jam descriptions (contains "jam" and >40 characters) - not a canonical song name
- Low confidence match (needs review flag)

**Example suspicious tags:**
- "Truckin > Nobody's Fault But Mine Jam >"
- "Dark Star > El Paso Jam > Dark Star > Sugar Magnolia"
- "Drums/Space/The Other One Jam"

When detected, the tagger checks the txt file first before using the suspicious tag.

### 4. **Smart Duplicate Detection**

The tagger now warns about unexpected duplicate songs while allowing legitimate duplicates.

**What it checks:**
- Counts how many times each song appears in the final tagging
- Compares against JerryBase setlist (expected duplicates)
- Compares against txt file (expected duplicates)
- Only warns if duplicates are NOT expected in either source

**Legitimate duplicates (no warning):**
- Song appears twice in JerryBase setlist: "Dark Star >", "Dark Star" (different segue markers)
- Song appears twice in txt file
- Song with/without segue marker when setlist has both

**Unexpected duplicates (WARNING):**
- "Brown Eyed Women" appears twice but setlist only has it once
- "Me And My Uncle" appears 3 times but setlist has it twice

**Warning output:**
```
WARNING: Unexpected duplicate song 'Brown Eyed Women' appears 2 times
  Expected in setlist: 1 times
  Expected in txt: 1 times
  Files: gd73-12-08d1t10.flac, gd73-12-08d2t10.flac
```

### 5. **Improved Priority Logic**

The matching priority has been completely restructured:

**When trust_txt=False (default):**
1. High-confidence existing FLAC tag (≥85%) in setlist
2. Txt file (if existing tag is low confidence or suspicious)
3. Low-confidence existing FLAC tag
4. Fallback to fuzzy matching

**When trust_txt=True:**
1. Txt file (if available)
2. Existing FLAC tag
3. Fallback to fuzzy matching

---

## Code Changes

### Modified Files

1. **tagger.py**
   - Added `trust_txt` parameter to `AutoTagger.__init__()`
   - Added `duplicate_warnings` list to track unexpected duplicates
   - Completely rewrote `_process_file()` method with new priority logic
   - Added `_check_for_duplicate_titles()` method
   - Added `--trust-txt` argument to CLI
   - Updated summary output to include duplicate warnings

2. **config.py**
   - Exported `AUTO_APPLY_THRESHOLD` (85) for use in tagger.py

---

## Testing the Fixes

### Test Case 1: The 12/8/73 Show (Original Problem)

**With --trust-txt flag:**
```bash
python tagger.py "/Volumes/DS_Main/Grateful Dead/gd73/gd73-12-08.sbd.remaster. shnid.105268.flac" --trust-txt --trial
```

**Expected behavior:**
- Files should match txt file mappings
- d1t01 should be "Me And My Uncle" (not "Nobody's Fault But Mine")
- d1t10 should be "Brown Eyed Women" at track 10 (not track 1)
- No unexpected duplicate warnings (txt file has correct structure)

### Test Case 2: Normal Show with Good Tags

**Without --trust-txt flag:**
```bash
python tagger.py "/path/to/normal/show" --trial
```

**Expected behavior:**
- High-confidence existing tags should be used
- Txt file consulted for low-confidence or suspicious tags
- Normal segue duplicates (e.g., "Dark Star >" and "Dark Star") should not trigger warnings

### Test Case 3: Show with Duplicate Issue

If a show has truly duplicated songs (tagging error):

**Expected output:**
```
WARNING: Unexpected duplicate song 'Sugar Magnolia' appears 2 times
  Expected in setlist: 1 times
  Expected in txt: 1 times
  Files: file1.flac, file2.flac
```

This alerts you to investigate and fix the matching.

---

## Recommendations

### When to Use --trust-txt

**Use it for:**
- Archive.org downloads with .txt file that you trust
- Retracked shows (like the 12/8/73 example)
- Shows where you've manually created/verified the txt file
- Batch retagging after fixing txt files

**Don't use it for:**
- Shows without txt files (it will fall back to normal logic anyway)
- Shows where existing FLAC tags are known to be good
- First-time tagging of freshly ripped shows

### Best Practice Workflow

1. **First pass:** Run without `--trust-txt` to see what happens
   ```bash
   python tagger.py /path/to/shows --trial
   ```

2. **Review warnings:** Check for duplicate warnings and low-confidence matches

3. **Second pass:** If there are issues, use `--trust-txt`
   ```bash
   python tagger.py /path/to/shows --trust-txt --trial
   ```

4. **Commit:** Run without `--trial` to write changes
   ```bash
   python tagger.py /path/to/shows --trust-txt
   ```

---

## Summary Statistics

The improved tagger now tracks:
- Files processed
- Files skipped (errors)
- Matches needing review
- Unmatched songs
- Segue discrepancies
- **Duplicate warnings** (NEW)
- Artwork copied
- Artwork not found

Example output:
```
============================================================
SUMMARY
============================================================
Files processed: 33
Files skipped (errors): 0
Matches needing review: 0
Unmatched songs: 1
Segue discrepancies: 0
Duplicate warnings: 0
Artwork copied: 1
Artwork not found: 0
```

---

## What This Prevents

These changes prevent the exact failure that occurred with the 12/8/73 show:

1. ✅ **Low-confidence matches trusted**: Now requires ≥85% confidence
2. ✅ **Txt file ignored**: Now consulted for suspicious/low-confidence tags
3. ✅ **Compound titles mismatched**: Now detected as suspicious
4. ✅ **Duplicates undetected**: Now warns about unexpected duplicates
5. ✅ **No override option**: Now has `--trust-txt` flag

The fixes maintain backward compatibility (default behavior is similar but safer) while adding powerful new options for problematic cases.
