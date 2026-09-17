"""Facebook Page Reel / video upload for CI — token env se aata hai."""
import os

import requests

from auth_env import meta_page_token

GRAPH = "https://graph.facebook.com/v21.0"
RUPLOAD = "https://rupload.facebook.com/video-upload/v21.0"


def upload(cfg, video_path, title, description):
    token = meta_page_token()
    page_id = os.environ.get("FB_PAGE_ID") or cfg["facebook"].get("page_id")
    if not page_id:
        raise RuntimeError("FB_PAGE_ID secret missing")

    if cfg["facebook"].get("publish_as_reel", True):
        return _reel(page_id, token, video_path, description)
    return _video(page_id, token, video_path, title, description)


def _reel(page_id, token, video_path, description):
    r = requests.post(f"{GRAPH}/{page_id}/video_reels",
                      data={"upload_phase": "start", "access_token": token},
                      timeout=60)
    r.raise_for_status()
    video_id = r.json()["video_id"]

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

    fin = requests.post(
        f"{GRAPH}/{page_id}/video_reels",
        data={
            "upload_phase": "finish",
            "video_id": video_id,
            "video_state": "PUBLISHED",
            "description": description[:2200],
            "access_token": token,
        }, timeout=120,
    )
    fin.raise_for_status()
    return video_id, "https://www.facebook.com/reel/" + video_id


def _video(page_id, token, video_path, title, description):
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
    return vid, "https://www.facebook.com/" + vid
