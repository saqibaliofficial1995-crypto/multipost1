"""Facebook Page video / Reel upload (Graph API).

Reels = 3-step resumable upload (start -> upload -> finish).
Normal video = single multipart POST.
"""
import json
import os

import requests

GRAPH = "https://graph.facebook.com/v21.0"
RUPLOAD = "https://rupload.facebook.com/video-upload/v21.0"


def _token(path):
    with open(path) as f:
        data = json.load(f)
    return data["page_access_token"]


def upload(cfg, video_path, title, description):
    fb = cfg["facebook"]
    page_id = fb["page_id"]
    token = _token(fb["page_access_token_file"])

    if fb.get("publish_as_reel", True):
        return _upload_reel(page_id, token, video_path, description)
    return _upload_video(page_id, token, video_path, title, description)


def _upload_reel(page_id, token, video_path, description):
    # 1) start
    r = requests.post(
        f"{GRAPH}/{page_id}/video_reels",
        data={"upload_phase": "start", "access_token": token}, timeout=60,
    )
    r.raise_for_status()
    video_id = r.json()["video_id"]

    # 2) upload binary
    size = os.path.getsize(video_path)
    with open(video_path, "rb") as f:
        up = requests.post(
            f"{RUPLOAD}/{video_id}",
            headers={
                "Authorization": f"OAuth {token}",
                "offset": "0",
                "file_size": str(size),
            },
            data=f, timeout=1800,
        )
    up.raise_for_status()

    # 3) finish + publish
    fin = requests.post(
        f"{GRAPH}/{page_id}/video_reels",
        data={
            "upload_phase": "finish",
            "video_id": video_id,
            "video_state": "PUBLISHED",   # DRAFT rakha to live nahi hoga
            "description": description[:2200],
            "access_token": token,
        }, timeout=120,
    )
    fin.raise_for_status()
    print(f"[fb] reel published: {video_id}")
    return video_id, "https://www.facebook.com/reel/" + video_id


def _upload_video(page_id, token, video_path, title, description):
    with open(video_path, "rb") as f:
        r = requests.post(
            f"{GRAPH}/{page_id}/videos",
            data={
                "title": title[:255],
                "description": description[:5000],
                "published": "true",
                "access_token": token,
            },
            files={"source": f}, timeout=1800,
        )
    r.raise_for_status()
    vid = r.json()["id"]
    print(f"[fb] video published: {vid}")
    return vid, "https://www.facebook.com/" + vid
