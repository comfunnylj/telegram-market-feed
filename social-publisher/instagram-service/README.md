# Instagram extension for the existing Social Publisher

**State (2026-10-18): deployed on the existing Oracle VM as the independent
`instagram-publisher` container. Instagram Login `/me` identity verification,
GitHub outbox polling, and receipt generation succeeded. No live Instagram
image/Reel has been posted or end-to-end publish-tested yet.**

This is a separate no-inbound-port Python worker. It reads a dedicated GitHub
outbox, verifies the exact Instagram account and media hashes, publishes with
Meta's official API, and records an idempotent local receipt in SQLite. It is
deliberately independent of the live Threads `social-publisher` container and
its `tasks.json`, which currently accepts only `network=threads`.

## Currently implemented

- Single JPEG image with caption; ordered 2–10 JPEG-image carousel; pre-edited MP4 Reel.
- `not_before` and `expires_at` scheduling, with 180-second minimum polling.
- SHA-256 and byte-size checks on the actual publicly downloadable media.
- Exactly-once safety policy: an accepted `dedup_key` is immutable. `publishing_unknown`
  is **never** automatically retried, because Meta may have completed a
  publish whose HTTP response was lost.
- Dedicated SQLite journal and private `/data/status.json`; no access tokens,
  captions, image URLs, or source text in the status file.
- Identity binding to *both* numeric Meta Instagram user ID and exact username.
- Instagram off by default (`IG_ENABLED=false`). No token or key in GitHub.

Deliberately **not** implemented: Stories, publishing a text-only post, an
Instagram music-library soundtrack, comment/DM automation, token refresh,
crossposting policy, a public receipt endpoint, or a plug-in to the current
closed-source Oracle worker. These are separate work items.

## Prerequisites

1. Instagram **Business or Creator** professional account (confirmed by the owner).
2. Meta developer app configured for **Instagram API with Instagram Login**.
   Facebook Page linkage is not required for this login method.
3. App authorization with `instagram_business_basic` and
   `instagram_business_content_publish`. Obtain the Instagram User ID **returned
   by `GET /me` for this exact Instagram Login token**, exact account username,
   and a valid long-lived Instagram access token from the authorized flow. The
   numeric ID displayed elsewhere in Meta setup may differ. Do not share token
   values in chats or commits.
4. Oracle server Docker/Compose access; keep the running Threads worker untouched.
5. Media hosted over public HTTPS that Meta can fetch. This service defaults
   to allowing only `raw.githubusercontent.com`. A public GitHub blob URL with
   an immutable 40-character commit SHA is suitable for reasonably-sized media.

Official Meta references:

- https://www.postman.com/meta/instagram/folder/1z5vxzu/instagram-api-with-instagram-login
- https://www.postman.com/meta/instagram/folder/y6xustx/reels-publishing
- https://developers.facebook.com/docs/instagram-platform/instagram-api-with-instagram-login/content-publishing

## Queue (public GitHub repository)

The new outbox is `social-publisher/instagram/outbox.json`. The owner confirmed
that the destination account is `genie_carrot`; it is intentionally **empty**
until a real post is approved. Before starting the worker, confirm this handle
still matches the Meta-authenticated Instagram user. Never add a token here.

Job structure, **illustrative only, not submitted**:

```json
{
  "dedup_key": "instagram:my-approved-post-001",
  "approved": true,
  "not_before": "2026-10-20T11:00:00+09:00",
  "expires_at": "2026-10-20T11:10:00+09:00",
  "caption": "Example caption #travel",
  "media_type": "image",
  "media": [
    {
      "url": "https://raw.githubusercontent.com/OWNER/REPO/EXACT_COMMIT/media.jpg",
      "sha256": "<sha256 of exactly those JPEG bytes>",
      "size": 123456
    }
  ]
}
```

