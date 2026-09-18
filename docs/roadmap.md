# Roadmap

Measured on 2026-09-02 against the live install: 180 documents, 1,873 chunks,
45.8 MB. Figures below are observed unless marked *projected*.

This file says *why* and *in what order*. What exactly each item delivers,
who holds it and whether it is done lives in [`../backlog/`](../backlog/):
one file per ticket, and [`BACKLOG.md`](../backlog/BACKLOG.md) as the index.
Ticket ids here are `T-NNN` and link to those files. Where a GitHub issue
exists too, the ticket names it. A ticket names the test cases that define
"done" — a ticket without them is a wish, not a ticket.

Updated 2026-09-18. Where this is going, and why the phases look like
this: [`strategy.md`](strategy.md).

---

## Now, next, later

| | What | Tickets |
|---|---|---|
| **Now** | Google Drive end to end: the product's core promise, and nothing has shipped for it yet | T-010 → T-012, then T-035 |
| **Next** | The gate before anyone else touches it: real workspaces, OCR, redaction, QA evidence, real-MCP boundary tests, then the Dawan rehearsal that proves it | T-017, T-018, T-019, T-034, T-036, then T-030 |
| **Then** | The rest of Drive and the pilot: picker, incremental sync, deletions, five days of real use | T-013 → T-015, then T-037 |
| **Later** | Earn the accuracy claim: baselines, harvest, answer-level eval, cross-language, Arabic full-text, revisions, spreadsheets | T-033, T-032, T-031, T-021, T-038, T-044, T-022, T-023, T-025 |
| **After the first client** | Onboarding in under a day, users and roles, per-file permissions, the Libyan national number, the audit trail | T-043, T-027, T-028, T-039, T-041 |
| **The bank tier** | All-local answering measured, install with no internet, scanned-Arabic eval | T-040, T-042, T-045 |
| **2027** | A second connector, hosted | T-024, T-026 |

Done so far: T-000 (this process), T-016 (auth in front of HTTP), T-029
(the Basira mirror).

**The one thing that matters most:** T-010 → T-012 is a serial chain of
three P1 tickets and nothing is claimed on it. Every other phase is
sharpening a product whose defining feature does not exist yet. The gate
tickets and the accuracy tickets are independent of it and can run in
parallel on other agents, but the Drive chain should always have someone
on it.

---

## Phase 0 — The process

*Done: [T-000](../backlog/tickets/T-000-file-based-backlog-and-ticket-process.md)
and [T-029](../backlog/tickets/T-029-mirror-the-backlog-into-basira-with-go2-backlog-sync.md).*

The toolchain, the full suite and an agent review run before a PR exists
(`/pre-pr`), and CI re-runs them on the PR. Work is planned in tickets
before code is written, and the ticket is the record of what landed and what
was measured, so several agents can share the queue without a service in the
way. `go2 backlog check` keeps the files honest; the fast tests run it. The
tickets are mirrored into Basira, where progress is watched.

One gap already seen: T-029 sat `in-review` for a night after its PR
merged, because closing is a manual step on `main`. A check that flags an
in-review ticket whose PR is merged would close it
([T-046](../backlog/tickets/T-046-close-in-review-tickets-whose-pr-has-merged.md)).

---

## Where the constraints actually are

Three measurements shape every decision here.

**Storage is not a constraint; index memory is.** 249 KB per document, measured.
Ten thousand documents is 2.5 GB and runs on a laptop. Disk stays cheap to a
million documents, but the HNSW index wants its vectors resident — *projected*
64 GB of working set at a million documents. That, not disk, is what forces a
bigger machine somewhere around a hundred thousand.

**Retrieval is nearly free; generation is the whole bill.** Embedding 100,000
documents costs about $7, once. A hundred questions a day costs $17–50 a month
depending on the model. Cost is therefore never a reason to compromise
retrieval quality — spend freely there and economise on generation.

**The provider APIs are thirty times faster than our pipeline.** A Drive
download costs 200 quota units against 325,000 per minute per user — roughly
1,600 files a minute, where ingestion measures 51. Rate limiting will not be
the thing that slows a sync down, so the sync loop should be written for
correctness and resumability rather than for throughput.

