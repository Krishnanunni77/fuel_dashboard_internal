import io
import json
import pandas as pd
import streamlit as st
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload, MediaIoBaseUpload
from google.oauth2 import service_account

SCOPES = ["https://www.googleapis.com/auth/drive"]

@st.cache_resource
def get_drive_service():
    creds_dict = dict(st.secrets["google_service_account"])
    creds = service_account.Credentials.from_service_account_info(
        creds_dict, scopes=SCOPES
    )
    return build("drive", "v3", credentials=creds)

def get_root_folder_id():
    return st.secrets["DRIVE_FOLDER_ID"]

def find_or_create_folder(service, folder_name, parent_id):
    """Find a subfolder by name under parent, create if missing."""
    query = (
        f"name='{folder_name}' and '{parent_id}' in parents "
        f"and mimeType='application/vnd.google-apps.folder' "
        f"and trashed=false"
    )
    results = service.files().list(q=query, fields="files(id, name)").execute()
    files = results.get("files", [])
    
    if files:
        return files[0]["id"]
    
    # Create the subfolder
    metadata = {
        "name": folder_name,
        "mimeType": "application/vnd.google-apps.folder",
        "parents": [parent_id]
    }
    folder = service.files().create(body=metadata, fields="id").execute()
    return folder["id"]

def find_file_id(service, filename, folder_id):
    """Find a file in a specific Drive folder."""
    query = (
        f"name='{filename}' and '{folder_id}' in parents "
        f"and trashed=false"
    )
    results = service.files().list(q=query, fields="files(id, name)").execute()
    files = results.get("files", [])
    return files[0]["id"] if files else None

def download_jsonl(service, region, filename, root_folder_id):
    """Download JSONL from region subfolder."""
    region_folder_id = find_or_create_folder(service, region, root_folder_id)
    file_id = find_file_id(service, filename, region_folder_id)
    
    if not file_id:
        print(f"[Drive] {region}/{filename} not found, returning empty DataFrame")
        return pd.DataFrame()
    
    buffer = io.BytesIO()
    request = service.files().get_media(fileId=file_id)
    downloader = MediaIoBaseDownload(buffer, request)
    
    done = False
    while not done:
        _, done = downloader.next_chunk()
    
    buffer.seek(0)
    try:
        df = pd.read_json(buffer, lines=True)
        print(f"[Drive] Downloaded {region}/{filename}: {len(df)} rows")
        return df
    except Exception as e:
        print(f"[Drive] Error reading {region}/{filename}: {e}")
        return pd.DataFrame()

def upload_jsonl(service, df, region, filename, root_folder_id):
    """Upload DataFrame as JSONL to region subfolder."""
    if df is None:
        df = pd.DataFrame()
    
    region_folder_id = find_or_create_folder(service, region, root_folder_id)
    
    content = df.to_json(orient="records", lines=True, date_format="iso")
    buffer = io.BytesIO(content.encode("utf-8"))
    
    file_id = find_file_id(service, filename, region_folder_id)
    media = MediaIoBaseUpload(
        buffer,
        mimetype="application/octet-stream",
        resumable=False
    )
    
    if file_id:
        service.files().update(
            fileId=file_id,
            media_body=media
        ).execute()
        print(f"[Drive] Updated {region}/{filename}: {len(df)} rows")
    else:
        metadata = {
            "name": filename,
            "parents": [region_folder_id]
        }
        service.files().create(
            body=metadata,
            media_body=media,
            fields="id"
        ).execute()
        print(f"[Drive] Created {region}/{filename}: {len(df)} rows")

def download_checkpoint(service, region, root_folder_id):
    """Download checkpoint for a region."""
    region_folder_id = find_or_create_folder(service, region, root_folder_id)
    file_id = find_file_id(service, "checkpoint.json", region_folder_id)
    
    if not file_id:
        return None
    
    buffer = io.BytesIO()
    request = service.files().get_media(fileId=file_id)
    downloader = MediaIoBaseDownload(buffer, request)
    done = False
    while not done:
        _, done = downloader.next_chunk()
    
    buffer.seek(0)
    try:
        return json.loads(buffer.read()).get("last_fetched_ms")
    except Exception:
        return None

def upload_checkpoint(service, region, ts, root_folder_id):
    """Upload checkpoint for a region."""
    region_folder_id = find_or_create_folder(service, region, root_folder_id)
    
    content = json.dumps({"last_fetched_ms": ts}).encode("utf-8")
    buffer = io.BytesIO(content)
    
    file_id = find_file_id(service, "checkpoint.json", region_folder_id)
    media = MediaIoBaseUpload(buffer, mimetype="application/json")
    
    if file_id:
        service.files().update(fileId=file_id, media_body=media).execute()
    else:
        service.files().create(
            body={"name": "checkpoint.json", "parents": [region_folder_id]},
            media_body=media,
            fields="id"
        ).execute()
    print(f"[Drive] Checkpoint saved for {region}: {ts}")