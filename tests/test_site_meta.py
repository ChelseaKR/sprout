"""The published site's metadata gate, and the description hook that feeds it.

Every check here breaks one property of a known-good tree and asserts the gate
notices. A gate that cannot fail is not a gate, and this file is what says these
can.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from sprout.site_meta import check_site, page_url

_ORIGIN = "https://sprout.example"

_HOOK = importlib.util.spec_from_file_location(
    "page_description",
    Path(__file__).resolve().parent.parent / "docs_hooks" / "page_description.py",
)
assert _HOOK is not None and _HOOK.loader is not None
page_description = importlib.util.module_from_spec(_HOOK)
_HOOK.loader.exec_module(page_description)


def _page(title: str, description: str, url: str, *, social: bool = True) -> str:
    tags = [
        '<meta charset="utf-8">',
        f"<title>{title}</title>",
        f'<meta name="description" content="{description}">',
        f'<link rel="canonical" href="{url}">',
    ]
    if social:
        tags += [
            '<meta property="og:type" content="website">',
            '<meta property="og:site_name" content="Sprout">',
            f'<meta property="og:url" content="{url}">',
            f'<meta property="og:title" content="{title}">',
            f'<meta property="og:description" content="{description}">',
            '<meta name="twitter:card" content="summary">',
            f'<meta name="twitter:title" content="{title}">',
            f'<meta name="twitter:description" content="{description}">',
        ]
    body = "".join(tags)
    return f'<!doctype html><html lang="en"><head>{body}</head><body><h1>{title}</h1></body></html>'


@pytest.fixture
def site(tmp_path: Path) -> Path:
    """A small published tree with nothing wrong with it."""
    root = tmp_path / "site"
    (root / "docs").mkdir(parents=True)
    (root / "index.html").write_text(
        _page("Home", "What this site is.", f"{_ORIGIN}/"), encoding="utf-8"
    )
    (root / "docs" / "index.html").write_text(
        _page("Docs", "How the pipeline is put together.", f"{_ORIGIN}/docs/"),
        encoding="utf-8",
    )
    (root / "robots.txt").write_text(
        f"User-agent: *\nAllow: /\n\nSitemap: {_ORIGIN}/sitemap.xml\n", encoding="utf-8"
    )
    (root / "sitemap.xml").write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        f"<url><loc>{_ORIGIN}/</loc></url>"
        f"<url><loc>{_ORIGIN}/docs/</loc></url>"
        "</urlset>\n",
        encoding="utf-8",
    )
    return root


def test_a_site_with_nothing_wrong_reports_nothing(site: Path) -> None:
    assert check_site(site, _ORIGIN) == []


def test_a_trailing_slash_on_the_origin_is_not_a_second_origin(site: Path) -> None:
    assert check_site(site, f"{_ORIGIN}/") == []


def test_the_root_page_is_addressed_as_the_root(site: Path) -> None:
    """A canonical naming index.html publishes a second address for one page."""
    assert page_url(_ORIGIN, site / "index.html", site) == f"{_ORIGIN}/"
    assert page_url(_ORIGIN, site / "docs" / "index.html", site) == f"{_ORIGIN}/docs/"


def test_a_missing_canonical_is_reported(site: Path) -> None:
    page = site / "docs" / "index.html"
    page.write_text(
        page.read_text(encoding="utf-8").replace('<link rel="canonical"', "<link rel="),
        encoding="utf-8",
    )
    assert any("no <link rel=canonical>" in p for p in check_site(site, _ORIGIN))


def test_a_canonical_pointing_somewhere_else_is_reported(site: Path) -> None:
    """This is the stale-origin case: a canonical left on the old address."""
    page = site / "docs" / "index.html"
    page.write_text(
        page.read_text(encoding="utf-8").replace(
            f'href="{_ORIGIN}/docs/"', 'href="https://chelseakr.github.io/sprout/docs/"'
        ),
        encoding="utf-8",
    )
    assert any("but the page answers on" in p for p in check_site(site, _ORIGIN))


def test_a_canonical_over_plain_http_is_reported(site: Path) -> None:
    root = site / "index.html"
    root.write_text(
        root.read_text(encoding="utf-8").replace(f"{_ORIGIN}/", "http://sprout.example/"),
        encoding="utf-8",
    )
    assert any("canonical" in p for p in check_site(site, _ORIGIN))


def test_two_pages_sharing_a_description_are_reported(site: Path) -> None:
    """The state this site shipped in: one site_description on every page."""
    page = site / "docs" / "index.html"
    page.write_text(
        page.read_text(encoding="utf-8").replace(
            "How the pipeline is put together.", "What this site is."
        ),
        encoding="utf-8",
    )
    assert any("share one description" in p for p in check_site(site, _ORIGIN))


def test_two_pages_sharing_a_title_are_reported(site: Path) -> None:
    page = site / "docs" / "index.html"
    page.write_text(page.read_text(encoding="utf-8").replace("Docs", "Home"), encoding="utf-8")
    assert any("share the title" in p for p in check_site(site, _ORIGIN))


def test_a_half_written_social_card_is_reported(site: Path) -> None:
    page = site / "docs" / "index.html"
    page.write_text(
        page.read_text(encoding="utf-8").replace(
            '<meta name="twitter:card" content="summary">', ""
        ),
        encoding="utf-8",
    )
    assert any("declares twitter:card nowhere" in p for p in check_site(site, _ORIGIN))


def test_a_card_that_says_something_the_page_does_not_is_reported(site: Path) -> None:
    page = site / "docs" / "index.html"
    page.write_text(
        page.read_text(encoding="utf-8").replace(
            '<meta property="og:title" content="Docs">',
            '<meta property="og:title" content="The best docs anywhere">',
        ),
        encoding="utf-8",
    )
    assert any("og:title does not match" in p for p in check_site(site, _ORIGIN))


def test_a_missing_robots_txt_is_reported(site: Path) -> None:
    (site / "robots.txt").unlink()
    assert any("robots.txt was not published" in p for p in check_site(site, _ORIGIN))


def test_robots_naming_a_path_the_site_does_not_serve_is_reported(site: Path) -> None:
    """The stale project path, which is what habitable's robots.txt had in it."""
    (site / "robots.txt").write_text(
        f"User-agent: *\nAllow: /sprout/\n\nSitemap: {_ORIGIN}/sitemap.xml\n",
        encoding="utf-8",
    )
    assert any("which this site does not serve" in p for p in check_site(site, _ORIGIN))


