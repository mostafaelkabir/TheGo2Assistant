# Use cases

What the product does for whom, with an example of each. Examples marked
**measured** were run against the live `dawan` workspace on 2026-09-18 and
show what came back. Examples marked **illustrative** are what a later rung
of the [strategy](strategy.md) looks like from the reader's chair, with the
ticket that has to land first. The citation format is the product's own:
document, then page, slide or section.

How every use case works underneath is the same. The reader asks a
question in a chat client. The model calls `search_documents`, reads the
passages and their scores, rephrases or calls `fetch_document` for more of
a file if it needs to, and answers with a citation per claim. If no passage
clears the evidence floor, the answer is "the documents do not say". That
refusal is a feature: a wrong answer costs more than no answer.

---

## Rung 1 — A small company on Google Drive

The reader is a founder, an engineer or an office manager. The corpus is a
few hundred files: pitch decks, supplier quotations, engineering
proposals, contracts, a few spreadsheets, some scans.

### Telling apart two near-identical supplier quotations — measured

Two quotations from the same supplier share a quotation number, a date and
every specification, and differ only in the number of weighing levels and
the price. This is the case embeddings are worst at, and the reason the
product fuses full-text search with vector search.

> **Q.** What is the price of the CQ-XP1010 8-level weighing sorting
> machine, and how does it compare with the 6-level?
>
> **A.** The 8-level CQ-XP1010 is quoted at USD 6,880 and the 6-level at
> USD 6,500, both from Guangdong Chaoqiang Electronic Technology on the
> same date.
> *Quotation of CQ-XP1010 8-level 20230515.pdf p.1;
> Quotation of CQ-XP1010 6-level 20230515.pdf p.1*

Both quotations rank in the top four for the question, and each price is
an eval case in `eval/dawan.yaml` that passes.

### Finding an engineering decision in a proposal — measured

> **Q.** How are dates ejected into their categories on the sorting line?
>
> **A.** By controlled air blow at stage 4 of the line; the design runs
> five parallel conveyor lines, each with four dedicated air blowers.
> *DATES SORTING MACHINE 12-13-2023.pdf p.7 and p.6*

The top passage scored 0.648. The corpus holds two revisions of this
proposal, dated December 2023 and January 2024, and both rank in the top
four with the same page numbers. A reader sees which revision each
citation comes from, which is the point of citing the file and not just
the fact.

### Asking in Arabic about an Arabic document — measured

> **س.** ما هو الهدف من النموذج الأولي للمنتج؟
>
> **ج.** The purpose of a prototype, from the introduction of the Arabic
> document of the same name: to learn the customer's interest and opinion,
> to test the product in practice, and to reach the market quickly with
> room to improve after launch.
> *النموذج الأولي للمنتج.pdf p.3*

The top passage scored 0.542. Arabic against Arabic is not the problem;
it scores higher here than several English pairs do.

### Asking in Arabic about an English document — measured, refused today

> **س.** ما هي الطاقة الإنتاجية لجهاز فرز التمور؟
>
> **What happened.** The top passage scored 0.285, under the 0.30 evidence
> floor, so the assistant declines. Asked in English, the same question
> scores 0.602 on the page that holds the answer, one ton per hour
> (*Pitch Deck - Sunbulah.pdf p.4*). Asked in Arabic, a different deck
> ranks first and nothing clears the floor.

This is the measured gap [T-021](../backlog/tickets/T-021-cross-language-retrieval-falls-below-the-evidence-floor.md)
exists to close, and the case is kept in the eval set as known-failing so
the limitation stays visible. Lowering the floor is not the fix: a correct
refusal scores 0.22 on this corpus, so the bands overlap.

### Refusing what the files do not contain — measured

> **Q.** What is the office wifi password?
>
> **A.** The documents do not say.

Every passage scored below zero. The same holds for a question answerable
in a *different* workspace: "What commercial structure was recommended for
Mido?" has an answer in `local` and is refused in `dawan`, which is how
the eval set asserts workspace isolation.

### Questions about the files, not their contents

