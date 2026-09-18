---
id: T-042
title: 'Install with no internet: models and packages vendored'
status: backlog
phase: 5-on-prem
priority: P3
blocked_by: [T-040]
github_issue:
owner:
branch:
pr:
created: 2026-09-18
updated: 2026-09-18
closed:
---

## Problem

First run downloads the embedding model (1.7 GB) and the reranker from
Hugging Face into `model_cache_dir`; `uv sync` fetches from PyPI; the chat
UI pulls Docker images. Network-dependent startup has already failed once
in an ordinary setting: the full test suite hung because IPv6 to
`api.jina.ai` black-holed. A bank network permits no outbound connection
at all, so today the product cannot be installed there, whatever the
on-prem configuration (T-040) measures.

## Definition

- `go2 bundle` (or a repository script) producing one archive: wheels for
  the locked dependency set, the model weights T-040 names, the chat UI
  images, and a manifest with a checksum per file.
- An install runbook in `docs/on-prem.md` from archive to first cited
  answer, verified on a clean Linux virtual machine with networking
  disabled, and the run recorded in the Outcome.
- Under the bundle, Hugging Face offline mode is set by default and a
  missing model fails at startup with the fix named, not at the first
  query with a network timeout.
- `go2 status` reports which bundle and model checksums are loaded.

Does not deliver: a Windows installer, a package for any distribution, or
automatic updates.

## Success metrics

- Clean VM, networking disabled: archive to first cited answer in under
  60 minutes following the runbook only.
- Zero outbound connection attempts during install, ingest of a test
  folder and ten searches, measured with the host firewall logging drops.
- Every file in the archive matches its manifest checksum; a corrupted
  file is refused by name.
- `go2 status` shows the bundle id on the installed machine.

## Test cases

- `test_models_load_from_cache_dir_with_hub_offline_set`
- `test_a_missing_model_in_offline_mode_fails_at_startup_naming_the_fix`
- `test_bundle_manifest_checksums_match_contents`
- `test_a_corrupted_bundle_file_is_refused_by_name`
- `install_on_a_clean_offline_vm` — manual acceptance, recorded.

## Design notes

Blocked by T-040 because the bundle must carry whichever local models
that ticket selects. Docker images are the largest part of the archive
and the chat UI is the only reason for them; if the bank tier ends up
served through a client the bank already runs, the images leave the
bundle. The memory note about the Jina hang is the reason offline mode is
a default under the bundle and not an option.

## Work log

- 2026-09-18 — Opened from the strategy review: a product for a network
  with no egress must install without one.

## Outcome
