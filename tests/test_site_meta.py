"""The published site's metadata gate, and the description hook that feeds it.

Every check here breaks one property of a known-good tree and asserts the gate
notices. A gate that cannot fail is not a gate, and this file is what says these
can.
"""

from __future__ import annotations

import importlib.util
import json
import re
from pathlib import Path
from typing import Any

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

_SD = importlib.util.spec_from_file_location(
    "structured_data",
    Path(__file__).resolve().parent.parent / "docs_hooks" / "structured_data.py",
)
assert _SD is not None and _SD.loader is not None
structured_data = importlib.util.module_from_spec(_SD)
_SD.loader.exec_module(structured_data)


def _ld(title: str, description: str, url: str) -> str:
    """The structured-data block a good page carries, built from that page.

    Written as a function of the same three values the tags are built from, so a
    test that changes one of them and expects a complaint has to say which side
    it changed. A fixture that wrote the node independently would let both sides
    drift together and still pass, which is the defect the gate exists to catch.
    """
    payload = {
        "@context": "https://schema.org",
        "@graph": [
            {
                "@type": "WebSite",
                "@id": f"{_ORIGIN}/#website",
                "url": f"{_ORIGIN}/",
                "name": "Sprout",
            },
            {
                "@type": "WebPage",
                "@id": f"{url}#webpage",
                "url": url,
                "name": title,
                "description": description,
                "isPartOf": {"@id": f"{_ORIGIN}/#website"},
            },
        ],
    }
    return f'<script type="application/ld+json">{json.dumps(payload)}</script>'


