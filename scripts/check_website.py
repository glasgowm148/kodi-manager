"""Check the deployed static artifact, including links and search metadata."""

import json
import sys
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urljoin, urlsplit
from xml.etree import ElementTree as ET


class Page(HTMLParser):
    def __init__(self, text):
        super().__init__()
        self.links = []
        self.ids = set()
        self.canonicals = []
        self.descriptions = []
        self.h1_count = 0
        self.schema = []
        self.in_schema = False
        self.feed(text)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if attrs.get("id"):
            self.ids.add(attrs["id"])
        if tag == "h1":
            self.h1_count += 1
        if tag == "link" and attrs.get("rel") == "canonical":
            self.canonicals.append(attrs.get("href"))
        if tag == "meta" and attrs.get("name") == "description":
            self.descriptions.append(attrs.get("content"))
        if tag == "script":
            assert attrs.get("type") == "application/ld+json", "Unexpected executable script"
            self.in_schema = True
        if tag == "img":
            assert "alt" in attrs, "Image missing alt attribute"
        for attr in ("href", "src"):
            if attrs.get(attr):
                self.links.append(attrs[attr])

    def handle_endtag(self, tag):
        if tag == "script":
            self.in_schema = False

    def handle_data(self, data):
        if self.in_schema:
            self.schema.append(json.loads(data))


def check(root):
    root = Path(root).resolve()
    urls = [
        element.text
        for element in ET.parse(root / "sitemap.xml").iter()
        if element.tag.endswith("}loc")
    ]
    assert urls and len(urls) == len(set(urls)), "Missing or duplicate sitemap URLs"
    base = urls[0]
    assert base.startswith("https://glasgowm148.github.io/"), "Unexpected site origin"
    pages = {}
    titles = set()
    for path in sorted(root.rglob("*.html")):
        text = path.read_text(encoding="utf-8")
        page = Page(text)
        pages[path.resolve()] = page
        relative = path.relative_to(root).as_posix().removesuffix("index.html")
        expected = urljoin(base, relative)
        assert page.canonicals == [expected], f"Wrong canonical: {path}"
        assert len(page.descriptions) == 1 and page.descriptions[0], path
        assert page.h1_count == 1, f"Expected one main heading: {path}"
        title = text.split("<title>")[1].split("</title>")[0]
        assert title and title not in titles, f"Duplicate or empty title: {path}"
        titles.add(title)
        assert expected in urls, f"Page missing from sitemap: {path}"
        for schema in page.schema:
            assert schema["url"] == expected, f"Wrong structured-data URL: {path}"
        assert 'content="index,follow' in text, f"Page not indexable: {path}"
    assert len(pages) == len(urls), "Sitemap contains missing pages"
    count = 0
    for path, page in pages.items():
        for link in page.links:
            parsed = urlsplit(link)
            if parsed.scheme or parsed.netloc:
                if not link.startswith(base):
                    continue
                parsed = urlsplit(link[len(base) :])
                target = root / unquote(parsed.path)
            else:
                target = path.parent / unquote(parsed.path) if parsed.path else path
            target = target.resolve()
            assert target.is_relative_to(root), f"Link escapes site: {path}: {link}"
            if target.is_dir():
                target = target / "index.html"
            assert target.is_file(), f"Broken local link: {path}: {link}"
            if parsed.fragment and target.suffix == ".html":
                assert unquote(parsed.fragment) in pages[target].ids, (path, link)
            count += 1
    print(f"Checked {len(pages)} pages, {count} local links, canonicals, sitemap and JSON-LD")


if __name__ == "__main__":
    check(sys.argv[1])
