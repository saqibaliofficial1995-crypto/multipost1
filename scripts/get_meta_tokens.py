"""Meta (Facebook + Instagram) ke long-lived Page token banane ka helper.

Session expire problem ka Meta-side fix:
  short-lived user token (1 ghanta)
     -> long-lived user token (60 din)
        -> PAGE token (ye NEVER expire hota hai jab tak password change /
           app remove na ho)  <-- humein yahi chahiye

Steps:
1. developers.facebook.com par app banao, product "Facebook Login" add karo.
2. Graph API Explorer kholo, apni app select karo, aur ye permissions maango:
     pages_show_list, pages_read_engagement, pages_manage_posts,
     instagram_basic, instagram_content_publish, business_management
3. "Generate Access Token" dabao -> short-lived user token copy karo.
4. Neeche command chalao:

   python scripts/get_meta_tokens.py \\
       --app-id YOUR_APP_ID \\
       --app-secret YOUR_APP_SECRET \\
       --short-token PASTE_TOKEN_HERE \\
       --out tokens/fb_page_token.json

Ye aapke saare Pages, unke never-expiring page tokens, aur linked
Instagram business account IDs print karega, aur JSON save kar dega.
"""
import argparse
import json
import os

import requests

GRAPH = "https://graph.facebook.com/v21.0"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--app-id", required=True)
    ap.add_argument("--app-secret", required=True)
    ap.add_argument("--short-token", required=True)
    ap.add_argument("--out", default="tokens/fb_page_token.json")
    args = ap.parse_args()

    # 1) short-lived -> long-lived user token (60 din)
    r = requests.get(f"{GRAPH}/oauth/access_token", params={
        "grant_type": "fb_exchange_token",
        "client_id": args.app_id,
        "client_secret": args.app_secret,
        "fb_exchange_token": args.short_token,
    }, timeout=60)
    r.raise_for_status()
    long_user_token = r.json()["access_token"]
    print("[1/2] long-lived user token mil gaya (60 din)")

    # 2) page tokens (in par expiry nahi hoti)
    p = requests.get(f"{GRAPH}/me/accounts", params={
        "fields": "id,name,access_token,instagram_business_account{id,username}",
        "access_token": long_user_token,
    }, timeout=60)
    p.raise_for_status()
    pages = p.json().get("data", [])
    if not pages:
        raise SystemExit("Koi Page nahi mila. Permissions check karo.")

    print("\n=== AAPKE PAGES ===")
    for pg in pages:
        ig = pg.get("instagram_business_account") or {}
        print(f"\nPage : {pg['name']}")
        print(f"  page_id      : {pg['id']}")
        print(f"  ig_user_id   : {ig.get('id', '(IG linked nahi hai)')}")
        if ig.get("username"):
            print(f"  ig_username  : @{ig['username']}")

    first = pages[0]
    ig = first.get("instagram_business_account") or {}
    payload = {
        "page_access_token": first["access_token"],
        "page_id": first["id"],
        "page_name": first["name"],
        "ig_user_id": ig.get("id"),
        "note": "Page tokens expire nahi hote. config.yaml me page_id aur ig_user_id daalo.",
    }
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w") as f:
        json.dump(payload, f, indent=2)
    os.chmod(args.out, 0o600)
    print(f"\n[2/2] saved -> {args.out}")
    print("Ab config.yaml me facebook.page_id aur instagram.ig_user_id set karo.")


if __name__ == "__main__":
    main()
