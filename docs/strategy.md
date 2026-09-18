# Strategy

Where the product is going, and which decisions that fixes today. The
roadmap ([`roadmap.md`](roadmap.md)) says in what order; the backlog
([`../backlog/`](../backlog/)) says what exactly and whether it is done.
This file is the reason the other two look the way they do.
What each rung looks like from the reader's chair, with examples:
[`use-cases.md`](use-cases.md).

Updated 2026-09-18.

---

## The goal

An assistant that answers a question from an organisation's own documents
with a citation to the page or section, or says plainly that the documents
do not say. The first buyer is a small Libyan company on Google Drive. The
buyer the product is built to reach is a bank or an office in Libya, then
the wider MENA region: first as a knowledge base for employees (procedures,
circulars, policies, contracts, product manuals), later as the source a
customer-support channel answers from.

Everything in the architecture that matters to that buyer already exists
in the wedge product: retrieval runs on the machine, every byte that leaves
passes one boundary, every row carries a workspace id, hybrid search finds
the identifier an embedding cannot, and a weak answer is refused rather
than dressed up. What separates the wedge from the destination is not the
retrieval core. It is deployment, generation, identity and how deep Arabic
goes. Those are the things this file is about.

## The ladder

Four rungs. Each is a different buyer, and each one is reached only from
the rung below it.

**1. Dawan.** One company, one workspace, one reader group, Google Drive
plus local files. This is Phases 1 and 2 of the roadmap. It ends when the
demo rehearsal ([T-030](../backlog/tickets/T-030-dawan-demo-readiness-the-exit-of-the-gate.md))
is recorded and the pilot ([T-037](../backlog/tickets/T-037-confirm-freshness-recovery-and-pilot-acceptance.md))
is signed. Nothing on a higher rung is built before a Dawan reader has
asked a question of a live Drive document and received a cited answer.

**2. Two or three more Libyan offices.** Law firms, engineering and
accounting practices, trading companies: the same product, on Drive or a
folder, one reader group each. What this rung teaches is the onboarding
cost. Eval sets are per workspace (the `local` suite scored 5/17 on
`dawan`), so every client costs a suite written by reading their files.
The rung ends when three workspaces are served and the third took under a
day to onboard, measured. That is when one process serving several
workspaces ([T-027](../backlog/tickets/T-027-users-and-workspace-roles-resolve-the-tenant-from-the-princi.md))
stops being premature.

**3. An office with teams, and a bank department.** The first client whose
readers must not all see the same files, and the first employee-facing
deployment inside a bank: internal circulars, operating procedures, HR
policy, product terms, vendor contracts. Staff are the readers, the corpus
is internal, and a wrong answer is caught by a professional who knows the
domain. That is the lowest-risk way into a regulated institution and the
one that teaches what a customer-facing deployment would need. This rung
is Phase 5 of the roadmap.

**4. Customer-facing support.** A curated, approved corpus rather than a
file share; a channel people actually use in Libya, which is WhatsApp
before it is a web widget; and refusal rate, not answer rate, as the
headline metric, because a wrong answer to a customer is a complaint and a
wrong refusal is a phone call. No ticket exists for this rung on purpose.
It is written after a rung-3 pilot has run for a quarter, because what a
bank will actually allow a bot to say is learned there, not guessed here.

## Why a bank, and why not yet

A Libyan bank runs on paper that became scanned PDFs, Arabic circulars
from the central bank, English vendor and core-banking documentation,
Windows file shares or on-premises SharePoint, and no public cloud. The
thing its staff cannot do is find the current version of a procedure.
That is exactly the question this product answers, and the reasons it is
hard there — scanned pages, two scripts in one corpus, a regulator, no
egress — are the reasons a generic hosted assistant cannot be sold there.
The moat is that the retrieval core was built local-first for a laptop and
happens to be what a bank's network requires.

Not yet, for three reasons. The defining feature, Google Drive, has not
shipped. A bank sale is six to twelve months of procurement, and that
clock should start with a product that has answered real questions for a
paying client. And this project already contains the alternative: the
superseded `component-architecture.md` described an on-premises banking
deployment for a buyer who did not exist yet, and none of it was built.
The rungs exist so that does not happen twice.

