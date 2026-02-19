"""
upload_local_cache_to_drive.py

One-time migration script:
- Reads existing local JSONL cache files
- Uploads them to Google Drive
- Sets checkpoint to the latest timestamp found in the data
  so next run only fetches the missing day(s)

Run once from your project root:
    python upload_local_cache_to_drive.py
"""

import sys

import tomli as tomllib
import pandas as pd
from pathlib import Path
from typing import Optional
from googleapiclient.discovery import build
from google.oauth2 import service_account

# ── Setup ────────────────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parent
CACHE_DIR = BASE_DIR / "cache_data"
SECRETS_PATH = BASE_DIR / ".streamlit" / "secrets.toml"

REGIONS = ["IND", "NASA", "EU", "FML"]

FILES = [
    "theft.jsonl",
    "fill.jsonl",
    "low_fuel.jsonl",
    "data_loss.jsonl",
    "theft_cev.jsonl",
    "fill_cev.jsonl",
]

SCOPES = ["https://www.googleapis.com/auth/drive"]


def read_local_jsonl(path: Path) -> pd.DataFrame:
    if not path.exists():
        print(f"  [SKIP] Not found: {path.name}")
        return pd.DataFrame()
    try:
        df = pd.read_json(path, lines=True)
        print(f"  [READ] {path.name}: {len(df)} rows")
        return df
    except Exception as e:
        print(f"  [ERROR] Reading {path.name}: {e}")
        return pd.DataFrame()


def get_latest_timestamp_ms(df: pd.DataFrame) -> Optional[int]:
    """Find the latest time_ms in a dataframe."""
    if df is None or df.empty:
        return None
    if "time_ms" in df.columns:
        return int(df["time_ms"].max())
    return None


def ensure_time_ms(df: pd.DataFrame) -> pd.DataFrame:
    """Ensure time_ms column exists."""
    if df.empty or "time_ms" in df.columns:
        return df
    if "time" not in df.columns:
        return df
    try:
        if pd.api.types.is_numeric_dtype(df["time"]):
            df["time_ms"] = df["time"]
        else:
            df["time"] = pd.to_datetime(df["time"], errors="coerce")
            df["time_ms"] = df["time"].astype("int64") // 10**6
    except Exception as e:
        print(f"  [WARN] Could not compute time_ms: {e}")
    return df


if __name__ == "__main__":
    sys.path.insert(0, str(BASE_DIR))

    # ── Load secrets ─────────────────────────────────────────
    if not SECRETS_PATH.exists():
        print(f"ERROR: secrets.toml not found at {SECRETS_PATH}")
        sys.exit(1)

    print(f"Reading secrets from: {SECRETS_PATH}")
    with open(SECRETS_PATH, "rb") as f:
        secrets = tomllib.load(f)

    # ── Connect to Drive ──────────────────────────────────────
    from drive_cache import upload_jsonl, upload_checkpoint, download_checkpoint

    creds = service_account.Credentials.from_service_account_info(
        secrets["google_service_account"], scopes=SCOPES
    )
    service = build("drive", "v3", credentials=creds)
    root_folder_id = secrets["DRIVE_FOLDER_ID"]
    print(f"Connected to Drive. Root folder: {root_folder_id}\n")

    # ── Process each region ───────────────────────────────────
    for region in REGIONS:
        region_dir = CACHE_DIR / region
        print(f"\n{'='*40}")
        print(f"Region: {region}")
        print(f"{'='*40}")

        if not region_dir.exists():
            print(f"  [SKIP] No local cache dir found")
            continue

        latest_ms = None

        for filename in FILES:
            df = read_local_jsonl(region_dir / filename)
            if df.empty:
                continue

            df = ensure_time_ms(df)

            ts = get_latest_timestamp_ms(df)
            if ts and (latest_ms is None or ts > latest_ms):
                latest_ms = ts

            print(f"  [UPLOAD] {filename} ({len(df)} rows) → Drive...")
            try:
                upload_jsonl(service, df, region, filename, root_folder_id)
                print(f"  [OK] {filename} uploaded")
            except Exception as e:
                print(f"  [ERROR] {filename}: {e}")

        # Set checkpoint to latest timestamp so only missing days are fetched next
        if latest_ms:
            existing = download_checkpoint(service, region, root_folder_id)
            print(f"\n  Existing checkpoint : {existing}")
            print(f"  New checkpoint      : {latest_ms}")
            print(f"  Date                : {pd.to_datetime(latest_ms, unit='ms')}")
            upload_checkpoint(service, region, latest_ms, root_folder_id)
            print(f"  [OK] Checkpoint updated for {region}")
        else:
            print(f"  [WARN] No timestamps found, checkpoint not updated")

    print(f"\n{'='*40}")
    print("Migration complete!")
    print("Next app run will only fetch data after the last cached timestamp.")
    print(f"{'='*40}")