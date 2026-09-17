"""Instagram Reels upload (Graph API).

Zaroori baatein:
 - Account BUSINESS ya CREATOR hona chahiye aur ek Facebook Page se linked.
   Personal account par API upload kaam nahi karta.
 - IG local file accept NAHI karta. Video ek PUBLIC https URL par honi chahiye.
 - 2 step hota hai: /media (container) -> wait until FINISHED -> /media_publish
   Dusra step miss karna = post live hi nahi hota. Ye bahut common galti hai.
"""
import json
import time

import requests

GRAPH = "https://graph.facebook.com/v21.0"


def _token(path):
    with open(path) as f:
        return json.load(f)["page_access_token"]


def upload(cfg, public_video_url, caption):
    ig = cfg["instagram"]
    user_id = ig["ig_user_id"]
    token = _token(ig["page_access_token_file"])

    if not public_video_url:
        raise RuntimeError(
            "Instagram ke liye public_url chahiye. Sidecar .json me "
            '"public_url" field do, ya hosting mode setup karo.'
        )

    # 1) container banao
    r = requests.post(
        f"{GRAPH}/{user_id}/media",
        data={
            "media_type": "REELS",
            "video_url": public_video_url,
            "caption": caption[:2200],
            "share_to_feed": "true",
            "access_token": token,
        }, timeout=120,
    )
    r.raise_for_status()
    container_id = r.json()["id"]
    print(f"[ig] container: {container_id}")

    # 2) FINISHED hone tak wait karo (warna publish fail hoga)
    for attempt in range(60):
        time.sleep(5)
        s = requests.get(
            f"{GRAPH}/{container_id}",
            params={"fields": "status_code,status", "access_token": token},
            timeout=60,
        )
        s.raise_for_status()
        code = s.json().get("status_code")
        if code == "FINISHED":
            break
        if code == "ERROR":
            raise RuntimeError(f"IG container error: {s.json().get('status')}")
        print(f"[ig] processing... ({code})")
    else:
        raise RuntimeError("IG container 5 min me ready nahi hua")

    # 3) publish
    p = requests.post(
        f"{GRAPH}/{user_id}/media_publish",
        data={"creation_id": container_id, "access_token": token}, timeout=120,
    )
    p.raise_for_status()
    media_id = p.json()["id"]

    permalink = ""
    try:
        pl = requests.get(
            f"{GRAPH}/{media_id}",
            params={"fields": "permalink", "access_token": token}, timeout=60,
        )
        permalink = pl.json().get("permalink", "")
    except Exception:
        pass

    print(f"[ig] published: {media_id}")
    return media_id, permalink
