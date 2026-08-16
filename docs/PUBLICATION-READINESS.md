# Publication readiness

**Audit date:** 2026-08-16 · **Commit audited:** `main` @ `ff6fb5b`, plus all 39
other branches (163 commits reachable from all refs) · **Current visibility:**
PRIVATE · **Recorded publication state:** none. No decision to publish has been
made, and **this document does not make one.** Changing the repository's
visibility is a separate, deliberate act reserved to the maintainer.

**Verdict: the working tree is ready. The history is not, and will not be until
the prepared rewrite runs.** Every finding below is either fixed here or stated
with a bounded remediation. One of them — the history rewrite — must land
*before* publication, not after, because publishing a repository publishes every
commit on every branch, not the tip of `main`.

This document exists to make the publication decision cheap and safe to make.
It does not make it.

---

## What was scrubbed, and why

The maintainer's standing rule is that an unpublished repository is never named
in public copy. Five such names appeared in this repository. **This document
does not repeat them** — a publication-readiness note becomes public with the
repository it audits, so writing the names here would recreate the exact defect
it records. They are described by role.

| Where | What it named | How it reads now |
|---|---|---|
| `docs/adr/0019-frozen-plugin-api-for-sprout-eval.md` | an unpublished sibling eval harness, cited as the motivating consumer of the plugin seam | "the author maintains other, unpublished eval-shaped projects that could consume the same runner" — the argument for freezing the API is unchanged; only the example is generalised |
| `src/sprout/_vendor/genai_telemetry/README.md` | three unpublished repositories, listed as the shim's binding scope | "every AI-full repo in the author's portfolio — this one included" — the scope rule is identical, the roster is not enumerated |
| `.github/workflows/ci.yml` | an unpublished repository, cited as precedent for disabling gitleaks PR comments | "the same stance the author's other repos take" — still records that this is a portfolio-wide decision rather than a one-off |
| `.github/workflows/release.yml` | an unpublished repository hosting the shared `release-authorize` reusable workflow | repointed at the publicly readable copy in the org profile repository |
| one commit message | an unpublished repository the CodeQL gate was ported from | unchanged in the tree; **only a history rewrite can reach a commit message** — see below |

Nothing was deleted to make a name go away. Each replacement keeps the claim the
sentence was making and drops only the identifier.

### The release workflow was also a functional defect

The `authorize` job consumed a reusable workflow from a repository a public
reader cannot resolve. That is not only a naming problem: **a caller can only
reuse a workflow it can read**, so on the day this repository went public its
release pipeline would have started failing at the first job. It now calls the
publicly readable copy, which was verified byte-identical to the copy it
replaced — same behaviour, same trust boundary, SHA-pinned. This is the same
pin two already-public sibling repositories use.

### One exposure is already live and predates this audit

The docs site at `sprout.chelseakr.com` is served publicly from this private
repository (GitHub Pages, `"public": true`). One of the five names was therefore
**already readable on the public internet**, in the rendered ADR, and listed in
the published sitemap. The scrub removes it from the next build; a rebuild is
required for the live page to change. Treat this as evidence for a general point:
this repository's `docs/` tree has been a public surface for some time, and the
privacy boundary people assume from "the repo is private" did not hold for it.

## What remains in history

Four of the five names remain in history: **17 occurrences across 14 distinct
blobs, reachable from 116 of the 163 commits** on `main` and on feature
branches. The fifth remains in a commit message. The working-tree scrub does not
touch any of them. Publishing before the rewrite publishes all of them.

A rewrite is prepared and rehearsed but **deliberately not run and not pushed**.
It lives outside this repository, because the expression files it needs contain
the names as search strings and committing them here would defeat the scrub.
Ask the maintainer for the kit path. It consists of:

- a `git-filter-repo` invocation over a fresh `--mirror` clone, driven by
  `--replace-text` (blobs) and `--replace-message` (commit messages);
- eight exact-line replacements chosen so each rewritten historical sentence
  still reads correctly, plus case-insensitive catch-all rules beneath them so
  any occurrence the line rules miss is still removed;
- an executable seven-check verification plan: no name in any blob in the
  rewritten object database, none in any commit message, none in any path, ref
  name, or tag annotation; commit count and ref set unchanged; a printed tree
  diff of old tip against new tip for every branch; a secret scan of the
  rewritten history; and the full local gate set green at the rewritten tip.

Three things about running it are the maintainer's, not this document's:

1. **Order matters.** The scrub must be merged first. The rules match only the
   old wording, so the tip's hand-written replacements pass through untouched
   and only historical blobs get the mechanical substitution. Running the
   rewrite first would produce worse prose at the tip.
2. **`main` carries `required_status_checks`.** History rewriting needs the
   ruleset temporarily relaxed. That is a maintainer action.
3. **A force-push is not the end of it.** GitHub keeps rewritten commits
   reachable by SHA until garbage collection, and merged pull requests still
   reference the old SHAs. Removing them fully needs a support request, as a
   sibling repository already had to file.

