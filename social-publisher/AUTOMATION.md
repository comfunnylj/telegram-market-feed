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
Each job has the following delivery fields (the optional images array is gated by the 0.4 capability checks below):
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
This engine currently supports the existing Threads account genie_carrot only. Other account/network values are rejected rather than silently routed to this account. Videos and extra SNS providers require a separate implementation. Image carousels require the compatible 0.4 server and the capability checks below; keep single-image envelopes on older servers.

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


# Image carousel extension for Social Publisher 0.4

Read current control, registry, task policy and receipt before sending. Existing source, topic, image-required policy, immutable keys and approval rules continue to apply. Do not change existing accepted envelopes.

## Required capability gate

Before writing a new carousel envelope, read a fresh public receipt from the configured status URL and verify `publisher_version=0.4` (or a later compatible version) and `capabilities.carousel=true`, `capabilities.max_images>=requested image count`, in addition to existing identity, health and enabled checks. Version 0.3 ignores unknown `images` fields, so do not send them to an unverified older server. PC 0.6 also checks this capability over SSH before multiple-image submission.

## Ordered image array

Legacy `image: {...}` and `image: null` remain accepted without change. New envelopes can instead supply `images: [...]`, an ordered array of 0 to 20 objects. `image` must be absent or null when `images` is supplied. Do not provide two nonempty representations.

Each automation image has the same fields as the legacy image: `url`, `sha256`, `size`. Use visually reviewed JPEG/PNG bytes, each at most 8 MiB. Upload and read back every image using the existing immutable GitHub commit URL procedure. Do not invent paths, hashes or commit SHAs. A partial upload or validation failure must not cause an automatic text-only or reduced-image fallback.

When image_required is true, require at least one image. An empty array is valid only for a text-only task. One image uses the existing single-image API; 2–20 images create ordered child containers then one CAROUSEL parent on the first post. Topic and first-part text belong to the parent. Only the parent is published; later parts remain ordinary linked text replies.

Example structural fragment only, not a request to publish:

```json
{
  "images": [
    {"url":"ACTUAL_IMMUTABLE_URL_1","sha256":"ACTUAL_SHA256_1","size":123},
    {"url":"ACTUAL_IMMUTABLE_URL_2","sha256":"ACTUAL_SHA256_2","size":456}
  ]
}
```

All dates, full text, exact concatenated parts, source-specific dedup_key, expiry and account checks remain unchanged. The array order is part of the immutable approved request. Do not reorder or replace images under an accepted key. Recheck all hashes and byte counts before creating any container. Do not publish child containers individually, retry under fresh IDs after uncertain publishing, or treat receipt image_count as independent proof that Meta rendered every image. Verify the real post when reporting completion.

The public receipt reports capabilities and requested image_count, while detailed child-container IDs and statuses are saved in the private history. It excludes image URLs, bodies and tokens.

Existing briefing-specific requirements to use one 4:5 image remain unchanged until the user requests another content policy.

Primary API reference used: https://www.postman.com/meta/threads/documentation/dht3nzz/threads-api

## Myeonmok9 recovery postmortem and preflight policy (2026-10-23)

Verified incident:
- Original job `realestate:myeonmok9-20261023` was accepted by Oracle Bridge 0.4. It entered `publishing_unknown` on part 1; parts 2–6 stayed `prepared`. Public status did not include the underlying Meta error or the parent creation ID, so exact root cause **is not established**.
- Explicitly user-authorized one-time recovery job `realestate:myeonmok9-20261023-retry1` used the **same two sourced photographs**, decoded them from their verified immutable SHA256 URLs, re-exported each as sRGB-compatible RGB JPEG at 1080 pixels wide with aspect ratio retained (no crop), and verified their immutable uploaded URL, SHA256 and byte size.
- Oracle returned `verified_published` on 2026-10-23 22:49 KST: six published parts, all with permalinks; requested image count 2; root topic tag `부동산`.
- This A/B outcome does **not** prove the first failure was a media-size issue, because time/network/API conditions also changed.

