---
id: T-045
title: A scanned-Arabic eval set before the bank tier is promised
status: backlog
phase: 5-on-prem
priority: P2
blocked_by: [T-018]
github_issue:
owner:
branch:
pr:
created: 2026-09-18
updated: 2026-09-18
closed:
---

## Problem

The strategy names Arabic OCR as the single largest accuracy risk on the
bank rung: a bank corpus is mostly scans, circulars are Arabic, and no
retrieval fix helps if the text that comes back from OCR is wrong. Nothing
measures it. The two image-only Dawan PDFs are English; T-018's Arabic
round-trip test proves the pipeline preserves Arabic characters, not that
OCR reads an Arabic scan correctly. There is no scanned-Arabic document in
either eval set, so a regression in Arabic OCR quality, or a switch from a
hosted OCR model to a local one under T-040, would be invisible.

## Definition

- A set of at least ten scanned Arabic documents with a text-layer
  counterpart or a hand-verified transcription: circular-style memos,
  stamped letters, a signed contract page, a table. Synthetic or
  self-authored, printed and scanned or rendered to image, so nothing
  confidential enters the repository.
- Character error rate and word error rate per document, measured against
  the transcription, for every OCR provider in `config.py`, recorded in the
  baselines file (T-033).
- At least fifteen retrieval eval cases over those documents in
  `eval/scanned-arabic.yaml`, each expectation read from the transcription,
  run by `go2 evaluate` like the other suites.

Does not deliver: a new OCR engine, a change to T-018's provider choice,
or Arabic OCR tuning; it produces the number those decisions need.

## Success metrics

- CER and WER recorded per provider per document; the first run is the
  baseline and sets no target.
- Retrieval pass rate and MRR on `eval/scanned-arabic.yaml` recorded per
  provider.
- The suite refuses to run against a workspace other than its own, like
  the others.
- Zero confidential content: every document in the set is authored for it.

## Test cases

- `test_scanned_arabic_suite_carries_its_tenant_guard`
- `test_cer_and_wer_are_computed_against_the_transcription`
- `test_every_scanned_document_has_a_transcription`
- The suite itself, under each OCR provider, with results in the Outcome.

## Design notes

Blocked by T-018 because there is no OCR to measure until it lands. The
same set is what T-040 runs its local OCR provider against, which is why
the documents must be free to commit. Rendering a Word document to an
image at 200 dpi with a scanner-like transform is enough for a first set;
real paper through a real scanner is better and should be added when
available.

## Work log

- 2026-09-18 — Opened from the strategy's risk section: the bank tier's
  largest accuracy risk had no measurement.

## Outcome
