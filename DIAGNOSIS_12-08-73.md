# Diagnosis: Auto-Tagger Failure for 12/8/73 Show

**Date:** February 7, 2026  
**Show:** gd73-12-08.sbd.remaster.shnid.105268  
**Issue:** Songs tagged with wrong titles, wrong disc numbers, and wrong track numbers

---

## Executive Summary

The auto-tagger failed due to a **fundamental mismatch** between the txt file's disc structure and the actual file organization, combined with **aggressive fuzzy matching** that incorrectly matched complex song titles, and **logic that prioritized bad existing tags over the txt file**.

---

## The Failure Chain

### 1. Txt File Contains Wrong Mappings for Filenames

**The txt file says:**
- Disc 1, Track 1: "Me And My Uncle"
- Disc 3, Track 1: "Truckin > Nobody's Fault But Mine Jam >"

**The actual file structure:**
- `gd73-12-08d1t01.flac` should be "Me And My Uncle" ✓
- `gd73-12-08d3t01.flac` should be "Truckin > Nobody's Fault But Mine Jam >" ✗

**What actually happened:**
The txt file parser created mappings like:
```
d1t01 -> "Me And My Uncle"
d3t01 -> "Truckin > Nobody's Fault But Mine Jam >"
```

But these files had ALREADY been tagged (incorrectly) before the auto-tagger ran. They had tags like:
- `gd73-12-08d1t01.flac` had TITLE: "Truckin > Nobody's Fault But Mine Jam >"
- `gd73-12-08d2t01.flac` had TITLE: "Truckin > Nobody's Fault But Mine Jam >"
- `gd73-12-08d3t01.flac` had TITLE: "Truckin > Nobody's Fault But Mine Jam >"

**Why?** Someone had previously bulk-tagged all the files, possibly copying tags from another source or using the track 1 tag for all files.

### 2. Fuzzy Matcher Incorrectly Matched Complex Title

When the auto-tagger processed `gd73-12-08d1t01.flac`:

