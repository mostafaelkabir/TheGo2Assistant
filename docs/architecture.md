# Architecture

The component diagram and the short version live in [`../README.md`](../README.md).
The working agreement and the invariants that must not be broken casually live
in [`../CLAUDE.md`](../CLAUDE.md). This file records *why* the shape is what it
is, for decisions whose reasoning is not obvious from the code.

> Supersedes `component-architecture.md`, which described an on-prem banking
> deployment on Qdrant, React and DocsGPT. That design was written for a
> different buyer and none of it was built.

## Why agentic search rather than single-shot RAG

Retrieve-top-k-then-stuff-the-prompt answers one shape of question well and
fails at three that come up constantly:

- *"What did we agree with Acme on pricing?"* often needs two searches, because
  the first returns the contract and the second the amendment.
- *"Which contracts expire this quarter?"* is a property of the files, not of
  any passage inside them. No amount of semantic similarity finds it.
- *"What's the total in the Q3 budget?"* needs the actual rows.

Exposing retrieval as tools lets the model rephrase, page through a document,
and combine metadata filters with semantic search. The same four typed
functions serve the MCP server today and an in-process agent loop later.

## Why hybrid retrieval

Exact identifiers are what embeddings are worst at and what people search for.
An invoice number is nearly meaningless to an embedding, and two contracts from
the same template are near-identical in vector space.

Vector and full-text results are fused by Reciprocal Rank Fusion — by *rank*,
not score, because cosine distance and `ts_rank_cd` are not on comparable
scales and any weighted sum of the raw numbers would be arbitrary.

Reranking then does the work that matters: measured, it was 98.7% of query
latency before the passage budget was introduced, and it is what turns a
recall-oriented candidate pool into a precise answer. Passages are reduced to
the window with the most query-term overlap rather than their opening — taking
the opening blindly made two candidates sharing a long preamble score
*identically*, collapsing a 3.7 gap to zero.

## Why chunks never merge across a location boundary

A chunk spanning pages 3 and 4 can only be cited as one of them. A citation
that sends a reader to the wrong page is worse than a slightly smaller chunk,
because it costs them the trust that makes the citation worth having.

Headings count as locations. A Word or Markdown document has no page numbers,
so the section heading is the only coordinate a citation has — found the hard
way, when a remote-work answer was correctly retrieved and incorrectly cited
under "Expense Policy".

## Why spreadsheets are not chunked

Prose-chunking a budget destroys exactly the numbers the question is about.
Each sheet is kept whole; the retrieval path indexes a summary and serves real
rows separately.

## Why vectors carry provenance

Embeddings from different models are not comparable, and mixing them fails
*silently*: queries return confident nonsense rather than an error, which is
the worst failure mode available. Each document records the model that produced
its vectors, and search scopes to the model currently configured — so switching
providers degrades to "nothing found", with an explanation, rather than to
garbage.

## Why sizing is in characters, not tokens

The corpus is mixed Arabic/English. A token budget borrowed from another
model's tokenizer misestimates one script badly: English chunks near the target
while Arabic chunks far under it. Characters are consistent across both, and
the model's real limit is far enough away that an approximate budget is safe.

## Why local and hosted providers both exist

On-device inference keeps every document on the machine, which is the right
default. It also costs roughly a millisecond per character to embed and
saturates every performance core, which made a laptop unusable during a folder
ingest. Measured on 93 files: 24 minutes locally versus 3 minutes through the
API, and search 3.4s versus 0.4s.

Neither is right for everyone, so both are supported and the trade is stated
where it is made. Note that a cheap cloud CPU is *slower* than an M2 — hosting
is not a substitute for this choice.

## Bounded batches

`fastembed` defaults to `batch_size=256`. On CPU that buys no throughput and
cost 24 GB resident on a 16 GB machine: the worker swap-thrashed for fourteen
minutes at 0% CPU rather than computing. Throughput is flat from batch 1 to 4
and only memory grows, so a small batch is strictly better.

## Multi-tenancy

`tenant_id` is on every table and in every query, and a `Scope` object is
threaded through every write. Single tenant today. Becoming multi-tenant means
resolving `Scope` from a request rather than auditing every call site.

## Configuration is not relative to the working directory

`go2` is installed as a tool and runs from anywhere, so config is read from
`~/.config/go2/.env` first and a project-local `.env` second. A bare `.env`
resolves against the *current* directory, which meant the same command silently
used different settings depending on where it was typed. Anything that depends
on the working directory will behave differently under a scheduled worker than
it does by hand.
