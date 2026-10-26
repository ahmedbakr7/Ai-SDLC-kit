---
id: ADR-0009
title: Binary files come from a declared generator or a pinned source, not from the agent
status: accepted
date: 2026-10-26
source: Hangout pilot assessment ("agents can't commit binary files"); proposed 2026-10-21, accepted by the lead in the kit session
---

# ADR-0009: Binary files come from a declared generator or a pinned source, not from the agent

## Context

Agents edit text. A ticket that needs an icon, a font, a fixture image or a sample PDF stalls:
the agent cannot produce the bytes, and a person who adds them by hand bypasses the play's
attribution. Reviewers also cannot read a binary diff, so a binary that is "just an asset" is
unreviewed content.

Options considered:

- **Declared assets (proposed).** A ticket, or a repository-wide `assets.toml` on the base branch,
  lists each binary path with either:
  - a `generate` command run from committed text sources (an SVG to PNG, a fixture builder); or
  - a `source` URL with a `sha256`.
  `sdlc assets` produces or fetches each one and verifies the hash. The play commits the result.
  A gate check `assets` fails any binary in the diff that is undeclared or does not match.
- **Git LFS.** It moves storage, not provenance. Agents still cannot make the bytes, and review
  still cannot read them.
- **Leave binaries to humans in lead PRs.** That works today but couples asset work to the lead
  and leaves no record of where the bytes came from.

## Decision

- Add declared assets in a repository-wide `assets.toml` (`paths.assets`), a lead artifact. Every
  entry has a `path`, a `sha256` and exactly one of `generate` (a command) or `source` (an
  `https://` URL). Declaring assets in a ticket is left for later: a ticket is written on the base
  branch too, so it would add a second place to look without changing who declares.
- Add an `assets` check for the build, test, PR, mechanical and refactor lists and `gate ci`, plus
  `sdlc assets [--check]`. A ticket's gate reads `assets.toml` as the base branch has it; a PR
  without a ticket reads its own, which the lead's approval covers.
- The check is opt-in, so no product that passes today fails on upgrade: by default
  (`[assets] mode = "warn"`) it reports undeclared or mismatched binaries and passes;
  `mode = "fail"` fails it.
- A binary is any file git reports as binary (`diff --numstat` shows `-`). That follows
  `.gitattributes` on purpose: a path marked `binary` or `-diff` counts, and a text file such as
  an SVG does not, even when generated. Whether a declared text asset is hash-checked too is an
  open question below.
- Fetching needs the network only where a `source` is used. A generator runs as a gate command
  does, under the base branch's config.

## Consequences

- Agents can ship tickets that need binaries.
- Every binary has a reviewable recipe or a pinned origin.
- Generators must be deterministic, or their hashes churn. Non-deterministic tools (some image
  encoders) need pinned flags or a `source` instead.

## Open questions

- Should vendored binaries (fonts, licensed images) carry a licence field the review must name?
- Should a declared asset that git sees as text (a generated SVG) be hash-checked as well? Not
  today: only binaries are checked, and a text asset is reviewed as text.