1. Read existing FLAC tag: "Truckin > Nobody's Fault But Mine Jam >"
2. Cleaned it to: "Truckin > Nobody's Fault But Mine Jam"
3. Fuzzy matched to: **"Nobody's Fault But Mine"** (76.67% confidence)
4. This triggered `needs_review` (between 75% and 85% thresholds)
5. Checked if "Nobody's Fault But Mine" is in the 12/8/73 setlist → **YES, it is!** (Set 2, song #9)
6. Used that match and **never consulted the txt file**

**The code logic in `tagger.py` lines 274-290:**
```python
# First, try to match the existing tag against this show's setlist
if raw_title and setlist_songs:
    result = self.matcher.match(raw_title)
    matched_lower = result.matched_title.lower() if result.matched_title else ''
    
    # Check if the matched song is in this show's setlist
    if matched_lower in setlist_songs:
        # Use the JerryBase canonical name from the setlist
        return MatchResult(...)  # RETURNS HERE - txt file never checked!
```

**The problem:** The check `if matched_lower in setlist_songs` succeeded because:
- The fuzzy matcher extracted "Nobody's Fault But Mine" from the complex jam title
- That song IS in the 12/8/73 setlist
- But it's the WRONG song for this file position

### 3. Wrong Song Match → Wrong Disc Assignment

Once `gd73-12-08d1t01.flac` was matched to "Nobody's Fault But Mine":

1. SetTagger looked up "Nobody's Fault But Mine" in the JerryBase setlist
2. Found it in **Set 2** (set_seq = 2)
3. Assigned `disc_number = 2`
4. File became Disc 2, Track 1

**The code in `set_tagger.py` lines 149-151:**
```python
if info['song_set'] is not None:
    # Real song with known set
    disc_number = info['song_set']  # Uses JerryBase set number
```

### 4. Track Renumbering Chaos

The `_renumber_tracks()` method renumbers all tracks **within each disc** sequentially:

```python
# Group by disc and renumber
for disc_num, tracks in disc_tracks.items():
    for i, track in enumerate(tracks, 1):
        track.track_number = i
```

So all the mismatched songs got renumbered within their wrong discs:
- Files wrongly assigned to Disc 2 became tracks 1, 2, 3, etc.
- Files wrongly assigned to Disc 1 became tracks 1, 2, 3, etc.
- This created the out-of-order chaos

### 5. Why "Brown Eyed Women" Appeared Twice

Looking at the JerryBase setlist, "Brown Eyed Women" is song #10 in Set 1.

Two different files got matched to it:
- `gd73-12-08d1t10.flac` - correctly matched (it IS Brown Eyed Women)
- `gd73-12-08d2t10.flac` - incorrectly matched (should be something from Set 2)

Both were assigned to Set 1 (because that's where Brown Eyed Women belongs in JerryBase), then renumbered within Set 1, creating two tracks with the same song title but different track numbers.

---

## Root Causes

### Root Cause #1: Pre-existing Incorrect Tags

The files had bad tags BEFORE the auto-tagger ran. The auto-tagger trusted these bad tags instead of the txt file.

**Evidence:**
- Multiple files (d1t01, d2t01, d3t01) all had the same title: "Truckin > Nobody's Fault But Mine Jam >"
- This is clearly wrong - three different files can't all be the same song

### Root Cause #2: Logic Priority Error

The `_process_file` method in `tagger.py` prioritizes:
1. Existing FLAC tag (if it fuzzy-matches something in the setlist)
2. Txt file (only if the existing tag didn't match)

**This is backwards!** For retracked shows, the txt file should be the source of truth.

### Root Cause #3: Aggressive Fuzzy Matching

The fuzzy matcher extracted "Nobody's Fault But Mine" from "Truckin > Nobody's Fault But Mine Jam >" with 76.67% confidence.

**Why this is wrong:**
- The title contains MULTIPLE songs: "Truckin", "Nobody's Fault But Mine", and "Jam"
- Matching to just one song loses context
- Low confidence (76%) should trigger txt file fallback, not be used

### Root Cause #4: No Positional Validation

The tagger never checks: "Does this match make sense given the file's position?"

For example:
- `d1t01.flac` is obviously the first track of the first disc
- "Nobody's Fault But Mine" is song #9 in Set 2
- These don't match positionally → should trigger review/txt file lookup

### Root Cause #5: SetTagger Uses Song Identity, Not Position

The `assign_discs` method assigns disc numbers based on which SET a song belongs to in JerryBase, not which disc the file is actually on.

This makes sense for most shows, but fails when:
- Songs are retracked (moved between discs)
- Files are renamed/reorganized
- Pre-existing tags are wrong

---

## JerryBase Setlist (Ground Truth)

```
Set 1 (17 songs):
  1. Me And My Uncle
  2. Sugaree
  3. Mexicali Blues
  4. Dire Wolf
  5. Black Throated Wind
  6. They Love Each Other
  7. Me And Bobby McGee
  8. Don't Ease Me In
  9. The Race Is On
 10. Brown Eyed Women
 11. Big River
 12. Candyman
 13. Weather Report Suite Prelude >
 14. Weather Report Suite Part 1 >
 15. Let It Grow
 16. China Cat Sunflower >
 17. I Know You Rider

Set 2 (14 songs):
  1. Around And Around
  2. Ramble On Rose
  3. El Paso
  4. Row Jimmy
  5. Greatest Story Ever Told >
  6. Bertha
  7. He's Gone >
  8. Truckin' >
  9. Nobody's Fault But Mine >
 10. The Other One >
 11. Wharf Rat >
 12. Stella Blue
 13. Johnny B. Goode >
 14. Uncle John's Band

Encore:
  1. One More Saturday Night
```

---

## Txt File Structure (What Actually Exists)

```
Disc 1 (14 tracks): Set 1 songs 1-14
Disc 2 (10 tracks): Set 1 songs 15-17 + Set 2 songs 1-7
Disc 3 (9 tracks): Set 2 songs 8-14 + Encore
```

**Note:** The txt file shows only 9 tracks on Disc 2, but there are actually 10 files (d2t01-d2t10).

---

## Actual File Organization

Files exist as:
- `gd73-12-08d1t01.flac` through `gd73-12-08d1t14.flac` (14 files)
- `gd73-12-08d2t01.flac` through `gd73-12-08d2t10.flac` (10 files)
- `gd73-12-08d3t01.flac` through `gd73-12-08d3t09.flac` (9 files)

**Total: 33 files**  
**Total songs in JerryBase: 32 songs (17 + 14 + 1)**

**Mystery:** Why 33 files for 32 songs? Likely one extra track (tuning/crowd/jam).

---

## What Should Have Happened

The auto-tagger should have:

1. **Detected low-confidence match** (76.67%) and fallen back to txt file
2. **Prioritized txt file** for retracked shows (where filenames match txt structure)
3. **Validated positional consistency** (first track should be first song)
4. **Used txt file as source of truth** when existing tags are clearly wrong (duplicates)
5. **Flagged mismatches** between txt structure and actual file count

---

## Recommended Fixes

### Fix #1: Add Confidence Threshold for Setlist Matching

In `tagger.py`, don't trust low-confidence matches even if they're in the setlist:

```python
# Check if the matched song is in this show's setlist
if matched_lower in setlist_songs:
    # ONLY trust high-confidence matches
    if result.confidence >= AUTO_APPLY_THRESHOLD:  # 85%
        return MatchResult(...)
    else:
        # Low confidence - check txt file first
        # (fall through to txt file logic)
```

### Fix #2: Prioritize Txt File for Generic/Bad Tags

Detect obviously bad tags (duplicates, complex jam titles) and prefer txt file:

```python
# Detect bad tags
is_bad_tag = (
    raw_title.count('>') > 2 or  # Multiple segues
    'jam' in raw_title.lower() and len(raw_title) > 40 or  # Long jam description
    result.needs_review  # Low confidence
)

if is_bad_tag and txt_mappings.get(flac_file.name):
    # Use txt file instead
    txt_title = txt_mappings.get(flac_file.name)
    txt_result = self.matcher.match(txt_title)
    # ... use txt_result
```

### Fix #3: Add Positional Validation

Check if the matched song's position in the setlist roughly matches the file's position:

```python
# Get expected position from filename
file_disc = int(re.search(r'd(\d+)', flac_file.name).group(1))
file_track = int(re.search(r't(\d+)', flac_file.name).group(1))

# Get matched song's position in setlist
song_set = song_to_set.get(matched_lower)
song_seq = get_song_sequence(matched_lower, setlist)

# If positions are wildly different, flag for review
position_mismatch = abs(file_track - song_seq) > 5

if position_mismatch and txt_mappings.get(flac_file.name):
    # Prefer txt file
```

### Fix #4: Detect Duplicate Titles

Before writing tags, check if multiple files will have the same title:

```python
# After creating all updates, check for duplicates
title_counts = {}
for update in updates:
    title_counts[update.title] = title_counts.get(update.title, 0) + 1

duplicates = [t for t, c in title_counts.items() if c > 1]
if duplicates:
    print(f"WARNING: Duplicate titles found: {duplicates}")
    print("This suggests incorrect matching - review needed")
```

### Fix #5: Add Txt File Structure Validation

Validate that txt file structure matches actual file count:

```python
# Count files per disc
actual_counts = {}
for f in flac_files:
    match = re.search(r'd(\d+)t', f.name)
    if match:
        disc = int(match.group(1))
        actual_counts[disc] = actual_counts.get(disc, 0) + 1

# Count txt mappings per disc
txt_counts = {}
for key in txt_mappings.keys():
    match = re.search(r'd(\d+)t', key)
    if match:
        disc = int(match.group(1))
        txt_counts[disc] = txt_counts.get(disc, 0) + 1

# Compare
if actual_counts != txt_counts:
    print("WARNING: Txt file structure doesn't match file organization")
    print(f"Actual: {actual_counts}")
    print(f"Txt: {txt_counts}")
```

---

## Conclusion

The failure was caused by a **cascade of logic errors**:

1. Bad pre-existing tags
2. Aggressive fuzzy matching that trusted low-confidence results
3. Logic that prioritized bad existing tags over the txt file
4. No validation of positional consistency or duplicate detection
5. SetTagger that uses song identity (from JerryBase) instead of file position

**The fundamental issue:** The auto-tagger was designed assuming existing FLAC tags are mostly correct and just need normalization. It wasn't designed to handle **completely wrong** pre-existing tags or **retracked shows** where the txt file is the source of truth.

**Primary recommendation:** Add a `--trust-txt` flag that prioritizes the txt file over existing tags for retracked/reorganized shows.

**IMPORTANT LIMITATION DISCOVERED:**

The txt file parser (txt_parser.py) does NOT correctly handle shows where the txt file uses a different disc structure than the filenames.

For example, this show's txt file says:
```
Disc 1.
01. Me And My Uncle
...

Disc 3
01. Truckin > Nobody's Fault But Mine Jam >
```

But the filenames are:
- gd73-12-08d1t01.flac (should be "Me And My Uncle")
- gd73-12-08d3t01.flac (should be "Truckin...")

The parser creates mappings like `01 -> "Me And My Uncle"` and later `01 -> "Truckin..."` (overwriting the first one!), but it does NOT create disc-specific mappings like `d1t01` and `d3t01`.

This means when filenames follow the `dXtYY` pattern but the txt file resets track numbers for each disc, the parser cannot correctly map files to songs.

**Additional fix needed:** The txt_parser.py needs to be enhanced to:
1. Detect disc boundaries in the txt file ("Disc 1", "Disc 2", etc.)
2. Create disc-specific mappings (d1t01, d2t01, etc.) based on the disc context
3. Handle track number resets at disc boundaries

Without this fix, the `--trust-txt` flag will only work correctly for shows where:
- The txt file uses sequential track numbers across all discs (01-32 for a 32-track show)
- OR the filenames don't use the dXtYY pattern
- OR the txt file structure exactly matches the filename structure
