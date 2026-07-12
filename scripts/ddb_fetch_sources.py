#!/usr/bin/env python3
"""
Fetch D&D Beyond adventure/source pages you own and convert them into the
markdown folder format consumed by scripts/marker_import_grok.py.

Two modes:

1) Online fetch (requires your own CobaltSession cookie — see README; note
   that automated access is against D&D Beyond's Terms of Service and is
   provided for personal import of content you have purchased):

     python scripts/ddb_fetch_sources.py \
       --url https://www.dndbeyond.com/sources/dnd/lmop \
       --out-dir C:\\campaigns\\lmop --whole-book

2) Offline conversion of pages you saved from your browser (Ctrl+S on each
   chapter while logged in — no scripted site access at all):

     python scripts/ddb_fetch_sources.py \
       --html-dir C:\\campaigns\\lmop_saved --out-dir C:\\campaigns\\lmop

Output:
  <out-dir>/<chapter-slug>.md      one file per chapter
  <out-dir>/images/<name>          map/handout images referenced by the text

Then run the existing campaign importer over the folder:

  python scripts/marker_import_grok.py --marker-dir <out-dir> \
    --source-title "Lost Mine of Phandelver" --edition 5e

This script is standalone (stdlib only) and does not import ai_dm code.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
import time
from html import unescape
from html.parser import HTMLParser
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen

USER_AGENT = "OgresVTT-AI-DM/1.0 (personal import of purchased content)"

SKIP_TAGS = {"script", "style", "noscript", "svg", "iframe", "form",
             "nav", "header", "footer", "aside", "button"}

CONTENT_CLASS_HINTS = ("p-article-content", "article-main", "compendium-page-content")


def parse_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for line in path.read_text(encoding="utf-8").splitlines():
        row = line.strip()
        if not row or row.startswith("#") or "=" not in row:
            continue
        key, val = row.split("=", 1)
        values[key.strip()] = val.strip().strip('"').strip("'")
    return values


def resolve_cookie(cli_cookie: str | None, dotenv: Path | None) -> str | None:
    if cli_cookie:
        return cli_cookie
    if os.environ.get("DDB_COBALT_SESSION"):
        return os.environ["DDB_COBALT_SESSION"]
    env_path = dotenv or Path(".env.local")
    return parse_env_file(env_path).get("DDB_COBALT_SESSION")


def slugify(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-") or "page"


def fetch(url: str, cookie: str | None, timeout: int = 30) -> bytes:
    headers = {"User-Agent": USER_AGENT, "Accept": "*/*"}
    if cookie:
        headers["Cookie"] = f"CobaltSession={cookie}"
    req = Request(url, headers=headers)
    with urlopen(req, timeout=timeout) as resp:
        return resp.read()


class MarkdownExtractor(HTMLParser):
    """Streams HTML into rough markdown, scoped to the article content
    container when one exists (detected by a pre-pass on the raw HTML)."""

    def __init__(self, require_container: bool, base_url: str):
        super().__init__(convert_charrefs=True)
        self.require_container = require_container
        self.base_url = base_url
        self.in_container = not require_container
        self.container_depth = 0
        self.depth = 0
        self.skip_depth = 0
        self.parts: list[str] = []
        self.images: list[tuple[str, str]] = []  # (absolute-url, local-name)
        self._seen_images: set[str] = set()
        self.list_depth = 0

    # -- helpers ------------------------------------------------------------
    def _emit(self, text: str) -> None:
        if self.in_container and self.skip_depth == 0 and text:
            self.parts.append(text)

    def _class_of(self, attrs) -> str:
        return next((v or "" for k, v in attrs if k == "class"), "")

    def _register_image(self, attrs) -> None:
        src = next((v for k, v in attrs if k == "src"), None)
        alt = next((v for k, v in attrs if k == "alt"), "") or "image"
        if not src or src.startswith("data:"):
            return
        absolute = urljoin(self.base_url, src)
        name = os.path.basename(urlparse(absolute).path) or "image"
        if absolute not in self._seen_images:
            self._seen_images.add(absolute)
            self.images.append((absolute, name))
        self._emit(f"\n\n![{alt}](images/{name})\n\n")

    # -- parser callbacks ---------------------------------------------------
    def handle_starttag(self, tag, attrs):
        self.depth += 1
        if tag in SKIP_TAGS:
            self.skip_depth += 1
            return
        if (self.require_container and not self.in_container
                and any(hint in self._class_of(attrs) for hint in CONTENT_CLASS_HINTS)):
            self.in_container = True
            self.container_depth = self.depth
            return
        if tag == "img":
            self._register_image(attrs)
        elif tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            self._emit("\n\n" + "#" * int(tag[1]) + " ")
        elif tag == "p":
            self._emit("\n\n")
        elif tag in ("ul", "ol"):
            self.list_depth += 1
        elif tag == "li":
            self._emit("\n" + "  " * max(0, self.list_depth - 1) + "- ")
        elif tag == "br":
            self._emit("\n")
        elif tag == "tr":
            self._emit("\n")
        elif tag in ("td", "th"):
            self._emit(" | ")
        elif tag == "blockquote":
            self._emit("\n\n> ")

    def handle_startendtag(self, tag, attrs):
        if tag == "img":
            self._register_image(attrs)
        elif tag == "br":
            self._emit("\n")

    def handle_endtag(self, tag):
        if tag in SKIP_TAGS and self.skip_depth > 0:
            self.skip_depth -= 1
        if tag in ("ul", "ol") and self.list_depth > 0:
            self.list_depth -= 1
        if tag in ("p", "div", "table") :
            self._emit("\n")
        if (self.require_container and self.in_container
                and self.depth == self.container_depth):
            self.in_container = False
        self.depth = max(0, self.depth - 1)

    def handle_data(self, data):
        text = re.sub(r"[ \t]+", " ", data)
        if text.strip():
            self._emit(text)


def html_to_markdown(raw_html: str, base_url: str) -> tuple[str, list[tuple[str, str]]]:
    has_container = any(hint in raw_html for hint in CONTENT_CLASS_HINTS)
    extractor = MarkdownExtractor(require_container=has_container, base_url=base_url)
    extractor.feed(raw_html)
    text = unescape("".join(extractor.parts))
    text = re.sub(r"\n{3,}", "\n\n", text).strip() + "\n"
    return text, extractor.images


def page_title(raw_html: str) -> str:
    match = re.search(r"<title[^>]*>(.*?)</title>", raw_html, re.IGNORECASE | re.DOTALL)
    if not match:
        return "page"
    title = unescape(re.sub(r"\s+", " ", match.group(1))).strip()
    return re.sub(r"\s*[-|–]\s*D&D Beyond\s*$", "", title) or "page"


def discover_chapters(raw_html: str, toc_url: str) -> list[str]:
    """Finds same-book chapter links on a table-of-contents page."""
    book_path = urlparse(toc_url).path.rstrip("/")
    pattern = re.compile(r'href="(%s/[^"#?]+)"' % re.escape(book_path))
    seen: list[str] = []
    for match in pattern.finditer(raw_html):
        url = urljoin(toc_url, match.group(1))
        if url not in seen:
            seen.append(url)
    return seen


def write_chapter(out_dir: Path, title: str, markdown: str) -> Path:
    path = out_dir / f"{slugify(title)}.md"
    counter = 2
    while path.exists():
        path = out_dir / f"{slugify(title)}-{counter}.md"
        counter += 1
    path.write_text(f"# {title}\n\n{markdown}", encoding="utf-8")
    return path


def download_images(images: list[tuple[str, str]], out_dir: Path,
                    cookie: str | None, delay: float) -> int:
    if not images:
        return 0
    img_dir = out_dir / "images"
    img_dir.mkdir(parents=True, exist_ok=True)
    count = 0
    for url, name in images:
        target = img_dir / name
        if target.exists():
            continue
        try:
            target.write_bytes(fetch(url, cookie))
            count += 1
            time.sleep(delay)
        except (HTTPError, URLError, OSError) as exc:
            print(f"  ! image failed {url}: {exc}", file=sys.stderr)
    return count


def process_html(raw_html: str, base_url: str, out_dir: Path,
                 cookie: str | None, delay: float, want_images: bool) -> None:
    title = page_title(raw_html)
    markdown, images = html_to_markdown(raw_html, base_url)
    path = write_chapter(out_dir, title, markdown)
    downloaded = download_images(images, out_dir, cookie, delay) if want_images else 0
    print(f"  wrote {path.name} ({len(markdown)} chars, "
          f"{len(images)} images referenced, {downloaded} downloaded)")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--url", action="append", default=[],
                        help="Chapter or table-of-contents URL (repeatable).")
    parser.add_argument("--whole-book", action="store_true",
                        help="Treat each --url as a ToC and fetch every same-book chapter.")
    parser.add_argument("--html-dir",
                        help="Convert browser-saved .html files from this folder instead of fetching.")
    parser.add_argument("--out-dir", required=True, help="Output folder for .md files and images/.")
    parser.add_argument("--cookie", help="CobaltSession cookie value (or set DDB_COBALT_SESSION in .env.local).")
    parser.add_argument("--dotenv", type=Path, help="Path to a .env file (default: .env.local).")
    parser.add_argument("--delay", type=float, default=1.5,
                        help="Seconds between requests (default 1.5).")
    parser.add_argument("--no-images", action="store_true", help="Skip image downloads.")
    args = parser.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    want_images = not args.no_images

    if args.html_dir:
        html_dir = Path(args.html_dir)
        files = sorted(html_dir.glob("*.htm*"))
        if not files:
            print(f"No .html files found in {html_dir}", file=sys.stderr)
            return 1
        for file in files:
            print(f"converting {file.name}")
            raw = file.read_text(encoding="utf-8", errors="replace")
            process_html(raw, "https://www.dndbeyond.com/", out_dir,
                         cookie=None, delay=args.delay, want_images=want_images)
        return 0

    if not args.url:
        parser.error("provide --url (repeatable) or --html-dir")

    cookie = resolve_cookie(args.cookie, args.dotenv)
    if not cookie:
        print("No CobaltSession cookie found (use --cookie or DDB_COBALT_SESSION "
              "in .env.local). Falling back is not possible for online fetch;\n"
              "alternatively save pages from your browser and use --html-dir.",
              file=sys.stderr)
        return 1

    queue: list[str] = []
    for url in args.url:
        if args.whole_book:
            try:
                toc_html = fetch(url, cookie).decode("utf-8", errors="replace")
            except (HTTPError, URLError) as exc:
                print(f"Failed to fetch ToC {url}: {exc}\n"
                      "If this is a 403, D&D Beyond is blocking scripted access — "
                      "save the chapters from your browser (Ctrl+S) and rerun with --html-dir.",
                      file=sys.stderr)
                return 1
            chapters = discover_chapters(toc_html, url)
            print(f"{url}: discovered {len(chapters)} chapters")
            queue.extend(chapters or [url])
            time.sleep(args.delay)
        else:
            queue.append(url)

    for url in queue:
        print(f"fetching {url}")
        try:
            raw = fetch(url, cookie).decode("utf-8", errors="replace")
        except (HTTPError, URLError) as exc:
            print(f"  ! failed: {exc} (skip; consider the --html-dir fallback)",
                  file=sys.stderr)
            continue
        process_html(raw, url, out_dir, cookie, args.delay, want_images)
        time.sleep(args.delay)

    print(f"\nDone. Next step:\n  python scripts/marker_import_grok.py "
          f"--marker-dir \"{out_dir}\" --source-title \"<Adventure Name>\" --edition 5e")
    return 0


if __name__ == "__main__":
    sys.exit(main())
