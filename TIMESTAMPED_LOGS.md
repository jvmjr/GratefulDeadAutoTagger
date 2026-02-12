# Timestamped Log Files - Implementation Complete

## ✅ Changes Implemented

All log files now have timestamps for tracking and historical record keeping.

### **File Structure**

```
GratefulDeadAutoTagger/
├── review_matches.csv                    ← Working copy (no timestamp)
└── logs/
    ├── review_matches_20260207_141023.csv   ← Timestamped backup
    ├── unmatched_songs_20260207_141023.txt  ← Timestamped
    └── segue_discrepancies_20260207_141023.log ← Timestamped
```

---

## Behavior

### **review_matches.csv**

**Two copies created:**

1. **Working copy:** `review_matches.csv` (root directory, no timestamp)
   - Used by `apply_reviewed.py` script
   - Overwritten on each run
   - Edit this file to approve/reject matches

2. **Timestamped backup:** `logs/review_matches_YYYYMMDD_HHMMSS.csv`
   - For historical record keeping
   - NOT overwritten - preserved for each run
   - Allows you to track what was reviewed in previous runs

### **unmatched_songs.txt**

**One copy created:**
- `logs/unmatched_songs_YYYYMMDD_HHMMSS.txt`
- Timestamped filename
- NOT overwritten - preserved for each run
- Track unmatched songs across different runs

### **segue_discrepancies.log**

**One copy created:**
- `logs/segue_discrepancies_YYYYMMDD_HHMMSS.log`
- Timestamped filename
- NOT overwritten - preserved for each run
- Track segue disagreements across different runs

---

## Timestamp Format

Format: `YYYYMMDD_HHMMSS`

**Example:** `20260207_141023` = February 7, 2026 at 2:10:23 PM

This format:
- ✅ Sorts chronologically when listed
- ✅ Easy to read
- ✅ No special characters (filesystem-safe)
- ✅ Includes date and time for precise tracking

---

## Example Run Output

```bash
$ python tagger.py /path/to/shows --trust-txt

Processing: gd73-12-08.sbd.remaster. shnid.105268.flac
  ...
  
Wrote 5 matches for review to /Users/.../review_matches.csv
Wrote timestamped copy to /Users/.../logs/review_matches_20260207_141023.csv
Wrote 3 unmatched songs to /Users/.../logs/unmatched_songs_20260207_141023.txt
Wrote 7 segue discrepancies to /Users/.../logs/segue_discrepancies_20260207_141023.log
```

---

## Benefits

### Historical Tracking
- See what issues existed in previous runs
- Compare before/after when you fix txt files or update corrections
- Track improvements over time

### Workflow Clarity
- Old timestamped files don't interfere with new runs
- Working `review_matches.csv` is always the latest
- Can keep logs from important runs without cluttering working directory

### Debugging
- If you need to investigate what happened in a previous run, the logs are preserved
- Timestamp shows exactly when each run occurred
- Can correlate with file modification times

---

## Cleanup

Over time, you may accumulate many timestamped log files. You can safely delete old ones:

```bash
# Keep only logs from last 7 days
find logs/ -name "*_*.txt" -mtime +7 -delete
find logs/ -name "*_*.log" -mtime +7 -delete
find logs/ -name "*_*.csv" -mtime +7 -delete

# Or keep only the 10 most recent
ls -t logs/unmatched_songs_*.txt | tail -n +11 | xargs rm -f
ls -t logs/segue_discrepancies_*.log | tail -n +11 | xargs rm -f
ls -t logs/review_matches_*.csv | tail -n +11 | xargs rm -f
```

**Important:** Always keep the working `review_matches.csv` (root directory) if you have pending reviews!

---

## Summary

| File | Location | Timestamp | Overwritten | Used By Script |
|------|----------|-----------|-------------|----------------|
| `review_matches.csv` | Root | ❌ No | ✅ Yes | apply_reviewed.py |
| `logs/review_matches_*.csv` | logs/ | ✅ Yes | ❌ No | (backup only) |
| `logs/unmatched_songs_*.txt` | logs/ | ✅ Yes | ❌ No | (documentation) |
| `logs/segue_discrepancies_*.log` | logs/ | ✅ Yes | ❌ No | (documentation) |

**Key Point:** The working `review_matches.csv` (without timestamp) must remain in the root directory for `apply_reviewed.py` to find it with default settings. The timestamped version in `logs/` is just for your records.
