# Social Publisher automation delivery protocol v1

Use this delivery protocol only after control.json enabled=true and the Oracle read-only probe is verified. Existing writing/fact-checking rules remain in force. Do not invoke Metricool after cutover. No SSH key or Threads token belongs in this repository.

Repository: comfunnylj/telegram-market-feed, branch main.
Control: social-publisher/automation/control.json.
Task registry: social-publisher/automation/tasks.json (schema_version=1).
Read the current registry and resolve source ID, enabled, account, network, topic and outbox from its task entry. Current initial registrations are morning, evening and energy; there is no server-side hardcoded list of those task IDs.
Receipt URL: https://161-33-141-193.sslip.io/social-publisher-status/status.json
Receipt JSON is public, contains delivery states and post URLs, and must never contain article bodies or tokens. Read it with an available HTTP client (Python urllib.request was verified for this host); do not assume the web search fetcher can open this host.

## Initial sources, keys, topics
- morning: dedup_key morning:YYYY-MM-DD in Asia/Seoul, topic 미국주식.
- evening: dedup_key evening:YYYY-MM-DD in Asia/Seoul, topic 국내주식.
- energy: dedup_key energy:<SHA256 of confirmed Gmail EmailMessageId>, topic 원자재.
- Job ID is Python str(uuid.uuid5(uuid.NAMESPACE_URL, 'social-publisher/'+dedup_key)).
- First root post only receives the real API topic_tag. Do not substitute a hashtag for an official topic.
- Email/internal database content must not be placed in public JSON. Include only the final approved-for-publication briefing.

## Image preparation
Follow the task's image_required setting and its content instructions. The existing morning/evening/energy tasks require one visually reviewed 4:5 JPEG/PNG, at most 8 MiB; never fall back to text-only on their image failure. A newly registered task may explicitly permit image=null by image_required=false.
Upload the exact verified bytes to social-publisher/media/<source>-<dedup-key-hash>.png or .jpg. Avoid guessing any local path or file ID.
Use available GitHub tools: read main's current commit/tree through GET https://api.github.com/repos/comfunnylj/telegram-market-feed/branches/main; create_blob with base64 of actual local bytes, create_tree based on that tree, create_commit with the actual parent, and update_ref to main with expected_sha=that parent and force=false. On a ref conflict re-read main and rebuild the tree on the new base, preserving other files. Never force push.
Use the returned asset commit SHA to form an immutable image URL:
https://raw.githubusercontent.com/comfunnylj/telegram-market-feed/<actual 40-character commit SHA>/social-publisher/media/<actual filename>
Read the committed file with fetch_file encoding=base64 at that commit, decode it, and confirm byte size and SHA-256 against the reviewed local image. Do not use expiring URLs, invented URLs, attachments IDs or local filesystem paths in the outbox.

## Outbox JSON
Each source file is a UTF-8 object: {"protocol":1,"source":"<registered task id>","jobs":[...]}.
Each job has exactly the following delivery fields:
- dedup_key: stable source key above
- created_at: actual preparation-complete timestamp, ISO 8601 with offset
- not_before: future publish timestamp, ISO 8601 with offset
- expires_at: not_before plus the registered late_grace_seconds (at most 300), ISO 8601 with offset
- topic: exact topic from the current registered task entry
- text: complete final briefing
- parts: array of nonempty final posts; concatenation must equal text exactly
- image: {"url":verified immutable GitHub URL,"sha256":actual lowercase 64-digit SHA256,"size":actual byte count}, or null only when the registered task explicitly permits it

Every parts entry must be at most the task's max_utf16 UTF-16 code units (global upper bound 450). Check final JS text.length and Array.from(text).length, including whitespace, URLs and additions. Keep paragraph breaks; do not cut URLs, company names, values and units. Respect the registered max_posts (global upper bound 500); do not truncate important content to bypass this validation. The reviewed first part must contain the date title and numbered news summary. Place the three verified indicators and detailed commentary in later parts if needed.
Retain all existing source jobs (up to 100 per source; retain at least the last 14 days where available). Read the current outbox and its blob SHA immediately before update_file. Add one job only if its dedup_key is absent. A matching key is immutable: inspect its receipt; do not replace its content/time or create a new key to retry it. If update_file conflicts, fetch the current file and repeat the merge once; never overwrite a concurrent job.
Perform the write only after image and text verification. Re-read the committed outbox to confirm the exact key, parts, topic, timestamp, image URL/hash/size. A successful GitHub write means submitted, not scheduled or published.

