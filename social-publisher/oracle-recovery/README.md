# October 24 morning recovery and durable Oracle publishing

Scope: existing `morning:2026-10-24`, 8 approved parts, one original image,
account `genie_carrot`, root official topic `미국주식`. No new outbox key,
schedule, task, control flag, or change to another historical job is requested.

## Established observations

- Live Oracle receipt reports the original job `cb9b3125-4bed-580c-9220-b5b9430de973`
  as `publishing_unknown` on its root; seven later parts are prepared.
- The original committed PNG hashes correctly and decodes to RGB 1122 × 1402.
  These dimensions alone do not prove a Meta rejection. The candidate converter
  keeps the same image and content, without cropping, at RGB JPEG 1080 × 1350.
- Reviewed server source is the user's `SocialPublisher_MultiImage_v0.4.zip`.
  `core.Publisher.send` marks a part `publishing_unknown` before `threads_publish`,
  then preserves that state on any exception. `worker.py` only claims pending
  rows and contains no same-job reconciliation/resume path. This explains why
  a transient or unverified response can leave a job stuck indefinitely.
- The exact upstream error for October 24 is **not established** until the
  protected SQLite result/history and authenticated Meta container/feed are read.
  A public receipt, or success after resizing a different post, cannot prove it.

## Contents

- `recovery.py`: stable schedule-ID write-ahead state; bounded read retries;
  persist container IDs and redacted structured Meta errors; same-container retry
  only after explicit rate-limit rejection; reconcile lost responses through
  container state and account-owned exact-text/parent timeline; resume only
  unpublished parts, preserving the existing root and reply chain. Existing
  public IDs, root official topic and image type must be verified before success.
- `worker.py`: uses the new publisher for future automatic jobs and performs at
  most three audited reconciliation/resume attempts, with backoff. Historical
  jobs other than this authorized incident are excluded by rollout timestamp.
- `run_recovery.py`: audits and repairs only the existing incident row, under
  worker lock. A complete empty timeline alone never authorizes re-publication.
  A failed/expired saved container plus complete negative account evidence is
  required before replacing a failed container under the same job. Normalized
  media is used only before any original part is published; old outbox is untouched.
- `deploy.py`: requires authenticated Oracle access, verifies actual core/worker
  hashes, checks no active/soon-due jobs, gracefully stops only this worker,
  makes private SQLite/history/container backups, runs target recovery, deploys
  the tested worker module while retaining existing mounts, environment, limits
  and restart policy. Never restores an old DB or force-kills a publication.
- `manifest.json`: hashes for compatibility checks. Baseline `core.py` and
  `scheduler.py` are included for offline tests only, not blindly deployed.

## Execution and authentication

The manual workflow `.github/workflows/recover-morning-20261024.yml` also runs
once on a push of that exact file. It has no cron schedule. Offline tests and
local image validation run before the credential gate.

The workflow defines optional SSH credential bindings:
`SOCIAL_PUBLISHER_SSH_KEY` (or existing `ORACLE_SSH_KEY` /
`ORACLE_SSH_PRIVATE_KEY`) and `SOCIAL_PUBLISHER_KNOWN_HOSTS` (or existing
`ORACLE_KNOWN_HOSTS`). These are **configuration names chosen for this workflow**,
not a claim that those secrets already exist. Credentials must never be committed
or printed. The pinned known_hosts entry must come from a trusted existing SSH
installation. Host checking is never disabled.

If the credential gate fails, there has been no public post, outbox mutation,
server patch, token change or schedule change. The failure report is a recoverable
configuration requirement, not a completed Oracle recovery. Add the two required
secret values through GitHub's secure settings and rerun the same workflow.

When authenticated, a non-secret report is retained in the Actions artifact
`morning-20261024-recovery-evidence`. It distinguishes worker deployment from
actual publication. Only eight verified permalinks, the exact root topic, and
Meta-confirmed root image justify reporting this incident resolved.

## API references

- https://www.postman.com/meta/threads/request/m47wqlq/check-container-s-publishing-status
- https://www.postman.com/meta/threads/documentation/dht3nzz/threads-api

Container states FINISHED / PUBLISHED / ERROR / EXPIRED have different meanings.
FINISHED plus no matching timeline entry does not prove a timed-out publish was
never accepted. Ambiguous outcomes remain protected from blind new-ID retries.
