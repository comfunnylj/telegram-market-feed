# 2026-10-26 morning verification incident

## Evidence and cause
The existing root was published by Meta, including its image and official 미국주식 topic.
The approved first part ended in two newline characters (244 Python characters).
Meta returned the same text without those trailing newlines (242 characters).
Exact text equality incorrectly raised "Published post verification mismatch".
Both original job 1bf31796-ced2-50e1-8f5e-7f531f683bef and prior retry
83a99347-6f9c-5c6f-be90-242a88897b9f reached published_unverified and exhausted
three automatic recovery attempts.

## Fix
recovery.py version 2026-10-26.1 compares text after trimming trailing ASCII
space/tab/CR/LF only. Leading and internal whitespace and every other character
remain significant. Apply the same comparison to account-feed reconciliation.
Account, post ID, permalink, official topic and image verification remain mandatory.
Approved queue payloads and IDs are unchanged.

## Regression validation
16 recovery tests pass, including trailing-newline round trips, stable job IDs,
resuming an existing root, topic mismatch, uncertain publish responses and
rejection of changed internal/leading text.

## Deployment and recovery
The repair workflow waits for running or imminently due jobs before replacing
only social-publisher, preserving its runtime configuration and private data.
Existing data and history are backed up; credentials never leave Oracle.
Resume only the original job after an atomic database claim. Re-verify its
existing first post, publish remaining approved replies, and verify their chain.
The prior retry's already-public duplicate root is retained with terminal state
duplicate_root_retained and canonical_job_id pointing to the completed original.
Do not publish its remaining replies or delete public content automatically.

Workflow: .github/workflows/repair-morning-20261026.yml
Deployment: social-publisher/oracle-recovery/deploy_verification_patch.py
Recovery: social-publisher/diagnostics/resume-morning-20261026.py

Do not re-run historical incident scripts for a new incident. Read the current
private diagnosis and Meta state first; never add another dedup_key to resolve
an ambiguous publish.
