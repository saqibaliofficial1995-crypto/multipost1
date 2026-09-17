"""Interactive setup for User-supplied Drive folder, Gemini API key, and Channel Topic.

Performs:
1. Prompt for Drive folder link, extract ID, verify access, count videos, create 'Uploaded' subfolder.
2. Prompt for Gemini API key via getpass, verify API call, set secret via stdin.
3. Prompt for channel topic and write to config.ci.yaml.
4. Update GitHub secrets and git configuration.
"""
import getpass
import json
import os
import re
import socket
import subprocess
import sys
import urllib3.util.connection
import yaml

try:
    urllib3.util.connection.allowed_gai_family = lambda: socket.AF_INET
except Exception:
    pass

import requests
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials

REPO = "bjviufutu-dot/multipost"
DRIVE_API = "https://www.googleapis.com/drive/v3"
GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent"
VIDEO_EXTS = (".mp4", ".mov", ".m4v")


def extract_folder_id(link_or_id):
    raw = (link_or_id or "").strip()
    m = re.search(r"/folders/([a-zA-Z0-9_-]+)", raw)
    if m:
        return m.group(1)
    m2 = re.search(r"[?&]id=([a-zA-Z0-9_-]+)", raw)
    if m2:
        return m2.group(1)
    if re.match(r"^[a-zA-Z0-9_-]{15,}$", raw):
        return raw
    return None


def set_secret_stdin(name, value):
    proc = subprocess.run(
        ["gh", "secret", "set", name, "--repo", REPO],
        input=str(value).encode("utf-8"),
        capture_output=True,
    )
    return proc.returncode == 0