---

## Phase 1 — Google Drive, end to end

*Now. The connector exists and is tested; nothing authorises it.*

`go2/connectors/gdrive.py` already implements the changes feed, the export map
and cursor handling, with 23 tests. What is missing is that no line in `go2/`
references OAuth, `token_blob` is written as `b""` and never read, and no CLI
command imports the connector.

| Ticket | | Depends on |
|---|---|---|
| [T-010](../backlog/tickets/T-010-encrypt-oauth-credentials-at-rest.md) | Encrypt OAuth credentials at rest | — |
| [T-011](../backlog/tickets/T-011-go2-connect-google-authorisation-flow.md) | `go2 connect google` — the authorisation flow | T-010 |
| [T-012](../backlog/tickets/T-012-go2-sync-drive-the-connector-from-the-cli.md) | `go2 sync` — drive the connector from the CLI | T-011 |
| [T-013](../backlog/tickets/T-013-google-picker-with-the-drive-file-scope.md) | Google Picker with the `drive.file` scope | T-012 |
| [T-014](../backlog/tickets/T-014-incremental-sync-persist-and-resume-from-the-cursor.md) | Incremental sync: persist and resume from the cursor | T-012 |
| [T-015](../backlog/tickets/T-015-deletions-must-drop-their-chunks.md) | Deletions must drop their chunks | T-014 |

**Scope decision: `drive.file`, not `drive.readonly`.** The account is a
personal Gmail, so the OAuth *Internal* user type is unavailable — that
requires a Workspace organisation. External plus Testing revokes refresh
tokens every 7 days, and leaving Testing means Production, which triggers a
CASA security assessment ($500–4,500, re-verified annually) for the restricted
`drive.readonly` scope. `drive.file` is non-sensitive: Production without an
audit, no weekly expiry, and `changes.list` still works. The cost is that the
user must pick folders explicitly — which is also the easier client
conversation.

**Stop after T-012 and use it for a few days.** Real questions against real
Drive files will reorder the rest better than this document can.

---

## Phase 2 — Safe for someone other than you

*A gate, not a backlog. A client demo cannot honestly happen before it closes.*

| Ticket | | Why it gates |
|---|---|---|
| [T-016](../backlog/tickets/T-016-authentication-in-front-of-go2-serve-http.md) | Authentication in front of `go2 serve --http` | There is none. Loopback binding is the only thing protecting the index. |
| [T-017](../backlog/tickets/T-017-split-local-into-real-per-project-workspaces.md) | Split `local` into real per-project workspaces | 92 HaramBlur + 20 Atmata + 5 test documents share one workspace. |
| [T-018](../backlog/tickets/T-018-ocr-for-scanned-documents.md) | OCR for scanned documents | Two Dawan files are image-only and unanswerable. |
| [T-019](../backlog/tickets/T-019-tool-output-redaction-when-the-reader-is-not-the-owner.md) | Tool-output redaction when the reader is not the owner | The switch works; nothing turns it on. |
| [T-030](../backlog/tickets/T-030-dawan-demo-readiness-the-exit-of-the-gate.md) | Dawan demo readiness | The exit criterion: a rehearsed demo on real files, recorded. |

