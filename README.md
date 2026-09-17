# MULTIPOST — 1 video → YouTube + Facebook + Instagram

Ek video `inbox/` me daalo. Script usko vertical 9:16 me convert karta hai,
phir teeno platform par auto-publish karta hai — daily, set time par.
Session ek baar setup, uske baad auto-refresh hota hai (refresh token + Instagram long-lived token).

---

## 1. Install

```bash
cd multipost
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp config.example.yaml config.yaml
```

ffmpeg + ffprobe system me install hona chahiye (`ffmpeg -version` se check karo).

---

## 2. YouTube setup (10 min)

1. console.cloud.google.com → naya project
2. APIs & Services → Library → **YouTube Data API v3** → Enable
3. OAuth consent screen → External → **PUBLISH karo (Testing mode me na chhodo)**
   - Testing mode me refresh token sirf **7 din** chalta hai — yahi "session
     khatam ho gaya" wali problem hai.
4. Credentials → Create Credentials → **OAuth client ID → Desktop app**
5. JSON download karke rakho: `tokens/google_client_secret.json`
6. Ek baar login:
   ```bash
   python src/main.py --config config.yaml login
   ```
   Browser khulega, login karo. Token `tokens/yt_token.json` me save ho jaayega
   aur uske baad apne aap refresh hota rahega. Dobara login nahi maangega.

---

## 3. Facebook + Instagram setup (15 min)

**Pehle ye zaroori hai:**
- Instagram account Professional (Business ya Creator) hona chahiye
- Setup Instagram API with Instagram Login (graph.instagram.com)
- Personal IG account par API upload kaam nahi karta

Run `python setup_wizard.py` to configure credentials automatically.

---

## 4. Instagram ka ek zaroori catch

Instagram Graph API **local file accept nahi karta** — usko public `https` URL
chahiye. Do options:

**Option A (recommended):** video kisi public bucket par daalo
(Cloudflare R2 / S3 / Bunny — free tier kaafi hai), aur sidecar json me URL do:

```json
{
  "title": "Blindfolded Sword Girl — Fight Scene",
  "description": "AAA cinematic fight sequence",
  "hashtags": "#shorts #reels #cinematic #ai",
  "public_url": "https://cdn.yoursite.com/videos/fight01.mp4"
}
```

**Option B (testing ke liye):** `cloudflared tunnel --url http://localhost:8080`
se local folder expose karo aur wo URL use karo.

Agar `public_url` nahi hoga to YouTube + Facebook chal jaayenge aur
Instagram "failed" mark hoga — baaki platforms block nahi honge.

---

## 5. Rozana use

```bash
# inbox scan + jitne pending hain sab upload
python src/main.py --config config.yaml run --all

# kya hua kya nahi
python src/main.py --config config.yaml status
```

**Auto daily (option 1 — built-in scheduler):**
```bash
nohup python src/scheduler.py --config config.yaml > scheduler.log 2>&1 &
```

**Auto daily (option 2 — cron, zyada reliable):**
```cron
30 9,15,20 * * * cd /path/to/multipost && .venv/bin/python src/main.py --config config.yaml run --all >> run.log 2>&1
```

**Windows:** Task Scheduler → Daily → Program: `.venv\Scripts\python.exe`,
Arguments: `src\main.py --config config.yaml run --all`

---

## 6. Folder structure

```
multipost/
├── config.yaml                 # aapki settings (git me na daalo)
├── inbox/                      # naye videos + optional .json + .jpg thumbnail
├── processed/                  # upload ho chuke videos
├── work/                       # ffmpeg ke vertical outputs
├── tokens/                     # OAuth tokens (secret!)
├── multipost.sqlite3           # job queue, duplicate-safe
├── src/
│   ├── main.py                 # CLI: scan / run / status / login
│   ├── scheduler.py            # daily automation
│   ├── db.py                   # SQLite queue
│   ├── normalize.py            # ffmpeg 9:16 Shorts/Reels-safe encode
│   ├── auth_google.py          # never-expiring YouTube session
│   ├── upload_youtube.py
│   └── upload_instagram.py
```

Ek video ke saath optional 2 files rakh sakte ho:
- `fight01.json` → title / description / hashtags / public_url
- `fight01.jpg`  → YouTube custom thumbnail (CTR ka sabse bada factor)

---

## 7. Views ke liye jo pehle se built-in hai

| Problem | Is project me fix |
|---|---|
| Video private reh jaana → 0 views | `privacyStatus: public` explicitly set hota hai |
| `madeForKids` galat → reach ~0 | `selfDeclaredMadeForKids: false` |
| Shorts/Reels detect na hona | ffmpeg se forced 1080x1920, ≤3 min |
| Thumbnail missing → low CTR | sidecar `.jpg` auto-upload |
| IG post live na hona | container FINISHED tak wait, phir `media_publish` |
| Silent video IG reject | audio na ho to silent track add |
| Spam pattern se reach cut | daily limit + platforms ke beech stagger |

**API se upload karne se views kam nahi hote** — algorithm ko farq nahi padta
ki upload browser se hua ya API se. Views metadata + content par depend karte hain.

---

## 8. Limits jaan lo

- YouTube API daily quota 10,000 units; 1 upload ≈ 1600 → **max ~6 uploads/din**
- Instagram Content Publishing: **25 posts / 24 ghante**
- Reels: 9:16, ≤90s (IG) / ≤3min (YT Shorts), ≤1GB
- Ek time par script ki ek hi instance chalao (SQLite lock + rate limits)

---

## 9. Troubleshooting

| Error | Fix |
|---|---|
| "session expired" baar baar | Google app Testing mode me hai → Publish karo |
| Refresh token nahi mila | Google account → 3rd party access → app remove → dobara login |
| `(#200) Permissions error` (IG) | `instagram_business_content_publish` permission missing |
| IG `media_type REELS` error | account Professional (Business/Creator) nahi hai |
| IG `video_url` fetch fail | URL public nahi hai, ya redirect/auth maang raha hai |
| `quotaExceeded` (YT) | din ka 6 upload limit cross — kal chalega |
