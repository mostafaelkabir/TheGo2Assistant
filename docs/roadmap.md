# Roadmap

Measured on 2026-09-02 against the live install: 180 documents, 1,873 chunks,
45.8 MB. Figures below are observed unless marked *projected*.

This file says *why* and *in what order*. What exactly each item delivers,
who holds it and whether it is done lives in [`../backlog/`](../backlog/):
one file per ticket, and [`BACKLOG.md`](../backlog/BACKLOG.md) as the index.
Ticket ids here are `T-NNN` and link to those files. Where a GitHub issue
exists too, the ticket names it. A ticket names the test cases that define
"done" — a ticket without them is a wish, not a ticket.

Updated 2026-09-16.

---

## Now, next, later

| | What | Tickets |
|---|---|---|
| **Now** | Google Drive end to end, and the process to build it with | T-000, T-010 → T-012 |
| **Next** | The gate before anyone else touches it: auth, real workspaces, OCR, then users and roles | T-016, T-017, T-018, T-019, T-027, T-028 |
| **Then** | The rest of Drive: picker, incremental sync, deletions | T-013 → T-015 |
| **Later** | Earn the accuracy claim: cross-language, spreadsheets, eval at scale | T-021, T-022, T-023, T-025 |
| **2027** | A second connector, hosted | T-024, T-026 |

---

## Phase 0 — The process

*Done with [T-000](../backlog/tickets/T-000-file-based-backlog-and-ticket-process.md).*

The toolchain, the full suite and an agent review run before a PR exists
(`/pre-pr`), and CI re-runs them on the PR. Work is planned in tickets
before code is written, and the ticket is the record of what landed and what
was measured, so several agents can share the queue without a service in the
way. `go2 backlog check` keeps the files honest; the fast tests run it.

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
| [T-027](../backlog/tickets/T-027-users-and-workspace-roles-resolve-the-tenant-from-the-princi.md) | Users and workspace roles | One token per process is one trust level; a company has many. |
| [T-028](../backlog/tickets/T-028-mirror-source-permissions-so-a-reader-sees-only-files-shared.md) | Mirror source permissions | Workspace membership shows every file, including ones Drive would refuse. |

T-016 is the one that gates the others: T-019 and any hosted deployment
depend on knowing whether a request is trusted.

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
| [T-021](../backlog/tickets/T-021-cross-language-retrieval-falls-below-the-evidence-floor.md) | Cross-language retrieval below the floor | Correct answers are refused; the fix must be retrieval-side. |
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