The source object wraps these `jobs` in `{"protocol":1,"network":"instagram",
"source":"instagram","account":"EXACT_USERNAME","jobs":[...]}`. Do not
publish an example with placeholder fields. Store only **owner-reviewed**, final
copy and media in the public queue. The queue must not contain private data.

- `media_type=image`: exactly one JPEG; Instagram does not support text-only publishing.
- `media_type=carousel`: 2–10 ordered JPEGs. Child containers are created first
  and checked for readiness, then a single parent container is published.
- `media_type=reels`: exactly one finished video, with audio already licensed
  and embedded in the file. Meta handles video encoding asynchronously.
- `approved=true` denotes that the *exact* content received owner approval.
  This worker cannot independently authenticate a chat approval.
- Existing keys cannot be changed; a new job requires a genuinely new approval
  and new stable deduplication key.

## Test offline

From this directory:

```sh
python3 -m unittest -v test_instagram_publisher.py
```

Tests mock all network calls and must pass before deployment. They do not prove
live Instagram API permissions, encoding compatibility, or publication success.

## Oracle deployment (verified 2026-10-18)

Do this in a checkout of this repository on the Oracle host, from the directory
`social-publisher/instagram-service`. Keep the current Threads container live:

```sh
cp .env.instagram.example .env.instagram
chmod 600 .env.instagram
# Edit .env.instagram locally on Oracle. Never commit or print the token.
# Fill the ID returned by `GET /me`, exact username, access token and graph version.
# Set IG_ENABLED=true only after the matching GitHub outbox account is configured.
# The current Oracle host has legacy docker-compose 1.25, not the v2 plugin.
# Use Docker CLI without modifying the existing Threads container:
sudo docker build -t instagram-publisher:trial .
sudo docker volume create instagram_publisher_data
sudo docker run -d --name instagram-publisher --restart unless-stopped \
  --env-file .env.instagram \
  --mount type=volume,source=instagram_publisher_data,target=/data \
  --memory 128m --pids-limit 64 --cap-drop ALL \
  --security-opt no-new-privileges instagram-publisher:trial
sudo docker exec instagram-publisher python -c 'from instagram_publisher import Settings,GraphClient; GraphClient(Settings.from_env()).verify_account(); print("INSTAGRAM ACCOUNT VERIFIED")'
sudo docker exec instagram-publisher python -c 'import json; print(json.load(open("/data/status.json")))'
```

An installation with a recent Compose v2 plugin may instead use
`docker compose --env-file .env.instagram -f compose.instagram.yml up -d --build`.
**Docker does not reload `.env.instagram` into a running container:** when
credentials, account ID, or queue URL change, stop/remove only the
`instagram-publisher` container and recreate it with the same named data volume.
Never remove the receipt volume as part of a routine update.

The new service is named `instagram-publisher`, uses its **own** Docker volume,
and has no published port. There is no `docker compose down` instruction and no
change to the running `social-publisher` worker. If deployment is rolled back,
stop only `instagram-publisher` and preserve its SQLite volume for audit.

Because the public GitHub repository currently has only the Threads outbox
protocol—not the Oracle `core.py`, `bridge.py`, `worker.py`, or other live engine
files—this sidecar cannot be honestly presented as a drop-in replacement for
those modules. The operating system still needs the source checkout and Meta
credentials provisioned through the owner's authenticated connection.

## Publication receipts and failure modes

`/data/status.json` reports `pending`, `awaiting_children`, `awaiting_media`,
`publishing_unknown`, `published_unverified`, `published`, `needs_review`, or
`expired`, with media ID and Instagram permalink if confirmed. A verified URL
and `published` are required before saying a post is live.

On a timeout after `/media_publish`, a job remains `publishing_unknown`. Inspect
the target Instagram profile and Meta media records manually before changing
state. **Never create a different dedup key to retry it.**

Long-lived tokens expire and this minimal sidecar does not refresh them: use
the appropriate Meta token renewal process before expiry. Keep `.env.instagram`
secret (file mode 600). Do not modify existing Threads token settings.
