# Roadmap

Measured on 2026-09-02 against the live install: 180 documents, 1,873 chunks,
45.8 MB. Figures below are observed unless marked *projected*.

Numbered tickets are tracked as GitHub issues. Each names the test cases that
define "done" — a ticket without them is a wish, not a ticket.

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

| # | Ticket | Depends on |
|---|---|---|
| [#10](../../issues/10) | Encrypt OAuth credentials at rest | — |
| [#11](../../issues/11) | `go2 connect google` — the authorisation flow | #10 |
| [#12](../../issues/12) | `go2 sync` — drive the connector from the CLI | #11 |
| [#13](../../issues/13) | Google Picker with the `drive.file` scope | #12 |
| [#14](../../issues/14) | Incremental sync: persist and resume from the cursor | #12 |
| [#15](../../issues/15) | Deletions must drop their chunks | #14 |

**Scope decision: `drive.file`, not `drive.readonly`.** The account is a
personal Gmail, so the OAuth *Internal* user type is unavailable — that
requires a Workspace organisation. External plus Testing revokes refresh
tokens every 7 days, and leaving Testing means Production, which triggers a
CASA security assessment ($500–4,500, re-verified annually) for the restricted
`drive.readonly` scope. `drive.file` is non-sensitive: Production without an
audit, no weekly expiry, and `changes.list` still works. The cost is that the
user must pick folders explicitly — which is also the easier client
conversation.

**Stop after #12 and use it for a few days.** Real questions against real
Drive files will reorder the rest better than this document can.

---

## Phase 2 — Safe for someone other than you

*A gate, not a backlog. A client demo cannot honestly happen before it closes.*

| # | Ticket | Why it gates |
|---|---|---|
| [#16](../../issues/16) | Authentication in front of `go2 serve --http` | There is none. Loopback binding is the only thing protecting the index. |
| [#17](../../issues/17) | Split `local` into real per-project workspaces | 92 HaramBlur + 20 Atmata + 5 test documents share one workspace. |
| [#18](../../issues/18) | OCR for scanned documents | Two Dawan files are image-only and unanswerable. |
| [#19](../../issues/19) | Tool-output redaction when the reader is not the owner | The switch works; nothing turns it on. |

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

**Cross-language retrieval is the real accuracy problem** ([#21](../../issues/21)).
Asking in Arabic instead of English, against the same English document, costs
a mean of 0.198 of score; three of five pairs fall under the 0.30 floor, so
the assistant refuses questions it can answer. This is *not* "Arabic scores
lower" — Arabic against Arabic scores 0.543, better than an English pair at
0.342. And it cannot be fixed by moving the floor: a correct Arabic query
scores 0.185 where a correct refusal scores 0.22, so the bands overlap and no
threshold separates them. That overlap is what the harness has been warning
about on this corpus; it now has a cause.

Remaining work: grow both sets to several hundred questions drawn from real
use; fix [#21](../../issues/21); build `query_spreadsheet` so a figure inside a
sheet is answerable rather than merely locatable.

---

## Phase 4 — Second connector, hosted

*2027.*

OneDrive via Graph `/delta`. Its real value is not OneDrive: it is proving the
connector seam holds with **zero new ingestion code**. If it needs any, the
abstraction was wrong, and better to learn that on the second connector than
the fifth. `tests/test_connector_contract.py` exists to make that verifiable
rather than a matter of opinion.

Then hosted deployment, once #16 is done, and per-tenant partitioning if
any single workspace approaches a million documents.

---

## Risks

**Silent retrieval drift.** The defining failure of this category: the system
keeps returning confident passages, just the wrong ones, and nothing alarms.
Only a large eval set catches it. This is why Phase 3 is not polish.

**A client with 500,000 documents.** Storage stays fine; the index working set
does not. The escape is dimension reduction — these embeddings are
Matryoshka-truncatable to 512 or 256 dimensions — but that trade has not been
measured here, and it should be measured before a customer forces it.

**Model tool-calling quality.** The design leans on the model to drive a loop
and to refuse when evidence is weak. A cheaper model skips the tools and
answers from its own weights, which has already been observed here with a
small local model. Any model change needs the eval set run against it first.
