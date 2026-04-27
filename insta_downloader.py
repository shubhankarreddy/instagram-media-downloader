"""Download Instagram reels or images from a public profile using browser cookies."""

from __future__ import annotations

import argparse
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable
from urllib.parse import urlparse

import browser_cookie3
import requests


USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
APP_ID = "936619743392459"
REQUEST_TIMEOUT = 30
DOWNLOAD_TIMEOUT = 60
SUPPORTED_BROWSERS = "Firefox, Chrome, or Edge"
RESERVED_INSTAGRAM_PATHS = {
    "about",
    "accounts",
    "developer",
    "explore",
    "graphql",
    "p",
    "reel",
    "reels",
    "stories",
}
USERNAME_PATTERN = re.compile(r"^[A-Za-z0-9._]{1,30}$")
STAMPED_FILE_PATTERN = re.compile(r"^\d{8}_\d{6}_(?P<code>[A-Za-z0-9_-]+)\.[^.]+$")
URL_NAMED_FILE_PATTERN = re.compile(
    r"^[A-Za-z0-9._]+_(?:reels|images)_\d{8}_\d{6}_(?P<code>[A-Za-z0-9_-]+)\.[^.]+$"
)
LEGACY_REEL_PATTERN = re.compile(r"^(?P<code>[A-Za-z0-9_-]+)\.mp4$")


def validate_username(username: str) -> str:
    normalized = username.strip().strip("@")
    if not normalized:
        raise SystemExit("Username is required.")

    lowered = normalized.lower()
    if lowered in RESERVED_INSTAGRAM_PATHS:
        raise SystemExit(
            "Input looks like an Instagram path, not a profile username. "
            "Please provide a profile URL or username."
        )

    if not USERNAME_PATTERN.fullmatch(normalized):
        raise SystemExit(f"Invalid Instagram username '{normalized}'.")
    return normalized


def sanitize_username(value: str) -> str:
    cleaned = value.strip()
    if cleaned.startswith("http://") or cleaned.startswith("https://"):
        parsed = urlparse(cleaned)
        if "instagram.com" not in parsed.netloc.lower():
            raise SystemExit("URL must point to instagram.com.")

        segments = [segment for segment in parsed.path.split("/") if segment]
        if not segments:
            raise SystemExit("Could not parse username from URL.")
        return validate_username(segments[0])
    return validate_username(cleaned)


def is_url_input(value: str) -> bool:
    cleaned = value.strip().lower()
    return cleaned.startswith("http://") or cleaned.startswith("https://")


def request_json(
    session: requests.Session,
    method: str,
    url: str,
    *,
    timeout: int,
    context: str,
    **request_kwargs: object,
) -> dict:
    try:
        response = session.request(method=method, url=url, timeout=timeout, **request_kwargs)
    except requests.RequestException as error:
        raise SystemExit(f"{context} failed due to a network error: {error}") from error

    if response.status_code != 200:
        raise SystemExit(
            f"{context} failed with HTTP {response.status_code}. "
            f"Body preview: {response.text[:180]!r}"
        )

    try:
        data = response.json()
    except ValueError as error:
        raise SystemExit(
            f"{context} returned a non-JSON response (HTTP {response.status_code}). "
            f"Body preview: {response.text[:180]!r}"
        ) from error
    return data


def build_session() -> requests.Session:
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": USER_AGENT,
            "x-ig-app-id": APP_ID,
            "Referer": "https://www.instagram.com/",
        }
    )

    cookie_loaders: list[tuple[str, Callable[..., object]]] = [
        ("Firefox", browser_cookie3.firefox),
        ("Chrome", browser_cookie3.chrome),
        ("Edge", browser_cookie3.edge),
    ]

    cookies = None
    used_browser = None
    for browser_name, loader in cookie_loaders:
        try:
            maybe_cookies = loader(domain_name="instagram.com")
        except Exception:
            continue

        if maybe_cookies and len(maybe_cookies) > 0:
            cookies = maybe_cookies
            used_browser = browser_name
            break

    if not cookies:
        raise SystemExit(
            f"Could not read Instagram cookies from {SUPPORTED_BROWSERS}. "
            "Open one of those browsers, log into Instagram, and retry."
        )

    session.cookies.update(cookies)
    print(f"Using Instagram login from {used_browser} cookies.")
    return session


