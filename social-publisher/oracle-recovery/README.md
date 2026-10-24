# Oracle Threads recovery — October 24, 2026

## Verified incident result

The original `morning:2026-10-24` job (`cb9b3125-4bed-580c-9220-b5b9430de973`)
was recovered under the same schedule ID. All eight original texts match the
stored approved parts. Authenticated Meta reads verified the root image, root
`topic_tag=미국주식`, eight permalinks, seven parent/reply relationships, and one
exact matching post per position in the account-owned root/reply feeds.
Verification run: https://github.com/comfunnylj/telegram-market-feed/actions/runs/40063738772

| Part | Public permalink |
| --- | --- |
| 1 | https://www.threads.com/@genie_carrot/post/De2vcNcAR5d |
| 2 | https://www.threads.com/@genie_carrot/post/De3TLzFlB6M |
| 3 | https://www.threads.com/@genie_carrot/post/De3TNRZFEzl |
| 4 | https://www.threads.com/@genie_carrot/post/De3TOvcFAYh |
| 5 | https://www.threads.com/@genie_carrot/post/De3TQQUFM6G |
| 6 | https://www.threads.com/@genie_carrot/post/De3TRpCFByo |
| 7 | https://www.threads.com/@genie_carrot/post/De3TSbDFFy4 |
| 8 | https://www.threads.com/@genie_carrot/post/De3TTzwlJVj |

Public webpage rendering was unavailable through the web retrieval tool. The
confirmation above is from authenticated Meta post/feed responses, not a claim
that the public UI was visually inspected. Future scheduled publications have
not yet been observed after this patch; no guarantee about future Meta service
availability is implied.

Final verification also confirmed the worker-ready log, no recent recovery or
permission errors, and identical schedules/payloads for all 33 other jobs against
the consistent pre-deployment backup. Runtime user, environment values and restart
policy match that backup.

## Established causes

1. Original protected history records HTTP 400, Meta code `24`, subcode
   `4279009`, “The requested resource does not exist”, naming saved media
   container `18124296265935413`. Later reads returned `FINISHED`; the original
   exact root was absent from a complete account feed before recovery. The
   upstream reason for this inconsistent Meta availability is not established.
   Image dimensions alone do not establish the cause.
2. Original v0.4 writes `publishing_unknown` before the publish request and
   preserves it on exceptions. The old pending-only worker did not resume it.
3. The initial recovery deployment created `/data/recovery-enabled-at` as
   `root:root`, mode `600`. The actual worker runs as `1001:1001`, so
   `flag.read_text()` in `recover_one()` raised `PermissionError`. The SQLite DB,
   worker lock, token, history directory and target history were readable by the
   worker. This exact file failure was reproduced with the runtime UID.
4. Live core/worker/recovery source initially matched the GitHub copies. The
   runtime UID was a deployment configuration difference; deployments now retain
   that user for the temporary recovery container as well as the final worker.

## Changes and safeguards

- `deploy.py` creates/repairs only the rollout marker ownership to match the data
  directory owner, retains mode `600`, and preserves the actual runtime user.
  It compares both worker and recovery module hashes, backs up SQLite/history
  and container configuration privately, stops the worker gracefully, and keeps
  its mounts, environment, limits and restart policy. It never restores an old DB.
- `recovery.py` persists IDs and structured errors before public side effects,
  verifies existing public IDs before continuing, and checks exact text/parent
  feed matches. `FINISHED` plus an empty feed alone does not authorize replay.
  A recorded HTTP 400 `24/4279009` rejection plus `FINISHED` and a complete
  negative feed permits a bounded retry of the SAME saved container. This is
  separate from ambiguous timeout handling, which never blindly reposts.
- The recovery reused the original saved root container rather than creating a
  second root. The remaining seven original parts were connected in order.
- The normalized 1080×1350 JPEG is available as a technical fallback, but an
  already saved/published root container is preserved. No new outbox key was added.
- `worker.py` uses recovery version `2026-10-24.2`, retains the existing bridge
  polling/schedules, and reports tracebacks for recovery errors. Recovery is
  bounded to three attempts with backoff; unrelated historical jobs are excluded.
- Fourteen offline tests cover stable IDs, reply chains, lost responses, account
  mismatch, topic mismatch, incomplete feeds, immutable content, rate limits,
  legacy media rejection, same-container retry, and disk failure before publish.

## Operations

`.github/workflows/recover-morning-20261024.yml` currently performs read-only
post-deployment verification. It does not issue publish requests. It runs on a
manual dispatch or a push of its own exact file and has no cron schedule.
It validates the original content/image, connects via pinned SSH host keys,
checks all eight Meta posts and their chain, and checks recent worker errors.
Non-secret evidence is retained as `morning-20261024-recovery-evidence`.

SSH secrets: `SOCIAL_PUBLISHER_SSH_KEY` (fallback `ORACLE_SSH_KEY` /
`ORACLE_SSH_PRIVATE_KEY`) and `SOCIAL_PUBLISHER_KNOWN_HOSTS` (fallback
`ORACLE_KNOWN_HOSTS`). Windows BOM/CRLF are normalized before private-key parsing.
No credentials belong in the repository, logs or chat. Host checking stays enabled.

The deployed staging directory is `/home/ubuntu/sp-recovery-20261024-v2`.
`deploy.py` is the explicit authenticated deployment entrypoint; it runs the
same-job `run_recovery.py` only with the existing worker stopped and its lock free.
`audit_live.py` and `verify_live.py` are read-only diagnostic entrypoints.
Baseline `core.py` and `scheduler.py` are offline test fixtures, not blindly
installed replacements for live files.
