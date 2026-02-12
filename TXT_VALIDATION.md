# Txt File Validation and Folder Skipping

## ✅ Final Implementation Complete!

### **The Safety Feature**

When `--trust-txt` is enabled and the txt file track count doesn't match the FLAC file count, **the entire folder is skipped** to prevent cascading tagging errors from incorrect mappings.

### **Why Skip the Folder?**

If the txt file is off (e.g., missing a track, or tracks renumbered), we can't reliably map filenames to songs:
- File `d2t03` might be mapped to song that's actually in `d2t04`
- File `d2t10` might have no mapping and get wrong fallback
- **All subsequent files could be mismatched by 1 or more positions**

This causes cascading errors throughout the entire folder, which is worse than not tagging at all.

### **The Exception: JerryBase Match**

If the FLAC file count **exactly matches** the JerryBase setlist count, processing is allowed (but with a clear warning):

**Example:**
```
FLAC files: 32
Txt mappings: 31
JerryBase songs: 32  ← MATCH!

⚠️  EXCEPTION: FLAC count (32) matches JerryBase setlist count (32)
→ Allowing processing - will use JerryBase for matching
→ CAUTION: This match could be coincidental - please review results!
```

This allows the tagger to fall back to JerryBase matching when the counts align, while still warning that the txt file doesn't match so you can verify afterwards.

## Behavior Matrix

| FLAC Files | Txt Mappings | JerryBase Songs | --trust-txt | Result |
|------------|--------------|-----------------|-------------|--------|
| 33 | 33 | 32 | ON | ✅ Process (perfect match) |
| 33 | 32 | 32 | ON | ⛔ SKIP (mismatch, no exception) |
| 32 | 31 | 32 | ON | ✅ Process (exception: FLAC=JerryBase) |
| 33 | 32 | 32 | OFF | ✅ Process (fuzzy matching) |

## Example Output: Folder Skipped

```bash
$ python tagger.py /path/to/show --trust-txt

Processing: gd73-12-08.sbd.remaster. shnid.105268.flac
  Date: 1973-12-08, Songs in setlist: 32, Sets: 3
  ⚠️  WARNING: Txt file track count mismatch!
    FLAC files in folder: 33
    Txt file mappings: 32
    Difference: 1 file(s)
    Files without txt mappings: gd73-12-08d2t10.flac
    → This may indicate:
       - Missing tracks in txt file (extra songs, jam segments)
       - Txt file is for a different version/retracking
       - Numbering mismatch causing offset errors
    ⛔ RESULT: Folder will be SKIPPED with --trust-txt enabled
    → Txt file mappings cannot be trusted
    → Incorrect mappings would cause cascading tagging errors
    → Fix txt file or run without --trust-txt to use fuzzy matching
  ⛔ SKIPPING FOLDER - txt file mismatch detected
  → Fix the txt file or run without --trust-txt flag
```

## Example Output: Exception Case

```bash
$ python tagger.py /path/to/show --trust-txt

Processing: some-show-folder
  Date: 1973-05-20, Songs in setlist: 32, Sets: 3
  ⚠️  WARNING: Txt file track count mismatch!
    FLAC files in folder: 32
    Txt file mappings: 31
    Difference: 1 file(s)
    Files without txt mappings: d2t10.flac
    → This may indicate:
       - Missing tracks in txt file (extra songs, jam segments)
       - Txt file is for a different version/retracking
       - Numbering mismatch causing offset errors
    ⚠️  EXCEPTION: FLAC count (32) matches JerryBase setlist count (32)
    → Allowing processing - will use JerryBase for matching
    → CAUTION: This match could be coincidental - please review results!
  
  [Processing continues...]
  [Tags assigned based on JerryBase setlist matching]
```

## What to Do When Folder is Skipped

### Option 1: Fix the Txt File
```bash
# Edit the txt file to include missing tracks
vim "/path/to/show/info.txt"

# Re-run with --trust-txt
python tagger.py /path/to/show --trust-txt
```

### Option 2: Run Without --trust-txt
```bash
# Use fuzzy matching + txt as fallback
python tagger.py /path/to/show --trial

# If results look good, run without --trial
python tagger.py /path/to/show
```

### Option 3: Manual Tagging
If the show is complex or txt file is too incorrect to fix easily, manually tag the files.

## Why This is Better

### Before (without folder skipping):
```
❌ 33 files processed with --trust-txt
❌ 1 file has no txt mapping (d2t10)
❌ Files d2t03-d2t09 all tagged 1 position off
❌ File d2t10 gets wrong tag from fallback
❌ Result: 8+ files incorrectly tagged
❌ Errors are subtle and hard to spot
```

### After (with folder skipping):
```
✅ Folder skipped immediately when mismatch detected
✅ Clear warning explains the issue
✅ No incorrect tags written
✅ User can fix txt file and re-run
✅ Alternative: run without --trust-txt for fuzzy matching
```

## Safety by Design

The `--trust-txt` flag means "**I trust this txt file completely**". If that trust can't be validated (counts don't match), it's safer to do nothing than to write potentially incorrect tags throughout the entire folder.

The exception for JerryBase matching provides a safety valve - if counts align, the tagger can use JerryBase as the source of truth instead of the txt file, while still warning you to review.

## Summary

- ✅ **Validation**: Txt file count checked against FLAC file count
- ✅ **Skipping**: Mismatched folders skipped when --trust-txt enabled
- ✅ **Exception**: If FLAC count = JerryBase count, processing allowed
- ✅ **Warning**: Always displayed when counts don't match
- ✅ **Fallback**: Can run without --trust-txt to use fuzzy matching
- ✅ **Safety**: Prevents cascading tagging errors from bad txt files
