# GratefulDead Auto-Tagger

Automated FLAC metadata tagging for Grateful Dead and Jerry Garcia live show recordings.

## Features

- **Song Title Matching**: Multi-tier fuzzy matching against JerryBase database
- **Learning Corrections**: Corrections are saved and reused automatically
- **Album/Artist Tagging**: Sets Album, Artist, AlbumArtist, Genre, Date from JerryBase
- **Set-Based Disc Numbers**: DISCNUMBER reflects musical sets (Set 1, Set 2, Encore)
- **Track Renumbering**: TRACKNUMBER renumbered within each set
- **Totals**: TRACKTOTAL per disc, DISCTOTAL for the show
- **Artwork Handling**: Detects existing artwork, copies missing artwork from external directories
- **TXT File Parsing**: Extracts song titles from accompanying .txt files when metadata is missing

## Installation

```bash
git clone https://github.com/jvmjr/GratefulDeadAutoTagger.git
cd GratefulDeadAutoTagger
pip install -r requirements.txt
```

## Usage

### Tag a directory of shows

```bash
# Grateful Dead shows
python tagger.py /path/to/gd/shows --gd 1

# Jerry Garcia shows
python tagger.py /path/to/jg/shows --gd 0

# Preview changes without writing (trial mode)
python tagger.py /path/to/shows --trial

# Include artwork copying
python tagger.py /path/to/shows --artwork-dir /path/to/covers
```

### Command Line Options

| Option | Description |
|--------|-------------|
| `path` | Path to show folder or directory of shows |
| `--gd {0,1}` | 1 for Grateful Dead (default), 0 for Jerry Garcia |
| `--pad N` | Number of prefix chars before date in folder name (default: 2) |
| `--db PATH` | Path to JerryBase.db (default: ./JerryBase.db) |
| `--trial` | Preview changes without writing |
| `--no-recursive` | Do not process subdirectories |
| `--artwork-dir PATH` | Directory containing artwork files to copy if missing |
| `--artwork-primary` | Use artwork-dir as primary (before parent folder) |

### Process review file

After running the tagger, low-confidence matches are written to `review_matches.csv`.
Edit the file to approve/reject/customize matches, then apply:

```bash
python apply_reviewed.py
python apply_reviewed.py --dry-run  # Preview without applying
```

## Tags Written

| Tag | Example |
|-----|---------|
| TITLE | `Scarlet Begonias >` |
| ARTIST | `Grateful Dead` |
| ALBUMARTIST | `Grateful Dead` |
| ALBUM | `1977-05-08  Barton Hall, Ithaca, NY` |
| GENRE | `GD` |
| DATE | `1977-05-08` |
| VERSION | `gd1977-05-08.12345.sbd.miller.flac16` (folder name) |
| DISCNUMBER | `2` |
| DISCTOTAL | `3` |
| TRACKNUMBER | `7` |
| TRACKTOTAL | `12` |

## Album Naming Format

- **Normal show**: `YYYY-MM-DD  Venue, City, ST` (2 spaces after date)
- **Early show**: `YYYY-MM-DD (Early)  Venue, City, ST`
- **Late show**: `YYYY-MM-DD (Late)  Venue, City, ST`

Examples:
- `1977-05-08  Barton Hall, Ithaca, NY`
- `1969-02-27 (Early)  Fillmore West, San Francisco, CA`
- `1969-02-27 (Late)  Fillmore West, San Francisco, CA`

## Matching Tiers

1. **Exact Match**: Case-insensitive against JerryBase songs
2. **Corrections Map**: Previously corrected titles (pipe-delimited CSV)
3. **Extra Songs Map**: Non-song tracks (tuning, crowd, etc.)
4. **Fuzzy Match 85%+**: Auto-apply and add to corrections
5. **Fuzzy Match 75-84%**: Write to review file
6. **Below 75%**: Mark as unmatched

## Artwork Handling

The tagger can automatically copy artwork to show folders that are missing it.

### Search Order

By default:
1. Check for embedded artwork in FLAC files
2. Check for square image files in the show folder
3. Check parent folder for `*cover*`, `*art*`, `*artwork*` directories
4. Check `--artwork-dir` if specified (as backup)

With `--artwork-primary`:
1. Check for embedded/existing artwork
2. Check `--artwork-dir` first
3. Check parent folder artwork directories as backup

### Artwork Matching

Artwork files are matched by date pattern:
- `gd77-05-08.*` (band + 2-digit year)
- `1977-05-08.*` (4-digit year)
- Searches subdirectories including year folders (e.g., `1977/`)

### Non-Square Artwork

If existing artwork is not approximately square (within 5% tolerance), the tagger will search for replacement artwork and copy it alongside the existing file (without overwriting).

## Files

| File | Purpose |
|------|---------|
| `tagger.py` | Main CLI - run the full pipeline |
| `song_matcher.py` | Fuzzy song title matching |
| `album_tagger.py` | Album, Artist, Genre tagging |
| `set_tagger.py` | Set/disc assignment, track renumbering |
| `txt_parser.py` | Parse show .txt files for missing titles |
| `artwork_handler.py` | Artwork detection and copying |
| `apply_reviewed.py` | Apply reviewed low-confidence matches |
| `config.py` | Shared configuration |
| `corrections_map.csv` | Learned title corrections (pipe-delimited) |
| `extra_songs.csv` | Non-song track mappings (pipe-delimited) |
| `JerryBase.db` | SQLite database of shows, songs, venues |

## Configuration

Edit `config.py` to adjust:

- `AUTO_APPLY_THRESHOLD`: Fuzzy match confidence for auto-apply (default: 85)
- `REVIEW_THRESHOLD`: Minimum confidence for review file (default: 75)
- `SQUARE_TOLERANCE`: Tolerance for "approximately square" artwork (default: 0.05)
- `DEFAULT_GENRE`: Genre tag value (default: "GD")

## Data Files

### corrections_map.csv

Pipe-delimited file mapping original titles to canonical names:

```
original_title|canonical_title|source
mississippi half-step uptown toodleloo|Mississippi Half-Step Uptown Toodeloo|learned
women are smarter|Man Smart (Woman Smarter)|learned
```

### extra_songs.csv

Pipe-delimited file for non-song tracks:

```
original_title|canonical_title
tuning|Tuning
crowd|Crowd
drums|Drums
space|Space
```

## Requirements

- Python 3.7+
- rapidfuzz (fuzzy string matching)
- mutagen (FLAC tagging)
- python-dateutil (date parsing)
- Pillow (optional, for artwork dimension checking)

## Acknowledgments

This project is heavily based on the work of **Jason A. Evans** ([@jasonumd](https://github.com/jasonumd)) and his [Grateful-Dead-and-Jerry-Garcia-Tagging](https://github.com/jasonumd/Grateful-Dead-and-Jerry-Garcia-Tagging) project. This auto-tagger would not have been possible without his foundational work and inspiration.

Special thanks also to:
- [JerryBase.com](https://jerrybase.com) for the comprehensive database of Grateful Dead and Jerry Garcia shows
- The taping and archiving community for preserving these recordings

## License

MIT License - see LICENSE file for details.
