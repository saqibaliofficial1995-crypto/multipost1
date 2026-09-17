import json
import os
import socket
import urllib3.util.connection
urllib3.util.connection.allowed_gai_family = lambda: socket.AF_INET

import requests
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request

scopes = [
    'https://www.googleapis.com/auth/youtube.upload',
    'https://www.googleapis.com/auth/youtube',
    'https://www.googleapis.com/auth/drive',
]

creds = Credentials.from_authorized_user_file('tokens/yt_token.json', scopes)
if not creds.valid and creds.refresh_token:
    creds.refresh(Request())
    with open('tokens/yt_token.json', 'w', encoding='utf-8') as f:
        f.write(creds.to_json())

session = requests.Session()
headers = {
    'Authorization': f'Bearer {creds.token}',
    'Accept': 'application/json'
}

DRIVE_API = 'https://www.googleapis.com/drive/v3'

# 1. Search for existing 'Multipost Inbox'
query = "name = 'Multipost Inbox' and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
resp = session.get(f"{DRIVE_API}/files", headers=headers, params={'q': query, 'spaces': 'drive', 'fields': 'files(id, name, webViewLink)'}, timeout=30)
resp.raise_for_status()
files = resp.json().get('files', [])

if files:
    inbox = files[0]
    print('Found existing Multipost Inbox')
else:
    meta = {
        'name': 'Multipost Inbox',
        'mimeType': 'application/vnd.google-apps.folder'
    }
    c_resp = session.post(f"{DRIVE_API}/files", headers=headers, json=meta, params={'fields': 'id, name, webViewLink'}, timeout=30)
    c_resp.raise_for_status()
    inbox = c_resp.json()
    print('Created Multipost Inbox')

inbox_id = inbox['id']
inbox_link = inbox.get('webViewLink') or f"https://drive.google.com/drive/folders/{inbox_id}"
print('INBOX_ID:', inbox_id)
print('INBOX_LINK:', inbox_link)

# 2. Check or create 'Uploaded' subfolder inside Multipost Inbox
sub_q = f"name = 'Uploaded' and '{inbox_id}' in parents and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
sub_resp = session.get(f"{DRIVE_API}/files", headers=headers, params={'q': sub_q, 'spaces': 'drive', 'fields': 'files(id, name)'}, timeout=30)
sub_resp.raise_for_status()
sub_files = sub_resp.json().get('files', [])

if sub_files:
    uploaded = sub_files[0]
    print('Found existing Uploaded subfolder ID:', uploaded['id'])
else:
    sub_meta = {
        'name': 'Uploaded',
        'mimeType': 'application/vnd.google-apps.folder',
        'parents': [inbox_id]
    }
    u_resp = session.post(f"{DRIVE_API}/files", headers=headers, json=sub_meta, params={'fields': 'id, name'}, timeout=30)
    u_resp.raise_for_status()
    uploaded = u_resp.json()
    print('Created Uploaded subfolder ID:', uploaded['id'])

uploaded_id = uploaded['id']

# Save to .setup_state.json
state_file = '.setup_state.json'
state_data = {}
if os.path.exists(state_file):
    with open(state_file, 'r', encoding='utf-8') as f:
        state_data = json.load(f)

cfg = state_data.setdefault('config', {})
cfg['drive_folder_id'] = inbox_id
cfg['drive_uploaded_folder_id'] = uploaded_id
cfg['drive_folder_link'] = inbox_link

with open(state_file, 'w', encoding='utf-8') as f:
    json.dump(state_data, f, indent=2)

print('Saved DRIVE_FOLDER_ID and DRIVE_UPLOADED_FOLDER_ID to state.')