### Two knock-on effects of the rewrite

- `docs/adr/0012-recalibrated-abstention-thresholds-supersedes-0005.md` cites a
  short commit SHA that the rewrite will invalidate. `git-filter-repo` writes an
  old-to-new commit map; update the citation from it afterwards. One line.
- Pull request bodies for three merged or closed PRs name unpublished
  repositories. **A history rewrite does not touch pull request bodies** — they
  live in GitHub's database, not in git. They become readable the moment the
  repository goes public. Editing them is a maintainer action and was
  deliberately not done here.

## The rest of the publication surface

| Gate | Status | Evidence |
|---|---|---|
| Full-history secret scan | **PASS** | gitleaks over all refs, 156 commits, ~7.76 MB: *no leaks found* — reproduced with the repo's own `.gitleaks.toml` and again with an empty config, so the result does not depend on the committed allowlist |
| PII in fixtures | **PASS** | the only PII-shaped literals are deliberate redaction canaries in the test suite; corpus and eval data are synthetic |
| Corpus and eval data licensing | **PASS** | every manifest row is `license: CC0-1.0` with an `example.invalid` source URL; `NOTICE` states the corpus is synthetic and license-clean. Nothing here is republished third-party data |
| Vendored code licensing | **PASS (documented here)** | `src/sprout/_vendor/genai_telemetry/` is first-party code by the same author, Apache-2.0 in its source library, with no third-party code and no foreign copyright headers. Redistribution needs no additional permission. `NOTICE` now says so, because a reader could not otherwise tell |
| License and attribution | **PASS** | complete unmodified Apache-2.0; `NOTICE` disclaims employer and client material; `CITATION.cff` is accurate and correctly omits `date-released` for a project with no tags |
| Real people other than the maintainer | **PASS** | none named anywhere in the tree or in history |
| Internal hosts, VPN, or local filesystem paths | **PASS** | every host referenced is public; no `/Users/`, `*.internal`, or `*.corp` anywhere |
| Commit authorship | **PASS** | all human commits are the maintainer's; two carry a personal address rather than the GitHub noreply one, which is her call |
| Stale privacy claims | **PASS (fixed here)** | `.github/workflows/codeql.yml` justified its local SARIF gate by saying the repository is private. Reworded to state the operative fact — code scanning is not enabled — which stays true after a visibility change |
| Claim accuracy | **PASS** | `make claims` reconciles `docs/claims.yaml` against code and config; green |

### Three things that are choices, not defects

- **`CODE_OF_CONDUCT.md` publishes a personal email as the enforcement
  channel.** Correct for a project with one maintainer, and it is a real
  address, so it will attract real mail once public. Whether that address is the
  right one is the maintainer's call.
- **Internal standards documents are referenced by name** (`AI-EVALUATION-STANDARD.md`
  and similar, in the vendored README). These leak no content — only the fact
  that an unpublished standards document exists. Left as written.
- **Commit history records that this repository was private,** in the message
  explaining why the CodeQL gate is local. That was true when written. Commit
  messages are a record, not documentation, and rewriting accurate history to
  flatter a later decision is worse than leaving it.

### One durable regression risk

The vendored `genai_telemetry` README has now diverged from its upstream source,
which still carries the original wording, while `.standards-version` still pins
that upstream commit. **A future re-vendor will reintroduce the names.** Fix the
upstream copy too, or the next routine sync silently undoes this scrub.

## What a reader should not infer

- **Not that this repository is, or is about to become, public.** It is private
  as of the audit date and the decision is unmade.
- **Not that the history is clean.** It is not, until the prepared rewrite runs
  and is verified. This document is explicit about that because a readiness note
  that overstates its own findings is worse than none.
- **Not that the absence of names means the absence of related work.** The scrub
  removed identifiers, not facts. The author maintains other projects; this
  document simply does not name the unpublished ones.
- **Not that CI verified any of this.** It could not. Actions billing is failing
  account-wide, so every check on this private repository reports "The job was
  not started because recent account payments have failed." Every claim above
  was verified locally instead, and the verification section below says exactly
  what that did and did not cover.

## What was verified, and how

Run locally against a fresh clone, because CI cannot run:

```
make lint type          → ruff clean; mypy clean, 121 source files
make test               → 779 passed, 94.31% coverage (90% floor)
make workflow-lint      → zizmor --min-severity high: no findings
make docs               → mkdocs build --strict: clean
make claims             → all claims reconciled with their source of truth
make gate-inventory     → no unresolved AUTO row
make ci-parity-check    → make verify and the required CI jobs agree
make slo                → SLO and alert files valid
actionlint              → clean on all three edited workflows
gitleaks (all refs)     → no leaks found
```

**Not verified, and honestly cannot be here:** that the `release` workflow
succeeds end to end. It is `workflow_dispatch`-only, no tag has ever been cut,
and the change to its `authorize` job is a repoint to a byte-identical copy of
the same reusable workflow — verified by diffing the two sources, which is
strong evidence but not a green run. The first real release will be the first
execution of that path either way.
