---
id: T-038
title: Normalise Arabic in the full-text leg of hybrid search
status: ready
phase: 3-accuracy
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

Measured on 2026-09-18 against the live database. The `chunks.tsv` column
is `to_tsvector('simple', text)` and `build_tsquery` lowercases and
nothing else, so the full-text leg matches Arabic only on its exact
surface form:

```
select to_tsvector('simple', 'الفاتورة فاتورة مؤسسة مؤسسه أحمد احمد الشركة وشركة');
'أحمد':5 'احمد':6 'الشركة':7 'الفاتورة':1 'فاتورة':2 'مؤسسة':3 'مؤسسه':4 'وشركة':8
```

Eight spellings of four words, eight unrelated lexemes. The definite
article, the conjunction, hamza-on-alef against bare alef and taa marbuta
against haa are all ordinary variation inside one document, never mind
between a question and a document. 192 of the 625 `dawan` chunks (31%)
contain Arabic. For those, the full-text half of hybrid search finds
nothing unless the question repeats the document's spelling, and hybrid
silently degrades to vector-only, which is the failure invariant 9 exists
to prevent. Latin text has the opposite problem in miniature and is out of
scope here: `simple` does no English stemming either, but the corpus's
identifiers are what the leg is for and they are exact by nature.

## Definition

One normaliser, applied at both boundaries, so the index and the query can
never disagree:

- Strip tashkeel (U+064B–U+0652), tatweel (U+0640) and the Quranic marks.
- Fold alef variants (أ إ آ ٱ) to bare alef, taa marbuta (ة) to haa (ه),
  alef maqsura (ى) to yaa (ي).
- Emit prefix-stripped forms for the clitics ال، و، ف، ب، ك، ل and their
  stacks (وال، بال، فال), as additional lexemes at index time and
  additional OR terms at query time. Stripping rather than stemming: a real
  Arabic stemmer over-merges (كتب and مكتب), and precision is what the
  reranker cannot give back.
- Latin text, digits and identifiers pass through unchanged. Case folding
  stays where it is.

Delivers: the normaliser in `go2/rag/`, a migration that replaces the
generated `tsv` with one over the normalised text (or a trigger, whichever
keeps the column generated), a backfill for existing rows, and
`build_tsquery` calling the same function. Does not deliver: Arabic
stemming, cross-language retrieval (T-021), synonym expansion, or any
change to the vector leg.

## Success metrics

- Every Arabic case in `eval/dawan.yaml` has its expected document in the
  top 20 of the full-text leg alone, measured before and after with a
  `go2 search --leg fulltext` debug flag or an equivalent test harness.
  Record the before number in the Outcome; today it is unmeasured.
- `dawan` stays at or above 19/20, MRR 0.97; `local` at or above 16/17,
  MRR 0.94. Every `expect_no_answer` case still refuses.
- The exact-identifier tests in `tests/test_retrieval.py` pass unchanged:
  an invoice number or a quotation id is not touched by the normaliser.
- Backfill of 1,873 chunks completes in under a minute on the dev machine.

## Test cases

- `test_prefix_variants_of_an_arabic_word_match_the_same_chunk`
- `test_alef_and_taa_marbuta_variants_normalise_to_one_lexeme`
- `test_tashkeel_and_tatweel_are_ignored`
- `test_latin_terms_digits_and_identifiers_are_unchanged`
- `test_query_and_index_use_the_same_normaliser`
- `test_arabic_cases_in_the_dawan_suite_are_found_by_the_fulltext_leg`
- Both eval suites, compared against the baselines above.

## Design notes

Touches invariant 9 (hybrid, never vector-only) by making it true for
Arabic rather than only for Latin. PostgreSQL ships a snowball `arabic`
configuration, and migration `001` rejected it because the corpus is
mixed; that reasoning holds, which is why this is a script-aware
normaliser in Python and not a text-search configuration. The generated
column cannot call a Python function, so the choice is between a stored
`text_normalised` column written by the app and a SQL rewrite of the same
rules; prefer whichever keeps one implementation. Migration `005` (Unicode
normalisation of titles) is the precedent for fixing this at the write
boundary with a backfill.

## Work log

- 2026-09-18 — Opened from the strategy review: Arabic is a first-class
  script in every leg of retrieval, and the full-text leg was not.

## Outcome
