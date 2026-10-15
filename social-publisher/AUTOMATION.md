# Social Publisher automation delivery protocol v1

Use this delivery protocol only after control.json enabled=true and the Oracle read-only probe is verified. Existing writing/fact-checking rules remain in force. Do not invoke Metricool after cutover. No SSH key or Threads token belongs in this repository.

Repository: comfunnylj/telegram-market-feed, branch main.
Control: social-publisher/automation/control.json.
Source outboxes: social-publisher/automation/morning.json, evening.json, energy.json.
Receipt URL: https://161-33-141-193.sslip.io/social-publisher-status/status.json
Receipt JSON is public, contains delivery states and post URLs, and must never contain article bodies or tokens. Read it with an available HTTP client (Python urllib.request was verified for this host); do not assume the web search fetcher can open this host.

## Sources, keys, topics
- morning: dedup_key morning:YYYY-MM-DD in Asia/Seoul, topic 미국주식.
- evening: dedup_key evening:YYYY-MM-DD in Asia/Seoul, topic 국내주식.
- energy: dedup_key energy:<SHA256 of confirmed Gmail EmailMessageId>, topic 원자재.
- Job ID is Python str(uuid.uuid5(uuid.NAMESPACE_URL, 'social-publisher/'+dedup_key)).
- First root post only receives the real API topic_tag. Do not substitute a hashtag for an official topic.
- Email/internal database content must not be placed in public JSON. Include only the final approved-for-publication briefing.

## Image preparation
Generate and visually verify one 4:5 JPEG/PNG, at most 8 MiB. Do not publish text-only if image creation fails.
Upload the exact verified bytes to social-publisher/media/<source>-<dedup-key-hash>.png or .jpg. Avoid guessing any local path or file ID.
Use available GitHub tools: read main's current commit/tree through GET https://api.github.com/repos/comfunnylj/telegram-market-feed/branches/main; create_blob with base64 of actual local bytes, create_tree based on that tree, create_commit with the actual parent, and update_ref to main with expected_sha=that parent and force=false. On a ref conflict re-read main and rebuild the tree on the new base, preserving other files. Never force push.
Use the returned asset commit SHA to form an immutable image URL:
https://raw.githubusercontent.com/comfunnylj/telegram-market-feed/<actual 40-character commit SHA>/social-publisher/media/<actual filename>
Read the committed file with fetch_file encoding=base64 at that commit, decode it, and confirm byte size and SHA-256 against the reviewed local image. Do not use expiring URLs, invented URLs, attachments IDs or local filesystem paths in the outbox.

## Outbox JSON
Each source file is a UTF-8 object: {"protocol":1,"source":"morning|evening|energy","jobs":[...]}.
Each job has exactly the following delivery fields:
- dedup_key: stable source key above
- created_at: actual preparation-complete timestamp, ISO 8601 with offset
- not_before: future publish timestamp, ISO 8601 with offset
- expires_at: not_before plus 300 seconds, ISO 8601 with offset
- topic: exact allowed topic for that source
- text: complete final briefing
- parts: array of nonempty final posts; concatenation must equal text exactly
- image: {"url":verified immutable GitHub URL,"sha256":actual lowercase 64-digit SHA256,"size":actual byte count}

Every parts entry must be at most 450 UTF-16 code units. Check final JS text.length and Array.from(text).length, including whitespace, URLs and additions. Keep paragraph breaks; do not cut URLs, company names, values and units. No artificial part-count cap. The reviewed first part must contain the date title and numbered news summary. Place the three verified indicators and detailed commentary in later parts if needed.
Retain all existing source jobs (up to 100 per source; retain at least the last 14 days where available). Read the current outbox and its blob SHA immediately before update_file. Add one job only if its dedup_key is absent. A matching key is immutable: inspect its receipt; do not replace its content/time or create a new key to retry it. If update_file conflicts, fetch the current file and repeat the merge once; never overwrite a concurrent job.
Perform the write only after image and text verification. Re-read the committed outbox to confirm the exact key, parts, topic, timestamp, image URL/hash/size. A successful GitHub write means submitted, not scheduled or published.

## Timing and delivery results
Oracle checks the outboxes roughly every 180 seconds. Schedule morning/evening for 08:30/18:30 Asia/Seoul if still feasible; if preparation runs late, use actual current time plus 5 minutes. Energy uses actual current time plus 5 minutes after confirmed email send and all checks.
Respect control.activated_at. Do not backfill pre-cutover mail or failed Metricool posts automatically.
Poll the receipt URL using ordinary bounded HTTP reads with a fresh query parameter and verify bridge_id=sp-oracle-genie-carrot-v1, account=genie_carrot, recent updated_at/last_success_at and enabled=true.
Find the exact deterministic job ID/key. pending means scheduled on the Oracle server; running means in progress. published plus every individual part status=published and actual permalink means the full thread was published. Confirm the root returned topic_tag equals the requested official topic before reporting topic verified.
Do not report published for a GitHub commit, a received event, a pending entry or an HTTP 200 alone. If execution time runs out, report the verified current state and the stable ID.
unknown, publishing_unknown, published_unverified, partial_failed, needs_review, expired or missed must never be retried under a fresh ID. Already-published parts remain published. Network failures do not mean the job was never received.
The source outbox is not a cancellation interface. Cancel only pending jobs through the existing authenticated server client. Never remove an outbox entry as a substitute for cancellation.
