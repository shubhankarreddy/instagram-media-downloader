# Instagram Media Downloader

Download reels and images from any public Instagram profile — no API key, no login prompts. Uses your existing browser session (Firefox, Chrome, or Edge) to authenticate automatically.

---

## What It Does

- Downloads **reels** (videos) or **image posts** from any public Instagram profile
- Picks the **highest available quality** for every file
- Skips files you have already downloaded (safe to re-run)
- Filters downloads by **date range** if needed
- Saves everything neatly to your `Downloads` folder, away from the script
- Works on **Windows, macOS, and Linux**
- Supports **Firefox, Chrome, and Edge** — tries them in order automatically

---

## Requirements

- Python 3.10 or later — [python.org/downloads](https://www.python.org/downloads/)
- One of: **Firefox**, **Chrome**, or **Edge** with an active Instagram login

---

## Installation

### Option A — Single file (simplest)

Just download `insta_downloader.py` and install the two runtime dependencies:

```bash
pip install browser-cookie3 requests
python insta_downloader.py
```

### Option B — Clone the full repository

**Step 1 — Clone the repository**

```bash
git clone https://github.com/shubhankarreddy/instagram-media-downloader.git
cd instagram-media-downloader
```

**Step 2 — (Recommended) Create a virtual environment**

```bash
# Windows
python -m venv .venv
.venv\Scripts\activate

# macOS / Linux
python3 -m venv .venv
source .venv/bin/activate
```

**Step 3 — Install dependencies**

```bash
pip install -r requirements.txt
```

> For running tests, also install dev dependencies:
> ```bash
> pip install -r requirements-dev.txt
> ```

---

## How to Use

### Interactive mode (recommended for first-time use)

Just run the script and answer the prompts:

```bash
python insta_downloader.py
```

```
Download by URL or username? (url/username): username
Enter Instagram username: natgeo
What to download? (reels/images): reels
Enter start date (YYYY-MM-DD) or press Enter to skip:
Enter end date (YYYY-MM-DD) or press Enter to skip:

Using Instagram login from Firefox cookies.
Starting download for @natgeo...
Fetching available reels (pages will be logged below):
  [Page 1] Found 24 items, more_available=True
  [Page 2] Found 24 items, more_available=True
  ...
  [Pagination Complete] Reached end after 5 pages, 112 total items processed.

============================================================
Reels Download Complete for @natgeo
  Total files processed : 112
  Filtered by date      : 0
  Downloaded (new)      : 112
  Skipped (existed)     : 0
  Failed                : 0
  Reels folder          : C:\Users\shubh\Downloads\insta_downloads\natgeo\reels
============================================================
Task completed.
Press Enter to exit...
```

---

### CLI mode

```bash
# Download reels
python insta_downloader.py some_username --media-type reels

# Download images with a date range
python insta_downloader.py some_username --media-type images --start-date 2024-01-01 --end-date 2024-12-31

# Pass a full profile URL instead of username
python insta_downloader.py https://www.instagram.com/some_username/ --media-type reels

# Limit to first 20 downloads
python insta_downloader.py some_username --media-type reels --limit 20

# Save to a custom folder
python insta_downloader.py some_username --media-type reels --output-dir "D:/my_downloads"

# Skip the end-of-run pause (for automation/scripts)
python insta_downloader.py some_username --media-type reels --no-pause
```

---

## Desktop App (GUI)

Run the desktop app:

```bash
python gui_app.py
```

The GUI supports:

- Username or profile URL input
- Reels or images selection
- Optional start/end date filtering
- Optional download limit
- Custom output folder selection
- Live download logs in the app window

---

## Build Windows .exe

Install build tools:

```bash
pip install -r requirements-dev.txt
```

Create the executable:

```bash
pyinstaller --onefile --windowed --name InstaDownloader gui_app.py
```

Output location:

- `dist/InstaDownloader.exe`

Notes:

- Run the `.exe` on a machine where Firefox, Chrome, or Edge is logged into Instagram.
- If SmartScreen shows a warning, click **More info** and run anyway (common for unsigned local builds).

---

## Output Structure

Downloads are saved to your `Downloads` folder by default:

```
~/Downloads/insta_downloads/
└── <username>/
    ├── reels/
    │   ├── 20260101_120000_CXyz123.mp4
    │   └── 20260102_093000_DAbc456.mp4
    └── images/
        ├── 20260101_120000_EFgh789.jpg
        └── 20260102_093000_GHij012.jpg
```

When downloaded via a profile **URL**, filenames include the username and type:

```
username_reels_20260101_120000_CXyz123.mp4
username_images_20260101_120000_EFgh789.jpg
```

---

## All CLI Options

| Option | Description | Default |
|---|---|---|
| `profile` | Username or profile URL | prompted |
| `--media-type` | `reels` or `images` | `reels` |
| `--output-dir` | Custom save folder | `~/Downloads/insta_downloads` |
| `--start-date` | Only download from this date (YYYY-MM-DD) | — |
| `--end-date` | Only download up to this date (YYYY-MM-DD) | — |
| `--limit` | Stop after N downloads | — |
| `--no-pause` | Exit without waiting for Enter | — |

---

## How Authentication Works

No passwords are stored or entered. The script reads the Instagram session cookie that your browser already holds after you log in normally. It tries browsers in this order: **Firefox → Chrome → Edge**.

> **macOS note:** Chrome cookie access triggers a one-time Keychain permission popup — click Allow and it will not ask again.

---

## Run Tests

```bash
pip install -r requirements-dev.txt
pytest -q
```

---

## License

MIT
