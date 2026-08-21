# Signed corpus bundle format (EXP-15)

Status: implemented — `sprout corpus verify|install`. See
[ADR-0022](adr/0022-signed-corpus-bundle-trust-model.md) for the trust-model decisions
behind this design, and `docs/ideation/03-expansions.md` (EXP-15) for the original pitch.

This lets a third-party publisher (an extension service, a subject-matter expert) ship a
horticulture corpus Sprout can verify and install without a fork — while making it
structurally impossible for that corpus to alter Sprout's own routing or never-certify-
"safe" deny-list strings.

## The bundle

A `.sproutcorpus` file is a gzip-compressed tar archive:

```
manifest.yaml          # the ONLY file a signature covers; source of truth for everything
signature/
  dev.sig                #   raw Ed25519 signature (dev-ed25519 scheme, test/dev only), or
  sigstore.json           #   a real Sigstore bundle (sigstore-keyless scheme, production)
processed/*.md           # passages, same shape as this repo's corpus/processed/*.md
toxicity.yaml            # optional toxicity table
suites/*.yaml              # optional eval cases
```

`manifest.yaml` carries a `file_hashes` map (relative path → sha256) covering every other
file in the archive, so the one signature over the manifest transitively covers the whole
bundle. Nothing outside `manifest.yaml`, `signature/`, `processed/`, `toxicity.yaml`, or
`suites/` is a legal archive member — anything else (including an attempted
`config/sprout.yaml`) is rejected before extraction.

## Trust model, in one paragraph

The bundle's own claim of who signed it is never authoritative. `sprout corpus
verify|install` looks the bundle's claimed `publisher.id` up in *your* config
(`corpus_registry.trusted_publishers`) and verifies the signature against *that* entry's
scheme/identity/issuer. An empty `trusted_publishers` list (the default) trusts nobody.
See ADR-0022 for why.

```yaml
# config/sprout.yaml
corpus_registry:
  registry_path: corpus/registry
  license_allowlist: [CC0-1.0, CC-BY-4.0, CC-BY-SA-4.0, MIT, Apache-2.0, Public Domain]
  trusted_publishers:
    - id: acme-botanicals
      name: Acme Botanicals
      signing_scheme: sigstore-keyless
      identity: publishing@acme-botanicals.example   # the signer's Sigstore SAN
      issuer: https://accounts.google.com             # the OIDC issuer that vouched for it
```

## Using it

```console
$ sprout corpus verify acme-tropicals-1.0.0.sproutcorpus
OK  acme-tropicals 1.0.0 by Acme Botanicals (acme-botanicals)
    signed: sigstore-keyless / publishing@acme-botanicals.example
    license: CC0-1.0  documents: 42

$ sprout corpus install acme-tropicals-1.0.0.sproutcorpus
Installed acme-tropicals 1.0.0 from publisher acme-botanicals -> corpus/registry/acme-botanicals/acme-tropicals/1.0.0
Provenance recorded at corpus/registry/acme-botanicals/acme-tropicals/1.0.0/PROVENANCE.json
```

`verify` never writes anything. `install` verifies first, then extracts under
`corpus_registry.registry_path/<publisher>/<name>/<version>/` and writes a
`PROVENANCE.json` sidecar recording the publisher, the bundle version, and the exact
signature that verified. Neither command ever touches `corpus.path`, `corpus.manifest`,
or `config/` — an installed bundle lives in its own namespace by construction, so it
cannot alter `guards.forbidden_safe_phrases` or any other routing/deny-list string (those
are hardcoded/config-loaded in `config.py`, with no field on `BundleManifest` that could
carry an override — see `corpus_bundle.py`).

`sigstore-keyless` verification needs the `corpus` extra (`pip install sprout[corpus]`)
and network access to Sigstore's public-good infrastructure. Every other Sprout command,
including `dev-ed25519` bundle verification (development/CI test fixture only — not a
substitute for Sigstore's transparency log; see `corpus_signing.py`), stays offline.

## What this does *not* do yet

An installed bundle sits in `corpus/registry/` but is not yet wired into live retrieval:
its passages are not queryable by `sprout ask`, and its citations do not yet render a
publisher-provenance banner. That wiring — teaching `ingest.py`/`retrieve.py`/`answer.py`
about a second, registry-sourced corpus, and extending the citation guard's provenance
tag (`corpus` / `household`, see `models.py`) with a third `registry:<publisher>` case
that always renders a "from &lt;publisher&gt;, not reviewed by Sprout" banner — is a
scoped follow-up, not done in this change. The part landed here is the trust boundary
itself: the format, the signature/license/manifest/integrity enforcement, and the
structural guarantee that a third-party bundle cannot touch Sprout's own config.

Also not done here: a `sprout corpus sign` command. Real publishers sign with the
standard `sigstore sign --bundle` (or `cosign sign-blob --bundle`) CLI directly against
their own OIDC identity — Sprout only needs to *verify*, and shipping our own signer
would misleadingly suggest Sprout is a certificate authority rather than a verifier.