## Timing and delivery results
Oracle checks for registry/outbox changes after each polling interval configured by poll_seconds (default 180; minimum 180). New task registrations and configuration changes are loaded without a server rebuild or restart. Schedule morning/evening for 08:30/18:30 Asia/Seoul if still feasible; if preparation runs late, use actual current time plus 5 minutes. Energy uses actual current time plus 5 minutes after confirmed email send and all checks.
Respect control.activated_at. Do not backfill pre-cutover mail or failed Metricool posts automatically.
Poll the receipt URL using ordinary bounded HTTP reads with a fresh query parameter and verify bridge_id=sp-oracle-genie-carrot-v1, account=genie_carrot, recent updated_at/last_success_at, last_error=null, the relevant registered task enabled=true and no relevant task_errors, and global enabled=true.
Find the exact deterministic job ID/key. pending means scheduled on the Oracle server; running means in progress. published plus every individual part status=published and actual permalink means the full thread was published. Confirm the root returned topic_tag equals the requested official topic before reporting topic verified.
Do not report published for a GitHub commit, a received event, a pending entry or an HTTP 200 alone. If execution time runs out, report the verified current state and the stable ID.
unknown, publishing_unknown, published_unverified, partial_failed, needs_review, expired or missed must never be retried under a fresh ID. Already-published parts remain published. Network failures do not mean the job was never received.
The source outbox is not a cancellation interface. Cancel only pending jobs through the existing authenticated server client. Never remove an outbox entry as a substitute for cancellation.

## Registering another task without server code changes
This engine currently supports the existing Threads account genie_carrot only. Other account/network values are rejected rather than silently routed to this account. Videos, image carousels and extra SNS providers require a separate implementation.

Registry root:
{"schema_version":1,"poll_seconds":180,"tasks":[task entries]}
Allowed task fields:
- id: stable lowercase [a-z][a-z0-9_-]{0,39}; unique and used as the source and dedup_key prefix
- name: descriptive display name, 1–80 characters
- enabled: boolean controlling NEW intake
- network: "threads"
- account: "genie_carrot"
- topic: exact requested official topic, 1–100 characters
- outbox: unique basename ending .json, e.g. travel-updates.json; no directory traversal or control/probe/tasks filenames
- image_required: boolean, default true
- max_posts: integer 1–500, default 500
- max_utf16: integer 1–450, default 450
- late_grace_seconds: integer 1–300, default 300

Example NEW registration, initially disabled:
{"id":"travel","name":"여행 콘텐츠","enabled":false,"network":"threads","account":"genie_carrot","topic":"여행","outbox":"travel-updates.json","image_required":true,"max_posts":500,"max_utf16":450,"late_grace_seconds":300}
This example is not an installed or scheduled travel automation.

Sequence:
1. Preserve all existing registry entries and queued jobs. Create the new outbox with {"protocol":1,"source":"travel","jobs":[]} first.
2. Validate the full proposed tasks.json with the packaged registry.py validator and add the new task initially disabled. Use fetch_file/update_file with the current blob SHA; re-read and merge after any conflict.
3. Confirm Oracle's receipt health shows the registered task and the correct settings. Validate required app connections for the new content automation before creating it.
4. Prepare the new content-generation prompt and schedule with that stable task ID, dedicated outbox, topic and dedup key rule. Registering a receiver task does not create a ChatGPT automation.
5. Enable the task's intake and its content automation only after the connection checks and within the user's authorized scope.

Important semantics:
- global control.enabled and task.enabled govern NEW imports only. Disabling/removing a task does not cancel jobs already accepted in the Oracle database. Cancel pending jobs with the authenticated PC client.
- Registry edits do not resume or pause existing ChatGPT schedules. Those are separate automation settings.
- An accepted job's content, topic, image and expiry are an immutable snapshot; later registry changes affect new jobs only. The old accepted key is never re-created.
- One unavailable source outbox is reported in task_errors without blocking other source imports. Invalid registry schema blocks new intake until fixed; existing accepted jobs continue on their saved snapshot.
- At most 50 tasks and 100 retained outbox entries per task are accepted by this version. These are validation limits, not a guaranteed workload throughput.