## What the destination fixes now

These are cheap to hold to today and expensive to retrofit. Each is a
constraint on current work or a ticket, not a phase.

**Generation stays behind a switch, and the eval set admits any model.**
Today generation happens in the chat client and goes to Alibaba Model
Studio in Singapore. A bank tier needs a model on the premises, and the
roadmap already records the risk: a small local model skipped the tools
and answered from its own weights. Nothing measures what an all-local
configuration costs in accuracy, so no bank conversation can be had with
numbers. [T-040](../backlog/tickets/T-040-an-all-local-answering-path-measured-against-the-eval-sets.md)
measures it.

**OCR is a provider, not a call.** [T-018](../backlog/tickets/T-018-ocr-for-scanned-documents.md)
routes page images through the egress boundary to a hosted OCR model,
which is right for Dawan. It must land behind the same interface the
embedding and reranking providers use, so a local OCR engine is a config
line later and not a second pipeline. A bank corpus is mostly scans, and
Arabic OCR quality is the single largest accuracy risk on rung 3.

**Arabic is a first-class script in every leg of retrieval.** Chunk sizing
is already in characters because tokens misestimate Arabic. Cross-language
retrieval, an Arabic question against an English document, is measured and
ticketed ([T-021](../backlog/tickets/T-021-cross-language-retrieval-falls-below-the-evidence-floor.md)).
The full-text leg is not: the index uses PostgreSQL's `simple`
configuration, which treats الفاتورة and فاتورة, أحمد and احمد, مؤسسة and
مؤسسه as unrelated words. A third of the Dawan chunks are Arabic. For those
the full-text half of hybrid search only matches an exact spelling, and
hybrid quietly degrades to vector-only, which is the failure invariant 9
exists to prevent.
[T-038](../backlog/tickets/T-038-normalise-arabic-in-the-full-text-leg-of-hybrid-search.md)
fixes it at both boundaries with one function.

**The guard knows Libyan identifiers.** Libyan mobile numbers in national
and international form are detected; a Libyan IBAN passes the generic
mod-97 check and is redacted. The national number, الرقم الوطني, twelve
digits on every HR file and KYC form in the country, is not detected at
all. [T-039](../backlog/tickets/T-039-detect-the-libyan-national-number-in-the-pii-guard.md)
adds it under the precision rule: measured on the existing corpora for
false positives before it ships on.

**Identity and audit are one seam.** Auth today answers only "may you talk
to this server". Per-user identity and roles
([T-027](../backlog/tickets/T-027-users-and-workspace-roles-resolve-the-tenant-from-the-princi.md))
and permissions mirrored from the source
([T-028](../backlog/tickets/T-028-mirror-source-permissions-so-a-reader-sees-only-files-shared.md))
hang off the same middleware seam T-016 built. A bank auditor's question
is "who was told what, from which document, when", and the trace table
already records tool steps without document text, which is the right
shape. [T-041](../backlog/tickets/T-041-audit-trail-who-asked-what-was-cited-exportable-and-retained.md)
turns it into an audit trail once there is a user to record.

**It runs where there is no internet.** First run downloads 1.7 GB of
embedding weights and the reranker from Hugging Face; `uv sync` reaches
PyPI; the chat UI pulls Docker images. A bank network permits none of
that. [T-042](../backlog/tickets/T-042-install-with-no-internet-models-and-packages-vendored.md)
makes the install an archive and proves it on a machine with networking
off.

**The connector seam is the product, not any one connector.** A bank's
"Drive" is a Windows share or on-premises SharePoint, not Google. The
local-folder path already indexes a mounted share and skips unchanged
content by hash, so the missing piece is change detection over a folder,
not a new pipeline. T-024's real value is proving OneDrive needs zero new
ingestion code; the connector after that is a file share, and its ticket
is written when a buyer names the share.

