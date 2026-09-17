# Cloud Mode — PC band ho to bhi daily upload (GitHub Actions)

Koi server nahi, koi PC nahi. GitHub ke server par cron chalta hai, free.

```
queue.csv (repo)  +  videos (R2/S3)
        ↓
GitHub Actions cron (din me 3 baar)
        ↓
download → ffmpeg 9:16 → YouTube + Facebook + Instagram
        ↓
state/uploaded.json repo me commit  (duplicate upload kabhi nahi)
```

---

## Step 1 — Local par ek baar login (sirf ek baar, zindagi me)

GitHub Actions me browser nahi hota, isliye login local par karna padta hai
aur uska **refresh token** GitHub ko de dete hain.

```bash
pip install -r requirements.txt
cp config.example.yaml config.yaml
# tokens/google_client_secret.json rakho (README Step 2 dekho)
python src/main.py --config config.yaml login
python src/print_refresh_token.py
```

Aakhri command 3 values print karegi. Unhe copy kar lo.

<b>Zaroori:</b> Google Cloud me OAuth app **PUBLISHED** honi chahiye. Testing mode
me refresh token 7 din me mar jaata hai — phir Actions fail hone lagega.

---

## Step 2 — Meta (FB + IG) token

```bash
python scripts/get_meta_tokens.py \
  --app-id YOUR_APP_ID --app-secret YOUR_APP_SECRET \
  --short-token PASTE_SHORT_TOKEN \
  --out tokens/fb_page_token.json
```

Ye `page_access_token` (never expires), `page_id`, aur `ig_user_id` dega.

---

## Step 3 — GitHub repo + Secrets

```bash
git init
git add -A
git commit -m "multipost"
gh repo create multipost --private --source=. --push
# ya manually: GitHub par private repo banao aur push karo
```

<b>Repo PRIVATE rakho.</b>

Phir: **Settings → Secrets and variables → Actions → New repository secret**

| Secret | Value | Zaroori? |
| --- | --- | --- |
| `YT_CLIENT_ID` | Step 1 se | YouTube ke liye |
| `YT_CLIENT_SECRET` | Step 1 se | YouTube ke liye |
| `YT_REFRESH_TOKEN` | Step 1 se | YouTube ke liye |
| `META_PAGE_TOKEN` | Step 2 ka page_access_token | FB + IG |
| `FB_PAGE_ID` | Step 2 se | Facebook |
| `IG_USER_ID` | Step 2 se | Instagram |
| `S3_ENDPOINT` | `https://<acct>.r2.cloudflarestorage.com` | Instagram |
| `S3_BUCKET` | bucket name | Instagram |
| `S3_ACCESS_KEY` | R2 API token | Instagram |
| `S3_SECRET_KEY` | R2 API secret | Instagram |
| `S3_PUBLIC_BASE` | `https://cdn.yoursite.com` (bucket ka public URL) | Instagram |

Secrets encrypted rehte hain, logs me kabhi print nahi hote, aur repo clone
karne wale ko bhi nahi milte.

---

## Step 4 — Videos kahan rakhein

**GitHub repo me videos na daalo** (100MB/file limit + repo bloat).
Videos Cloudflare R2 par rakho (10GB free), repo me sirf `queue.csv` (text).

R2 setup: Cloudflare dashboard → R2 → Create bucket → Settings me
"Public access" on karo (ya custom domain jodo) → API token banao.

---

## Step 5 — queue.csv bharo

```csv
id,source,title,description,hashtags,platforms,scheduled_date
fight01,s3:raw/fight01.mp4,Night Duel,Cinematic fight,#shorts #reels,youtube|facebook|instagram,2026-09-17
```

| Column | Matlab |
| --- | --- |
| `id` | unique naam — duplicate upload isi se rukta hai |
| `source` | `s3:path/file.mp4` (bucket ke andar) ya `https://...` public URL |
| `platforms` | `youtube\|facebook\|instagram` — khaali chhodo to teeno |
| `scheduled_date` | `YYYY-MM-DD` — us date se pehle upload nahi hoga; khaali = jab turn aaye |

Ek nayi line add karke `git push` — bas, agla scheduled run usko upload kar dega.

---

## Step 6 — Test karo

GitHub → **Actions** tab → "Daily Multipost Upload" → **Run workflow**

- pehle `dry_run = true` se chalao (kuch upload nahi hoga, sirf plan dikhega)
- sab theek lage to `dry_run = false`, `max_uploads = 1`

Log Actions tab me live dikhta hai, aur artifact me bhi save hota hai.

---

## Timing badalna

`.github/workflows/daily-upload.yml` me cron **UTC** me hai. PKT = UTC + 5.

| Aap chahte ho (PKT) | cron likho (UTC) |
| --- | --- |
| 09:30 | `30 4 * * *` |
| 15:00 | `0 10 * * *` |
| 20:30 | `30 15 * * *` |
| 00:00 | `0 19 * * *` |

GitHub ka cron busy time par 5–15 min late ho sakta hai — ye normal hai,
aur social uploads ke liye koi farq nahi padta.

---

## Cost

| Cheez | Free limit | Hamara use |
| --- | --- | --- |
| GitHub Actions (private repo) | 2,000 min/month | ~5–10 min/run × 3 = ~900 min |
| GitHub Actions (public repo) | unlimited | — |
| Cloudflare R2 | 10 GB + free egress | videos |
| YouTube API | 10,000 units/day | ~6 uploads/day max |
| Instagram publish | 25 posts/24h | — |

Total: **$0/month** normal use par.

---

## Safety features jo already andar hain

- `concurrency` group → do run ek saath nahi chalenge (duplicate upload nahi)
- `state/uploaded.json` repo me commit → upload ho chuki video dobara nahi jaayegi
- per-platform status → IG fail hua to YouTube dobara upload nahi hoga
- `max_attempts: 3` → barbaad retry loop nahi
- fail hone par workflow red + GitHub se email alert
- secrets logs me masked rehte hain

---

## Troubleshooting

| Error | Fix |
| --- | --- |
| `invalid_grant` | Refresh token dead — app Publish karo, phir Step 1 dohrao |
| `YT_REFRESH_TOKEN missing` | Secret naam galat likha hai (case-sensitive) |
| IG `video_url` fetch fail | `S3_PUBLIC_BASE` public nahi hai — R2 public access on karo |
| `quotaExceeded` | Din ka ~6 upload limit — `max_videos_per_run` kam karo |
| Workflow chala hi nahi | Repo 60 din inactive tha → GitHub cron disable kar deta hai; ek commit karo |
| `Permission denied` on push | Workflow permissions → Read and write enable karo |