def get_user_id(session: requests.Session, username: str) -> str:
    url = f"https://www.instagram.com/api/v1/users/web_profile_info/?username={username}"
    data = request_json(
        session,
        "GET",
        url,
        timeout=REQUEST_TIMEOUT,
        context=(
            f"Profile lookup for '{username}'"
            f" (ensure you are logged into Instagram in {SUPPORTED_BROWSERS})"
        ),
    )
    user = (data.get("data") or {}).get("user") or {}
    user_id = user.get("id")
    if not user_id:
        raise SystemExit("Could not resolve profile ID from Instagram response.")
    return str(user_id)


def pick_highest_quality(candidates: list[dict]) -> str | None:
    best_url = None
    best_score = -1
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        url = candidate.get("url")
        if not url:
            continue

        width = candidate.get("width") or 0
        height = candidate.get("height") or 0
        quality_rank = width * height
        if quality_rank > best_score:
            best_score = quality_rank
            best_url = url
    return best_url


def build_existing_code_index(target_dir: Path, include_legacy_reels: bool = False) -> set[str]:
    codes: set[str] = set()
    if not target_dir.exists():
        return codes

    for child in target_dir.iterdir():
        if not child.is_file():
            continue

        stamped_match = STAMPED_FILE_PATTERN.match(child.name)
        if stamped_match:
            codes.add(stamped_match.group("code"))
            continue

        url_named_match = URL_NAMED_FILE_PATTERN.match(child.name)
        if url_named_match:
            codes.add(url_named_match.group("code"))
            continue

        if include_legacy_reels:
            legacy_match = LEGACY_REEL_PATTERN.match(child.name)
            if legacy_match:
                codes.add(legacy_match.group("code"))

    return codes


def normalize_end_of_day(end_date: datetime | None) -> datetime | None:
    if not end_date:
        return None
    return end_date.replace(hour=23, minute=59, second=59, microsecond=999999)


def normalize_timestamp_to_datetime(timestamp: object) -> datetime | None:
    if timestamp is None:
        return None

    raw_value: object = timestamp
    if isinstance(raw_value, str):
        raw_value = raw_value.strip()
        if not raw_value:
            return None

    try:
        ts_int = int(float(raw_value))
    except (TypeError, ValueError):
        return None

    abs_ts = abs(ts_int)
    if abs_ts > 10**14:
        ts_int //= 1_000_000
    elif abs_ts > 10**11:
        ts_int //= 1_000

    try:
        return datetime.fromtimestamp(ts_int, tz=timezone.utc)
    except (OverflowError, OSError, ValueError):
        return None


def pick_media_timestamp(media: dict, fallback: object = None) -> object:
    for key in ("taken_at", "taken_at_ts", "device_timestamp", "original_timestamp"):
        value = media.get(key)
        if value not in (None, ""):
            return value

    caption = media.get("caption")
    if isinstance(caption, dict):
        for key in ("created_at_utc", "created_at"):
            value = caption.get(key)
            if value not in (None, ""):
                return value

    return fallback


def setup_profile_dirs(profile: str, output_dir: Path, media_type: str) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    profile_dir = output_dir / profile
    profile_dir.mkdir(parents=True, exist_ok=True)

    target_dir = profile_dir / media_type
    target_dir.mkdir(parents=True, exist_ok=True)
    return profile_dir, target_dir


def build_media_filename(
    profile: str,
    media_type: str,
    stamp: str,
    media_code: str,
    extension: str,
    source_was_url: bool,
) -> str:
    if source_was_url:
        return f"{profile}_{media_type}_{stamp}_{media_code}.{extension}"
    return f"{stamp}_{media_code}.{extension}"


def positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("--limit must be a positive integer")
    return parsed


def default_output_dir() -> Path:
    return Path.home() / "Downloads" / "insta_downloads"