def test_a_missing_sitemap_is_reported(site: Path) -> None:
    (site / "sitemap.xml").unlink()
    assert any("sitemap.xml was not published" in p for p in check_site(site, _ORIGIN))


def test_a_sitemap_that_is_not_a_urlset_is_reported(site: Path) -> None:
    (site / "sitemap.xml").write_text("<html><body>oops</body></html>", encoding="utf-8")
    assert any("not a urlset" in p for p in check_site(site, _ORIGIN))


def test_a_urlset_that_lists_nothing_is_reported(site: Path) -> None:
    """An empty sitemap is not a passing one; it is a sitemap that says nothing."""
    (site / "sitemap.xml").write_text("<urlset></urlset>", encoding="utf-8")
    assert any("lists no URL at all" in p for p in check_site(site, _ORIGIN))


def test_a_sitemap_url_with_no_page_behind_it_is_reported(site: Path) -> None:
    sitemap = site / "sitemap.xml"
    sitemap.write_text(
        sitemap.read_text(encoding="utf-8").replace(
            "</urlset>", f"<url><loc>{_ORIGIN}/gone/</loc></url></urlset>"
        ),
        encoding="utf-8",
    )
    assert any("which this build did not write" in p for p in check_site(site, _ORIGIN))


def test_a_published_page_missing_from_the_sitemap_is_reported(site: Path) -> None:
    """The orphan case: the standalone eval report, published and listed nowhere."""
    (site / "report.html").write_text(
        _page("Report", "The run this build recorded.", f"{_ORIGIN}/report.html"),
        encoding="utf-8",
    )
    assert any("in neither the sitemap nor a noindex" in p for p in check_site(site, _ORIGIN))


