# 22. Signed corpus bundle trust model (EXP-15)

- Status: Accepted
- Date: 2026-07-08
- Author: Chelsea Kelly-Reif
- Deciders: Chelsea Kelly-Reif (maintainer)

## Context

`docs/ideation/03-expansions.md` EXP-15 asks for a signed, verifiable corpus bundle
format so third-party publishers (extension services, SMEs) can distribute cited
horticulture corpora that Sprout can trust without a fork. The ideation doc names the
hard part directly: "trust-model design is the hard part (who may sign; how revocation
works)," with a hard floor — installed bundles must not be able to alter Sprout's own
routing/deny-list strings — and an excellence bar of "an unsigned or tampered bundle is
unloadable by construction."

Two trust-model questions had to be settled before any code:

1. **Whose claim about identity counts?** A bundle format that lets the bundle itself
   declare "I am publisher X, verify me with key Y" is not a trust model — it is
   self-attestation. Anyone can publish a bundle claiming to be a well-known publisher.
2. **What does "signed" mean in an offline-by-default project?** Sprout's hard rule 4 is
   "offline by default." Real Sigstore keyless verification (certificate chain to
   Fulcio's root + Rekor transparency-log inclusion) requires network access to
   Sigstore's public-good infrastructure — the correct trade for a feature whose entire
   point is trusting a party outside the repo, but it cannot be the only way to exercise
   this code in CI, which must stay offline and fast.

## Decision

- **Trust root lives in the installer's config, never in the bundle.** A new
  `corpus_registry.trusted_publishers` list in `config.py` is the only source of which
  publisher IDs verify and against which scheme/identity/issuer. `BundleManifest.publisher`
  is descriptive only; `corpus_registry.py` looks up the *claimed* publisher ID in that
  config list and verifies against *that* entry's declared scheme, never against
  anything the bundle asserts about its own signer. An empty list (the default) trusts
  nobody, which is the safe out-of-the-box state.
- **Two signing schemes, not one:**
  - `sigstore-keyless` is the production path: a real Sigstore bundle verified via the
    `sigstore` PyPI package (`corpus` extra) against the public-good instance —
    certificate chain, Rekor inclusion, and an OIDC issuer + Subject Alternative Name
    identity check. This mirrors the release pipeline's existing cosign/SLSA posture
    (`.github/workflows/release.yml`), extended across the publisher trust boundary
    instead of confined to this repo's own CI.
  - `dev-ed25519` is a local-keypair scheme explicitly documented as development/CI-test
    only (see `corpus_signing.py`'s module docstring) — no transparency log, no
    third-party root of trust, trust is whatever public key the config was given out of
    band. It exists solely so the enforcement logic (signature check, license
    allowlist, manifest completeness, integrity tree, path-traversal defense) is
    unit-tested for real, offline, in every CI run, without either hitting Sigstore's
    live infrastructure or accepting a fabricated "signed bundle" as evidence of
    production Sigstore integration. `verify_signature` fails closed if a bundle's
    scheme does not match the *config's* scheme for that publisher, so a dev-ed25519
    bundle can never satisfy a publisher configured as `sigstore-keyless`.
- **The routing/deny-list floor is structural, not a denylist check.** `BundleManifest`
  (`corpus_bundle.py`) is a Pydantic model with `extra="forbid"` and a fixed set of
  fields; there is no `guards`, `config`, or `routing` field anywhere on it. A bundle
  manifest containing such a key fails to parse before any of its content is read. This
  is why the excellence bar ("unsigned or tampered bundle is unloadable by
  construction") extends to "and cannot smuggle a config override" — enforced by the
  schema itself, the same way `ManifestEntry`/`Dataset` already fail closed elsewhere in
  this codebase (`ingest.py`, `eval/dataset.py`).
- **Verification happens before any content is trusted**, in a fixed order inside
  `corpus_registry.verify_bundle`: archive-layout safety (no path traversal, no
  non-regular-file members, a per-member size cap against decompression bombs) → the
  manifest parses → the publisher is trusted → the signature verifies → licenses are
  allowlisted → every file's content hash matches the manifest's declared tree. Any
  failure raises before the next check runs and before any passage content reaches a
  caller.
- **Install lands in its own namespace.** `corpus_registry.registry_path` (default
  `corpus/registry/`) is a directory Sprout's own `corpus.path`/`corpus.manifest`
  loading (`ingest.py`) never reads from, and `install_bundle` never writes to
  `config/` or `corpus/manifest.yaml`. This is what makes "cannot alter Sprout's own
  routing/deny-list strings" true by construction rather than by convention — there is
  no code path from an installed bundle to `GuardsConfig`.

## Consequences

- `sprout corpus verify|install` against a `sigstore-keyless` bundle needs the `corpus`
  extra (`pip install sprout[corpus]`) and network access; every other Sprout command
  stays fully offline, unchanged.
- This PR does not wire an installed bundle into live retrieval — its passages are not
  yet queryable and its citations do not yet carry a publisher-provenance banner. That
  is deliberately out of scope here (see `docs/corpus-bundle-format.md` "Follow-up");
  EXP-15 in the ideation doc is XL effort, and the verification/trust-model layer is the
  part with real design risk worth landing and reviewing on its own.
- A second real "publisher" signing a demo bundle with `sigstore-keyless` and installing
  it requires a live, interactive OIDC signing step (`sigstore sign`) that only a human
  with a real identity provider account can perform — it is not something this change
  fabricates or claims to have exercised end to end.