def iter_reel_video_urls(session: requests.Session, user_id: str):
    csrf_token = session.cookies.get("csrftoken", "")
    if csrf_token:
        session.headers["x-csrftoken"] = csrf_token
    session.headers["X-Requested-With"] = "XMLHttpRequest"

    next_max_id = None
    page_num = 0
    total_items_processed = 0
    while True:
        page_num += 1
        url = "https://www.instagram.com/api/v1/clips/user/"
        payload = {"target_user_id": user_id, "page_size": "24"}
        if next_max_id:
            payload["max_id"] = next_max_id

        data = request_json(
            session,
            "POST",
            url,
            data=payload,
            timeout=REQUEST_TIMEOUT,
            context="Clips request",
        )
        items = data.get("items") or []
        paging_info = data.get("paging_info") or {}
        more_available = paging_info.get("more_available", False)
        print(f"  [Page {page_num}] Found {len(items)} items, more_available={more_available}")
        total_items_processed += len(items)
        
        for item in items:
            media = item.get("media") or item
            if str(media.get("product_type", "")).lower() not in {"clips", "reels"}:
                continue

            video_versions = media.get("video_versions") or []
            if video_versions:
                video_url = pick_highest_quality(video_versions)
                media_code = media.get("code") or media.get("id") or media.get("pk")
                taken_at = pick_media_timestamp(media)
                if video_url and media_code:
                    yield str(media_code), video_url, taken_at

            for carousel in media.get("carousel_media") or []:
                carousel_video_versions = carousel.get("video_versions") or []
                carousel_code = carousel.get("code") or carousel.get("id") or carousel.get("pk")
                if not carousel_video_versions or not carousel_code:
                    continue
                carousel_video_url = pick_highest_quality(carousel_video_versions)
                if carousel_video_url:
                    carousel_taken_at = pick_media_timestamp(carousel, fallback=taken_at)
                    yield str(carousel_code), carousel_video_url, carousel_taken_at

        if not more_available:
            print(f"  [Pagination Complete] Reached end after {page_num} pages, {total_items_processed} total items processed.")
            break
        next_max_id = paging_info.get("max_id")
        if not next_max_id:
            print(f"  [Pagination Stopped] No max_id token after {page_num} pages.")
            break


def iter_image_urls(session: requests.Session, user_id: str):
    next_max_id = None
    page_num = 0
    total_items_processed = 0

    while True:
        page_num += 1
        url = f"https://www.instagram.com/api/v1/feed/user/{user_id}/?count=24"
        if next_max_id:
            url += f"&max_id={next_max_id}"

        data = request_json(
            session,
            "GET",
            url,
            timeout=REQUEST_TIMEOUT,
            context="Feed request",
        )
        items = data.get("items") or []
        more_available = data.get("more_available", False)
        print(f"  [Page {page_num}] Found {len(items)} items, more_available={more_available}")
        total_items_processed += len(items)

        for media in items:
            if str(media.get("product_type", "")).lower() in {"clips", "reels"}:
                continue

            taken_at = pick_media_timestamp(media)

            image_versions = (media.get("image_versions2") or {}).get("candidates") or []
            if image_versions:
                image_url = pick_highest_quality(image_versions)
                media_code = media.get("code") or media.get("id") or media.get("pk")
                if image_url and media_code:
                    yield str(media_code), image_url, taken_at

            for carousel in media.get("carousel_media") or []:
                carousel_images = (carousel.get("image_versions2") or {}).get("candidates") or []
                if not carousel_images:
                    continue
                image_url = pick_highest_quality(carousel_images)
                carousel_code = carousel.get("code") or carousel.get("id") or carousel.get("pk")
                carousel_taken_at = pick_media_timestamp(carousel, fallback=taken_at)
                if image_url and carousel_code:
                    yield str(carousel_code), image_url, carousel_taken_at

        if not more_available:
            print(
                f"  [Pagination Complete] Reached end after {page_num} pages, {total_items_processed} total items processed."
            )
            break

        next_max_id = data.get("next_max_id")
        if not next_max_id:
            print(f"  [Pagination Stopped] No max_id token after {page_num} pages.")
            break


def download_file(session: requests.Session, url: str, output_path: Path) -> None:
    with session.get(url, stream=True, timeout=DOWNLOAD_TIMEOUT) as response:
        response.raise_for_status()
        with output_path.open("wb") as file_handle:
            for chunk in response.iter_content(chunk_size=1024 * 512):
                if chunk:
                    file_handle.write(chunk)


def format_taken_at(value: object) -> str:
    timestamp_dt = normalize_timestamp_to_datetime(value)
    if not timestamp_dt:
        return "unknown_date"

    return timestamp_dt.strftime("%Y%m%d_%H%M%S")


def parse_date(date_str: str | None) -> datetime | None:
    if not date_str:
        return None
    try:
        return datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError as error:
        raise SystemExit(f"Invalid date format '{date_str}'. Use YYYY-MM-DD") from error


def is_within_date_range(
    timestamp: object,
    start_date: datetime | None,
    end_datetime: datetime | None,
) -> bool:
    media_date = normalize_timestamp_to_datetime(timestamp)
    if not media_date:
        return start_date is None and end_datetime is None

    if start_date and media_date < start_date:
        return False
    if end_datetime and media_date > end_datetime:
        return False

    return True


