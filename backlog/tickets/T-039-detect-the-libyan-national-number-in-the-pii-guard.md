---
id: T-039
title: Detect the Libyan national number in the PII guard
status: ready
phase: 2-gate
priority: P2
blocked_by: []
github_issue:
owner:
branch:
pr:
created: 2026-09-18
updated: 2026-09-18
closed:
---

## Problem

Measured on 2026-09-18:

```
redact('IBAN LY83002048000020100120361 and id 119850123456 and phone 0912345678')
-> 'IBAN [IBAN] and id 119850123456 and phone [PHONE]'
```

The Libyan IBAN is redacted through the generic mod-97 path and the Libyan
mobile through the `09` national form. The national number
(الرقم الوطني) is not detected at all: `_NATIONAL_ID` knows only the US
SSN shape `ddd-dd-dddd`. The national number is twelve digits, the first
being 1 or 2 for sex and the next four the birth year, and it sits on
every HR file, contract and KYC form in the country. Under the `redact`
policy those files leave the machine with the number intact, and under
`block` they are not blocked.

## Definition

Add a `LIBYAN_NATIONAL_ID` kind (or extend `NATIONAL_ID`) that matches
exactly twelve digits at word boundaries whose first digit is 1 or 2 and
whose next four form a year between 1900 and the current year. There is
no public checksum, so this is structural validation, and the precision
rule applies in full: the detector ships only after a `go2 scan` over the
`local` and `dawan` corpora reports its false-positive count, and that
count is recorded in the Outcome. If it fires on ordinary content, the
year window is tightened or the kind is dropped, not shipped noisy.

Also delivers a regression test that a Libyan IBAN is detected, so the
generic path cannot lose it silently. Does not deliver: passport numbers,
family-book numbers, or any detector without a stated structure.

## Success metrics

- Both `119850123456` and `219901234567` are detected and redacted in
  text and in tool output when `pii_redact_tool_output` is on.
- `300000012345` (impossible leading digit), `120000012345` (year out of
  range) and a thirteen-digit run are not detected.
- `go2 scan` over the `local` and `dawan` corpora reports 0 new findings
  of this kind on documents that do not contain a national number,
  verified by reading each hit. The count is written into the Outcome.
- `tests/test_pii.py` runs in the same time as before within noise; the
  detector is one anchored regex.

## Test cases

- `test_a_libyan_national_number_is_detected`
- `test_a_libyan_national_number_in_arabic_context_is_detected`
- `test_impossible_sex_digit_or_birth_year_is_not_a_national_number`
- `test_a_longer_digit_run_is_not_a_national_number`
- `test_a_libyan_iban_is_detected_by_the_generic_path`
- `test_a_libyan_mobile_next_to_a_national_number_yields_two_findings`

## Design notes

`go2.security.pii` already orders detection so a card is not also a
phone; the national number must be checked after cards and IBANs and
before phones, because `00218` international phone forms are fourteen
digits and a twelve-digit substring of one must not become a national
number. The precision rule in `CLAUDE.md` is the constraint: a redactor
that fires on ordinary content gets switched off, and a switched-off
control protects nothing.

## Work log

- 2026-09-18 — Opened from the strategy review; the guard knew Libyan
  phones and IBANs and not the identifier every Libyan file carries.

## Outcome