> **Q.** Which supplier quotations do we have, and which came from Drive
> this month?
>
> **A.** A list from `list_documents`, filtered by source and date, with
> each file's title, origin and indexing status.

Metadata questions cannot be answered by similarity search, which is why
listing is a separate tool. The Drive half of this example needs
[T-012](../backlog/tickets/T-012-go2-sync-drive-the-connector-from-the-cli.md).

### A figure inside a spreadsheet — planned

> **Q.** What was the total budget for milestone 2?
>
> **Today.** The proposal PDF answers it (27,650) because the figure is in
> prose. The same figure in a budget sheet is *locatable* through the
> per-sheet summary but not *answerable*, because sheets are never chunked
> as prose.
> **After [T-022](../backlog/tickets/T-022-query-spreadsheet-tool.md):**
> `query_spreadsheet` returns the row, and the citation is the sheet and
> row.

### A scanned brochure — planned

Two Dawan files are image-only PDFs. They are marked `pending` rather
than silently empty, and are unanswerable until
[T-018](../backlog/tickets/T-018-ocr-for-scanned-documents.md) lands OCR
behind a provider interface.

---

## Rung 2 — Professional offices — illustrative

Law firms, accounting practices, engineering consultancies, trading
companies. Same product, one workspace each, one reader group. What
changes is that the questions carry exact identifiers more often, and the
onboarding cost per client is a per-workspace eval set.

### A law office: what did we agree, and where

> **Q.** What notice period did we agree with the landlord for the Tripoli
> office, and was it amended?
>
> **A.** Ninety days in the original lease, extended to one hundred and
> twenty days by the 2025 amendment.
> *Tripoli office lease.pdf p.4; Lease amendment 2025.pdf p.1*

Two searches, not one: the first returns the lease, the second the
amendment. That is what an agentic loop is for and what a single
retrieve-and-stuff pass gets wrong.

### An accounting practice: an invoice by number

> **Q.** Who was invoice INV-2024-0871 issued to, and has it been paid?
>
> **A.** Issued to Al-Madar Trading on 14 March 2024 for LYD 18,400; the
> payment confirmation is dated 2 April.
> *Invoices Q1 2024.pdf p.37; Bank confirmations March-April.pdf p.6*

An invoice number is nearly meaningless to an embedding. The full-text leg
finds it exactly, and the reranker does the rest.

### An engineering consultancy: which specification applies

> **Q.** What concrete grade does the client specification require for the
> foundation slabs?
>
> **A.** C35/45, per section 4.2 of the client's technical specification;
> the earlier tender document said C30/37 and was superseded.
> *Technical Specification Rev C.pdf p.12; Tender Document.pdf p.8*

The answer names both documents because a reader who only sees the
superseded one will pour the wrong concrete.

---

## Rung 3 — An office with teams, and a bank department — illustrative

Employee-facing. The reader is staff. The corpus is internal: circulars,
operating procedures, HR policy, product terms, vendor contracts, IT
runbooks. Mostly scans, mixed Arabic and English, on a file share or
SharePoint, on a network with no internet. Every question is recorded with
who asked it and what was cited.

Needs, beyond rung 2: users and roles
([T-027](../backlog/tickets/T-027-users-and-workspace-roles-resolve-the-tenant-from-the-princi.md)),
permissions mirrored from the source
([T-028](../backlog/tickets/T-028-mirror-source-permissions-so-a-reader-sees-only-files-shared.md)),
Arabic in the full-text leg
([T-038](../backlog/tickets/T-038-normalise-arabic-in-the-full-text-leg-of-hybrid-search.md)),
the Libyan national number in the guard
([T-039](../backlog/tickets/T-039-detect-the-libyan-national-number-in-the-pii-guard.md)),
an all-local answering path
([T-040](../backlog/tickets/T-040-an-all-local-answering-path-measured-against-the-eval-sets.md)),
an audit trail
([T-041](../backlog/tickets/T-041-audit-trail-who-asked-what-was-cited-exportable-and-retained.md))
and an offline install
([T-042](../backlog/tickets/T-042-install-with-no-internet-models-and-packages-vendored.md)).

