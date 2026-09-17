import json
import time
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

scopes = [
    'https://www.googleapis.com/auth/youtube.upload',
    'https://www.googleapis.com/auth/youtube',
    'https://www.googleapis.com/auth/drive',
]

with open('tokens/yt_token.json') as f:
    d = json.load(f)

print('Refresh token present:', bool(d.get('refresh_token')))
for sc in scopes:
    name = sc.split('/')[-1]
    print(f'Scope {name}:', sc in d.get('scopes', []))

tok = d.get('token')
s = requests.Session()
retries = Retry(total=5, backoff_factor=1, status_forcelist=[502, 503, 504])
s.mount('https://', HTTPAdapter(max_retries=retries))

for attempt in range(5):
    try:
        r = s.get('https://www.googleapis.com/youtube/v3/channels', params={'part': 'snippet', 'mine': 'true'}, headers={'Authorization': f'Bearer {tok}'}, timeout=15)
        if r.status_code == 200:
            data = r.json()
            items = data.get('items', [])
            if items:
                ch = items[0]
                print('Channel Title:', ch['snippet']['title'])
                print('Channel ID:', ch['id'])
                print('Channel Confirmation:', 'MATCH' if ch['id'] == 'UC6WQ7nljzB1DmVHP61LF3Ug' else 'MISMATCH')
                break
            else:
                print('No channels found')
        else:
            print('Status code:', r.status_code, r.text)
    except Exception as e:
        print(f'Attempt {attempt+1} failed: {e}')
        time.sleep(2)