def test_a_page_that_says_noindex_may_be_left_out_of_the_sitemap(site: Path) -> None:
    """It can be left out. It cannot be left out silently."""
    (site / "report.html").write_text(
        '<!doctype html><html lang="en"><head><meta name="robots" content="noindex">'
        "<title>Report</title></head><body><h1>Report</h1></body></html>",
        encoding="utf-8",
    )
    assert check_site(site, _ORIGIN) == []


def test_the_error_page_is_neither_indexed_nor_expected_in_the_sitemap(site: Path) -> None:
    """404.html is served in place of a missing page, never at its own address."""
    (site / "404.html").write_text(
        '<!doctype html><html lang="en"><head><title>Not found</title></head>'
        "<body><h1>Not found</h1></body></html>",
        encoding="utf-8",
    )
    assert check_site(site, _ORIGIN) == []


def test_an_empty_tree_says_it_checked_nothing(tmp_path: Path) -> None:
    """A gate that runs over nothing must not report success for having done so."""
    (tmp_path / "empty").mkdir()
    assert check_site(tmp_path / "empty", _ORIGIN) == [
        f"{tmp_path / 'empty'} holds no indexable page, so this checked nothing"
    ]


# ----------------------------------------------------------------------------------
# The description hook
# ----------------------------------------------------------------------------------


def test_a_page_gets_its_own_opening_paragraph() -> None:
    described = page_description.describe(
        "# Architecture\n\nSprout is extractive RAG with a post-generation citation "
        "guard, so groundedness is by construction rather than by hope.\n\nMore text.\n"
    )
    assert described.startswith("Sprout is extractive RAG")
    assert "More text" not in described


def test_a_paragraph_opening_on_bold_text_is_still_a_paragraph() -> None:
    """`**` at the start of a line is emphasis, not a bullet marker."""
    described = page_description.describe(
        "# Sprout\n\nA grounded assistant\n**and the harness** that holds it to "
        "account, which is the part worth reading.\n"
    )
    assert "and the harness" in described


def test_headings_lists_tables_and_code_are_not_prose() -> None:
    described = page_description.describe(
        "# Report\n\n| a | b |\n|---|---|\n| 1 | 2 |\n\n- a bullet point here\n\n"
        "```\nsome code\n```\n\n> The only sentence on this page that is a sentence.\n"
    )
    assert described == "The only sentence on this page that is a sentence."
    assert "bullet" not in described and "some code" not in described


def test_a_page_with_no_prose_at_all_falls_back_to_its_heading() -> None:
    described = page_description.describe("# Sprout smoke suite over the corpus\n\n| a |\n|---|\n")
    assert described == "Sprout smoke suite over the corpus"


def test_a_long_paragraph_is_trimmed_on_a_word_boundary() -> None:
    described = page_description.describe(f"# T\n\n{'word ' * 100}\n")
    assert len(described) <= page_description._LIMIT + 3
    assert described.endswith("...")
    assert "wor..." not in described


def test_a_page_that_declares_its_own_description_is_left_alone() -> None:
    class _Page:
        def __init__(self) -> None:
            self.meta = {"description": "Written by hand."}

    page = _Page()
    page_description.on_page_markdown(
        "# T\n\nSomething else entirely on the page.\n", page, None, None
    )
    assert page.meta["description"] == "Written by hand."


def test_a_quotation_mark_cannot_break_out_of_the_attribute() -> None:
    """Unescaped, an ADR quoting its own model card closed the attribute early."""

    class _Page:
        def __init__(self) -> None:
            self.meta: dict[str, str] = {}

    page = _Page()
    page_description.on_page_markdown(
        '# T\n\nThe model card says "add an NLI-grade verifier" and this ADR agrees.\n',
        page,
        None,
        None,
    )
    assert '"' not in page.meta["description"]
    assert "&quot;" in page.meta["description"]