### Compliance: the current rule, with its circular number

> **س.** ما هو الحد الأقصى للسحب النقدي للأفراد حسب آخر تعميم؟
>
> **ج.** The limit and the circular that set it, with the date, and a note
> that an earlier circular set a different figure and was superseded.
> *تعميم رقم 2025/14 ص.2; تعميم رقم 2024/9 ص.1*

Freshness is the whole value: an employee who quotes a superseded limit
to a customer is the failure this replaces. Which is why the pilot ticket
measures that a changed file replaces the old answer after sync, and a
deleted one disappears from search, list and fetch.

### Operations: the procedure, step by step

> **Q.** What are the steps to reverse a duplicate transfer, and who must
> approve it?
>
> **A.** The five steps from the operations manual, and the approval
> threshold from the delegation-of-authority matrix.
> *Operations Manual v7.pdf p.88; Delegation of Authority.xlsx sheet
> "Payments", row 14*

Two documents, one of them a spreadsheet, served through
`query_spreadsheet` rather than guessed from a summary.

### HR: policy in the reader's language

> **س.** كم يوم إجازة سنوية يستحق الموظف بعد خمس سنوات خدمة؟
>
> **ج.** The entitlement from the HR policy, cited by section, answered in
> Arabic because the policy is in Arabic.
> *لائحة شؤون الموظفين، المادة 21*

An HR file carries national numbers on nearly every page. When the reader
is not the file's owner, tool output is redacted before it reaches them,
and the national number is one of the identifiers the guard knows.

### A branch: product terms a customer is asking about right now

> **Q.** What documents does a sole trader need to open a business
> current account?
>
> **A.** The list from the account-opening procedure, and the fee from the
> tariff sheet, each cited.
> *Account Opening Procedure.pdf p.6; Tariff of Charges 2026.pdf p.2*

This is the rung-3 question that becomes the rung-4 product: the same
answer, given to the customer directly.

### Audit: who was told what

> **Q.** (from the audit function, to the export, not the assistant)
> Which staff asked about the cash withdrawal limit last week, and which
> circular were they shown?
>
> **A.** A JSONL export of every request in the window with user, question,
> the tool calls and the cited document and page. No passage text.

### What a reader with the wrong role sees

> A reader in the retail team asks about a treasury procedure they have no
> access to on the file share.
>
> **A.** The documents do not say.

Not "access denied", which would confirm the document exists. The reader's
permissions are mirrored from the source, and a document they cannot open
there is not in their search here.

---

## Rung 4 — Customer-facing support — illustrative, unticketed

A curated corpus of approved documents, not the file share. A channel
customers use, which in Libya is WhatsApp before it is a web widget. The
headline metric is refusal rate, because a wrong answer to a customer is a
complaint and a wrong refusal is a phone call.

> **س.** ما هي رسوم التحويل الدولي؟
>
> **ج.** The fee from the published tariff, with its effective date, and
> "for the exact amount on your account, please contact your branch".
> *Tariff of Charges 2026, p.3*

> **س.** كم رصيد حسابي؟
>
> **ج.** I can answer questions about the bank's published products and
> procedures. For your account, please use the mobile app or your branch.

The second answer is the important one. The product never sees account
data, and a corpus that contains only approved public documents cannot
leak what it does not hold. No ticket exists for this rung on purpose: what
a bank will allow a bot to say is learned from a rung-3 pilot, not guessed.

---

## What the product is not for

- **Transactions or account data.** It reads documents. It does not touch
  a core banking system and should not be connected to one.
- **Open-domain questions.** "How many employees does Toyota have in
  Japan?" is refused, by design and by eval case.
- **Summarising a whole corpus.** "What do all our contracts say?" is a
  report, not a lookup. The tools page through one document at a time
  with citations, which is the wrong shape for that job.
- **A chat UI of its own.** The interface is whatever the organisation
  already runs: Claude Code, LibreChat, later WhatsApp. The product is the
  tools behind it.