Permanent requirements for *future* Threads carousel attempts through this integration:
1. Before uploading, read each real picture's pixels and verify that it belongs to the requested site. Convert to JPEG RGB/sRGB at an appropriate 1080-pixel width when its source dimensions are small; preserve the aspect ratio, never crop/alter meaning or substitute a different site. Check both files are between 20 KB and 8 MiB and match supported dimensions.
2. After GitHub asset upload, fetch both commit-pinned raw.githubusercontent.com URLs and verify SHA256 and exact sizes. Do not put guessed or unverified URLs into `images`.
3. Confirm live Oracle Bridge account, version 0.4+, task `realestate`, and `capabilities.carousel` / `max_images` **before** queue submission.
4. Use a stable dedup key; publish request is immutable after accepted. Verify that the exact image count, official topic, all parts, and a single job entry reached the outbox.
5. If `publishing_unknown` occurs, **do not** claim failure or auto-resubmit. First check the private server history `/home/ubuntu/social-publisher/data/history/<request-id>.json` and Meta authenticated account timeline for an already-published root. This read-only reconciliation requires authorized server access and cannot be replaced by public receipt data alone.
6. When the user expressly authorizes another attempt after reconciliation, use a **new** stable recovery key. Do not overwrite or erase the original uncertain job; preserve a separate status file and audit IDs.
7. Report success only on `published`, each part `published` with an actual permalink, the correct root official topic tag, and expected image_count. The receipt's requested image_count is not independent proof of client-side rendered images; inspect the live post when possible.
8. Avoid claiming a definitive failure cause unless server-side Meta error and the publishing-stage transaction are available. Scaling to 1080px is a defensive preflight measure, not a verified universal fix for `publishing_unknown`.

Auditable recovery sources:
- `social-publisher/diagnostics/myeonmok9-20261023-result.json` — original root uncertain.
- `social-publisher/diagnostics/myeonmok9-recovery-status.json` — recovery result.
- `social-publisher/diagnostics/recover-myeonmok9-20261023.py` — concrete image/receipt/retry gate.
- `social-publisher/diagnostics/diagnose-myeonmok9-unknown.py` — read-only server diagnosis (run only inside authorized Oracle container).

Server-side future fix, **not yet deployed**: persist Meta child/parent container IDs and upstream status/errors before publishing; implement reconciliation by container status and account timeline when publish response is lost, rather than immediately terminal `publishing_unknown`. Update Oracle software only with proper server access, backups, and tests.


## Shared REAL ESTATE Threads pre-submit gate (2026-10-23)

MANDATORY before adding any future `realestate` job to the live outbox. This code is NOT the Oracle server patch: `social-publisher/automation/preflight.py`. Offline regression tests: `test_preflight.py`; GitHub Actions: `threads-preflight-regression.yml`.

1. Visually review each source image and confirm that it depicts the correct site, is readable, and has suitable usage rights. Do not invent images or silently replace with another location.
2. Normalize each image to a 1080-pixel-width JPEG, sRGB encoding, preserved aspect ratio, no cropping. Example: `python3 social-publisher/automation/preflight.py normalize original.jpg social-publisher/media/realestate-NEWKEY-01.jpg`. Inspect the actual output files. This reduces variation in encoding but does not establish the root cause of the 2026-10-23 incident.
3. Commit each image, use the resulting immutable 40-hex Git commit URLs, and read back *the actual remote bytes*. URLs to news site images, branch-main aliases, and image placeholders must never be passed to the Oracle outbox.
4. Construct a **candidate job file not yet in the live outbox** with all the parts, images, topic and dates. Before submitting, run `python3 social-publisher/automation/preflight.py verify-job candidate.json --outbox social-publisher/automation/realestate.json --remote`. A nonzero exit status means **do not enqueue**. This checks remote image SHA256, decoded JPEG/PNG, width, size, original order, duplicate content, immutable job ID, timestamps and 450 UTF-16 limit.
5. Fetch the current Oracle public receipt to a fresh local JSON file. Run `python3 social-publisher/automation/preflight.py receipt-check receipt.json --source realestate --images 2`. Account/receiver/topic/capabilities and last heartbeat must pass. A stale GitHub copy of receipt data is not live verification.
6. Only then append the complete immutable job to the existing outbox, verify the committed readback, and confirm the Oracle receipt accepted the exact key. Do not queue a fallback text-only or single-image version if a photo failed.
7. On `publishing_unknown` or `published_unverified`, STOP automated new-key retries and reconcile the original private server history and Meta status first. Explicit permission to retry by itself does not prove the first post was never published; avoid accidental double-posting.
8. Declare success only if Oracle reports each part `published`, each permalink is present, image count matches, and the root official topic is correct. The count in the receipt is not proof of end-user image rendering. If possible inspect the live Threads post directly.
9. The pre-submit code must be invoked by EACH FUTURE publishing script/workflow **before** its outbox write; the GitHub regression workflow runs on source changes but cannot stop an outbox already consumed by Oracle.

