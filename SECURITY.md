# Security Policy

Sprout is an independent personal open-source project (Apache-2.0). It runs **offline by default**
— no auth, no network, no persisted user data — so its app-security posture is **OWASP ASVS L1**
(see [`SECURITY-AND-SUPPLY-CHAIN-STANDARD.md`](../STANDARDS/SECURITY-AND-SUPPLY-CHAIN-STANDARD.md)
for the cross-cutting controls this repo references rather than restates; per-repo values are in
[`docs/ROADMAP.md`](docs/ROADMAP.md)). The optional serverless API and the Family-Greenhouse
household-data path raise the bar to L2 and are deferred to a later phase.

## Supported versions

Sprout is pre-1.0, so per the portfolio release policy **only the latest minor on the latest major
receives security fixes**; fixes ship forward in a new patch release (no re-publish of a version).

| Version | Supported          | Notes                                               |
|---------|--------------------|-----------------------------------------------------|
| 0.1.x   | ✅ Yes             | Current release line; receives security patches.    |
| < 0.1.0 | ❌ No              | Pre-release / unreleased; upgrade to 0.1.x.         |

When a `0.2.0` ships, `0.1.x` security support ends and this table is updated in the same release.

## Reporting a vulnerability

**Please do not open a public GitHub issue, PR, or discussion for a security report.**

Report privately, by either:

1. **GitHub Security Advisory** — open a draft advisory via *Security → Report a vulnerability* on
   the repository (preferred; keeps the report, fix, and CVE/GHSA linked), **or**
2. **Email** — `ckellyreif@gmail.com` with subject `SECURITY: sprout`.

Please include, as far as you can:

- affected version / commit and the mode (offline CLI, served UI/API, or a provider seam),
- a minimal reproduction or proof-of-concept,
- the impact you believe it has, and
- any suggested remediation.

If you want an encrypted channel, say so in a first low-detail email and we will arrange one.

## Our commitments (disclosure SLA)

| Stage                      | Target                                                              |
|----------------------------|---------------------------------------------------------------------|
| Acknowledgement & triage   | **≤ 72 hours** from receipt                                         |
| Severity assessment        | CVSS-based, shared with you with the triage reply                   |
| Fix or mitigation plan     | communicated after triage, prioritized by severity                  |
| Coordinated disclosure     | by mutual agreement; default embargo up to 90 days                  |
| Credit                     | named in the advisory and CHANGELOG `Security` entry, unless you prefer to remain anonymous |

A fix ships *forward* in a new patch release; the release notes and the `CHANGELOG.md` `Security`
section reference the advisory (GHSA) per
[`RELEASE-AND-VERSIONING-STANDARD.md`](../STANDARDS/RELEASE-AND-VERSIONING-STANDARD.md) §7.

## Scope

In scope: the `sprout` package and CLI, the eval harness, the bundled web UI, the build/release
workflows, and the dependency supply chain (pinned + scanned with pip-audit, gitleaks, Semgrep,
SHA-pinned Actions, SBOM on release).

Out of scope: the **synthetic CC0** bundled corpus and eval data contain no secrets or PII by
construction; findings about plant-care *correctness* are eval-case or corpus issues, not security
issues — file those as normal issues. The same goes for accessibility regressions (a merge-blocking
quality gate, not a vulnerability).

Note: Sprout's answers are not veterinary, medical, or safety advice. The never-certify-"safe"
toxicity guard and poison-control routing are *product safety* properties tested in the eval
`safety` suite, not part of this vulnerability-disclosure scope.

## Hardening notes for self-hosters

- Keep the default **offline** mode unless you have a reason not to; it has the smallest attack
  surface (no network, no auth, no persistence).
- If you enable a cloud provider seam (Bedrock/Anthropic), supply credentials via environment only
  — secrets are never committed and gitleaks blocks them in CI.
- Run `pip-audit` (`make security`) before deploying and keep dependencies on the pinned lockfile.