def download_reels(
    profile: str,
    output_dir: Path,
    limit: int | None,
    start_date: datetime | None = None,
    end_date: datetime | None = None,
    source_was_url: bool = False,
) -> None:
    profile = sanitize_username(profile)
    profile_dir, reels_dir = setup_profile_dirs(profile, output_dir, "reels")

    session = build_session()
    user_id = get_user_id(session, profile)

    date_filter_str = ""
    if start_date or end_date:
        start_str = start_date.strftime("%Y-%m-%d") if start_date else "*"
        end_str = end_date.strftime("%Y-%m-%d") if end_date else "*"
        date_filter_str = f" (dates: {start_str} to {end_str})"

    print(f"Starting download for @{profile}{date_filter_str}...")
    print(f"Fetching available reels (pages will be logged below):")
    end_datetime = normalize_end_of_day(end_date)
    
    seen = set()
    existing_codes = build_existing_code_index(reels_dir, include_legacy_reels=True)
    downloaded = 0
    skipped = 0
    filtered_out = 0
    failed = 0
    processed = 0
    for media_code, media_url, taken_at in iter_reel_video_urls(session, user_id):
        processed += 1
        if media_code in seen:
            continue
        seen.add(media_code)

        if not is_within_date_range(taken_at, start_date, end_datetime):
            filtered_out += 1
            continue

        if media_code in existing_codes:
            skipped += 1
            continue

        stamp = format_taken_at(taken_at)
        filename = build_media_filename(
            profile,
            "reels",
            stamp,
            media_code,
            "mp4",
            source_was_url,
        )
        output_path = reels_dir / filename
        try:
            download_file(session, media_url, output_path)
        except requests.RequestException as error:
            failed += 1
            raise SystemExit(f"Failed downloading reel {media_code}: {error}") from error

        downloaded += 1
        existing_codes.add(media_code)
        if downloaded % 10 == 0:
            print(f"  Progress: Downloaded {downloaded} files so far...")

        if limit is not None and downloaded >= limit:
            print(f"  [Limit reached] Stopping after {downloaded} downloads.")
            break

    if downloaded == 0 and skipped == 0 and filtered_out == 0:
        print(
            f"No reels found for @{profile}. If this looks wrong, open Instagram in {SUPPORTED_BROWSERS} and refresh login."
        )
    else:
        print()
        print("=" * 60)
        print(f"Reels Download Complete for @{profile}")
        print(f"  Total files processed: {processed}")
        print(f"  Filtered by date: {filtered_out}")
        print(f"  Downloaded (new): {downloaded}")
        print(f"  Skipped (already existed): {skipped}")
        print(f"  Failed: {failed}")
        print(f"  Profile folder: {profile_dir}")
        print(f"  Reels folder: {reels_dir}")
    print(f"=" * 60)


def download_images(
    profile: str,
    output_dir: Path,
    limit: int | None,
    start_date: datetime | None = None,
    end_date: datetime | None = None,
    source_was_url: bool = False,
) -> None:
    profile = sanitize_username(profile)
    profile_dir, images_dir = setup_profile_dirs(profile, output_dir, "images")

    session = build_session()
    user_id = get_user_id(session, profile)

    date_filter_str = ""
    if start_date or end_date:
        start_str = start_date.strftime("%Y-%m-%d") if start_date else "*"
        end_str = end_date.strftime("%Y-%m-%d") if end_date else "*"
        date_filter_str = f" (dates: {start_str} to {end_str})"

    print(f"Starting image download for @{profile}{date_filter_str}...")
    print("Fetching available posts (pages will be logged below):")
    end_datetime = normalize_end_of_day(end_date)

    seen = set()
    existing_codes = build_existing_code_index(images_dir)
    downloaded = 0
    skipped = 0
    filtered_out = 0
    failed = 0
    processed = 0
    for media_code, media_url, taken_at in iter_image_urls(session, user_id):
        processed += 1
        if media_code in seen:
            continue
        seen.add(media_code)

        if not is_within_date_range(taken_at, start_date, end_datetime):
            filtered_out += 1
            continue

        if media_code in existing_codes:
            skipped += 1
            continue

        stamp = format_taken_at(taken_at)
        filename = build_media_filename(
            profile,
            "images",
            stamp,
            media_code,
            "jpg",
            source_was_url,
        )
        output_path = images_dir / filename
        try:
            download_file(session, media_url, output_path)
        except requests.RequestException as error:
            failed += 1
            raise SystemExit(f"Failed downloading image {media_code}: {error}") from error

        downloaded += 1
        existing_codes.add(media_code)
        if downloaded % 10 == 0:
            print(f"  Progress: Downloaded {downloaded} files so far...")

        if limit is not None and downloaded >= limit:
            print(f"  [Limit reached] Stopping after {downloaded} downloads.")
            break

    if downloaded == 0 and skipped == 0 and filtered_out == 0:
        print(
            f"No images found for @{profile}. If this looks wrong, open Instagram in {SUPPORTED_BROWSERS} and refresh login."
        )
    else:
        print()
        print("=" * 60)
        print(f"Image Download Complete for @{profile}")
        print(f"  Total files processed: {processed}")
        print(f"  Filtered by date: {filtered_out}")
        print(f"  Downloaded (new): {downloaded}")
        print(f"  Skipped (already existed): {skipped}")
        print(f"  Failed: {failed}")
        print(f"  Profile folder: {profile_dir}")
        print(f"  Images folder: {images_dir}")
        print("=" * 60)