def main():
    print("\n" + "=" * 65)
    print(" MULTIPOST CONFIGURATION UPDATE")
    print("=" * 65)

    # -------------------------------------------------------------
    # 1. Drive Folder Link
    # -------------------------------------------------------------
    print("\n[1/3] GOOGLE DRIVE FOLDER SETUP")
    folder_input = input("Paste your Google Drive folder link: ").strip()
    folder_id = extract_folder_id(folder_input)

    if not folder_id:
        print("[FAIL] Could not parse a valid folder ID from the link provided.")
        sys.exit(1)

    print(f"Extracted Folder ID: {folder_id}")

    # Verify Drive Access
    scopes = [
        "https://www.googleapis.com/auth/youtube.upload",
        "https://www.googleapis.com/auth/youtube",
        "https://www.googleapis.com/auth/drive",
    ]
    creds = Credentials.from_authorized_user_file("tokens/yt_token.json", scopes)
    if not creds.valid and creds.refresh_token:
        creds.refresh(Request())

    headers = {"Authorization": f"Bearer {creds.token}", "Accept": "application/json"}

    try:
        r = requests.get(f"{DRIVE_API}/files/{folder_id}", headers=headers, params={"fields": "id, name, mimeType, trashed"}, timeout=25)
        if r.status_code == 404:
            print("[FAIL] Access failed. Cause: wrong link (the folder ID does not exist or link is malformed).")
            sys.exit(1)
        elif r.status_code == 403:
            print("[FAIL] Access failed. Cause: permissions problem (your account bjviufutu@gmail.com does not have permission to view this folder).")
            sys.exit(1)
        r.raise_for_status()
        f_data = r.json()
        folder_name = f_data.get("name")
        print(f"  - Folder Name: {folder_name}")
        print(f"  - Access Verified: True")
    except requests.exceptions.RequestException as e:
        status = getattr(getattr(e, 'response', None), 'status_code', None)
        if status == 404:
            print("[FAIL] Access failed. Cause: wrong link (folder does not exist).")
        elif status == 403:
            print("[FAIL] Access failed. Cause: permissions problem (access denied).")
        else:
            print(f"[FAIL] Access failed. Cause: network or API error ({e}).")
        sys.exit(1)
    except Exception as e:
        print(f"[FAIL] Failed accessing Drive folder: {e}")
        sys.exit(1)

    # Clean up old auto-created folder & test video if present
    old_folder_id = "1aUp67POY-VoCMMx-T1H7jFb1em924DB4"
    old_video_id = "xJfx0UbyF4g"
    try:
        # Delete old folder from Drive
        del_f = requests.delete(f"{DRIVE_API}/files/{old_folder_id}", headers=headers, timeout=15)
        if del_f.status_code in (200, 204):
            print(f"  - Old auto-created Drive folder deleted: True (ID: {old_folder_id})")
        elif del_f.status_code == 404:
            print(f"  - Old auto-created Drive folder already deleted: True")
    except Exception:
        pass

    try:
        # Delete test video from YouTube
        del_v = requests.delete(f"https://www.googleapis.com/youtube/v3/videos?id={old_video_id}", headers=headers, timeout=15)
        if del_v.status_code in (200, 204):
            print(f"  - YouTube test video deleted: True (ID: {old_video_id})")
        elif del_v.status_code == 404:
            print(f"  - YouTube test video already deleted: True")
    except Exception:
        pass

    # Count videos currently in folder
    q = f"'{folder_id}' in parents and trashed = false and mimeType != 'application/vnd.google-apps.folder'"
    c_resp = requests.get(f"{DRIVE_API}/files", headers=headers, params={"q": q, "fields": "files(id, name)"}, timeout=25)
    c_resp.raise_for_status()
    all_files = c_resp.json().get("files", [])
    videos = [f for f in all_files if os.path.splitext(f.get("name", ""))[1].lower() in VIDEO_EXTS]
    print(f"  - Video Files in Folder: {len(videos)}")
    for v in videos[:5]:
        print(f"      • {v.get('name')} (ID: {v.get('id')})")
    if len(videos) > 5:
        print(f"      ... and {len(videos) - 5} more.")

    # Create 'Uploaded' subfolder inside user folder if not present
    sub_q = f"name = 'Uploaded' and '{folder_id}' in parents and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
    sub_res = requests.get(f"{DRIVE_API}/files", headers=headers, params={"q": sub_q, "fields": "files(id, name)"}, timeout=25)
    sub_res.raise_for_status()
    sub_files = sub_res.json().get("files", [])
    if sub_files:
        uploaded_id = sub_files[0]["id"]
        print(f"  - 'Uploaded' subfolder already exists: True (ID: {uploaded_id})")
    else:
        meta = {"name": "Uploaded", "mimeType": "application/vnd.google-apps.folder", "parents": [folder_id]}
        u_resp = requests.post(f"{DRIVE_API}/files", headers=headers, json=meta, params={"fields": "id, name"}, timeout=25)
        u_resp.raise_for_status()
        uploaded_id = u_resp.json()["id"]
        print(f"  - Created 'Uploaded' subfolder: True (ID: {uploaded_id})")

    # Update .setup_state.json
    state_file = ".setup_state.json"
    with open(state_file, "r", encoding="utf-8") as f:
        st = json.load(f)
    st.setdefault("config", {})["drive_folder_id"] = folder_id
    st["config"]["drive_uploaded_folder_id"] = uploaded_id
    with open(state_file, "w", encoding="utf-8") as f:
        json.dump(st, f, indent=2)

    # Update config.ci.yaml
    with open("config.ci.yaml", "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    cfg.setdefault("drive", {})["inbox_folder_id"] = folder_id

    # -------------------------------------------------------------
    # 2. Channel Topic
    # -------------------------------------------------------------
    print("\n[2/3] CHANNEL TOPIC SETUP")
    topic = input("Enter your channel topic / niche (e.g. Tech Reviews, Gaming Clips, DIY, Cooking): ").strip()
    if not topic:
        topic = "General Entertainment"
    print(f"  - Channel Topic set to: '{topic}'")
    cfg.setdefault("metadata", {})["channel_topic"] = topic

    with open("config.ci.yaml", "w", encoding="utf-8") as f:
        yaml.dump(cfg, f, default_flow_style=False, sort_keys=False)
    print("  - Saved to config.ci.yaml: True")

    # -------------------------------------------------------------
    # 3. Gemini API Key
    # -------------------------------------------------------------
    print("\n[3/3] GOOGLE GEMINI API KEY")
    print("Get your free Gemini API key from: https://aistudio.google.com/app/apikey")
    gemini_key = getpass.getpass("Enter Gemini API Key (hidden): ").strip()

    if not gemini_key:
        print("[FAIL] Gemini API Key cannot be empty.")
        sys.exit(1)

    # Verify Gemini API Key
    print("Verifying Gemini API key with test generation...")
    test_payload = {
        "contents": [{"parts": [{"text": "Reply with only the word OK"}]}],
        "generationConfig": {"temperature": 0.1}
    }
    g_resp = requests.post(f"{GEMINI_API_URL}?key={gemini_key}", json=test_payload, timeout=20)
    if g_resp.status_code == 200:
        print("  - Gemini API Key verified: True")
    else:
        err_msg = g_resp.text
        print(f"[FAIL] Gemini API Key verification failed (HTTP {g_resp.status_code}): {err_msg}")
        sys.exit(1)

    # -------------------------------------------------------------
    # 4. Deploy Secrets to GitHub
    # -------------------------------------------------------------
    print("\nDeploying secrets to GitHub repository...")
    ok1 = set_secret_stdin("DRIVE_FOLDER_ID", folder_id)
    print(f"  - DRIVE_FOLDER_ID deployed: {ok1}")
    ok2 = set_secret_stdin("GEMINI_API_KEY", gemini_key)
    print(f"  - GEMINI_API_KEY deployed: {ok2}")

    if not (ok1 and ok2):
        print("[FAIL] Failed setting GitHub secrets.")
        sys.exit(1)

    print("\n[SUCCESS] All inputs verified and saved successfully!\n")


if __name__ == "__main__":
    main()
