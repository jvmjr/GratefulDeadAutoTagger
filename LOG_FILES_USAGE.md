# Log Files Usage Summary

## Overview

The auto-tagger creates three log files for documentation and review. Two of them are **purely informational**, while one (`review_matches.csv`) is **actively used by a separate script**.

---

## 1. `review_matches.csv` ✅ **USED BY SCRIPTS**

### Purpose
Stores low-confidence matches (between 75-85%) that need manual review before applying.

### Created By
- **`tagger.py`** - Writes this file during tagging

### Used By
- **`apply_reviewed.py`** - Reads this file to apply reviewed matches

### Workflow
```bash
# Step 1: Run tagger (creates review_matches.csv)
python tagger.py /path/to/shows --trial

# Step 2: Review and edit the CSV file
# - Leave 'action' empty or 'y' to accept suggested match
# - Set 'action' to 'n' to skip the file
# - Set 'action' to a custom title to use that instead

# Step 3: Apply the reviewed matches
python apply_reviewed.py
# Or for specific file:
python apply_reviewed.py --file /path/to/review_matches.csv

# Optional: Preview without applying
python apply_reviewed.py --dry-run
```

### Format
```csv
file_path,original_title,suggested_match,confidence,action
/path/to/file.flac,Original Title,Suggested Match,82.5,
```

### What `apply_reviewed.py` Does
1. Reads the `review_matches.csv` file
2. For each row:
   - If `action` is empty or 'y': Uses the `suggested_match`
   - If `action` is 'n': Skips the file
   - If `action` is any other text: Uses that as the custom title
3. Writes the TITLE tag to the FLAC file
4. Adds the correction to `corrections_map.csv` for future runs
5. Saves the updated corrections map

### Example
```csv
file_path,original_title,suggested_match,confidence,action
/path/to/file1.flac,Sugar Mag,Sugar Magnolia,82.5,
/path/to/file2.flac,Dark Str,Dark Star,78.2,y
/path/to/file3.flac,Drums Space,Drums,76.1,n
/path/to/file4.flac,Other 1,The Other One,81.0,The Other One >
```

Result:
- file1: Tagged as "Sugar Magnolia" (accepted suggested)
- file2: Tagged as "Dark Star" (accepted suggested)
- file3: Skipped (rejected)
- file4: Tagged as "The Other One >" (custom title)

---

## 2. `logs/unmatched_songs.txt` ℹ️ **DOCUMENTATION ONLY**

### Purpose
Lists songs that couldn't be matched to any known song in JerryBase.

### Created By
- **`tagger.py`** - Writes this file during tagging

### Used By
- **Nothing** - Purely for user review

### Format
```
file_path|original_title|cleaned_title
/path/to/file.flac|Weir's Story|Weir's Story
/path/to/file2.flac|Crowd Noise|Crowd Noise
```

### What To Do With It
1. Review the file to see what songs weren't matched
2. Options:
   - Add them to `extra_songs.csv` if they're non-songs (tuning, crowd, etc.)
   - Add them to `corrections_map.csv` if they're misspelled song names
   - Update JerryBase if they're legitimate songs not in the database
   - Update txt files if the titles are wrong at the source

---

## 3. `logs/segue_discrepancies.log` ℹ️ **DOCUMENTATION ONLY**

### Purpose
Logs when JerryBase and txt file disagree about segue markers (` >`).

### Created By
- **`tagger.py`** - Writes this file during tagging

### Used By
- **Nothing** - Purely for user review

### Format
```
Segue Discrepancies (JerryBase vs txt file)
============================================================
Segue applied if EITHER source indicates one.

Dark Star
  File:     /path/to/file.flac
  JerryBase: >  |  Txt file: (none)  |  Result: > applied

Sugar Magnolia
  File:     /path/to/file2.flac
  JerryBase: (none)  |  Txt file: >  |  Result: > applied
```

### What To Do With It
1. Review to see where sources disagree
2. The tagger uses **OR logic** - applies segue if EITHER source indicates one
3. Options:
   - Update txt file if it's wrong
   - Update JerryBase if it's wrong (less common)
   - Usually safe to ignore - the tagger makes the best choice

### Logic
The segue is applied if **any** of these sources indicate it:
- JerryBase database (`segue` field = 1)
- Txt file (title ends with ` >`)
- Existing FLAC tag (title ends with ` >`)

This is conservative - better to have a segue when in doubt.

---

## Summary Table

| File | Created By | Used By | Purpose |
|------|-----------|---------|---------|
| `review_matches.csv` | tagger.py | **apply_reviewed.py** | Apply low-confidence matches after manual review |
| `logs/unmatched_songs.txt` | tagger.py | **(none)** | Document songs that couldn't be matched |
| `logs/segue_discrepancies.log` | tagger.py | **(none)** | Document segue marker disagreements |

---

## Best Practices

### After Running the Tagger

1. **Check the summary output:**
   ```
   Matches needing review: 5
   Unmatched songs: 2
   Segue discrepancies: 3
   ```

2. **If "Matches needing review" > 0:**
   - Open `review_matches.csv`
   - Review each suggested match
   - Fill in the `action` column
   - Run `python apply_reviewed.py`

3. **If "Unmatched songs" > 0:**
   - Open `logs/unmatched_songs.txt`
   - Review the list
   - Update `extra_songs.csv` or `corrections_map.csv` as needed
   - Re-run tagger on those shows

4. **If "Segue discrepancies" > 0:**
   - Open `logs/segue_discrepancies.log`
   - Review the list
   - Usually safe to ignore (tagger handles it)
   - Update sources if you find systematic errors

### Files Are Overwritten

All three files are **overwritten** on each run of `tagger.py`. They accumulate results from all shows processed in that run.

If you want to keep history:
```bash
# Backup before next run
cp review_matches.csv review_matches_backup_$(date +%Y%m%d).csv
```

---

## Key Insight

Only `review_matches.csv` is used by another script. The other two files are purely informational logs to help you improve the auto-tagger's accuracy over time by updating the corrections map, extra songs list, or source data.