**English-answerable first, Arabic measured from day one.** The retrieval
core's bugs are language-independent, so the gate and the demo are judged
first on the English cases, where a failure means retrieval broke and not
that Arabic handling did. But the first client's corpus is a third Arabic,
and both user-facing Arabic bugs found so far (character sizing, decomposed
filenames) were found by having Arabic in the corpus. So Arabic cases stay
in every suite from the start and a failing one is recorded as
known-failing, never removed; T-021 and T-038 stay after the Drive chain
and are not gates for rung 1; and an English-speaking client, if one
appears, joins rung 1 in parallel rather than replacing it. An
English-only phase would not make metrics easier, since an Arabic eval
case costs exactly what an English one costs, and would defer the Arabic
discoveries to the moment a Libyan office is watching.

## What is deliberately not built

- **A customer-facing bot before rung 3.** See the ladder.
- **Our own chat UI.** LibreChat and Claude Code are the interface; the
  product is the tools behind them. A UI is the fastest way to spend a
  year on something a bank already has.
- **Hosted multi-tenant SaaS as the bank offer.** Banks do not buy that.
  Hosting ([T-026](../backlog/tickets/T-026-hosted-deployment-behind-authentication.md))
  is for the small offices on rung 2 who do not want a server.
- **Fine-tuning.** Every accuracy problem measured so far was retrieval,
  and retrieval is where the eval set can prove a fix.
- **The Beijing endpoint, vector-only search, or a top-k-and-stuff path.**
  Invariants, not preferences.

## What is next, in order

1. **The Drive chain, always staffed.** T-010 → T-011 → T-012, then the
   live user journey (T-035). Nothing else on this list matters if a Drive
   document is not searchable.
2. **The gate, in parallel on other agents.** Workspaces (T-017), OCR
   (T-018, behind a provider interface), redaction on (T-019), the QA
   evidence report (T-034) and the real-MCP boundary tests (T-036). Then
   the rehearsal (T-030).
3. **Earn the accuracy claim.** Baselines in one file (T-033), harvest
   questions from traces (T-032), answer-level eval (T-031),
   cross-language (T-021), Arabic in the full-text leg (T-038).
4. **The pilot.** Incremental sync (T-014), deletions (T-015), then the
   five-day pilot acceptance (T-037). Rung 1 ends here.
5. **After the first client.** Users and roles (T-027), mirrored
   permissions (T-028), the Libyan national number (T-039), the audit
   trail (T-041). Rung 2 and the first half of rung 3.
6. **The bank tier.** All-local answering measured (T-040), offline
   install (T-042), a file-share connector once a buyer names one.
7. **2027.** OneDrive (T-024), hosting for small offices (T-026).

## How we will know it is working

| Rung | Evidence |
|---|---|
| 1 | T-030 rehearsal: 8 of 10 cited, 0 confident wrong. T-037 signed by the reader's organisation. |
| 2 | Three workspaces served; the third onboarded in under a day; every suite at MRR ≥ 0.90. |
| 3 | An all-local configuration with zero egress steps in `go2 trace`, within a measured and published margin of the cloud path on the same suite; an audit export a reviewer accepts. |
| 4 | Decided after rung 3, from what the pilot showed a bank will allow. |

## Risks specific to this direction

**Arabic OCR.** Hosted OCR on Arabic scans is unmeasured here, and local
Arabic OCR is worse than hosted. If rung-3 corpora are mostly scans and the
text that comes back is wrong, no retrieval fix helps. T-018's Arabic
round-trip test is the first measurement; the bank tier needs a scanned
Arabic eval set before any promise is made.

**A local model that will not drive the loop.** Observed once already.
T-040 exists to put a number on it before a hardware budget is set. If the
number is bad, the honest bank offer is a smaller one: retrieval and
citations with a lighter generation step, not a worse copy of the cloud
product.

**Procurement time.** A bank cycle is longer than the roadmap's horizon.
Starting the conversation on rung 2 with rung-1 evidence is right; starting
it on rung 1 with nothing shipped is the mistake this file exists to
prevent.