Server-side work STILL required to eliminate the blind spot: persist Meta carousel child IDs, root creation ID, publish attempt timestamp, and redacted HTTP code/error to protected Oracle history; for ambiguous responses, GET the saved container status using official Threads API fields `id,status,error_message`, compare the authenticated feed, and resume only definitively unposted parts using saved IDs. This requires SSH access, backup and tested Oracle deployment. It has NOT been done merely by adding this preflight module.


## Automatic failure diagnosis and safe recovery (2026-10-24)

For every publishing attempt, perform a bounded read-only reconciliation whenever a job is failed, partial_failed, publishing_unknown, published_unverified, expired, missed, or lacks a confirmed permalink. Automatically report: source/key/job ID, stage and per-part state, observed upstream error (if available), evidence-backed root cause or "unconfirmed", corrective action, retry eligibility, and final receipt/permalinks/topic status. Never present hypotheses as established causes.

1. Read fresh control, task registry, immutable outbox job, Oracle receipt, and any authorized server history / Meta account timeline available. Compare the intended part count, image checksums, actual Meta post IDs, public permalinks, root topic_tag, and the last successful stage. If privileged logs are unavailable, explicitly say that the root cause cannot be determined from the public receipt.
2. Classify failures: (a) confirmed pre-publication validation/transient transport errors with reliable proof that no Meta publish was initiated; (b) confirmed published or partially published; (c) ambiguous publish response / unknown state; (d) permanent auth, policy, topic, media, or configuration errors. Propose and document a concrete prevention improvement for each identified failure.
3. Automatic retry is authorized ONLY for class (a), after verifying the original request was not accepted for publication and no post/container was created, and only through an idempotent server-side retry of the SAME immutable job ID/key and approved content, if the running Oracle protocol explicitly supports that operation. Apply bounded exponential backoff (maximum three attempts), rate-limit awareness and an audit trail. Never change an accepted job's dedup_key, text, images, topic, or schedule to force retry. If the current Oracle server has no verified safe idempotent retry mechanism, report "automatic retry blocked: server support required" instead of inventing one.
4. For (b), resume only unpublished parts when the server can prove and preserve the existing root/parent linkage and prevent duplicates. Never repost already published parts. For (c), perform reconciliation first; no automatic resubmission until the actual Meta state is conclusively resolved. For (d), do not retry unchanged invalid requests; recommend a validated fix for FUTURE jobs. Changing an accepted envelope requires an explicitly supported recovery workflow and user authorization.
5. Recheck the receipt after any eligible retry. Report success only when every part has an actual public permalink and the root's official topic_tag is verified. Report partial or unresolved status otherwise. Preserve existing tasks, outboxes, schedules, and control flags.

This section adds automatic diagnosis and conditional safe recovery; it does NOT assert that the Oracle server currently implements an idempotent retry endpoint, and it does not override the immutable-key or unknown-state safety rules.