def _page(title: str, description: str, url: str, *, social: bool = True) -> str:
    tags = [
        '<meta charset="utf-8">',
        f"<title>{title}</title>",
        f'<meta name="description" content="{description}">',
        f'<link rel="canonical" href="{url}">',
        _ld(title, description, url),
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


# --- Card images -----------------------------------------------------------------------------
#
# The root page carries an og:image now, and the tag's whole job is done by a machine that
# fetches the URL once and caches whatever came back. Every way that can go wrong is silent on
# the page itself, so each one is broken here and asserted against.

_CARD = f"{_ORIGIN}/og.png"
_CARD_TAGS = (
    f'<meta property="og:image" content="{_CARD}">'
    '<meta property="og:image:alt" content="A card.">'
    f'<meta name="twitter:image" content="{_CARD}">'
    '<meta name="twitter:image:alt" content="A card.">'
)


def _with_card(site: Path, tags: str = _CARD_TAGS, *, publish: bool = True) -> Path:
    """Give the home page a card, optionally without publishing the file it names."""
    if publish:
        (site / "og.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    page = site / "index.html"
    page.write_text(page.read_text(encoding="utf-8").replace("</head>", tags + "</head>"), "utf-8")
    return page


def test_a_published_card_image_passes(site: Path) -> None:
    _with_card(site)
    assert check_site(site, _ORIGIN) == []


def test_a_card_naming_a_file_the_build_did_not_write_is_reported(site: Path) -> None:
    _with_card(site, publish=False)
    problems = check_site(site, _ORIGIN)
    assert any("this build did not write" in p for p in problems)
    assert any("unfurl empty" in p for p in problems)


def test_a_relative_card_image_is_reported(site: Path) -> None:
    _with_card(
        site,
        '<meta property="og:image" content="og.png">'
        '<meta property="og:image:alt" content="A card.">',
    )
    problems = check_site(site, _ORIGIN)
    assert any("not an absolute URL" in p for p in problems)
    assert any("resolves against the site doing the sharing" in p for p in problems)


def test_a_card_image_on_another_origin_is_reported(site: Path) -> None:
    _with_card(
        site,
        '<meta property="og:image" content="https://cdn.example/og.png">'
        '<meta property="og:image:alt" content="A card.">',
    )
    assert any("not an absolute URL" in p for p in check_site(site, _ORIGIN))


def test_a_card_image_without_alt_text_is_reported(site: Path) -> None:
    _with_card(site, f'<meta property="og:image" content="{_CARD}">')
    assert any("og:image is declared with no og:image:alt" in p for p in check_site(site, _ORIGIN))


def test_a_card_image_with_empty_alt_text_is_reported(site: Path) -> None:
    _with_card(
        site,
        f'<meta property="og:image" content="{_CARD}"><meta property="og:image:alt" content="   ">',
    )
    assert any("no og:image:alt" in p for p in check_site(site, _ORIGIN))


def test_a_page_with_no_card_image_is_still_fine(site: Path) -> None:
    """The gate asks for a card image where one is claimed, not everywhere.

    The mkdocs-rendered documentation pages declare no social tags at all, and this
    check must not start failing them by implication.
    """
    assert check_site(site, _ORIGIN) == []


# --- Links. Every same-site address a page publishes must lead somewhere. -------------
#
# The defect this section pins shipped to the live site and left no mark on the page
# carrying it: the docs are written to be read in the repository, where
# `../src/sprout/answer.py` resolves from `docs/`, and are published at `/ARCHITECTURE/`,
# where the same link addresses a path the site does not serve. Twenty-five such links
# were live at once, and every gate the project had was green.


def _links(site: Path, markup: str, *, page: str = "docs/index.html") -> None:
    """Put `markup` in the body of a published page, leaving its head alone."""
    target = site / page
    target.write_text(
        target.read_text(encoding="utf-8").replace("</body>", f"{markup}</body>"),
        encoding="utf-8",
    )


def test_a_link_to_a_published_page_passes(site: Path) -> None:
    _links(site, '<a href="../">Home</a>')
    assert check_site(site, _ORIGIN) == []


def test_a_relative_link_that_escapes_the_published_tree_is_reported(site: Path) -> None:
    """The live defect, exactly: a repository path published as a site path."""
    _links(site, '<a href="../src/sprout/answer.py">answer.py</a>')
    problems = check_site(site, _ORIGIN)
    assert any("links '../src/sprout/answer.py'" in p for p in problems)


def test_a_root_relative_link_to_a_file_the_build_did_not_write_is_reported(
    site: Path,
) -> None:
    _links(site, '<a href="/ACCESSIBILITY.md">Accessibility</a>')
    assert any("links '/ACCESSIBILITY.md'" in p for p in check_site(site, _ORIGIN))


def test_a_link_to_a_directory_with_no_index_is_reported(site: Path) -> None:
    """A directory answers on its index.html; without one the address is a 404."""
    (site / "reference").mkdir()
    (site / "reference" / "notes.txt").write_text("", encoding="utf-8")
    _links(site, '<a href="/reference/">Reference</a>')
    assert any("links '/reference/'" in p for p in check_site(site, _ORIGIN))


def test_a_link_written_against_this_origin_in_full_is_checked_like_a_relative_one(
    site: Path,
) -> None:
    _links(site, f'<a href="{_ORIGIN}/nowhere/">Nowhere</a>')
    assert any("links '/nowhere/'" in p for p in check_site(site, _ORIGIN))


def test_an_address_on_another_site_is_not_this_gate_s_business(site: Path) -> None:
    """Reaching off-site to check a link would make this gate need a network."""
    _links(site, '<a href="https://github.com/ChelseaKR/sprout/blob/main/src/x.py">x</a>')
    assert check_site(site, _ORIGIN) == []


def test_a_fragment_query_or_mail_address_is_not_a_file(site: Path) -> None:
    _links(site, '<a href="#section">S</a><a href="?q=1">Q</a><a href="mailto:a@b.c">M</a>')
    assert check_site(site, _ORIGIN) == []


def test_an_href_inside_a_script_body_is_not_read_as_a_link(site: Path) -> None:
    """Script bodies carry template strings; a gate reading them invents failures."""
    _links(site, "<script>var t = '<a href=\"../src/nope.py\">x</a>';</script>")
    assert check_site(site, _ORIGIN) == []


def test_an_image_or_stylesheet_the_build_did_not_write_is_reported(site: Path) -> None:
    _links(site, '<img src="/assets/missing.png" alt="">')
    assert any("links '/assets/missing.png'" in p for p in check_site(site, _ORIGIN))


def test_a_tree_whose_pages_link_nothing_says_the_sweep_read_nothing(site: Path) -> None:
    """A sweep with no input passes forever, and its green means nothing.

    This is the check on the check: strip every address out of the tree and the
    gate must say it read nothing rather than reporting no problems.
    """
    for page in site.rglob("*.html"):
        page.write_text(
            re.sub(r"\b(?:href|src)=", "data-was=", page.read_text(encoding="utf-8")),
            encoding="utf-8",
        )
    assert any("the link sweep read nothing" in p for p in check_site(site, _ORIGIN))


# --- structured data -------------------------------------------------------
#
# Every test below breaks one property of a page that states what it is, and
# asserts the gate says so. The block is the one surface on a published page no
# human reviewer ever looks at, so "somebody would notice" is not available as a
# defence: if the gate does not catch it, nothing does.


def _replace_ld(site: Path, page: str, block: str) -> Path:
    """Swap a page's structured-data block for `block` (or remove it if empty)."""
    target = site / page
    doc = target.read_text(encoding="utf-8")
    found = re.search(r'<script type="application/ld\+json">.*?</script>', doc, re.DOTALL)
    assert found is not None, f"{page} carries no block to replace"
    target.write_text(doc.replace(found.group(0), block), encoding="utf-8")
    return site


def _graph_of(site: Path, page: str) -> dict[str, Any]:
    doc = (site / page).read_text(encoding="utf-8")
    found = re.search(r'<script type="application/ld\+json">(.*?)</script>', doc, re.DOTALL)
    assert found is not None
    payload: dict[str, Any] = json.loads(found.group(1))
    return payload


def _rewrite_graph(site: Path, page: str, payload: dict[str, Any]) -> Path:
    return _replace_ld(
        site, page, f'<script type="application/ld+json">{json.dumps(payload)}</script>'
    )


def test_a_page_that_states_nothing_about_itself_is_reported(site: Path) -> None:
    _replace_ld(site, "docs/index.html", "")
    problems = check_site(site, _ORIGIN)
    assert any("carries no application/ld+json block" in problem for problem in problems)


def test_a_page_making_two_statements_about_itself_is_reported(site: Path) -> None:
    doc = (site / "docs" / "index.html").read_text(encoding="utf-8")
    found = re.search(r'<script type="application/ld\+json">.*?</script>', doc, re.DOTALL)
    assert found is not None
    (site / "docs" / "index.html").write_text(
        doc.replace(found.group(0), found.group(0) * 2), encoding="utf-8"
    )
    assert any("2 ld+json blocks" in problem for problem in check_site(site, _ORIGIN))


def test_a_block_that_is_not_valid_json_is_reported(site: Path) -> None:
    _replace_ld(site, "docs/index.html", '<script type="application/ld+json">{,}</script>')
    assert any("not valid JSON" in problem for problem in check_site(site, _ORIGIN))


def test_a_block_in_some_other_vocabulary_is_reported(site: Path) -> None:
    # `http://schema.org` is the commonest way this goes wrong and the hardest
    # to see: it is one character from correct and consumers simply drop it.
    payload = _graph_of(site, "docs/index.html")
    payload["@context"] = "http://schema.org"
    _rewrite_graph(site, "docs/index.html", payload)
    assert any("@context" in problem for problem in check_site(site, _ORIGIN))


def test_an_unexpected_node_type_is_reported(site: Path) -> None:
    payload = _graph_of(site, "docs/index.html")
    payload["@graph"].append({"@type": "Recipe", "@id": f"{_ORIGIN}/docs/#recipe"})
    _rewrite_graph(site, "docs/index.html", payload)
    assert any("unexpected node type" in problem for problem in check_site(site, _ORIGIN))


def test_a_dataset_node_is_refused(site: Path) -> None:
    # The one test here that is about a decision rather than a mistake.
    #
    # A `Dataset` descriptor is not a description of a page, it is a request:
    # it exists so that dataset search engines and open-data catalogs harvest
    # what it names and list it as a dataset of record, and a listing is far
    # easier to acquire than to withdraw. Whether this project should solicit
    # that over its corpus is an open question with an owner's name on it. This
    # keeps the difference a decision somebody makes rather than a line somebody
    # adds during an unrelated change.
    payload = _graph_of(site, "docs/index.html")
    payload["@graph"].append({"@type": "Dataset", "@id": f"{_ORIGIN}/docs/#data", "name": "Corpus"})
    _rewrite_graph(site, "docs/index.html", payload)
    assert any("solicits dataset harvest" in problem for problem in check_site(site, _ORIGIN))


def test_harvest_vocabulary_is_refused_even_without_a_dataset_node(site: Path) -> None:
    # DCAT reaches the same catalogs by another road, and does it with a `@type`
    # this gate's allow-list would wave through.
    payload = _graph_of(site, "docs/index.html")
    payload["@graph"][1]["dcat:distribution"] = f"{_ORIGIN}/corpus.json"
    _rewrite_graph(site, "docs/index.html", payload)
    assert any("Harvest vocabulary" in problem for problem in check_site(site, _ORIGIN))


def test_a_node_naming_another_pages_address_is_reported(site: Path) -> None:
    payload = _graph_of(site, "docs/index.html")
    payload["@graph"][1]["url"] = f"{_ORIGIN}/"
    _rewrite_graph(site, "docs/index.html", payload)
    assert any("but it answers on" in problem for problem in check_site(site, _ORIGIN))


def test_a_node_describing_the_page_differently_is_reported(site: Path) -> None:
    payload = _graph_of(site, "docs/index.html")
    payload["@graph"][1]["description"] = "Something the page does not say."
    _rewrite_graph(site, "docs/index.html", payload)
    assert any(
        "not the page's meta description" in problem for problem in check_site(site, _ORIGIN)
    )


def test_a_node_naming_the_page_something_else_is_reported(site: Path) -> None:
    payload = _graph_of(site, "docs/index.html")
    payload["@graph"][1]["name"] = "Some other page"
    _rewrite_graph(site, "docs/index.html", payload)
    assert any("which is not how its <title>" in problem for problem in check_site(site, _ORIGIN))


def test_a_reference_to_a_node_that_is_not_there_is_reported(site: Path) -> None:
    # A dangling `@id` is the quietest failure available: consumers drop the
    # reference without complaint, so the page reads as described and is not.
    payload = _graph_of(site, "docs/index.html")
    payload["@graph"][1]["isPartOf"] = {"@id": f"{_ORIGIN}/#nothing"}
    _rewrite_graph(site, "docs/index.html", payload)
    assert any(
        "which this graph does not define" in problem for problem in check_site(site, _ORIGIN)
    )


def test_an_empty_property_is_reported(site: Path) -> None:
    payload = _graph_of(site, "docs/index.html")
    payload["@graph"][0]["name"] = "  "
    _rewrite_graph(site, "docs/index.html", payload)
    assert any("is empty" in problem for problem in check_site(site, _ORIGIN))


def test_a_missing_web_page_node_is_reported(site: Path) -> None:
    payload = _graph_of(site, "docs/index.html")
    payload["@graph"] = [payload["@graph"][0]]
    _rewrite_graph(site, "docs/index.html", payload)
    assert any("0 WebPage nodes" in problem for problem in check_site(site, _ORIGIN))


def test_a_trail_that_ends_somewhere_else_is_reported(site: Path) -> None:
    payload = _graph_of(site, "docs/index.html")
    payload["@graph"][1]["breadcrumb"] = {"@id": f"{_ORIGIN}/docs/#breadcrumb"}
    payload["@graph"].append(
        {
            "@type": "BreadcrumbList",
            "@id": f"{_ORIGIN}/docs/#breadcrumb",
            "itemListElement": [
                {"@type": "ListItem", "position": 1, "name": "Home", "item": f"{_ORIGIN}/"},
            ],
        }
    )
    _rewrite_graph(site, "docs/index.html", payload)
    assert any("rather than at this page" in problem for problem in check_site(site, _ORIGIN))


def test_a_trail_through_a_page_the_build_did_not_write_is_reported(site: Path) -> None:
    # The same defect as a dead link, with none of a dead link's symptoms: no
    # reader clicks a breadcrumb in a script block, so nothing ever reports it.
    payload = _graph_of(site, "docs/index.html")
    payload["@graph"][1]["breadcrumb"] = {"@id": f"{_ORIGIN}/docs/#breadcrumb"}
    payload["@graph"].append(
        {
            "@type": "BreadcrumbList",
            "@id": f"{_ORIGIN}/docs/#breadcrumb",
            "itemListElement": [
                {"@type": "ListItem", "position": 1, "name": "Home", "item": f"{_ORIGIN}/"},
                {
                    "@type": "ListItem",
                    "position": 2,
                    "name": "Gone",
                    "item": f"{_ORIGIN}/gone/",
                },
                {"@type": "ListItem", "position": 3, "name": "Docs", "item": f"{_ORIGIN}/docs/"},
            ],
        }
    )
    _rewrite_graph(site, "docs/index.html", payload)
    assert any("this build did not write" in problem for problem in check_site(site, _ORIGIN))


def test_a_trail_numbered_out_of_order_is_reported(site: Path) -> None:
    payload = _graph_of(site, "docs/index.html")
    payload["@graph"][1]["breadcrumb"] = {"@id": f"{_ORIGIN}/docs/#breadcrumb"}
    payload["@graph"].append(
        {
            "@type": "BreadcrumbList",
            "@id": f"{_ORIGIN}/docs/#breadcrumb",
            "itemListElement": [
                {"@type": "ListItem", "position": 5, "name": "Home", "item": f"{_ORIGIN}/"},
                {"@type": "ListItem", "position": 2, "name": "Docs", "item": f"{_ORIGIN}/docs/"},
            ],
        }
    )
    _rewrite_graph(site, "docs/index.html", payload)
    assert any("claims position" in problem for problem in check_site(site, _ORIGIN))


def test_an_ampersand_in_a_title_is_not_a_disagreement(tmp_path: Path) -> None:
    """A correct page whose words contain markup characters must pass.

    This is a regression test for a real bug in the first version of this gate,
    found by running it over the real site: the tags carry HTML and the node
    carries text, so a page titled `Personas & Interviews` renders
    `Personas &amp; Interviews` in its `<title>` and holds `Personas &
    Interviews` in its node. Compared raw, seventeen pages failed for being
    right, which is a worse gate than none — the only way to pass it would have
    been to put markup into the node, where it means nothing.
    """
    root = tmp_path / "site"
    root.mkdir()
    title = "Personas &amp; Interviews"
    description = "Synthetic personas &amp; simulated interviews, and what they cannot show."
    url = f"{_ORIGIN}/"
    payload = {
        "@context": "https://schema.org",
        "@graph": [
            {"@type": "WebSite", "@id": f"{_ORIGIN}/#website", "url": url, "name": "Sprout"},
            {
                "@type": "WebPage",
                "@id": f"{url}#webpage",
                "url": url,
                "name": "Personas & Interviews",
                "description": (
                    "Synthetic personas & simulated interviews, and what they cannot show."
                ),
                "isPartOf": {"@id": f"{_ORIGIN}/#website"},
            },
        ],
    }
    block = f'<script type="application/ld+json">{json.dumps(payload)}</script>'
    (root / "index.html").write_text(
        f'<!doctype html><html lang="en"><head><title>{title}</title>'
        f'<meta name="description" content="{description}">'
        f'<link rel="canonical" href="{url}">{block}</head><body></body></html>',
        encoding="utf-8",
    )
    (root / "robots.txt").write_text(
        f"User-agent: *\nAllow: /\n\nSitemap: {_ORIGIN}/sitemap.xml\n", encoding="utf-8"
    )
    (root / "sitemap.xml").write_text(
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        f"<url><loc>{_ORIGIN}/</loc></url></urlset>",
        encoding="utf-8",
    )
    assert [p for p in check_site(root, _ORIGIN) if "ld+json" in p] == []


# --- the hook that writes it ----------------------------------------------


class _Config:
    site_url = "https://sprout.example/"
    site_name = "Sprout"
    site_description = "A grounded, evaluated, multilingual plant-care assistant."
    repo_url = "https://github.com/ChelseaKR/sprout"


class _Section:
    def __init__(self, title: str) -> None:
        self.title = title


class _Page:
    def __init__(
        self,
        title: str,
        url: str,
        ancestors: list[_Section] | None = None,
        home: bool = False,
    ) -> None:
        self.title = title
        self.canonical_url = url
        self.ancestors = ancestors or []
        self.is_homepage = home
        self.meta = {"description": "What this page says, in its own opening words."}


def test_the_hook_takes_every_value_from_the_page(tmp_path: Path) -> None:
    page = _Page("Architecture", "https://sprout.example/ARCHITECTURE/")
    graph = structured_data.graph(page, _Config(), "en")
    nodes = {node["@type"]: node for node in graph["@graph"]}
    assert graph["@context"] == "https://schema.org"
    assert nodes["WebPage"]["name"] == "Architecture"
    assert nodes["WebPage"]["url"] == "https://sprout.example/ARCHITECTURE/"
    assert nodes["WebPage"]["description"] == page.meta["description"]
    assert nodes["WebSite"]["name"] == _Config.site_name
    assert nodes["SoftwareApplication"]["sameAs"] == _Config.repo_url


def test_the_hook_decodes_what_the_page_escaped(tmp_path: Path) -> None:
    page = _Page("Personas &amp; Interviews", "https://sprout.example/x/")
    page.meta["description"] = "Personas &amp; interviews."
    nodes = {n["@type"]: n for n in structured_data.graph(page, _Config(), "en")["@graph"]}
    assert nodes["WebPage"]["name"] == "Personas & Interviews"
    assert nodes["WebPage"]["description"] == "Personas & interviews."


def test_the_hook_builds_the_trail_from_the_nav(tmp_path: Path) -> None:
    page = _Page("Statement", "https://sprout.example/a11y/STATEMENT/", [_Section("Accessibility")])
    nodes = {n["@type"]: n for n in structured_data.graph(page, _Config(), "en")["@graph"]}
    trail = nodes["BreadcrumbList"]["itemListElement"]
    assert [item["name"] for item in trail] == ["Home", "Accessibility", "Statement"]
    # A nav section has no address of its own, and saying so is more honest than
    # inventing one for it.
    assert "item" not in trail[1]
    assert trail[-1]["item"] == page.canonical_url


def test_the_home_page_gets_no_trail_to_itself(tmp_path: Path) -> None:
    page = _Page("Sprout", "https://sprout.example/", home=True)
    types = {n["@type"] for n in structured_data.graph(page, _Config(), "en")["@graph"]}
    assert "BreadcrumbList" not in types


def test_the_hook_emits_no_dataset_node(tmp_path: Path) -> None:
    page = _Page("Data card", "https://sprout.example/cards/data-card-corpus/")
    payload = structured_data.graph(page, _Config(), "en")
    types = {node["@type"] for node in payload["@graph"]}
    assert types.isdisjoint({"Dataset", "DataCatalog", "DataDownload", "DataFeed"})
    assert "dcat" not in json.dumps(payload)


def test_the_block_cannot_end_its_own_element(tmp_path: Path) -> None:
    # `</script` inside a JSON string closes the element as far as an HTML
    # parser is concerned, whatever JSON thinks of it.
    page = _Page("Hostile", "https://sprout.example/x/")
    page.meta["description"] = "A description holding </script><img src=x> and an & sign."
    rendered = structured_data.block(structured_data.graph(page, _Config(), "en"))
    assert "</script" not in rendered
    assert "<" not in rendered and ">" not in rendered
    assert json.loads(rendered)["@graph"][1]["description"] == page.meta["description"]


def test_a_file_picker_is_not_structured_data(site: Path) -> None:
    """The string `application/ld+json` on a page is not a node on it.

    This is the trap the portfolio audit that asked for this markup fell into:
    it scored a sibling project as carrying structured data because that string
    appeared in its HTML, and the single occurrence turned out to be the
    `accept` attribute of an `<input type="file">`. A sweep that counts a string
    scores an upload widget as a schema.org node — and, in the other direction,
    misses a real node written with unusual spacing. So the gate reads the
    element and its `type`, and this holds it to that.
    """
    _replace_ld(
        site,
        "docs/index.html",
        '<input type="file" accept="application/ld+json,application/json">',
    )
    problems = check_site(site, _ORIGIN)
    assert any("carries no application/ld+json block" in problem for problem in problems)


def test_a_node_written_with_unusual_spacing_is_still_found(site: Path) -> None:
    """And the other direction: whitespace in the type attribute is not a defect."""
    payload = _graph_of(site, "docs/index.html")
    _replace_ld(
        site,
        "docs/index.html",
        f"<script  type = 'application/ld+json' >{json.dumps(payload)}</script >",
    )
    assert [p for p in check_site(site, _ORIGIN) if "ld+json" in p] == []
