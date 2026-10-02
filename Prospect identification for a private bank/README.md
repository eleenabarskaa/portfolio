# Prospect Identification for a private bank

**Internal tool · Python / Flask · n8n · PostgreSQL · LLM agents · vector search**

An internal application that helps a bank's private-wealth desk find and qualify
potential clients: it detects liquidity events in public sources and turns a
name into a sourced research brief, replacing work that relationship managers
were doing by hand.

*Source code and screenshots are not published - this is an internal tool. What
follows is the problem, the architecture and the reasoning behind the technical
decisions.*

---

## The problem

A private-wealth desk acquires clients by noticing **liquidity events** - a
company sold, a listing, a private-equity exit, a generational handover - and
reaching the people behind them early. Two things have to happen fast: someone
has to *notice* the event, and someone has to know enough about the person to
have a credible first conversation.

Both were manual. Relationship managers read the financial press themselves, and
when something looked relevant they assembled a background dossier by hand -
ownership structures, transaction history, professional network - spread across
registries, filings and press archives. That is hours of work per name.

The cost showed up in two places: **coverage**, because a person reading the
press finds what they happen to read, and **latency**, because by the time a
dossier is ready the moment may have passed.

## What was built

An internal web application with two automated capabilities behind a normal desk
interface - an event feed with filters, a reading view for dossiers, a watchlist,
and PDF export for client-meeting preparation.

**Trigger detection.** A curated set of financial sources is scanned on demand.
Candidate articles are extracted into structured, deduplicated events - date,
entity, event type, counterparties, source - and land in a searchable feed.

**Prospect briefs.** A name produces a structured research brief from public
sources: identity and ownership, transaction and liquidity history, professional
background and network, and an explicit list of what could not be confirmed.
Every factual claim carries its source and a status saying how it was
established.

## Architecture

Three layers, split by what changes at what speed:

- **Web application** - routing, data contracts, rendering, PDF export. This is
  what must be fast, versioned and tested, so it is ordinary Python.
- **Automation platform (n8n)** - the scanning, the classification and the
  research agents. This is the part that was still changing weekly: which
  sources, which prompt, which model, what counts as a qualifying event.
  Changing a prompt there is a click; in application code it is a deployment.
- **Managed PostgreSQL** - the shared state, and the only channel through which
  the two sides report results to each other.


## Technical decisions

**Slow work never lives inside a web request.** Research runs for minutes; an
HTTP request cannot. So the automation layer answers immediately with a receipt,
writes a job row, and the page polls that row. A long research run and a health
check cost the same connection time - and failure becomes a *state* in the
database rather than a spinner that never resolves.

**The classifier is not allowed to be a source.** It may use only the article
text it is given; the link it returns must match the link it was given; an
article that does not fit the criteria is skipped rather than stretched to fit.
A model that quietly fills gaps produces deals that read perfectly and never
happened - in this domain that is worse than missing them.

**Deduplication is semantic, not by link.** Events are keyed on date, entity,
event type and counterparties. The same transaction reported by two outlets is
one event; a link-based check would file it twice and inflate the feed.

**Research is split into collect → verify → write - three model calls with
different permissions.** The researcher gathers facts with sources and is not
allowed to write prose. The validator has no web access and may not add facts;
its only job is to re-check attribution, claim statuses and the arithmetic. The
writer also has no web access and fills a fixed template from the validated
material alone. A single agent that searches, judges and writes in one pass will
promote an inference to a fact somewhere in a long generation, and nothing
downstream can detect it. Here, that promotion has to survive a reviewer whose
only job is to find it.

**Domain rules are encoded as hard constraints, not hints.** The financial
reasoning around a liquidity event is exactly where a naive system produces
confident wrong numbers, so the rules are explicit: enterprise value is not the
seller's proceeds; attribution uses ownership *at the transaction date*, not
today's; personal net proceeds are never estimated unless disclosed; a share
buyback is not shareholder liquidity without evidence of a sale; a retained
stake is not a realised event; nothing is counted twice. Every fact is labelled
- verified, calculated, third-party estimate, inference, or unknown - and
anything unconfirmed goes to an explicit *open questions* section instead of
into the narrative.

**Two cost tiers, deliberately biased.** A full research run costs minutes and
real money. A question about a prospect already researched is routed instead to
retrieval over the briefs already produced, and finished briefs are indexed back
so each run makes the next question cheaper. The intent classifier is tuned to
prefer the cheap path, because a lookup that misses falls through to full
research, while the opposite mistake wastes the whole run.

**Privacy boundaries are part of the specification.** No conclusions about
personal relationships, motives or willingness to be introduced; no private
contact details; family members only where they bear on ownership, governance or
succession; anything internal to the bank is explicitly out of scope and
recorded as a gap rather than guessed at.


## What it changes for the desk

Coverage stops depending on what one person happened to read. Preparation that
took hours per name becomes a request that returns a structured, sourced brief.
And because every claim carries its provenance and its confidence, the output is
something a relationship manager can check before walking into a meeting - which
is the only version of this tool that is actually usable in a regulated setting.