def parse_timeframe_interactive() -> tuple[datetime | None, datetime | None]:
    start_raw = input("Enter start date (YYYY-MM-DD) or press Enter to skip: ").strip()
    end_raw = input("Enter end date (YYYY-MM-DD) or press Enter to skip: ").strip()
    return parse_date(start_raw or None), parse_date(end_raw or None)


def choose_media_type_interactive() -> str:
    while True:
        media_type = input("What to download? (reels/images): ").strip().lower()
        if media_type in {"reels", "images"}:
            return media_type
        print("Please type 'reels' or 'images'.")


def choose_source_interactive() -> tuple[str, str, datetime | None, datetime | None, bool]:
    while True:
        source = input("Download by URL or username? (url/username): ").strip().lower()
        if source in {"url", "username"}:
            break
        print("Please type 'url' or 'username'.")

    if source == "url":
        raw_url = input("Enter Instagram profile URL: ").strip()
        profile = sanitize_username(raw_url)
        media_type = choose_media_type_interactive()
        start_date, end_date = parse_timeframe_interactive()
        return profile, media_type, start_date, end_date, True

    username = input("Enter Instagram username: ").strip()
    if not username:
        raise SystemExit("Username is required.")

    media_type = choose_media_type_interactive()

    start_date, end_date = parse_timeframe_interactive()
    return sanitize_username(username), media_type, start_date, end_date, False


def main() -> None:
    default_output = default_output_dir()
    parser = argparse.ArgumentParser(
        description="Download Instagram reels or images from a public profile.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    python insta_downloader.py
    python insta_downloader.py some_username --media-type reels
    python insta_downloader.py some_username --media-type images --start-date 2024-01-01 --end-date 2024-12-31
        """,
    )
    parser.add_argument(
        "profile",
        nargs="?",
        default=None,
        help="Instagram profile username (will be prompted if not provided)",
    )
    parser.add_argument(
        "--output-dir",
        default=str(default_output),
        help=(
            f"Base folder for downloads (default: {default_output}). "
            "Creates {output_dir}/{profile}/reels and {output_dir}/{profile}/images"
        ),
    )
    parser.add_argument(
        "--limit",
        type=positive_int,
        default=None,
        help="Stop after downloading this many files",
    )
    parser.add_argument(
        "--media-type",
        choices=["reels", "images"],
        default="reels",
        help="Choose what to download in CLI mode (default: reels)",
    )
    parser.add_argument(
        "--start-date",
        default=None,
        help="Download media from this date onwards (format: YYYY-MM-DD)",
    )
    parser.add_argument(
        "--end-date",
        default=None,
        help="Download media up to this date (format: YYYY-MM-DD)",
    )
    parser.add_argument(
        "--no-pause",
        action="store_true",
        help="Exit immediately after completion without waiting for Enter",
    )
    args = parser.parse_args()

    output_dir = Path(args.output_dir).expanduser()

    if args.profile:
        source_was_url = is_url_input(args.profile)
        profile = sanitize_username(args.profile)
        start_date = parse_date(args.start_date)
        end_date = parse_date(args.end_date)
        media_type = args.media_type
    else:
        profile, media_type, start_date, end_date, source_was_url = choose_source_interactive()

    if media_type == "images":
        download_images(
            profile,
            output_dir,
            args.limit,
            start_date=start_date,
            end_date=end_date,
            source_was_url=source_was_url,
        )
    else:
        download_reels(
            profile,
            output_dir,
            args.limit,
            start_date=start_date,
            end_date=end_date,
            source_was_url=source_was_url,
        )

    print("Task completed.")
    if not args.no_pause:
        try:
            input("Press Enter to exit...")
        except EOFError:
            pass


if __name__ == "__main__":
    main()

