# Naver Blog publishing outbox (MVP)

ChatGPT can place a fully reviewed and approved blog post in `outbox.json` through the connected GitHub integration. A separate Playwright worker reads this queue and attempts the operation in a persistent, locally logged-in Naver session. The worker is provided as `naver-blog-publisher-mvp.zip` in the ChatGPT conversation on 2026-10-21. This folder does NOT install or execute that worker automatically.

- Account: `comfunny_lj`
- Jobs are initially empty. No posts were created or published.
- Protocol 1: fields `dedup_key`, `approved`, `mode` (draft|publish), `title`, `category`, `body_markdown`, `images` (marker/url/sha256/kind).
- Real estate publication jobs require a verifiably authentic official rendering. An unverified or AI-generated picture must not be presented as a real rendering.
- Never put a password, cookie, session token, or private manuscript in this public repository.
- A job needs separate approval. A queue entry on its own is not evidence of publication.
- The worker logs results locally; a remote status feedback integration has not been configured. Do not claim publication without verifying a Naver public post URL.
- The exact SmartEditor selectors and login on the user's own device are not yet live-tested. Its unsupported UI automation may fail if Naver changes the page.

Official Naver statement: https://developers.naver.com/notice/article/7527 (blog writing API retired 2020-05-06)
