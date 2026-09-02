#!/usr/bin/env python3
"""Fail when sprout.chelseakr.com is not what this checkout builds.

Every gate here grades the build tree. `sprout a11y-check` runs on
`site/index.html` and on `web/dist/index.html`, the conformance suite runs the
browser corpus against the Python pipeline, `mkdocs build --strict` refuses a
broken reference. All of that runs before the artifact leaves the runner.
Nothing has ever looked at the bytes a reader receives, so a pages run that
failed, never fired, or published an older commit would leave every gate green
while the deployed page answered from a stale corpus index, and nothing in this
repository could tell.

This is the check for the deployment. It takes a `site/` tree built from the
checkout by exactly the steps pages.yml runs, fetches each published file over
HTTPS, and fails naming every byte-level difference.

    scripts/verify_live_site.py --site site

WHAT IS NOT COMPARED BYTE FOR BYTE, AND WHY

Two files, both stamped by mkdocs with the day the build ran rather than with
anything about the content:

  * `sitemap.xml` carries a `<lastmod>` per URL, which mkdocs fills from
    `get_build_date()`. Every one of the 52 entries reads today's date on a page
    untouched for weeks. It is compared with those elements removed, so the URL
    set, the change frequencies and the priorities are all still gated and only
    the build stamp is not.
  * `sitemap.xml.gz` embeds a gzip MTIME field, so its bytes move whenever a
    build crosses a UTC midnight. It is not compared as bytes. Instead its live
    body must decompress, and what it decompresses to must be the live
    `sitemap.xml` byte for byte, which is the property the file exists to have.

Both are day-granular build stamps, and forcing byte equality on them would make
the check fail for a reason that is not drift. Everything else is exact: the
corpus index, the config bundle, every ES module, the shell, the 52 rendered
pages, the theme assets, the search index and all seven audit artifacts.

Vacuity is the failure mode a check like this is most exposed to, so four things
are refused outright instead of being reported as a pass:

  * a build tree below the file floor, because a sentinel that compares nothing
    and prints OK is worse than no sentinel at all (`--minimum`);
  * a build tree in which neither excluded file is present, which would mean the
    two exclusions above had silently become the whole story;
  * any fetch that does not return HTTP 200, an unreachable host included;
  * an origin that answers a guaranteed-missing path with anything but 404,
    which is how a catch-all would make every matching comparison meaningless.

Exit codes: 0 the live site is the built site, 1 it is not, 4 the check could
not run.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import http.client
import re
import secrets
import ssl
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

REPO = Path(__file__).resolve().parents[1]

LIVE_URL = "https://sprout.chelseakr.com/"

# The floor under the comparison set. 129 files are published today.
MINIMUM_FILES = 100

# The two files mkdocs stamps with the build date. See the note above.
SITEMAP = "sitemap.xml"
SITEMAP_GZ = "sitemap.xml.gz"
LASTMOD = re.compile(rb"\s*<lastmod>[^<]*</lastmod>")

MAXIMUM_FILE_BYTES = 16 * 1024 * 1024
EXIT_DIFFERS = 1
EXIT_CANNOT_RUN = 4


class LiveSiteError(RuntimeError):
    """The live site could not be verified against this checkout."""


@dataclass(frozen=True)
class Response:
    status: int
    body: bytes


class Origin:
    """Bounded HTTPS reads from one fixed public origin. Redirects are not followed."""

    def __init__(self, url: str, *, timeout_seconds: float) -> None:
        parts = urlsplit(url)
        if parts.scheme != "https" or not parts.hostname or parts.query or parts.fragment:
            raise LiveSiteError(f"live URL {url!r} is not a canonical HTTPS origin")
        if not 1.0 <= timeout_seconds <= 60.0:
            raise LiveSiteError("timeout must be between 1 and 60 seconds")
        self.host = parts.hostname
        self.base = parts.path.rstrip("/")
        self.url = url
        self._timeout = timeout_seconds

    def target(self, relative: str, nonce: str) -> str:
        if relative.startswith("/") or "?" in relative or "#" in relative:
            raise LiveSiteError(f"relative path {relative!r} is not canonical")
        return f"{self.base}/{relative}?live-integrity={nonce}"

    def get(
        self,
        relative: str,
        *,
        nonce: str,
        maximum_bytes: int = MAXIMUM_FILE_BYTES,
    ) -> Response:
        target = self.target(relative, nonce)
        # The audit rule below is about HTTPSConnection used without certificate
        # verification: Python before 3.4.3 did not verify by default. This call
        # passes ssl.create_default_context(), which verifies both the chain and
        # the hostname, and is the condition the rule exists to require.
        # nosemgrep: httpsconnection-detected
        connection = http.client.HTTPSConnection(
            self.host, timeout=self._timeout, context=ssl.create_default_context()
        )
        try:
            connection.request(
                "GET",
                target,
                headers={
                    "Accept-Encoding": "identity",
                    "Cache-Control": "no-cache, no-store, max-age=0",
                    "Pragma": "no-cache",
                    "User-Agent": "sprout-live-integrity/1",
                },
            )
            response = connection.getresponse()
            encoding = response.getheader("Content-Encoding")
            if encoding not in {None, "identity"}:
                raise LiveSiteError(f"{target} came back {encoding}-encoded, not identity")
            body = response.read(maximum_bytes + 1)
            if len(body) > maximum_bytes:
                raise LiveSiteError(f"{target} exceeds the {maximum_bytes} byte read limit")
            return Response(status=response.status, body=body)
        except (OSError, http.client.HTTPException) as exc:
            raise LiveSiteError(f"GET https://{self.host}{target} failed: {exc}") from exc
        finally:
            connection.close()


def short(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()[:16]


def built_inventory(root: Path) -> dict[str, bytes]:
    """Every file the deploy uploads, keyed by the path it is served at."""
    if not root.is_dir():
        raise LiveSiteError(
            f"{root} is not a directory. Build it the way pages.yml does before "
            f"running this: sprout ingest, export_web_bundle.py, "
            f"npm run build:site --prefix web-static, mkdocs build --strict, "
            f"then cp -R web-static/public/. site/"
        )
    inventory: dict[str, bytes] = {}
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise LiveSiteError(f"{path} is a symlink; refusing to publish-compare it")
        if not path.is_file():
            continue
        inventory[path.relative_to(root).as_posix()] = path.read_bytes()
    return inventory


def prove_the_origin_discriminates(origin: Origin, nonce: str) -> None:
    """A host that answers everything with 200 makes every comparison vacuous."""
    missing = f".live-integrity-guaranteed-absent-{nonce}"
    response = origin.get(missing, nonce=nonce, maximum_bytes=1024 * 1024)
    if response.status != 404:
        raise LiveSiteError(
            f"the origin answered a guaranteed-missing path with HTTP {response.status} "
            f"instead of 404, so a matching fetch would prove nothing: /{missing}"
        )


def compare(origin: Origin, inventory: dict[str, bytes], nonce: str) -> list[str]:
    differences: list[str] = []
    live_sitemap: bytes | None = None
    for relative, expected in sorted(inventory.items()):
        if relative == SITEMAP_GZ:
            continue
        response = origin.get(relative, nonce=nonce)
        if response.status != 200:
            differences.append(
                f"{relative}: the live origin returned HTTP {response.status}; "
                f"this checkout builds {len(expected)} bytes"
            )
            continue
        if relative == SITEMAP:
            live_sitemap = response.body
            live = LASTMOD.sub(b"", response.body)
            expected = LASTMOD.sub(b"", expected)
            label = " (with the build-stamped lastmod elements removed)"
        else:
            live = response.body
            label = ""
        if live != expected:
            differences.append(
                f"{relative}{label}: live sha256 {short(live)} ({len(live)} bytes) is "
                f"not the built {short(expected)} ({len(expected)} bytes)"
            )
    differences.extend(compare_sitemap_gz(origin, nonce, live_sitemap))
    index = inventory.get("index.html")
    if index is not None:
        root = origin.get("", nonce=nonce)
        if root.status != 200:
            differences.append(f"/: the live origin returned HTTP {root.status}")
        elif root.body != index:
            differences.append(
                f"/: live sha256 {short(root.body)} is not the built index.html {short(index)}"
            )
    return differences


def compare_sitemap_gz(origin: Origin, nonce: str, live_sitemap: bytes | None) -> list[str]:
    """The gzip is checked for what it is for: decompressing to the sitemap."""
    if live_sitemap is None:
        return [f"{SITEMAP} was never fetched, so {SITEMAP_GZ} cannot be checked against it"]
    response = origin.get(SITEMAP_GZ, nonce=nonce)
    if response.status != 200:
        return [f"{SITEMAP_GZ}: the live origin returned HTTP {response.status}"]
    try:
        decompressed = gzip.decompress(response.body)
    except (OSError, EOFError) as exc:
        return [f"{SITEMAP_GZ}: the live bytes do not decompress ({exc})"]
    if decompressed != live_sitemap:
        return [
            f"{SITEMAP_GZ}: decompresses to sha256 {short(decompressed)}, which is not "
            f"the live {SITEMAP} {short(live_sitemap)}"
        ]
    return []


def refuse_an_empty_comparison(count: int, minimum: int, what: str) -> None:
    """A check that compares nothing must fail, not pass."""
    if count < minimum:
        raise LiveSiteError(
            f"{what} holds {count} file(s), below the floor of {minimum}. "
            f"A check that compares nothing must fail, not pass."
        )


def refuse_unbounded_options(parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    """Bounds on the knobs, so a typo cannot quietly turn the check into nothing."""
    if not 1 <= args.attempts <= 10:
        parser.error("--attempts must be between 1 and 10")
    if not 0 <= args.retry_seconds <= 120:
        parser.error("--retry-seconds must be between 0 and 120")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--site", default="site", help="the built tree to compare (default site)")
    parser.add_argument("--url", default=LIVE_URL, help=f"live site root (default {LIVE_URL})")
    parser.add_argument("--timeout-seconds", type=float, default=20.0)
    parser.add_argument(
        "--minimum",
        type=int,
        default=MINIMUM_FILES,
        help="refuse to pass on fewer built files than this",
    )
    parser.add_argument(
        "--attempts",
        type=int,
        default=3,
        help="how many times to look before reporting a difference (default 3)",
    )
    parser.add_argument(
        "--retry-seconds",
        type=float,
        default=20.0,
        help="seconds to wait between attempts, for a deploy to settle (default 20)",
    )
    args = parser.parse_args(argv)
    refuse_unbounded_options(parser, args)

    last_error: LiveSiteError | None = None
    differences: list[str] = []
    for attempt in range(1, args.attempts + 1):
        last_error = None
        try:
            root = Path(args.site)
            if not root.is_absolute():
                root = REPO / root
            inventory = built_inventory(root)
            refuse_an_empty_comparison(len(inventory), args.minimum, "the built tree")
            excluded = {name for name in (SITEMAP, SITEMAP_GZ) if name in inventory}
            if not excluded:
                raise LiveSiteError(
                    f"neither {SITEMAP} nor {SITEMAP_GZ} is in the built tree, so the two "
                    f"documented exclusions no longer describe this build. Re-read them "
                    f"before trusting what is left."
                )
            origin = Origin(args.url, timeout_seconds=args.timeout_seconds)
            nonce = secrets.token_hex(16)
            prove_the_origin_discriminates(origin, nonce)
            differences = compare(origin, inventory, nonce)
        except LiveSiteError as exc:
            last_error = exc
            differences = []
        if last_error is None and not differences:
            break
        if attempt < args.attempts:
            reason = last_error if last_error else f"{len(differences)} difference(s)"
            print(
                f"attempt {attempt}/{args.attempts}: {reason}; waiting "
                f"{args.retry_seconds:.0f}s in case a deploy is still settling",
                file=sys.stderr,
            )
            time.sleep(args.retry_seconds)
    if last_error is not None:
        print(f"live integrity check could not run: {last_error}", file=sys.stderr)
        return EXIT_CANNOT_RUN

    if differences:
        print(f"The live site at {origin.url} is not what this checkout builds.", file=sys.stderr)
        for difference in differences:
            print(f"  {difference}", file=sys.stderr)
        print(
            "\nRe-run docs-pages to publish this commit, or find out why the "
            "deployment is behind main.",
            file=sys.stderr,
        )
        return EXIT_DIFFERS

    total = sum(len(payload) for payload in inventory.values())
    print(
        f"{origin.url} serves exactly what this checkout builds: {len(inventory)} "
        f"file(s), {total} bytes. {SITEMAP} was compared without its build-stamped "
        f"lastmod elements and {SITEMAP_GZ} was checked by decompressing it, both "
        f"for the reasons in this file's header."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
