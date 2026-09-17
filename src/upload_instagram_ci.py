"""Instagram Reels publish for CI — token env se, video public URL se."""
import os
import time

import requests

from auth_env import meta_page_token

GRAPH = "https://graph.facebook.com/v21.0"


def is_available(cfg=None):
    token = os.environ.get("META_PAGE_TOKEN")
    user_id = os.environ.get("IG_USER_ID") or (cfg.get("instagram", {}).get("ig_user_id") if cfg else None)
    return bool(token and user_id)


def upload(cfg, public_video_url, caption):
    if not is_available(cfg):
        print("[ig] SKIPPED: META_PAGE_TOKEN and/or IG_USER_ID are unset.")
        return None, ""

    token = meta_page_token()
    user_id = os.environ.get("IG_USER_ID") or cfg["instagram"].get("ig_user_id")

    # 0) Check publishing limit
    try:
        limit_resp = requests.get(
            f"{GRAPH}/{user_id}/content_publishing_limit",
            params={"fields": "config,quota_usage", "access_token": token},
            timeout=30,
        )
        if limit_resp.status_code == 200:
            limit_data = limit_resp.json().get("data", [{}])[0]
            quota = limit_data.get("quota_usage", 0)
            max_limit = limit_data.get("config", {}).get("quota_total", 50)
            print(f"[ig] Publishing quota: {quota}/{max_limit} used in last 24 hours.")
            if quota >= max_limit:
                raise RuntimeError(f"Instagram publishing limit reached ({quota}/{max_limit})")
    except Exception as e:
        print(f"[ig] notice: could not verify publishing limit ({e})")

    # 1) container
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
    print(f"[ig] container {container_id}", flush=True)

    # 2) FINISHED tak wait (warna publish fail hota hai)
    for _ in range(90):
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
    else:
        raise RuntimeError("IG container ready nahi hua (7+ min)")

    # 3) publish — ye step miss karna = post live hi nahi hoga
    p = requests.post(
        f"{GRAPH}/{user_id}/media_publish",
        data={"creation_id": container_id, "access_token": token}, timeout=120,
    )
    p.raise_for_status()
    media_id = p.json()["id"]

    permalink = ""
    try:
        pl = requests.get(f"{GRAPH}/{media_id}",
                          params={"fields": "permalink", "access_token": token},
                          timeout=60)
        permalink = pl.json().get("permalink", "")
    except Exception:
        pass

    return media_id, permalink