T-016 shipped on 2026-09-16 (PR #24): a bearer token per serving process,
and binding beyond loopback refuses to start without one.

The phase ends with [T-030](../backlog/tickets/T-030-dawan-demo-readiness-the-exit-of-the-gate.md):
a rehearsed ten-question demo on Dawan's real files, on a machine that is
not the developer's, with at least one live Drive document in the
workspace. Until that rehearsal is recorded, the gate is not passed,
whatever the ticket statuses say.

**Evidence, not statuses.** Four QA tickets were added on 2026-09-17 so
that "done" means something a reviewer can check:
[T-034](../backlog/tickets/T-034-produce-a-repeatable-qa-evidence-report.md)
(one repeatable QA report per candidate commit),
[T-035](../backlog/tickets/T-035-verify-the-first-live-google-drive-user-journey.md)
(the first live Drive journey, account to cited answer),
[T-036](../backlog/tickets/T-036-test-client-boundaries-through-real-mcp-tools.md)
(tenant isolation and redaction through real MCP calls, not stubs) and
[T-037](../backlog/tickets/T-037-confirm-freshness-recovery-and-pilot-acceptance.md)
(five days of real use before a demo is called a pilot).

**Deliberately after the first client:**
[T-027](../backlog/tickets/T-027-users-and-workspace-roles-resolve-the-tenant-from-the-princi.md)
(users and roles) and
[T-028](../backlog/tickets/T-028-mirror-source-permissions-so-a-reader-sees-only-files-shared.md)
(per-file permissions from the source). Dawan is one workspace with one
reader group, which one token per process serves honestly. Building
multi-user access before a single Drive document is searchable would put
the platform ahead of the product.

---

## Phase 3 — Earn the accuracy claim

*Q4 2026.*

`go2 evaluate` reports **MRR 0.94, 16/17** on `local`. That is seventeen
questions: a smoke test, not a benchmark. It is enough to catch a regression
that breaks retrieval outright and nowhere near enough to quote to a customer.

### Baselines to beat

| Workspace | Suite | Passed | Rank 1 | MRR | Margin |
|---|---|---|---|---|---|
| `local` | `eval/questions.yaml` | 16/17 | 11 | 0.94 | +0.16 |
| `dawan` | `eval/dawan.yaml` | 19/20 | 15 | 0.97 | +0.08 |

Dawan's 20 cases were written by reading each document first — a case whose
answer was guessed measures the guess. They include the two near-identical
CQ-XP1010 quotations, which share a quotation number, a date and their
specifications and differ only in level count and price. That pair is what
hybrid search exists for, and it passes.

### What building the second suite found

**Eval sets are per-workspace.** The `local` suite scored 5/17 on `dawan` — it
asks about documents that workspace has never held. That reads like a
retrieval regression and is not one, so `tenant:` in an eval file now refuses
to run against the wrong workspace rather than returning a meaningless number.
Eval is therefore a per-client onboarding cost, not a one-time build.

**Titles were not Unicode-normalised.** macOS stores filenames decomposed;
a name typed into a query or a YAML file is composed. They render identically
and compare unequal, so `title_contains` on an Arabic filename returned
nothing and an eval case failed against the very document it named. Fixed at
the write boundary, with migration `005` for existing rows — this was a
user-facing bug, not only an eval one.

**Cross-language retrieval is the real accuracy problem** ([T-021](../backlog/tickets/T-021-cross-language-retrieval-falls-below-the-evidence-floor.md)).
Asking in Arabic instead of English, against the same English document, costs
a mean of 0.198 of score; three of five pairs fall under the 0.30 floor, so
the assistant refuses questions it can answer. This is *not* "Arabic scores
lower" — Arabic against Arabic scores 0.543, better than an English pair at
0.342. And it cannot be fixed by moving the floor: a correct Arabic query
scores 0.185 where a correct refusal scores 0.22, so the bands overlap and no
threshold separates them. That overlap is what the harness has been warning
about on this corpus; it now has a cause.

| Ticket | | Why |
|---|---|---|
| [T-033](../backlog/tickets/T-033-eval-baselines-in-one-file-not-three-documents.md) | Baselines in one file | The numbers below are typed by hand in three places; first, so the rest is measured against a record. |
| [T-032](../backlog/tickets/T-032-harvest-real-questions-from-traces-into-eval-candidates.md) | Harvest questions from traces | Invariant 8 has no mechanism; the suites are still 17 and 20 after two weeks of use. |
| [T-031](../backlog/tickets/T-031-answer-level-eval-through-the-tool-loop.md) | Answer-level eval | MRR stops one step short of what the user sees; the model's step is unmeasured. |
| [T-021](../backlog/tickets/T-021-cross-language-retrieval-falls-below-the-evidence-floor.md) | Cross-language retrieval below the floor | Correct answers are refused; the fix must be retrieval-side. |
| [T-038](../backlog/tickets/T-038-normalise-arabic-in-the-full-text-leg-of-hybrid-search.md) | Arabic in the full-text leg | `simple` treats eight spellings of four Arabic words as eight lexemes; a third of `dawan` is Arabic, and for it hybrid is vector-only. |
| [T-044](../backlog/tickets/T-044-near-duplicate-revisions-collapse-in-results-and-show-the-date.md) | Near-duplicate revisions | Two revisions of one proposal fill four of five slots, and passages carry no date, so the model cannot prefer the current one. |
| [T-022](../backlog/tickets/T-022-query-spreadsheet-tool.md) | `query_spreadsheet` | A figure in a sheet is locatable but not answerable. |
| [T-023](../backlog/tickets/T-023-grow-the-eval-sets-to-several-hundred-questions.md) | Eval sets to several hundred questions | 17 and 20 cases catch a breakage, not a drift. |
| [T-025](../backlog/tickets/T-025-measure-matryoshka-truncation-before-a-customer-forces-it.md) | Measure Matryoshka truncation | Decide the index-memory trade before a customer forces it. |

---

## Phase 4 — Second connector, hosted

*2027.*

OneDrive via Graph `/delta` ([T-024](../backlog/tickets/T-024-onedrive-connector-over-graph-delta.md)).
Its real value is not OneDrive: it is proving the connector seam holds with
**zero new ingestion code**. If it needs any, the abstraction was wrong, and
better to learn that on the second connector than the fifth.
`tests/test_connector_contract.py` exists to make that verifiable rather
than a matter of opinion.

Then hosted deployment ([T-026](../backlog/tickets/T-026-hosted-deployment-behind-authentication.md)),
once T-016 and T-019 are done, and per-tenant partitioning if any single
workspace approaches a million documents.

---

## Phase 5 — On-prem, for a bank

*After the first client. The buyer this is built to reach; see
[`strategy.md`](strategy.md).*

A Libyan bank or ministry permits no egress, runs on scans and Arabic
circulars, and asks who was told what from which document. The retrieval
core already meets that; deployment, generation, identity and audit do
not. These tickets measure before promising.

| Ticket | | Why |
|---|---|---|
| [T-039](../backlog/tickets/T-039-detect-the-libyan-national-number-in-the-pii-guard.md) | Libyan national number in the PII guard | Phones and IBANs are redacted; the identifier on every Libyan HR file is not. Phase 2, because it is a gate item once a Libyan office is the reader. |
| [T-040](../backlog/tickets/T-040-an-all-local-answering-path-measured-against-the-eval-sets.md) | All-local answering, measured | Generation and OCR still leave the machine, and a local model was once seen skipping the tools. Put a number on it. |
| [T-041](../backlog/tickets/T-041-audit-trail-who-asked-what-was-cited-exportable-and-retained.md) | Audit trail | The trace table is the right shape and has no user, no export, no retention. |
| [T-042](../backlog/tickets/T-042-install-with-no-internet-models-and-packages-vendored.md) | Install with no internet | First run downloads 1.7 GB from Hugging Face; a bank network downloads nothing. |
| [T-045](../backlog/tickets/T-045-a-scanned-arabic-eval-set-before-the-bank-tier-is-promised.md) | A scanned-Arabic eval set | The bank tier's largest accuracy risk, and no document in either suite measures it. |

Not ticketed on purpose: a file-share connector (written when a buyer
names the share) and anything customer-facing (written after a rung-3
pilot has run).

## Risks

**Silent retrieval drift.** The defining failure of this category: the system
keeps returning confident passages, just the wrong ones, and nothing alarms.
Only a large eval set catches it. This is why Phase 3 is not polish.

**A client with 500,000 documents.** Storage stays fine; the index working set
does not. The escape is dimension reduction — these embeddings are
Matryoshka-truncatable to 512 or 256 dimensions — but that trade has not been
measured here, and it should be measured before a customer forces it (T-025).

**Model tool-calling quality.** The design leans on the model to drive a loop
and to refuse when evidence is weak. A cheaper model skips the tools and
answers from its own weights, which has already been observed here with a
small local model. Any model change needs the eval set run against it first.
