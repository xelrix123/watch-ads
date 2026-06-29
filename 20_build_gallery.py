#!/usr/bin/env python3
"""Generate a lightweight static gallery for extracted advertisement images."""

from __future__ import annotations

import argparse
import base64
import gzip
import json
import os
import re
import shutil
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Any, Iterable, List, Tuple


def log_info(message: str) -> None:
    print(message, file=sys.stderr)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Create a simplified thumbnail gallery. Source images can come from "
            "Google Drive (--drive-json) or a local HTTP-served directory (--http-json)."
        )
    )
    parser.add_argument(
        "--http-json",
        type=Path,
        required=True,
        help="Path to index JSON produced by build_index.py (local HTTP mode)",
    )
    parser.add_argument(
        "--thumbnails-root",
        type=Path,
        default=Path("thumbnails"),
        help="Directory where generated WebP thumbnails are stored",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("viewer_simple.html"),
        help="Output HTML file",
    )
    parser.add_argument(
        "--thumb-size",
        type=int,
        default=320,
        help="Max thumbnail long-edge in pixels (default: 320)",
    )
    parser.add_argument(
        "--quality",
        type=int,
        default=70,
        help="WebP quality setting 0-100 (default: 70)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Regenerate thumbnails even if they already exist",
    )
    parser.add_argument(
        "--include-plausible",
        action="store_true",
        help="Include the Plausible analytics snippet in the generated HTML",
    )
    parser.add_argument(
        "--thumbnail-in-dialog",
        action="store_true",
        help="Enable the thumbnail pip shown at the lower-left of the modal dialog",
    )
    parser.add_argument(
        "--statistics",
        type=str,
        default=None,
        metavar="FILE",
        help="Path/URL to a statistics page; adds a stats button linking to FILE?back=<gallery-filename>",
    )
    parser.add_argument(
        "--no-loader-screen",
        action="store_true",
        help="Disable the full-screen loader with progress bar shown on first load",
    )
    parser.add_argument(
        "--sort-by-meta-brand",
        action="store_true",
        help="Sort thumbnails by brand then sub-brand (no sub-brand first within each brand)",
    )
    parser.add_argument(
        "--html-title",
        type=str,
        default="Search tool",
        help="Title for the generated HTML page (default: 'Search tool')",
    )
    parser.add_argument(
        "--favicon-svg",
        type=Path,
        default=None,
        help="Path to an SVG file to embed as the page favicon",
    )
    parser.add_argument(
        "--use-original-url-fallback",
        action="store_true",
        help="If the full image fails to load, fall back to the originalUrl from metadata (resolves via same CDN logic as viewUrl)",
    )
    parser.add_argument(
        "--acknowledgements-html",
        type=Path,
        default=None,
        metavar="FILE",
        help="Path to an HTML file whose content is embedded in the Acknowledgements section of the info dialog",
    )
    return parser.parse_args()


def _brand_sort_key(item: tuple) -> tuple:
    """Sort by (brand, year, has_sub_brands, sub_brand, filename)."""
    filename, _path, _view_url, metadata, _original_url = item
    if isinstance(metadata, list):
        entry = metadata[0] if metadata else {}
    elif isinstance(metadata, dict):
        entry = metadata
    else:
        entry = {}
    bp = (entry.get("brands-products") or entry.get("ad_metadata", {}).get("brands-products") or {})
    brands = bp.get("brand") or []
    sub_brands = bp.get("sub_brands") or []
    raw = brands[0].lower() if brands else "\xff"
    # Letters first, then digits, then unknown (\xff)
    brand_str = ("\x00" + raw) if raw[0:1].isalpha() else ("\x01" + raw) if raw[0:1].isdigit() else raw
    # Year: try filename pattern first, then metadata
    year = 9999
    fn_match = re.match(r'^[^-]+-(\d{4})-[^-]+-[^-]+-\d{2}\.[^.]+$', filename)
    if fn_match:
        y = int(fn_match.group(1))
        if 1830 <= y <= 2050:
            year = y
    else:
        ya = (entry.get("ad_metadata") or {}).get("year_ad") or {}
        y = int(ya.get("year") or 0)
        if 1830 <= y <= 2050:
            year = y
    has_sub = 1 if sub_brands else 0
    sub_str = sub_brands[0].lower() if sub_brands else ""
    return (brand_str, year, has_sub, sub_str, filename.lower())


def main() -> int:
    args = parse_args()

    args.thumbnails_root.mkdir(parents=True, exist_ok=True)

    try:
        http_payload = json.loads(args.http_json.read_text())
    except FileNotFoundError:
        print(f"! http index not found: {args.http_json}", file=sys.stderr)
        return 1
    files = http_payload.get("files", []) if isinstance(http_payload, dict) else []
    if not files:
        print("! no files found inside http index JSON", file=sys.stderr)
        return 1
    web_root = http_payload.get("webRoot", "").rstrip("/")
    input_dir_str = http_payload.get("inputDir")
    if not input_dir_str:
        print("! 'inputDir' missing from http index JSON (regenerate with build_index.py)", file=sys.stderr)
        return 1
    input_dir = Path(input_dir_str)
    log_info(f"Loaded {len(files)} entries from {args.http_json}; webRoot={web_root}; inputDir={input_dir}")
    thumbnails, skipped = build_dataset_http(
        files=files,
        web_root=web_root,
        input_dir=input_dir,
        thumbnails_root=args.thumbnails_root,
        thumb_size=args.thumb_size,
        quality=args.quality,
        force=args.force,
    )

    if args.sort_by_meta_brand:
        thumbnails.sort(key=_brand_sort_key)
    else:
        thumbnails.sort(key=lambda item: item[0].lower())

    rel_entries = [
        {
            "filename": filename,
            "thumb": Path(os.path.relpath(path, args.output.parent)).as_posix(),
            "viewUrl": view_url,
            "originalUrl": original_url,
            "metadata": metadata,
            "searchTargets": derive_search_targets(metadata, filename),
        }
        for filename, path, view_url, metadata, original_url in thumbnails
    ]

    filter_options = [
        {"key": "brand", "label": "BRAND"},
        {"key": "filename", "label": "FILENAME"},
        {"key": "objects", "label": "OBJECTS"},
        {"key": "text", "label": "TEXT"},
        {"key": "shape", "label": "SHAPE"},
        {"key": "summary", "label": "SUMMARY"},
        {"key": "watchType", "label": "WATCH TYPE"},
    ]

    bundles = load_thumbnail_bundles(args.thumbnails_root, args.output.parent)

    metadata = {
        "entries": rel_entries,
        "filters": filter_options,
        "bundles": bundles,
    }

    metadata_json_path = args.output.parent / "metadata.json"
    metadata_gz_path = args.output.parent / "metadata.json.gz"
    metadata_text = json.dumps(metadata, ensure_ascii=False, separators=(",", ":"))
    metadata_json_path.write_text(metadata_text)
    with gzip.open(metadata_gz_path, "wb") as fh:
        fh.write(metadata_text.encode("utf-8"))
    log_info(f"Wrote metadata -> {metadata_json_path.name} + {metadata_gz_path.name}")

    metadata_gz_rel = Path(os.path.relpath(metadata_gz_path, args.output.parent)).as_posix()
    favicon_svg = None
    if args.favicon_svg:
        try:
            favicon_svg = args.favicon_svg.read_text()
        except FileNotFoundError:
            print(f"! favicon SVG not found: {args.favicon_svg}", file=sys.stderr)
            return 1
    acknowledgements_html = None
    if args.acknowledgements_html:
        try:
            acknowledgements_html = args.acknowledgements_html.read_text()
        except FileNotFoundError:
            print(f"! acknowledgements file not found: {args.acknowledgements_html}", file=sys.stderr)
            return 1
    thumbnails_root_rel = Path(os.path.relpath(args.thumbnails_root, args.output.parent)).as_posix()
    html = render_html(args.output, metadata_gz_rel, no_thumb_pip=not args.thumbnail_in_dialog, http_mode=True, include_plausible=args.include_plausible, statistics_url=args.statistics, use_loader_screen=not args.no_loader_screen, html_title=args.html_title, favicon_svg=favicon_svg, acknowledgements_html=acknowledgements_html, use_original_url_fallback=args.use_original_url_fallback, thumbnails_root_rel=thumbnails_root_rel)
    args.output.write_text(html)

    print(
        f"Generated {len(thumbnails)} entries (skipped {skipped}), HTML -> {args.output}",
        file=sys.stderr,
    )
    return 0


def build_dataset_http(
    *,
    files: Iterable[dict],
    web_root: str,
    input_dir: Path,
    thumbnails_root: Path,
    thumb_size: int,
    quality: int,
    force: bool,
) -> Tuple[List[Tuple[str, Path, str, Any]], int]:
    """Return [(filename, thumb_path, view_url, metadata)] for HTTP-indexed images."""

    magick = detect_magick_binary()
    log_info(f"Using ImageMagick binary: {magick}")
    dataset: List[Tuple[str, Path, str, Any]] = []
    skipped = 0

    for entry in files:
        filepath = entry.get("filepath")
        if not filepath:
            skipped += 1
            continue

        image_path = input_dir / filepath
        if not image_path.is_file():
            log_info(f"  skip (image not found): {image_path}")
            skipped += 1
            continue

        sidecar = image_path.parent / (image_path.name + ".json")
        if sidecar.is_file():
            try:
                payload = json.loads(sidecar.read_text())
            except Exception:
                payload = {}
        else:
            payload = {}

        web_filepath = entry.get("web_filepath") or filepath
        view_url = f"{web_root}/{web_filepath}"
        filename = Path(filepath).name
        thumb_key = uuid.uuid5(uuid.NAMESPACE_URL, filepath).hex
        thumb_target = thumbnails_root / f"{thumb_key}.webp"

        if thumb_target.exists() and not force:
            log_info(f"Using cached thumbnail: {thumb_target}")
        else:
            log_info(f"Building thumbnail: {image_path} -> {thumb_target}")
            create_thumbnail(
                magick_bin=magick,
                src=image_path,
                dest=thumb_target,
                size=thumb_size,
                quality=quality,
            )

        original_url = None
        if isinstance(payload, list) and payload:
            original_url = (payload[0].get("file_meta") or {}).get("crop_info", {}).get("original_url")
        dataset.append((filename, thumb_target, view_url, payload, original_url))

    log_info(f"Collected {len(dataset)} thumbnails; skipped {skipped} entries")
    return dataset, skipped


def detect_magick_binary() -> str:
    for binary in ("magick", "convert"):
        if shutil.which(binary):
            return binary
    raise RuntimeError("ImageMagick 'magick' or 'convert' command is required")


def create_thumbnail(*, magick_bin: str, src: Path, dest: Path, size: int, quality: int) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        magick_bin,
        str(src),
        "-resize",
        f"{size}x{size}>",
        "-quality",
        str(quality),
        "-strip",
        str(dest),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"magick failed for {src}: {proc.stderr.strip()}" or proc.stdout)


def render_html(
    output_path: Path,
    metadata_gz_rel: str,
    no_thumb_pip: bool = False,
    http_mode: bool = False,
    include_plausible: bool = False,
    statistics_url: str | None = None,
    use_loader_screen: bool = False,
    html_title: str = "Search tool",
    favicon_svg: str | None = None,
    acknowledgements_html: str | None = None,
    use_original_url_fallback: bool = False,
    thumbnails_root_rel: str = "thumbnails",
) -> str:
    metadata_gz_path = json.dumps(metadata_gz_rel)
    thumb_pip_enabled = "false" if no_thumb_pip else "true"
    open_button_label = "Open raw" if http_mode else "Open in Drive"
    gallery_filename = output_path.name
    statistics_url_js = json.dumps(statistics_url) if statistics_url else "null"
    loader_screen_enabled = "true" if use_loader_screen else "false"
    drive_link_hidden = ' hidden' if use_original_url_fallback else ''
    if acknowledgements_html is not None:
        acknowledgements_snippet = f'      <hr class="info-dialog-hr" />\n      <p class="info-dialog-section-label">Acknowledgements</p>\n{acknowledgements_html}'
    else:
        acknowledgements_snippet = ""
    if favicon_svg:
        favicon_b64 = base64.b64encode(favicon_svg.encode("utf-8")).decode("ascii")
        favicon_snippet = f'  <link rel="icon" type="image/svg+xml" href="data:image/svg+xml;base64,{favicon_b64}" />'
    else:
        favicon_snippet = ""
    plausible_snippet = """  <!-- Privacy-friendly analytics by Plausible -->
  <script async src="https://plausible.io/js/pa-rQ77GcOf_OMaqzLW3wWXn.js"></script>
  <script>
    window.plausible=window.plausible||function(){(plausible.q=plausible.q||[]).push(arguments)},plausible.init=plausible.init||function(i){plausible.o=i||{}};
    plausible.init()
  </script>""" if include_plausible else ""
    return f"""<!DOCTYPE html>
<html lang=\"en\">
<head>
  <meta charset=\"utf-8\" />
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
  <title>{html_title}</title>
{favicon_snippet}
{plausible_snippet}
  <style>
    :root {{
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
      color: #0a0a0a;
      background: #f5f5f7;
    }}
    body {{
      margin: 0;
      padding: 1.5rem;
    }}
    .controls {{
      max-width: 800px;
      margin: 0 0 0.5rem;
      display: flex;
      flex-direction: column;
      gap: 0.5rem;
    }}
    #search {{
      width: 100%;
      padding: 0.75rem 1rem;
      font-size: 1rem;
      border: 1px solid #ccc;
      border-radius: 999px;
      outline: none;
    }}
    .info-dialog {{
      background: #fff;
      border: 1px solid #ddd;
      border-radius: 0.75rem;
      box-shadow: 0 4px 24px rgba(0,0,0,0.12);
      padding: 1.25rem 1.5rem;
      margin: 0 0 1rem;
    }}
    .info-dialog p {{
      margin: 0 0 0.75rem;
      font-size: 0.9rem;
      color: #3c3c3c;
      line-height: 1.5;
    }}
    .info-dialog a {{
      color: #0a84ff;
    }}
    .info-dialog code {{
      font-family: 'SFMono-Regular', Consolas, 'Liberation Mono', Menlo, monospace;
      font-size: 0.82rem;
      background: #f0f0f0;
      border-radius: 0.25rem;
      padding: 0.05em 0.35em;
    }}
    .info-dialog-hr {{
      border: none;
      border-top: 1px solid #eee;
      margin: 0.75rem 0;
    }}
    .info-dialog-section-label {{
      font-size: 0.75rem !important;
      text-transform: uppercase;
      letter-spacing: 0.06em;
      color: #999 !important;
      margin: 0 0 0.5rem !important;
    }}
    .info-dialog-setting-label {{
      font-size: 0.8rem !important;
      color: #555 !important;
      margin: 0 0 0.35rem !important;
    }}
    .info-dialog-filters {{
      display: flex;
      flex-wrap: wrap;
      gap: 0.35rem;
      margin-bottom: 0.75rem;
    }}
    .info-dialog-cache-row {{
      display: flex;
      align-items: center;
      gap: 0.5rem;
      margin-bottom: 0.75rem;
      font-size: 0.85rem;
      color: #555;
    }}
    .filter-buttons {{
      display: flex;
      gap: 0.35rem;
      flex-wrap: wrap;
      width: 100%;
    }}
    .filter-button {{
      border: 1px solid #bbb;
      background: #fff;
      color: #555;
      border-radius: 999px;
      padding: 0.3rem 0.7rem;
      font-size: 0.8rem;
      font-weight: 600;
      cursor: pointer;
    }}
    .filter-button.active {{
      border-color: #0a84ff;
      color: #0a84ff;
      background: rgba(10,132,255,0.1);
    }}
    #counts {{
      margin-bottom: 1rem;
      font-size: 0.95rem;
      color: #555;
      max-width: 800px;
    }}
    .cache-stats {{
      position: absolute;
      top: 0.5rem;
      right: 1rem;
      font-size: 0.75rem;
      color: #666;
      letter-spacing: 0.02em;
      pointer-events: auto;
      cursor: pointer;
      z-index: 10;
    }}
    .cache-indicator {{
      background: rgba(10,132,255,0.14);
      color: #0a84ff;
      border-radius: 999px;
      padding: 0.05rem 0.5rem;
      font-size: 0.75rem;
      margin-left: 0.4rem;
      text-transform: uppercase;
      letter-spacing: 0.06em;
    }}
    .grid {{
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
      gap: 1rem;
      margin-top: 2rem;
    }}
    .card {{
      position: relative;
      background: white;
      border-radius: 0.75rem;
      box-shadow: 0 2px 12px rgba(0,0,0,0.1);
      overflow: hidden;
      transition: transform 120ms ease;
      aspect-ratio: 3 / 4;
      display: flex;
      align-items: center;
      justify-content: center;
      padding: 0.5rem;
    }}
    .card.card-missing-thumb {{
      background: #f1f1f1;
    }}
    .card.card-missing-thumb::after {{
      content: 'Thumbnail unavailable';
      position: absolute;
      inset: 0.75rem;
      border-radius: 0.5rem;
      background: rgba(255,255,255,0.85);
      color: #6b6b6b;
      font-size: 0.8rem;
      text-align: center;
      display: flex;
      align-items: center;
      justify-content: center;
      padding: 0.5rem;
    }}
    .card:hover {{
      transform: translateY(-3px);
    }}
    .card img {{
      display: block;
      width: 100%;
      height: 100%;
      object-fit: contain;
    }}
    .card.card-missing-thumb img {{
      opacity: 0;
    }}
    .card-year {{
      position: absolute;
      bottom: 0.4rem;
      left: 0.4rem;
      background: rgba(0,0,0,0.52);
      color: #fff;
      font-size: 0.72rem;
      font-weight: 600;
      letter-spacing: 0.04em;
      padding: 0.15rem 0.45rem;
      border-radius: 0.3rem;
      pointer-events: none;
      line-height: 1.4;
    }}
    .loading-overlay {{
      position: fixed;
      inset: 0;
      background: rgba(245,245,247,0.9);
      display: flex;
      align-items: center;
      justify-content: center;
      z-index: 1200;
      transition: opacity 180ms ease;
    }}
    .loading-overlay.hidden {{
      opacity: 0;
      pointer-events: none;
    }}
    .loading-card {{
      background: white;
      border-radius: 1rem;
      padding: 1.5rem 2rem;
      box-shadow: 0 12px 40px rgba(0,0,0,0.12);
      display: flex;
      flex-direction: column;
      align-items: center;
      gap: 0.75rem;
      max-width: 320px;
      text-align: center;
    }}
    .loading-overlay .spinner {{
      width: 32px;
      height: 32px;
      border-radius: 50%;
      border: 3px solid rgba(10,132,255,0.2);
      border-top-color: #0a84ff;
      animation: spin 1s linear infinite;
    }}
    .loading-overlay.loading-error .spinner {{
      display: none;
    }}
    .loading-text {{
      font-size: 0.95rem;
      color: #333;
    }}
    .loading-overlay.loading-error .loading-text {{
      color: #c0392b;
    }}
    @keyframes spin {{
      to {{ transform: rotate(360deg); }}
    }}
    .modal {{
      position: fixed;
      inset: 0;
      background: rgba(0,0,0,0.7);
      display: none;
      align-items: center;
      justify-content: center;
      padding: 2rem;
      z-index: 1000;
    }}
    .modal.open {{
      display: flex;
    }}
    .modal-content {{
      position: relative;
      background: #fff;
      width: min(1320px, 96vw);
      height: min(90vh, 900px);
      border-radius: 1rem;
      overflow: hidden;
      display: flex;
      flex-direction: column;
      box-shadow: 0 20px 80px rgba(0,0,0,0.35);
      touch-action: manipulation;
    }}
    .modal-header {{
      display: flex;
      flex-wrap: wrap;
      justify-content: space-between;
      align-items: center;
      padding: 1rem 1.5rem;
      border-bottom: 1px solid #eee;
      gap: 0.5rem 1rem;
    }}
    .modal-summary-line {{
      font-size: 0.9rem;
      word-break: break-word;
      color: #1f1f1f;
    }}
    .modal-summary-brand {{
      text-transform: uppercase;
      font-size: 0.75rem;
      letter-spacing: 0.04em;
      color: #0a0a0a;
      word-break: break-word;
    }}
    .json-key {{ color: #ff9d45; }}
    .json-string {{ color: #a3e88b; }}
    .json-number {{ color: #6ec6ff; }}
    .json-boolean {{ color: #ff6f91; }}
    .json-null {{ color: #bdbdbd; }}
    .modal-actions {{
      display: flex;
      gap: 0.5rem;
      align-items: center;
    }}
    .action-button[hidden] {{
      display: none !important;
    }}
    .action-button {{
      text-decoration: none;
      border: 1px solid #0a84ff;
      color: #0a84ff;
      padding: 0.4rem 0.9rem;
      border-radius: 999px;
      font-weight: 600;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      background: transparent;
      cursor: pointer;
      font-size: 0.95rem;
      font-family: inherit;
      line-height: 1;
      appearance: none;
    }}
    .action-button:focus {{
      outline: none;
    }}
    .action-button-icon {{
      padding: 0.4rem 0.6rem;
      line-height: 0;
    }}
    .action-button:hover {{
      background: rgba(10,132,255,0.1);
    }}
    .modal-close {{
      border: none;
      background: transparent;
      font-size: 1.75rem;
      cursor: pointer;
      line-height: 1;
      color: #333;
    }}
    .modal-body {{
      flex: 1;
      display: grid;
      position: relative;
      grid-template-columns: 3fr 2fr;
      height: 100%;
      min-height: 0;
    }}
    .modal-visual {{
      display: grid;
      grid-template-areas: 'slot';
      min-height: 0;
      height: 100%;
    }}
    .modal-visual > * {{
      grid-area: slot;
      min-height: 0;
    }}
    .modal-image {{
      background: #000;
      display: flex;
      align-items: stretch;
      justify-content: center;
      padding: 1rem;
      min-height: 0;
      position: relative;
      overflow: hidden;
    }}
    .image-stage {{
      flex: 1;
      border-radius: 0.5rem;
      overflow: hidden;
      display: flex;
      align-items: center;
      justify-content: center;
      min-height: 0;
    }}
    .modal-image img {{
      width: 100%;
      height: 100%;
      object-fit: contain;
      border-radius: 0.5rem;
      transform-origin: center center;
      transition: transform 80ms ease-out;
      cursor: default;
      touch-action: none;
    }}
    .modal-image img.can-pan {{
      cursor: grab;
    }}
    .modal-image img.dragging {{
      cursor: grabbing;
    }}
    .modal-meta {{
      padding: 1rem 1.5rem;
      overflow-y: auto;
      background: #fafafa;
      border-left: 1px solid #eee;
      min-height: 0;
    }}
    .modal-raw-view {{
      position: relative;
      background: #11131a;
      color: #e6edf3;
      border-radius: 0.75rem;
      padding: 1rem;
      overflow: auto;
      font-size: 0.64rem;
      font-family: 'SFMono-Regular', Consolas, 'Liberation Mono', Menlo, monospace;
      white-space: pre;
      word-break: break-word;
      border: 1px solid rgba(255,255,255,0.1);
      visibility: hidden;
      pointer-events: none;
    }}
    .modal-raw-view.active {{
      visibility: visible;
      pointer-events: auto;
    }}
    .modal-image.hidden {{
      visibility: hidden;
      pointer-events: none;
    }}
    #modal-image-debug {{
      position: absolute;
      bottom: 0.4rem;
      right: calc(40% + 0.5rem);
      font-size: 0.55rem;
      color: rgba(255,255,255,0.7);
      pointer-events: auto;
      cursor: pointer;
      font-family: monospace;
      text-shadow: 0 1px 2px rgba(0,0,0,0.8);
      z-index: 10;
      user-select: none;
      -webkit-user-select: none;
    }}
    .modal-raw-view pre {{
      background: transparent;
      border: none;
      padding: 0;
      margin: 0;
      max-height: none;
      font-size: 0.64rem;
      color: inherit;
      white-space: pre-wrap;
      word-break: break-word;
    }}
    .modal-raw-copy {{
      position: absolute;
      top: 0.6rem;
      right: 0.6rem;
      background: rgba(255,255,255,0.08);
      border: 1px solid rgba(255,255,255,0.15);
      border-radius: 0.4rem;
      color: #e6edf3;
      font-size: 1rem;
      line-height: 1;
      padding: 0.25rem 0.4rem;
      cursor: pointer;
      opacity: 0.6;
      transition: opacity 120ms ease;
    }}
    .modal-raw-copy:hover {{
      opacity: 1;
    }}
    .toggle {{
      display: inline-flex;
      align-items: center;
      gap: 0.35rem;
      margin-left: 0.75rem;
      vertical-align: middle;
    }}
    .toggle input {{
      appearance: none;
      width: 32px;
      height: 16px;
      border-radius: 999px;
      background: #d0d5dd;
      position: relative;
      outline: none;
      cursor: pointer;
      transition: background 120ms ease;
    }}
    .toggle input::after {{
      content: '';
      position: absolute;
      width: 12px;
      height: 12px;
      border-radius: 50%;
      background: #fff;
      top: 2px;
      left: 2px;
      transition: transform 120ms ease;
      box-shadow: 0 1px 3px rgba(0,0,0,0.3);
    }}
    .toggle input:checked {{
      background: #0a84ff;
    }}
    .toggle input:checked::after {{
      transform: translateX(16px);
    }}
    .toggle span {{
      font-size: 0.75rem;
      text-transform: uppercase;
      letter-spacing: 0.05em;
      color: #555;
      line-height: 1;
      display: inline-flex;
      align-items: center;
    }}
    .zoom-controls {{
      position: absolute;
      top: 5.7rem;
      left: 2.5rem;
      transform: translateX(-50%);
      z-index: 2;
      pointer-events: none;
    }}
    .zoom-slider {{
      width: 170px;
      height: 26px;
      transform: rotate(-90deg);
      transform-origin: center;
      direction: rtl;
      -webkit-appearance: none;
      appearance: none;
      background: transparent;
      accent-color: #0a84ff;
      cursor: pointer;
      pointer-events: auto;
    }}
    .zoom-slider::-webkit-slider-runnable-track {{
      height: 4px;
      background: rgba(255,255,255,0.35);
      border-radius: 999px;
    }}
    .zoom-slider::-webkit-slider-thumb {{
      -webkit-appearance: none;
      width: 18px;
      height: 18px;
      border-radius: 50%;
      background: #0a84ff;
      border: 2px solid rgba(0,0,0,0.3);
      box-shadow: 0 2px 6px rgba(0,0,0,0.4);
      margin-top: -7px;
    }}
    .zoom-slider::-moz-range-track {{
      height: 4px;
      background: rgba(255,255,255,0.35);
      border-radius: 999px;
    }}
    .zoom-slider::-moz-range-thumb {{
      width: 18px;
      height: 18px;
      border-radius: 50%;
      background: #0a84ff;
      border: 2px solid rgba(0,0,0,0.3);
      box-shadow: 0 2px 6px rgba(0,0,0,0.4);
    }}
    .meta-block {{
      margin-bottom: 1rem;
    }}
    .meta-block h3 {{
      margin: 0 0 0.35rem;
      font-size: 1rem;
    }}
    .block-label {{
      display: flex;
      align-items: center;
      gap: 0.75rem;
      margin: 0 0 0.35rem;
      text-transform: uppercase;
      font-size: 0.75rem;
      font-weight: 700;
      letter-spacing: 0.04em;
      color: #0a0a0a;
    }}
    .meta-row {{
      margin-bottom: 0.6rem;
    }}
    .meta-label {{
      text-transform: uppercase;
      font-size: 0.75rem;
      letter-spacing: 0.04em;
      color: #777;
      margin-bottom: 0.25rem;
      display: block;
    }}
    .meta-value {{
      font-weight: 400;
      font-size: 0.9rem;
      color: #3c3c3c;
    }}
    pre {{
      background: #fff;
      border: 1px solid #ddd;
      border-radius: 0.4rem;
      padding: 0.75rem;
      font-size: 0.8rem;
      overflow-x: auto;
      max-height: 200px;
      white-space: pre-wrap;
      word-break: break-word;
    }}
    .ad-text {{
      margin-top: 0.45rem;
      font-size: 0.85rem;
      color: #3a3a3a;
      line-height: 1.4;
      white-space: pre-wrap;
      word-break: break-word;
    }}
    body.modal-open {{
      overflow: hidden;
    }}
    .modal-pip-spacer {{
      height: 220px;
      flex-shrink: 0;
    }}
    .modal-thumb-pip {{
      position: absolute;
      bottom: 0.75rem;
      right: 0.75rem;
      z-index: 10;
      visibility: hidden;
      pointer-events: none;
    }}
    .modal-thumb-pip img {{
      display: block;
      max-width: 160px;
      max-height: 200px;
      width: auto;
      height: auto;
      border-radius: 0.75rem;
      box-shadow: 0 4px 16px rgba(0,0,0,0.3);
    }}
    .modal-nav-btn {{
      display: none;
      user-select: none;
      -webkit-user-select: none;
    }}
    .modal-image {{
      user-select: none;
      -webkit-user-select: none;
    }}
    #scroll-top-btn {{
      display: none;
      position: fixed;
      top: 1rem;
      right: 1rem;
      z-index: 500;
      width: 2.5rem;
      height: 2.5rem;
      border-radius: 50%;
      border: none;
      background: rgba(10,132,255,0.85);
      color: #fff;
      font-size: 1.5rem;
      line-height: 1;
      cursor: pointer;
      box-shadow: 0 2px 8px rgba(0,0,0,0.25);
      backdrop-filter: blur(4px);
      -webkit-backdrop-filter: blur(4px);
      align-items: center;
      justify-content: center;
    }}
    #scroll-top-btn.scroll-top-hidden {{
      display: none !important;
    }}
    @media (max-width: 960px) {{
      #scroll-top-btn {{
        display: flex;
      }}
    }}
    @media (max-width: 960px) {{
      #modal-image-debug {{
        display: none;
      }}
      .cache-stats {{
        display: none;
      }}
      .card {{
        padding: 1.5rem;
      }}
      .modal {{
        padding: 2rem 1rem;
      }}
      .modal-header > div:first-child {{
        width: 100%;
      }}
      .modal-body {{
        grid-template-columns: 1fr;
      }}
      .modal-image img {{
        touch-action: pan-x pan-y pinch-zoom;
      }}
      .modal-thumb-pip {{
        display: none !important;
      }}
      .modal-close {{
        position: absolute;
        top: 0.75rem;
        right: 1rem;
        z-index: 10;
      }}
      .modal-actions {{
        padding-right: 2.5rem;
      }}
      .modal-nav-btn {{
        display: flex;
        align-items: center;
        justify-content: center;
        position: absolute;
        bottom: 1rem;
        width: 2.5rem;
        height: 2.5rem;
        border-radius: 50%;
        border: none;
        background: rgba(255,255,255,0.18);
        color: #fff;
        font-size: 1.75rem;
        line-height: 1;
        cursor: pointer;
        backdrop-filter: blur(4px);
        -webkit-backdrop-filter: blur(4px);
        z-index: 3;
      }}
      .modal-nav-btn:active {{
        background: rgba(255,255,255,0.32);
      }}
      .modal-nav-prev {{ left: 1rem; }}
      .modal-nav-next {{ right: 1rem; }}
    }}
    #loader-screen {{
      position: fixed;
      inset: 0;
      z-index: 9000;
      background: #0d0d14;
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      gap: 2rem;
      transition: opacity 200ms ease;
    }}
    #loader-screen.fade-out {{
      opacity: 0;
      pointer-events: none;
    }}
    #loader-screen.gone {{
      display: none;
    }}
    .loader-title {{
      font-size: clamp(0.85rem, 3vw, 1.2rem);
      font-weight: 400;
      letter-spacing: 0.18em;
      text-transform: uppercase;
      color: #e0e0e0;
    }}
    .loader-sub {{
      font-size: 0.82rem;
      letter-spacing: 0.1em;
      text-transform: uppercase;
      color: #555;
      min-height: 1.2em;
      text-align: center;
    }}
    .loader-bar-wrap {{
      width: min(340px, 72vw);
      height: 6px;
      background: #1e1e2e;
      border-radius: 999px;
      overflow: hidden;
    }}
    .loader-bar {{
      height: 100%;
      width: 0%;
      border-radius: 999px;
      background: linear-gradient(90deg, #b5956a 0%, #d4b896 100%);
      transition: width 280ms cubic-bezier(0.4, 0, 0.2, 1);
    }}
    .loader-bar.indeterminate {{
      width: 38% !important;
      animation: loader-slide 1.4s ease-in-out infinite;
      transition: none;
    }}
    @keyframes loader-slide {{
      0%   {{ transform: translateX(-120%); }}
      100% {{ transform: translateX(370%); }}
    }}
    .loader-dots {{
      display: inline-block;
    }}
    .loader-dots::after {{
      content: '';
      animation: dots 1.5s steps(4, end) infinite;
    }}
    @keyframes dots {{
      0%   {{ content: ''; }}
      25%  {{ content: '.'; }}
      50%  {{ content: '..'; }}
      75%  {{ content: '...'; }}
      100% {{ content: ''; }}
    }}
  </style>
</head>
<body>
  <div id=\"loader-screen\" aria-live=\"polite\" aria-label=\"Loading\">
    <div class=\"loader-title\">Initializing</div>
    <div class=\"loader-bar-wrap\"><div id=\"loader-bar\" class=\"loader-bar indeterminate\"></div></div>
    <div id=\"loader-sub\" class=\"loader-sub\">Loading assets<span class=\"loader-dots\"></span></div>
  </div>
  <div id=\"cache-stats\" class=\"cache-stats\">Cache: 0 images · 0 B</div>
  <div class=\"controls\">
    <div class=\"filter-buttons\" id=\"filter-buttons\"></div>
    <input id=\"search\" type=\"search\" placeholder=\"Type your search here...\" autocomplete=\"off\" />
  </div>
  <div id=\"info-dialog\" class=\"info-dialog\" hidden>
    <div class=\"info-dialog-content\">
      <p class=\"info-dialog-section-label\">Help</p>
      <p class=\"info-dialog-setting-label\">Search supports free text and the following special filters:</p>
      <p class=\"info-dialog-setting-label\"><code>lang:fr</code> — filter by original ad language (2-letter code, e.g. <code>fr</code>, <code>de</code>, <code>en</code>)</p>
      <p class=\"info-dialog-setting-label\"><code>year:1934</code> — filter by ad year; prefix matching, so <code>year:19</code> matches any 1900s ad and <code>year:193</code> matches 1930–1939</p>
      <p class=\"info-dialog-setting-label\">Multiple terms are combined with AND substring search — each term must appear somewhere in the selected fields. Phrase search: wrap in quotes, e.g. <code>"chronograph automatic"</code></p>
{acknowledgements_snippet}
      <hr class=\"info-dialog-hr\" />
      <p class=\"info-dialog-section-label\">Settings</p>
      <p class=\"info-dialog-setting-label\">Search in:</p>
      <div id=\"info-dialog-filters\" class=\"info-dialog-filters\"></div>
      <div class=\"info-dialog-cache-row\">
        <span id=\"info-dialog-cache-label\">Cache: 0 MB</span>
        <button id=\"info-dialog-cache-clear\" class=\"filter-button\" type=\"button\">Clear</button>
      </div>
      <button class=\"info-dialog-close filter-button\" type=\"button\">Close</button>
    </div>
  </div>
  <div id=\"counts\"></div>
  <div id=\"grid\" class=\"grid\"></div>
  <div id=\"grid-sentinel\"></div>
  <button id=\"scroll-top-btn\" class=\"scroll-top-hidden\" aria-label=\"Back to top\">&#8679;</button>
  <div id=\"modal\" class=\"modal\" aria-hidden=\"true\">
    <div class=\"modal-content\">
      <div class=\"modal-header\">
        <div>
          <div id=\"modal-summary-line\" class=\"modal-summary-line\"></div>
        </div>
        <div class=\"modal-actions\">
          <button id=\"modal-toggle\" class=\"action-button\" type=\"button\">JSON</button>
          <a id=\"modal-drive-link\" class=\"action-button action-button-icon\" target=\"_blank\" rel=\"noopener noreferrer\" title=\"Open image in new tab\"{drive_link_hidden}><svg width="16px" height="16px" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg"><path d="M14.2647 15.9377L12.5473 14.2346C11.758 13.4519 11.3633 13.0605 10.9089 12.9137C10.5092 12.7845 10.079 12.7845 9.67922 12.9137C9.22485 13.0605 8.83017 13.4519 8.04082 14.2346L4.04193 18.2622M14.2647 15.9377L14.606 15.5991C15.412 14.7999 15.8149 14.4003 16.2773 14.2545C16.6839 14.1262 17.1208 14.1312 17.5244 14.2688C17.9832 14.4253 18.3769 14.834 19.1642 15.6515L20 16.5001M14.2647 15.9377L18.22 19.9628M18.22 19.9628C17.8703 20 17.4213 20 16.8 20H7.2C6.07989 20 5.51984 20 5.09202 19.782C4.7157 19.5903 4.40973 19.2843 4.21799 18.908C4.12583 18.7271 4.07264 18.5226 4.04193 18.2622M18.22 19.9628C18.5007 19.9329 18.7175 19.8791 18.908 19.782C19.2843 19.5903 19.5903 19.2843 19.782 18.908C20 18.4802 20 17.9201 20 16.8V13M11 4H7.2C6.07989 4 5.51984 4 5.09202 4.21799C4.7157 4.40973 4.40973 4.71569 4.21799 5.09202C4 5.51984 4 6.0799 4 7.2V16.8C4 17.4466 4 17.9066 4.04193 18.2622M18 9V6M18 6V3M18 6H21M18 6H15" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg></a>
          <a id=\"modal-original-link\" class=\"action-button action-button-icon\" target=\"_blank\" rel=\"noopener noreferrer\" hidden><svg fill="currentColor" height="16px" width="16px" viewBox="0 0 207.027 207.027" xmlns="http://www.w3.org/2000/svg"><path d="M69.866,15.557L0,138.919l28.732,52.552l143.288-0.029l35.008-59.588L136.39,15.735L69.866,15.557z M17.166,139.046L74.268,38.205L91.21,67.783L33.24,168.447L17.166,139.046z M99.841,82.851l23.805,41.558l-47.732-0.006L99.841,82.851z M163.434,176.443l-117.332,0.024l21.53-37.065l64.606,0.008l0.067,0.119l52.865-0.085L163.434,176.443z M140.932,124.411L90.157,35.767l-2.966-5.178l40.751,0.121l57.003,93.706L140.932,124.411z"/></svg></a>
          <button id=\"modal-close\" class=\"modal-close\" aria-label=\"Close\">&times;</button>
        </div>
      </div>
      <div class=\"modal-body\">
        <div class=\"modal-visual\">
          <div class=\"modal-image\" id=\"modal-image-panel\">
            <div class=\"zoom-controls\" title=\"Zoom\">
              <input id=\"zoom-slider\" class=\"zoom-slider\" type=\"range\" min=\"1\" max=\"3.6\" step=\"0.1\" value=\"1\" />
            </div>
            <div id=\"modal-image-stage\" class=\"image-stage\">
              <img id=\"modal-image\" alt=\"Selected advert\" referrerpolicy=\"no-referrer\" />
            </div>
            <button class=\"modal-nav-btn modal-nav-prev\" aria-label=\"Previous\" onclick=\"moveModal(-1)\">&#8249;</button>
            <button class=\"modal-nav-btn modal-nav-next\" aria-label=\"Next\" onclick=\"moveModal(1)\">&#8250;</button>
          </div>
          <div class=\"modal-raw-view\" id=\"modal-raw-view\">
            <button id=\"modal-raw-copy\" class=\"modal-raw-copy\" aria-label=\"Copy JSON\" title=\"Copy JSON\">&#128203;</button>
            <pre id=\"modal-raw\"></pre>
          </div>
        </div>
        <div id=\"modal-image-debug\"></div>
        <div class=\"modal-meta\">
          <div id=\"modal-summary\" class=\"meta-block\"></div>
          <div id=\"modal-extra\" class=\"meta-block\"></div>
          <div id=\"modal-pip-spacer\" class=\"modal-pip-spacer\" hidden></div>
        </div>
        <div id=\"modal-thumb-pip\" class=\"modal-thumb-pip\" aria-hidden=\"true\"><img id=\"modal-thumb-pip-img\" alt=\"\" /></div>
      </div>
    </div>
  </div>
  <div id=\"loading-overlay\" class=\"loading-overlay\">
    <div class=\"loading-card\">
      <div class=\"spinner\"></div>
      <div id=\"loading-text\" class=\"loading-text\">Loading metadata…</div>
    </div>
  </div>
  <script>
    const METADATA_GZ_URL = {metadata_gz_path};
    const THUMB_PIP_ENABLED = {thumb_pip_enabled};
    const STATISTICS_URL = {statistics_url_js};
    const GALLERY_FILENAME = {json.dumps(gallery_filename)};
    const LOADER_SCREEN_ENABLED = {loader_screen_enabled};
    const USE_ORIGINAL_URL_FALLBACK = {'true' if use_original_url_fallback else 'false'};
    let DATA = [];
    let FILTER_OPTIONS = [];
    let THUMB_BUNDLES = [];
    const EMPTY_THUMBNAIL_SRC = 'data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///ywAAAAAAQABAAACAUwAOw==';
    const tarDecoder = new TextDecoder('utf-8');
    const grid = document.getElementById('grid');
    const counts = document.getElementById('counts');
    const search = document.getElementById('search');
    const filterButtonsContainer = document.getElementById('filter-buttons');
    const bundleMap = new Map();
    const bundlePromises = new Map();
    const cacheStats = document.getElementById('cache-stats');
    const loadingOverlay = document.getElementById('loading-overlay');
    const loadingText = document.getElementById('loading-text');
    const DB_NAME = 'watchad-cache';
    const DB_VERSION = 3;
    const STORE_THUMBS = 'thumbs';
    const STORE_FULLSIZE = 'fullsize';
    const STORE_HASHES = 'bundle-hashes';
    const FULLSIZE_MAX = 100;
    const dbPromise = openDatabase();
    const modal = document.getElementById('modal');
    const modalImage = document.getElementById('modal-image');
    const zoomSlider = document.getElementById('zoom-slider');
    const imageStage = document.getElementById('modal-image-stage');
    const modalSummaryLine = document.getElementById('modal-summary-line');
    const modalDriveLink = document.getElementById('modal-drive-link');
    const modalOriginalLink = document.getElementById('modal-original-link');
    const modalSummary = document.getElementById('modal-summary');
    const modalExtra = document.getElementById('modal-extra');
    const modalRaw = document.getElementById('modal-raw');
    const modalToggle = document.getElementById('modal-toggle');
    const modalRawView = document.getElementById('modal-raw-view');
    const modalImagePanel = document.getElementById('modal-image-panel');
    const modalClose = document.getElementById('modal-close');
    const modalThumbPip = document.getElementById('modal-thumb-pip');
    const modalThumbPipImg = document.getElementById('modal-thumb-pip-img');
    const modalContent = modal.querySelector('.modal-content');
    if (counts) {{
      counts.textContent = 'Loading thumbnails…';
    }}

    // --- Loader screen ---
    const loaderScreen = document.getElementById('loader-screen');
    const loaderBar = document.getElementById('loader-bar');
    const loaderSub = document.getElementById('loader-sub');
    let loaderDismissed = false;
    let loaderTimeout = null;
    let loaderRafId = null;
    let loaderStartTime = null;

    function loaderStartFakeProgress() {{
      if (!LOADER_SCREEN_ENABLED || !loaderBar || loaderDismissed) return;
      loaderBar.classList.remove('indeterminate');
      loaderBar.style.transition = 'none';
      loaderBar.style.width = '0%';
      loaderStartTime = performance.now();
      function tick(now) {{
        if (loaderDismissed) return;
        const elapsed = now - loaderStartTime;
        // Asymptotic curve: fast early, decelerates, caps at 90%
        const frac = Math.min(1 - 1 / (1 + elapsed / 1800), 0.9);
        loaderBar.style.width = (frac * 100).toFixed(1) + '%';
        loaderRafId = requestAnimationFrame(tick);
      }}
      loaderRafId = requestAnimationFrame(tick);
    }}

    function loaderDismiss() {{
      if (!LOADER_SCREEN_ENABLED || loaderDismissed) return;
      loaderDismissed = true;
      if (loaderTimeout) {{ clearTimeout(loaderTimeout); loaderTimeout = null; }}
      if (loaderRafId) {{ cancelAnimationFrame(loaderRafId); loaderRafId = null; }}
      if (!loaderScreen) return;
      if (loaderBar) {{
        loaderBar.style.transition = 'width 280ms cubic-bezier(0.4, 0, 0.2, 1)';
        loaderBar.style.width = '100%';
      }}
      if (loaderSub) loaderSub.textContent = 'Ready';
      loaderScreen.classList.add('fade-out');
      loaderScreen.addEventListener('transitionend', () => loaderScreen.classList.add('gone'), {{ once: true }});
    }}

    if (LOADER_SCREEN_ENABLED) {{
      loaderTimeout = setTimeout(loaderDismiss, 5000);
    }} else if (loaderScreen) {{
      loaderScreen.classList.add('gone');
    }}

    bootstrap();

    let lastQuery = '';
    let currentItems = DATA;
    let modalIndex = -1;
    let debugStateIndex = 0; // persisted across images
    let debugStates = []; // [{{label, title}}] for current image
    const DEBUG_STATE_KEY = 'gallery-debug-state';
    try {{ debugStateIndex = parseInt(localStorage.getItem(DEBUG_STATE_KEY) || '0', 10) || 0; }} catch (e) {{}}
    let zoomLevel = 1;
    let panX = 0;
    let panY = 0;
    let isDragging = false;
    let dragStartX = 0;
    let dragStartY = 0;
    let panStartX = 0;
    let panStartY = 0;
    let activePointerId = null;
    const activeFilters = new Set(['brand', 'filename', 'objects', 'text', 'shape', 'summary', 'watchType']);
    const thumbCache = new Map();
    let thumbBytes = 0;
    let showingMetadata = false;
    let showingTranslated = true;
    let persistentThumbCount = 0;
    let persistentThumbBytes = 0;
    let persistentFullCount = 0;
    let persistentFullBytes = 0;
    const fullsizeMemCache = new Map(); // url → objectURL
    updateCacheStats();
    dbPromise
      .then((db) => {{
        if (!db) {{ updateCacheStats(); return; }}
        initializePersistentStats(db);
      }})
      .catch(() => updateCacheStats());

    async function bootstrap() {{
      showLoadingOverlay(true);
      setLoadingMessage('Loading metadata…');
      loaderStartFakeProgress();
      try {{
        const meta = await fetchMetadata();
        applyMetadata(meta);
        setLoadingMessage('Loading assets…');
        renderFilterButtons();
        render(DATA);
        showLoadingOverlay(false);
        if (THUMB_BUNDLES.length === 0) {{
          loaderDismiss();
        }} else {{
          // Fetch asset-hashes.txt first, then load bundles (skipping unchanged ones)
          fetchAssetHashes(window.location.href).then(() =>
            Promise.all(THUMB_BUNDLES.map((_, idx) => ensureBundleLoaded(idx)))
              .finally(() => loaderDismiss())
          );
        }}
      }} catch (error) {{
        console.error('Failed to load metadata', error);
        showLoadingError(error);
        loaderDismiss();
      }}
    }}

    async function fetchMetadata() {{
      return fetchAndDecodeMetadata(METADATA_GZ_URL);
    }}

    async function fetchAndDecodeMetadata(url) {{
      const response = await fetch(url);
      if (!response.ok) {{
        throw new Error(`Failed to load ${{url}}`);
      }}
      const ds = new DecompressionStream('gzip');
      const sourceStream = response.body
        ? response.body
        : new Blob([await response.arrayBuffer()]).stream();
      const decompressedStream = sourceStream.pipeThrough(ds);
      const text = await new Response(decompressedStream).text();
      return JSON.parse(text);
    }}

    function applyMetadata(meta) {{
      DATA = Array.isArray(meta.entries) ? meta.entries : [];
      FILTER_OPTIONS = Array.isArray(meta.filters) ? meta.filters : [];
      THUMB_BUNDLES = Array.isArray(meta.bundles) ? meta.bundles : [];
      currentItems = DATA;
      bundleMap.clear();
      bundlePromises.clear();
      THUMB_BUNDLES.forEach((bundle, index) => {{
        (bundle.files || []).forEach((name) => bundleMap.set(name, index));
      }});
      if (!FILTER_OPTIONS.length) {{
        FILTER_OPTIONS = [
          {{ key: 'brand', label: 'BRAND' }},
          {{ key: 'filename', label: 'FILENAME' }},
          {{ key: 'objects', label: 'OBJECTS' }},
          {{ key: 'text', label: 'TEXT' }},
          {{ key: 'shape', label: 'SHAPE' }},
          {{ key: 'summary', label: 'SUMMARY' }},
          {{ key: 'watchType', label: 'WATCH TYPE' }},
        ];
      }}
      const availableKeys = new Set(FILTER_OPTIONS.map((option) => option.key));
      const hasActive = [...activeFilters].some((key) => availableKeys.has(key));
      if (!hasActive && FILTER_OPTIONS.length) {{
        activeFilters.clear();
        activeFilters.add(FILTER_OPTIONS[0].key);
      }}
    }}

    function setLoadingMessage(message) {{
      if (loadingText) {{
        loadingText.textContent = message;
      }}
    }}

    function showLoadingOverlay(show) {{
      if (!loadingOverlay) {{
        return;
      }}
      if (show) {{
        loadingOverlay.classList.remove('hidden');
        loadingOverlay.classList.remove('loading-error');
      }} else {{
        loadingOverlay.classList.add('hidden');
      }}
    }}

    function showLoadingError(error) {{
      if (!loadingOverlay) {{
        alert('Failed to load metadata.');
        return;
      }}
      loadingOverlay.classList.remove('hidden');
      loadingOverlay.classList.add('loading-error');
      setLoadingMessage(`Failed to load metadata: ${{(error && error.message) || 'Unknown error'}}`);
    }}

    const MOBILE_PAGE_SIZE = 100;
    let mobilePage = 0;
    let mobileItems = [];
    let sentinelObserver = null;

    function makeCard(item, index) {{
      const link = document.createElement('a');
      link.href = item.viewUrl;
      link.target = '_blank';
      link.rel = 'noopener noreferrer';
      link.className = 'card';
      link.title = item.filename;
      const img = document.createElement('img');
      img.loading = 'lazy';
      img.alt = item.filename;
      hydrateThumbnail(img, item.thumb);
      link.appendChild(img);
      const yearMatch = item.filename.match(/^[^-]+-(\\d{{4}})-[^-]+-[^-]+-\\d{{2}}\\.[^.]+$/);
      if (yearMatch) {{
        const badge = document.createElement('span');
        badge.className = 'card-year';
        badge.textContent = yearMatch[1];
        link.appendChild(badge);
      }}
      link.addEventListener('click', (event) => {{
        event.preventDefault();
        openModal(index);
      }});
      return link;
    }}

    function appendCards(items, startIndex, endIndex) {{
      const fragment = document.createDocumentFragment();
      for (let i = startIndex; i < endIndex; i++) {{
        fragment.appendChild(makeCard(items[i], i));
      }}
      grid.appendChild(fragment);
    }}

    function render(items) {{
      currentItems = items;
      grid.innerHTML = '';
      if (sentinelObserver) {{ sentinelObserver.disconnect(); sentinelObserver = null; }}

      if (!isMobile()) {{
        // Desktop: render all at once
        appendCards(items, 0, items.length);
      }} else {{
        // Mobile: render first page, observe sentinel for more
        mobilePage = 0;
        mobileItems = items;
        const end = Math.min(MOBILE_PAGE_SIZE, items.length);
        appendCards(items, 0, end);
        mobilePage = end;
        if (end < items.length) {{
          setupSentinelObserver();
        }}
      }}
      counts.textContent = `Showing ${{items.length}} of ${{DATA.length}} thumbnails`;
    }}

    function setupSentinelObserver() {{
      const sentinel = document.getElementById('grid-sentinel');
      if (!sentinel) return;
      sentinelObserver = new IntersectionObserver((entries) => {{
        if (!entries[0].isIntersecting) return;
        const end = Math.min(mobilePage + MOBILE_PAGE_SIZE, mobileItems.length);
        appendCards(mobileItems, mobilePage, end);
        mobilePage = end;
        if (mobilePage >= mobileItems.length) {{
          sentinelObserver.disconnect();
          sentinelObserver = null;
        }}
        counts.textContent = `Showing ${{mobileItems.length}} of ${{DATA.length}} thumbnails`;
      }}, {{ rootMargin: '200px' }});
      sentinelObserver.observe(sentinel);
    }}

    function filterItems(query) {{
      const terms = parseSearchTerms(query);
      if (!terms.length) {{
        return DATA;
      }}
      const langTerms = [];
      const yearPrefixes = [];
      const otherTerms = [];
      for (const term of terms) {{
        const lm = term.match(/^lang:([a-z]{{2}})$/);
        if (lm) {{ langTerms.push(lm[1]); continue; }}
        const ym = term.match(/^year:(\\d{{1,4}})$/);
        if (ym) {{ yearPrefixes.push(ym[1]); continue; }}
        otherTerms.push(term);
      }}
      return DATA.filter(item => {{
        const meta = Array.isArray(item.metadata) ? (item.metadata[0] || {{}}) : (item.metadata || {{}});
        if (langTerms.length) {{
          const lang = (meta.text_ocr && meta.text_ocr.original_language || '').toLowerCase();
          if (!langTerms.includes(lang)) return false;
        }}
        if (yearPrefixes.length) {{
          const year = String((meta.ad_metadata && meta.ad_metadata.year_ad && meta.ad_metadata.year_ad.year) || 0);
          if (!yearPrefixes.some(p => year.startsWith(p) && year !== '0')) return false;
        }}
        if (!otherTerms.length) return true;
        const targets = item.searchTargets || {{}};
        return otherTerms.every(term => {{
          for (const key of activeFilters) {{
            const target = targets[key];
            if (target && target.includes(term)) {{
              return true;
            }}
          }}
          return false;
        }});
      }});
    }}

    function parseSearchTerms(raw) {{
      const terms = [];
      const regex = /"([^\\"]+)"|([^\\s"]+)/g;
      const input = raw.toLowerCase();
      let match;
      while ((match = regex.exec(input))) {{
        const term = (match[1] || match[2] || '').trim();
        if (term) {{
          terms.push(term);
        }}
      }}
      return terms;
    }}

    let assetHashes = null; // map: bundle path → hash string, null = not yet fetched

    async function fetchAssetHashes(baseUrl) {{
      try {{
        const url = new URL('{thumbnails_root_rel}/asset-hashes.txt', baseUrl).href;
        const response = await fetch(url);
        if (!response.ok) return;
        const text = await response.text();
        assetHashes = new Map();
        for (const line of text.split('\\n')) {{
          const colon = line.indexOf(':');
          if (colon === -1) continue;
          assetHashes.set(line.slice(0, colon).trim(), line.slice(colon + 1).trim());
        }}
        console.log(`[cache] asset-hashes.txt loaded (${{assetHashes.size}} entries)`);
      }} catch (e) {{
        console.log('[cache] asset-hashes.txt unavailable, loading all bundles');
        assetHashes = null;
      }}
    }}

    async function getStoredHash(bundlePath) {{
      try {{
        const db = await dbPromise;
        if (!db || !db.objectStoreNames.contains(STORE_HASHES)) return null;
        return await new Promise((res, rej) => {{
          const tx = db.transaction(STORE_HASHES, 'readonly');
          const req = tx.objectStore(STORE_HASHES).get(bundlePath);
          req.onsuccess = () => res(req.result ? req.result.hash : null);
          req.onerror = () => rej(req.error);
        }});
      }} catch (e) {{ return null; }}
    }}

    async function storeHash(bundlePath, hash) {{
      try {{
        const db = await dbPromise;
        if (!db || !db.objectStoreNames.contains(STORE_HASHES)) return;
        await new Promise((res, rej) => {{
          const tx = db.transaction(STORE_HASHES, 'readwrite');
          tx.objectStore(STORE_HASHES).put({{ bundle: bundlePath, hash: hash }});
          tx.oncomplete = () => res();
          tx.onerror = () => rej(tx.error);
        }});
      }} catch (e) {{}}
    }}

    async function ensureBundleLoaded(index) {{
      if (bundlePromises.has(index)) {{
        return bundlePromises.get(index);
      }}
      const promise = (async () => {{
        const bundle = THUMB_BUNDLES[index];
        if (!bundle) {{
          console.warn(`[thumb] ensureBundleLoaded: no bundle at index ${{index}}`);
          return;
        }}
        const bundleUrl = new URL(bundle.bundle, window.location.href).href;
        // Check if bundle is unchanged and already cached
        if (assetHashes !== null) {{
          const serverHash = assetHashes.get(bundle.bundle);
          if (serverHash) {{
            const storedHash = await getStoredHash(bundle.bundle);
            if (storedHash === serverHash) {{
              console.log(`[cache] bundle ${{bundle.bundle}} unchanged, skipping fetch`);
              return;
            }}
          }} else {{
            console.warn(`[thumb] no server hash for bundle ${{bundle.bundle}} — will fetch unconditionally`);
          }}
        }}
        console.log(`[thumb] fetching bundle ${{bundle.bundle}} (${{(bundle.files || []).length}} files expected)`);
        const response = await fetch(bundleUrl);
        if (!response.ok) {{
          throw new Error(`[thumb] bundle fetch failed: ${{bundle.bundle}} — HTTP ${{response.status}} ${{response.statusText}}`);
        }}
        const buffer = await response.arrayBuffer();
        const expected = new Set((bundle.files || []).map((name) => name || ''));
        const files = parseTarArchive(new Uint8Array(buffer));
        if (files.length > 0) {{
          console.log(`[thumb] bundle ${{bundle.bundle}}: tar has ${{files.length}} entries, first few raw names:`, files.slice(0, 3).map(f => f.name));
          const firstNorm = getFileName(files[0].name) || files[0].name;
          const firstExpected = [...expected][0];
          console.log(`[thumb] first tar name normalized: "${{firstNorm}}", first expected: "${{firstExpected}}"`);
        }} else {{
          console.warn(`[thumb] bundle ${{bundle.bundle}}: tar parsed but 0 entries found — buffer size: ${{buffer.byteLength}}`);
        }}
        const registeredNames = new Set();
        for (const file of files) {{
          const normalized = getFileName(file.name) || file.name || '';
          if (!normalized || !expected.has(normalized)) {{
            continue;
          }}
          await registerBundleThumbnail(normalized, file.blob);
          registeredNames.add(normalized);
        }}
        // Warn about files listed in metadata but absent from tar
        const missing = [...expected].filter(n => n && !registeredNames.has(n));
        if (missing.length > 0) {{
          console.warn(`[thumb] bundle ${{bundle.bundle}}: ${{missing.length}} file(s) listed in metadata but absent from tar:`, missing);
        }}
        console.log(`[thumb] bundle ${{bundle.bundle}} loaded: ${{registeredNames.size}}/${{expected.size}} thumbnails registered`);
        // Store hash after successful load
        if (assetHashes !== null) {{
          const serverHash = assetHashes.get(bundle.bundle);
          if (serverHash) await storeHash(bundle.bundle, serverHash);
        }}
      }})();
      bundlePromises.set(index, promise);
      return promise;
    }}

    async function registerBundleThumbnail(name, blob) {{
      const cacheKey = name;
      if (thumbCache.has(cacheKey)) {{
        return;
      }}
      try {{
        const dataUrl = await blobToDataUrl(blob);
        thumbCache.set(cacheKey, {{ objectUrl: dataUrl, size: blob.size }});
        thumbBytes += blob.size;
        updateCacheStats();
        const record = {{ url: cacheKey, dataUrl, size: blob.size }};
        const existed = await putPersistentEntry(STORE_THUMBS, record);
        if (!existed) {{
          persistentThumbCount += 1;
          persistentThumbBytes += blob.size;
        }}
        updateCacheStats();
      }} catch (error) {{
        console.warn('Failed to persist bundle thumbnail', error);
      }}
    }}

    function parseTarArchive(bytes) {{
      const files = [];
      let offset = 0;
      while (offset + 512 <= bytes.length) {{
        const name = decodeTarString(bytes, offset, 100);
        if (!name) {{
          break;
        }}
        const sizeText = decodeTarString(bytes, offset + 124, 12);
        const size = parseInt(sizeText || '0', 8) || 0;
        offset += 512;
        const fileBytes = bytes.slice(offset, offset + size);
        files.push({{ name, blob: new Blob([fileBytes], {{ type: 'image/webp' }}) }});
        offset += Math.ceil(size / 512) * 512;
      }}
      return files;
    }}

    function decodeTarString(bytes, start, length) {{
      const slice = bytes.slice(start, start + length);
      let end = 0;
      while (end < slice.length && slice[end] !== 0) {{
        end += 1;
      }}
      const view = slice.slice(0, end);
      const text = view.length ? tarDecoder.decode(view) : '';
      return text.trim();
    }}

    function getFileName(path) {{
      if (!path) {{
        return null;
      }}
      const clean = path.split('?')[0].split('#')[0].replace(/\0+/g, '');
      const parts = clean.split('/');
      const name = parts[parts.length - 1];
      return name || null;
    }}

    let searchTimer = null;
    let pendingQuery = '';
    search.addEventListener('input', () => {{
      const query = search.value.trim();
      pendingQuery = query;
      if (searchTimer) {{
        clearTimeout(searchTimer);
      }}
      if (query.length < 3) {{
        searchTimer = setTimeout(() => {{
          if (lastQuery !== '') {{
            lastQuery = '';
            render(DATA);
          }}
        }}, 300);
        return;
      }}
      searchTimer = setTimeout(() => {{
        if (pendingQuery !== query) {{
          return;
        }}
        if (query === lastQuery) {{
          return;
        }}
        lastQuery = query;
        const filtered = filterItems(query);
        render(filtered);
      }}, 150);
    }});

    function renderFilterButtons() {{
      if (!filterButtonsContainer) return;
      filterButtonsContainer.innerHTML = '';

      // Top bar: only ℹ️ and 📊
      const infoBtn = document.createElement('button');
      infoBtn.type = 'button';
      infoBtn.textContent = 'ℹ️';
      infoBtn.className = 'filter-button';
      infoBtn.title = 'Info & Settings';
      infoBtn.addEventListener('click', () => {{
        const dialog = document.getElementById('info-dialog');
        if (dialog) dialog.hidden = !dialog.hidden;
      }});
      filterButtonsContainer.appendChild(infoBtn);
      if (STATISTICS_URL) {{
        const statsBtn = document.createElement('a');
        statsBtn.href = STATISTICS_URL + '?back=' + encodeURIComponent(GALLERY_FILENAME);
        statsBtn.textContent = '📊';
        statsBtn.className = 'filter-button';
        statsBtn.title = 'Statistics';
        filterButtonsContainer.appendChild(statsBtn);
      }}

      // Filter buttons inside the info dialog
      const dialogFilters = document.getElementById('info-dialog-filters');
      if (dialogFilters) {{
        dialogFilters.innerHTML = '';
        FILTER_OPTIONS.forEach(option => {{
          const btn = document.createElement('button');
          btn.type = 'button';
          btn.textContent = option.label;
          btn.className = 'filter-button';
          if (activeFilters.has(option.key)) btn.classList.add('active');
          btn.addEventListener('click', () => toggleFilter(option.key, btn));
          dialogFilters.appendChild(btn);
        }});
      }}

      // Cache clear button in dialog
      const cacheClearBtn = document.getElementById('info-dialog-cache-clear');
      if (cacheClearBtn) {{
        cacheClearBtn.addEventListener('click', () => clearAllCaches());
      }}

      // Close button
      const infoClose = document.querySelector('.info-dialog-close');
      if (infoClose) {{
        infoClose.addEventListener('click', () => {{
          const dialog = document.getElementById('info-dialog');
          if (dialog) dialog.hidden = true;
        }});
      }}
    }}

    function toggleFilter(key, button) {{
      const isActive = activeFilters.has(key);
      if (isActive && activeFilters.size === 1) {{
        return;
      }}
      if (isActive) {{
        activeFilters.delete(key);
        button.classList.remove('active');
      }} else {{
        activeFilters.add(key);
        button.classList.add('active');
      }}
      const query = search.value.trim();
      if (query.length >= 3) {{
        const filtered = filterItems(query);
        render(filtered);
      }}
    }}

    function positionThumbPip() {{
      // positioning handled by CSS (position: sticky)
    }}

    async function showThumbPip(item) {{
      if (!modalThumbPip || !modalThumbPipImg) return;
      const fileName = getFileName(item.thumb);
      const cacheKey = fileName || item.thumb;
      const cached = thumbCache.get(cacheKey);
      if (cached) {{
        modalThumbPipImg.src = cached.objectUrl;
      }} else {{
        try {{
          const persistent = await readPersistentEntry(STORE_THUMBS, cacheKey);
          if (persistent && persistent.dataUrl) {{
            modalThumbPipImg.src = persistent.dataUrl;
          }} else {{
            modalThumbPipImg.src = item.thumb;
          }}
        }} catch (e) {{
          modalThumbPipImg.src = item.thumb;
        }}
      }}
      positionThumbPip();
      modalThumbPip.style.visibility = 'visible';
      const pipSpacer = document.getElementById('modal-pip-spacer');
      if (pipSpacer) pipSpacer.hidden = false;
    }}

    function openModal(index) {{
      if (!currentItems.length) {{
        return;
      }}
      modalIndex = index;
      const item = currentItems[index];
      showingTranslated = true;
      const debugEl = document.getElementById('modal-image-debug');
      setModalImage(item);
      modalImage.alt = item.filename;
      renderSummaryLine(item);
      modalDriveLink.href = item.viewUrl;
      if (item.originalUrl) {{
        modalOriginalLink.href = item.originalUrl;
        try {{ modalOriginalLink.title = 'Open at ' + new URL(item.originalUrl).host; }} catch (e) {{}}
        modalOriginalLink.hidden = false;
      }} else {{
        modalOriginalLink.href = '';
        modalOriginalLink.title = '';
        modalOriginalLink.hidden = true;
      }}
      setMetadataView(showingMetadata);
      populateMetadata(item);
      modal.classList.add('open');
      document.body.classList.add('modal-open');
      modal.setAttribute('aria-hidden', 'false');
      if (THUMB_PIP_ENABLED && !isMobile()) showThumbPip(item);
    }}

    function closeModal() {{
      modal.classList.remove('open');
      document.body.classList.remove('modal-open');
      modal.setAttribute('aria-hidden', 'true');
      modalIndex = -1;
      setMetadataView(false);
      if (modalThumbPip) modalThumbPip.style.visibility = 'hidden';
      const pipSpacer = document.getElementById('modal-pip-spacer');
      if (pipSpacer) pipSpacer.hidden = true;
    }}

    function moveModal(step) {{
      if (modalIndex === -1 || !currentItems.length) {{
        return;
      }}
      const next = (modalIndex + step + currentItems.length) % currentItems.length;
      openModal(next);
    }}

    function isMobile() {{
      return window.matchMedia('(max-width: 960px)').matches;
    }}

    async function setModalImage(item) {{
      resetZoom();
      const zoomControls = document.querySelector('.zoom-controls');
      if (isMobile()) {{
        if (zoomControls) zoomControls.hidden = true;
        const fileName = getFileName(item.thumb);
        const cacheKey = fileName || item.thumb;
        // 1. In-memory cache
        const cached = thumbCache.get(cacheKey);
        if (cached) {{
          modalImage.src = cached.objectUrl;
          modalImage.addEventListener('load', () => updateSummaryLineTooltip(item, modalImage.naturalWidth, modalImage.naturalHeight), {{ once: true }});
          return;
        }}
        // 2. IndexedDB
        try {{
          const persistent = await readPersistentEntry(STORE_THUMBS, cacheKey);
          if (persistent && persistent.dataUrl) {{
            modalImage.src = persistent.dataUrl;
            modalImage.addEventListener('load', () => updateSummaryLineTooltip(item, modalImage.naturalWidth, modalImage.naturalHeight), {{ once: true }});
            return;
          }}
        }} catch (e) {{}}
        // 3. Load from bundle (always wait — no server fallback)
        if (fileName && bundleMap.has(fileName)) {{
          const bundleIndex = bundleMap.get(fileName);
          const bundleName = (THUMB_BUNDLES[bundleIndex] || {{}}).bundle || `bundle#${{bundleIndex}}`;
          try {{
            await ensureBundleLoaded(bundleIndex);
            const bundleHit = thumbCache.get(cacheKey);
            if (bundleHit) {{
              modalImage.src = bundleHit.objectUrl;
              modalImage.addEventListener('load', () => updateSummaryLineTooltip(item, modalImage.naturalWidth, modalImage.naturalHeight), {{ once: true }});
              return;
            }}
            console.warn(`[thumb] modal: "${{fileName}}" not in memory cache after loading bundle ${{bundleName}}`);
          }} catch (e) {{
            console.warn(`[thumb] modal: bundle load error for "${{fileName}}" (bundle: ${{bundleName}})`, e);
          }}
        }} else {{
          if (fileName) {{
            console.warn(`[thumb] modal: "${{fileName}}" not in bundleMap — not listed in any bundle`);
          }}
        }}
        // 4. No bundle available — show missing thumbnail placeholder
        markThumbnailMissing(modalImage, `modal:${{fileName || item.thumb}}`);
      }} else {{
        if (zoomControls) zoomControls.hidden = false;
        if (USE_ORIGINAL_URL_FALLBACK && item.originalUrl) {{
          const ucUrl = resolveUcUrl(item.originalUrl);
          modalImage.src = ucUrl;
          modalImage.addEventListener('load', () => {{
            updateSummaryLineTooltip(item, modalImage.naturalWidth, modalImage.naturalHeight);
            prefetchNeighbours(modalIndex);
          }}, {{ once: true }});
        }} else {{
          const urls = resolvePreviewUrls(item.viewUrl);
          // Try fullsize cache first
          const cached = await getFullsize(urls.primary);
          if (cached) {{
            modalImage.src = cached;
            modalImage.addEventListener('load', () => {{
              updateSummaryLineTooltip(item, modalImage.naturalWidth, modalImage.naturalHeight);
              prefetchNeighbours(modalIndex);
            }}, {{ once: true }});
            return;
          }}
          // Try fetch() to store in cache
          try {{
            const response = await fetch(urls.primary, {{ mode: 'cors' }});
            if (!response.ok) throw new Error(`HTTP ${{response.status}}`);
            const blob = await response.blob();
            const objUrl = await putFullsize(urls.primary, blob);
            modalImage.src = objUrl;
            modalImage.addEventListener('load', () => {{
              updateSummaryLineTooltip(item, modalImage.naturalWidth, modalImage.naturalHeight);
              prefetchNeighbours(modalIndex);
            }}, {{ once: true }});
          }} catch (e) {{
            // CORS or network error — fall back to direct img src
            console.log(`[cache] fetch failed (${{e.message}}), falling back to img src`);
            modalImage.src = urls.primary;
            modalImage.addEventListener('load', () => {{
              updateSummaryLineTooltip(item, modalImage.naturalWidth, modalImage.naturalHeight);
              prefetchNeighbours(modalIndex);
            }}, {{ once: true }});
            modalImage.addEventListener('error', () => {{
              modalImage.src = urls.fallback;
            }}, {{ once: true }});
          }}
        }}
      }}
    }}

    function resolveUcUrl(driveUrl) {{
      const marker = '/d/';
      const idx = driveUrl.indexOf(marker);
      if (idx === -1) return driveUrl;
      const fileId = driveUrl.slice(idx + marker.length).split('/')[0];
      if (!fileId) return driveUrl;
      return `https://lh3.googleusercontent.com/d/${{fileId}}=w2000`;
    }}

    function resolvePreviewUrls(viewUrl) {{
      const marker = '/d/';
      const idx = viewUrl.indexOf(marker);
      if (idx === -1) {{
        return {{ primary: viewUrl, fallback: viewUrl }};
      }}
      const rest = viewUrl.slice(idx + marker.length);
      const fileId = rest.split('/')[0];
      if (!fileId) {{
        return {{ primary: viewUrl, fallback: viewUrl }};
      }}
      const fallback = `https://drive.google.com/uc?id=${{fileId}}&export=view`;
      const cdn = `https://lh3.googleusercontent.com/d/${{fileId}}=w2000`;
      return {{ primary: cdn, fallback }};
    }}

    function setMetadataView(showMetadata) {{
      showingMetadata = !!showMetadata;
      if (modalImagePanel) {{
        modalImagePanel.classList.toggle('hidden', showingMetadata);
      }}
      if (modalRawView) {{
        modalRawView.classList.toggle('active', showingMetadata);
      }}
      if (modalToggle) {{
        modalToggle.textContent = showingMetadata ? 'Image' : 'JSON';
      }}
      if (modalThumbPip) {{
        modalThumbPip.style.visibility = (!THUMB_PIP_ENABLED || showingMetadata) ? 'hidden' : (modal.classList.contains('open') && !isMobile() ? 'visible' : 'hidden');
      }}
    }}

    function markThumbnailMissing(img, context) {{
      if (!img) {{
        return;
      }}
      const label = context ? ` [${{context}}]` : '';
      console.warn(`[thumb] marking thumbnail unavailable${{label}}`);
      img.src = EMPTY_THUMBNAIL_SRC;
      img.alt = 'Thumbnail unavailable';
      img.classList.add('missing-thumb');
      const card = img.closest('.card');
      if (card) {{
        card.classList.add('card-missing-thumb');
      }}
    }}

    async function hydrateThumbnail(img, url) {{
      const fileName = getFileName(url);
      const cacheKey = fileName || url;
      const cached = thumbCache.get(cacheKey);
      if (cached) {{
        img.src = cached.objectUrl;
        return;
      }}
      try {{
        const persistent = await readPersistentEntry(STORE_THUMBS, cacheKey);
        if (persistent && persistent.dataUrl) {{
          thumbCache.set(cacheKey, {{ objectUrl: persistent.dataUrl, size: persistent.size }});
          thumbBytes += persistent.size || 0;
          img.src = persistent.dataUrl;
          updateCacheStats();
          return;
        }}
      }} catch (error) {{
        console.warn(`[thumb] IndexedDB read failed for "${{cacheKey}}"`, error);
      }}

      if (fileName && bundleMap.has(fileName)) {{
        const bundleIndex = bundleMap.get(fileName);
        const bundleName = (THUMB_BUNDLES[bundleIndex] || {{}}).bundle || `bundle#${{bundleIndex}}`;
        try {{
          await ensureBundleLoaded(bundleIndex);
          const bundleHit = thumbCache.get(cacheKey);
          if (bundleHit) {{
            img.src = bundleHit.objectUrl;
            return;
          }}
          console.warn(`[thumb] "${{fileName}}" not in memory cache after loading bundle ${{bundleName}} — file may be absent from tar`);
        }} catch (error) {{
          console.warn(`[thumb] bundle load error for "${{fileName}}" (bundle: ${{bundleName}})`, error);
        }}
      }} else {{
        if (fileName) {{
          console.warn(`[thumb] "${{fileName}}" not found in bundleMap — not listed in any bundle (url: ${{url}})`);
        }} else {{
          console.warn(`[thumb] could not extract filename from url: ${{url}}`);
        }}
      }}
      markThumbnailMissing(img, fileName || url);
    }}

    function populateMetadata(item) {{
      const payload = item.metadata || {{}};
      const primary = Array.isArray(payload) ? (payload[0] || {{}}) : payload;
      const ocr = primary.text_ocr || {{}};

      modalSummary.innerHTML = '';
      const summaryHeaderRow = document.createElement('div');
      summaryHeaderRow.style.cssText = 'display:flex;align-items:center;gap:0.25rem;margin:0 0 0.35rem;';
      const summaryHeader = document.createElement('h3');
      summaryHeader.textContent = 'Summary';
      summaryHeader.className = 'meta-label';
      summaryHeader.style.cssText = 'margin:0;color:#0a0a0a;font-weight:700;font-size:0.75rem;';
      summaryHeaderRow.appendChild(summaryHeader);
      const yearLabel = resolveYearLabel(item.filename, (primary.ad_metadata || {{}}).year_ad);
      if (yearLabel) {{
        const badge = document.createElement('span');
        badge.className = 'cache-indicator';
        badge.style.textTransform = 'none';
        badge.textContent = yearLabel;
        summaryHeaderRow.appendChild(badge);
      }}
      const priceInfo = primary.ad_metadata && primary.ad_metadata.price_info;
      if (priceInfo && Array.isArray(priceInfo.prices) && priceInfo.prices.length > 0) {{
        const badge = document.createElement('span');
        badge.className = 'cache-indicator';
        badge.textContent = 'PRICING';
        summaryHeaderRow.appendChild(badge);
      }}
      const summaryBody = document.createElement('p');
      summaryBody.style.marginTop = '0.45rem';
      summaryBody.textContent = primary.summary || 'No summary provided.';
      modalSummary.append(summaryHeaderRow, summaryBody);

      modalExtra.innerHTML = '';
      renderAdTextBlock(ocr);

      const spacer = document.createElement('div');
      spacer.style.marginTop = '0.7rem';
      modalExtra.appendChild(spacer);

      addMetaRow('Objects', formatList(primary.objects || []));

      if (modalRaw) {{
        modalRaw.innerHTML = highlightJson(payload);
      }}
    }}

    function renderSummaryLine(item) {{
      if (!modalSummaryLine) {{
        return;
      }}
      const payload = item.metadata || {{}};
      const primary = Array.isArray(payload) ? (payload[0] || {{}}) : payload;
      const brandsProducts = primary['brands-products'] || {{}};
      const brands = brandsProducts.brand || [];
      const subBrands = brandsProducts.sub_brands || [];
      let brandStr = brands.join(', ');
      if (brandStr && subBrands && subBrands.length) {{
        brandStr = `${{brandStr}} (${{subBrands.join(', ')}})`;
      }}
      brandStr = truncateValue(brandStr, 48);
      modalSummaryLine.innerHTML = '';
      if (isMobile()) {{
        modalSummaryLine.textContent = truncateValue(brandStr, 32) || 'Advertisement';
        modalSummaryLine.title = item.filename;
      }} else {{
        const adLabel = document.createElement('div');
        adLabel.className = 'meta-label';
        adLabel.textContent = 'Advertisement';
        adLabel.title = item.filename;
        modalSummaryLine.appendChild(adLabel);
        const brandLabel = document.createElement('div');
        brandLabel.className = 'modal-summary-brand';
        brandLabel.textContent = brandStr || '\u00a0';
        modalSummaryLine.appendChild(brandLabel);
      }}
    }}

    function buildDebugStates(item, w, h) {{
      const states = [];
      if (w && h) states.push({{ label: `${{w}}\u00d7${{h}}px`, title: 'resolution' }});
      const payload = item.metadata;
      const primary = Array.isArray(payload) ? (payload[0] || {{}}) : (payload || {{}});
      const fileMeta = primary.file_meta || {{}};
      const modelMeta = primary.model || {{}};
      if (fileMeta.filename) states.push({{ label: fileMeta.filename, title: 'filename' }});
      if (modelMeta.filename) states.push({{ label: modelMeta.filename, title: 'model' }});
      const lcVersion = modelMeta['llama.cpp.version'];
      if (lcVersion) states.push({{ label: `llama.cpp ${{lcVersion}}`, title: 'llama.cpp version' }});
      return states;
    }}

    function applyDebugState() {{
      const debugEl = document.getElementById('modal-image-debug');
      if (!debugEl || isMobile()) return;
      if (!debugStates.length) {{ debugEl.textContent = ''; return; }}
      const idx = debugStateIndex % debugStates.length;
      const state = debugStates[idx];
      debugEl.textContent = state.label;
      debugEl.title = state.title;
    }}

    function updateSummaryLineTooltip(item, w, h) {{
      const parts = [item.filename];
      if (w && h) parts.push(`${{w}}\u00d7${{h}}px`);
      const tip = parts.join(', ');
      debugStates = buildDebugStates(item, w, h);
      applyDebugState();
      if (isMobile()) {{
        modalSummaryLine.title = tip;
      }} else {{
        const adLabel = modalSummaryLine.querySelector('.meta-label');
        if (adLabel) adLabel.title = tip;
      }}
    }}

    function resolveYearLabel(filename, yearAd) {{
      const MIN = 1830, MAX = 2050;
      // Try filename pattern: <str>-<4digityear>-<str>-<str>-<2digits>.<ext>
      const fnMatch = (filename || '').match(/^[^-]+-(\\d{{4}})-[^-]+-[^-]+-\\d{{2}}\\.[^.]+$/);
      if (fnMatch) {{
        const y = parseInt(fnMatch[1], 10);
        if (y >= MIN && y <= MAX) return String(y);
      }}
      // Fall back to year_ad metadata
      const ya = yearAd || {{}};
      const y = parseInt(ya.year, 10);
      if (!y || y < MIN || y > MAX) return null;
      if (ya.estimate) {{
        return Math.floor(y / 10) * 10 + 's';
      }}
      return String(y);
    }}

    function truncateValue(value, maxLength) {{
      if (!value) {{
        return '';
      }}
      return value.length > maxLength ? `${{value.slice(0, maxLength)}}…` : value;
    }}

    function addMetaRow(label, value) {{
      const block = document.createElement('div');
      block.className = 'meta-row';
      const title = document.createElement('div');
      title.className = 'meta-label';
      title.textContent = label;
      const val = document.createElement('div');
      val.className = 'meta-value';
      val.textContent = value;
      block.append(title, val);
      modalExtra.appendChild(block);
    }}

    function formatList(items) {{
      if (!items || !items.length) {{
        return '—';
      }}
      return items.join(', ');
    }}

    function renderAdTextBlock(ocr) {{
      const block = document.createElement('div');
      block.className = 'meta-block';
      const labelRow = document.createElement('div');
      labelRow.className = 'block-label';
      const labelText = document.createElement('span');
      labelText.textContent = 'Advertisement Text';
      labelRow.appendChild(labelText);
      const toggleContainer = document.createElement('label');
      toggleContainer.className = 'toggle';
      const toggleInput = document.createElement('input');
      toggleInput.type = 'checkbox';
      toggleInput.checked = showingTranslated;
      const toggleLabel = document.createElement('span');
      const languageCode = (ocr.original_language || 'n/a').toUpperCase();
      const updateToggleLabel = () => {{
        const base = showingTranslated ? 'Translated' : 'Original';
        const suffix = showingTranslated
          ? ` (from ${{languageCode}})`
          : ` (${{languageCode}})`;
        toggleLabel.textContent = base + suffix;
      }};
      updateToggleLabel();
      toggleContainer.append(toggleInput, toggleLabel);
      labelRow.appendChild(toggleContainer);
      const textEl = document.createElement('div');
      textEl.className = 'ad-text';
      const updateText = () => {{
        if (showingTranslated) {{
          textEl.textContent = ocr.translated_text_en || 'Unavailable';
        }} else {{
          textEl.textContent = ocr.original_text || 'Unavailable';
        }}
      }};
      updateText();
      toggleInput.addEventListener('change', () => {{
        showingTranslated = toggleInput.checked;
        updateToggleLabel();
        updateText();
      }});
      block.append(labelRow, textEl);
      modalExtra.appendChild(block);
    }}

    function highlightJson(obj) {{
      let json = '';
      try {{
        json = JSON.stringify(obj, null, 2) || '';
      }} catch (error) {{
        json = String(obj || '');
      }}
      const escaped = json
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;');
      return escaped.replace(/("(?:\\u[a-fA-F0-9]{{4}}|\\[^u]|[^\\"])*"(?=\\s*:))|("(?:\\u[a-fA-F0-9]{{4}}|\\[^u]|[^\\"])*")|(\\btrue\\b|\\bfalse\\b|\\bnull\\b)|(-?\\d+(?:\\.\\d+)?(?:[eE][+-]?\\d+)?)/g, (match, key, string, boolNull, number) => {{
        if (key) {{
          return `<span class="json-key">${{key}}</span>`;
        }}
        if (string) {{
          return `<span class="json-string">${{string}}</span>`;
        }}
        if (boolNull) {{
          if (boolNull === 'null') {{
            return `<span class="json-null">null</span>`;
          }}
          return `<span class="json-boolean">${{boolNull}}</span>`;
        }}
        return `<span class="json-number">${{number}}</span>`;
      }});
    }}

    if (cacheStats) {{
      cacheStats.addEventListener('click', () => {{
        console.log('[cache] Cache stats clicked — clearing caches…');
        clearAllCaches();
      }});
    }}

    modalClose.addEventListener('click', closeModal);

    const modalRawCopy = document.getElementById('modal-raw-copy');
    if (modalRawCopy) {{
      modalRawCopy.addEventListener('click', () => {{
        const text = modalRaw ? modalRaw.textContent : '';
        navigator.clipboard.writeText(text).then(() => {{
          const prev = modalRawCopy.textContent;
          modalRawCopy.textContent = '✓';
          setTimeout(() => {{ modalRawCopy.innerHTML = '&#128203;'; }}, 1200);
        }}).catch(() => {{}});
      }});
    }}
    modal.addEventListener('click', (event) => {{
      if (event.target === modal) {{
        closeModal();
      }}
    }});

    if (modalToggle) {{
      modalToggle.addEventListener('click', () => {{
        setMetadataView(!showingMetadata);
      }});
    }}

    modalImage.addEventListener('error', () => {{
      const fallback = modalImage.dataset.fallback;
      if (fallback && modalImage.src !== fallback) {{
        modalImage.src = fallback;
      }}
    }});

    zoomSlider.addEventListener('input', () => {{
      zoomLevel = parseFloat(zoomSlider.value);
      if (zoomLevel <= 1) {{
        panX = 0;
        panY = 0;
      }}
      clampPan();
      updateTransform();
      updateCursor();
    }});

    zoomSlider.addEventListener('dblclick', resetZoom);

    const debugEl = document.getElementById('modal-image-debug');
    if (debugEl) {{
      debugEl.addEventListener('click', (e) => {{
        if (!debugStates.length) return;
        debugStateIndex = (debugStateIndex + 1) % debugStates.length;
        try {{ localStorage.setItem(DEBUG_STATE_KEY, String(debugStateIndex)); }} catch (e) {{}}
        applyDebugState();
      }});
    }}

    modalImage.addEventListener('pointerdown', (event) => {{
      if (zoomLevel <= 1) {{
        return;
      }}
      isDragging = true;
      activePointerId = event.pointerId;
      dragStartX = event.clientX;
      dragStartY = event.clientY;
      panStartX = panX;
      panStartY = panY;
      modalImage.setPointerCapture(activePointerId);
      modalImage.classList.add('dragging');
      event.preventDefault();
    }});

    modalImage.addEventListener('pointermove', (event) => {{
      if (!isDragging || event.pointerId !== activePointerId) {{
        return;
      }}
      panX = panStartX + (event.clientX - dragStartX);
      panY = panStartY + (event.clientY - dragStartY);
      clampPan();
      updateTransform();
    }});

    const endDrag = (event) => {{
      if (!isDragging || event.pointerId !== activePointerId) {{
        return;
      }}
      isDragging = false;
      modalImage.classList.remove('dragging');
      modalImage.releasePointerCapture(activePointerId);
      activePointerId = null;
    }};

    modalImage.addEventListener('pointerup', endDrag);
    modalImage.addEventListener('pointercancel', endDrag);

    const scrollTopBtn = document.getElementById('scroll-top-btn');
    if (scrollTopBtn) {{
      const searchEl = document.getElementById('search');
      window.addEventListener('scroll', () => {{
        if (!isMobile()) return;
        const searchBottom = searchEl ? searchEl.getBoundingClientRect().bottom : 0;
        scrollTopBtn.classList.toggle('scroll-top-hidden', searchBottom >= 0);
      }}, {{ passive: true }});
      scrollTopBtn.addEventListener('click', () => {{
        window.scrollTo({{ top: 0, behavior: 'smooth' }});
      }});
    }}

    window.addEventListener('resize', () => {{
      clampPan();
      updateTransform();
      // pip positioning is CSS-driven, no resize handling needed
    }});

    window.addEventListener('keydown', (event) => {{
      if (!modal.classList.contains('open')) {{
        return;
      }}
      if (event.key === 'Escape') {{
        closeModal();
      }} else if (event.key === 'ArrowRight') {{
        event.preventDefault();
        moveModal(1);
      }} else if (event.key === 'ArrowLeft') {{
        event.preventDefault();
        moveModal(-1);
      }}
    }});

    function updateCacheStats() {{
      const totalBytes = persistentThumbBytes + persistentFullBytes;
      const mb = (totalBytes / (1024 * 1024)).toFixed(0);
      if (cacheStats) {{
        cacheStats.textContent = `Cache: ${{persistentFullCount}} imgs, ${{persistentThumbCount}} thumbnails. ${{mb}} MB`;
      }}
      const dialogLabel = document.getElementById('info-dialog-cache-label');
      if (dialogLabel) {{
        dialogLabel.textContent = `Cache: ${{mb}} MB`;
      }}
    }}

    function formatBytes(bytes) {{
      if (!bytes) {{
        return '0 B';
      }}
      const units = ['B', 'KB', 'MB', 'GB'];
      let idx = 0;
      let value = bytes;
      while (value >= 1024 && idx < units.length - 1) {{
        value /= 1024;
        idx += 1;
      }}
      return `${{value.toFixed(value >= 10 ? 0 : 1)}} ${{units[idx]}}`;
    }}

    function blobToDataUrl(blob) {{
      return new Promise((resolve, reject) => {{
        const reader = new FileReader();
        reader.onload = () => resolve(reader.result);
        reader.onerror = () => reject(reader.error);
        reader.readAsDataURL(blob);
      }});
    }}

    async function clearAllCaches() {{
      console.log('[cache] Clear requested');
      const prevLive = thumbCache.size;
      const prevPersistent = persistentThumbCount;
      const prevFull = persistentFullCount;
      thumbCache.clear();
      bundlePromises.clear();
      thumbBytes = 0;
      persistentThumbCount = 0;
      persistentThumbBytes = 0;
      for (const objUrl of fullsizeMemCache.values()) URL.revokeObjectURL(objUrl);
      fullsizeMemCache.clear();
      persistentFullCount = 0;
      persistentFullBytes = 0;
      console.log(`[cache] In-memory cache cleared (${{prevLive}} thumb entries)`);
      updateCacheStats();
      try {{
        const db = await dbPromise;
        if (db) {{
          await clearStore(db, STORE_THUMBS);
          console.log(`[cache] IndexedDB thumbs cleared (${{prevPersistent}} entries)`);
          if (db.objectStoreNames.contains(STORE_FULLSIZE)) {{
            await clearStore(db, STORE_FULLSIZE);
            console.log(`[cache] IndexedDB fullsize cleared (${{prevFull}} entries)`);
          }}
          if (db.objectStoreNames.contains(STORE_HASHES)) {{
            await clearStore(db, STORE_HASHES);
            console.log('[cache] IndexedDB bundle hashes cleared');
          }}
        }} else {{
          console.log('[cache] IndexedDB not available, skipped');
        }}
      }} catch (error) {{
        console.warn('[cache] Failed to clear persistent cache', error);
      }}
      updateCacheStats();
      console.log('[cache] Done');
    }}

    function clearStore(db, storeName) {{
      return new Promise((resolve, reject) => {{
        const tx = db.transaction(storeName, 'readwrite');
        const store = tx.objectStore(storeName);
        store.clear();
        tx.oncomplete = () => resolve();
        tx.onabort = () => reject(tx.error || new Error('IndexedDB transaction aborted'));
        tx.onerror = () => reject(tx.error || new Error('IndexedDB transaction failed'));
      }});
    }}

    function openDatabase() {{
      if (!('indexedDB' in window)) return Promise.resolve(null);
      return new Promise((resolve, reject) => {{
        const request = indexedDB.open(DB_NAME, DB_VERSION);
        request.onupgradeneeded = (event) => {{
          const db = request.result;
          if (!db.objectStoreNames.contains(STORE_THUMBS)) {{
            db.createObjectStore(STORE_THUMBS, {{ keyPath: 'url' }});
          }}
          if (!db.objectStoreNames.contains(STORE_FULLSIZE)) {{
            const store = db.createObjectStore(STORE_FULLSIZE, {{ keyPath: 'url' }});
            store.createIndex('accessed', 'accessed', {{ unique: false }});
          }}
          if (!db.objectStoreNames.contains(STORE_HASHES)) {{
            db.createObjectStore(STORE_HASHES, {{ keyPath: 'bundle' }});
          }}
        }};
        request.onsuccess = () => resolve(request.result);
        request.onerror = () => reject(request.error);
      }});
    }}

    async function initializePersistentStats(db) {{
      try {{
        const stores = db.objectStoreNames.contains(STORE_FULLSIZE)
          ? [STORE_THUMBS, STORE_FULLSIZE]
          : [STORE_THUMBS];
        const tx = db.transaction(stores, 'readonly');
        let thumbCount = 0, thumbBytes = 0, fullCount = 0, fullBytes = 0;
        const countStore = (storeName, onCount, onBytes) => new Promise((res) => {{
          const req = tx.objectStore(storeName).openCursor();
          req.onsuccess = (e) => {{
            const cursor = e.target.result;
            if (!cursor) {{ res(); return; }}
            onCount(); onBytes(cursor.value.size || 0);
            cursor.continue();
          }};
          req.onerror = () => res();
        }});
        await countStore(STORE_THUMBS, () => thumbCount++, (b) => thumbBytes += b);
        if (stores.includes(STORE_FULLSIZE)) {{
          await countStore(STORE_FULLSIZE, () => fullCount++, (b) => fullBytes += b);
        }}
        persistentThumbCount = thumbCount;
        persistentThumbBytes = thumbBytes;
        persistentFullCount = fullCount;
        persistentFullBytes = fullBytes;
        updateCacheStats();
      }} catch (error) {{
        console.warn('Failed to read IndexedDB stats', error);
      }}
    }}

    async function readPersistentEntry(storeName, key) {{
      const db = await dbPromise;
      if (!db) return null;
      return new Promise((resolve, reject) => {{
        const tx = db.transaction(storeName, 'readonly');
        const store = tx.objectStore(storeName);
        const request = store.get(key);
        request.onsuccess = () => resolve(request.result || null);
        request.onerror = () => reject(request.error);
      }});
    }}

    async function putPersistentEntry(storeName, record) {{
      const db = await dbPromise;
      if (!db) return false;
      return new Promise((resolve, reject) => {{
        const tx = db.transaction(storeName, 'readwrite');
        const store = tx.objectStore(storeName);
        const getReq = store.get(record.url);
        getReq.onsuccess = () => {{
          const existed = !!getReq.result;
          store.put(record);
          tx.oncomplete = () => resolve(existed);
        }};
        tx.onabort = () => reject(tx.error || new Error('IndexedDB transaction aborted'));
        tx.onerror = () => reject(tx.error || new Error('IndexedDB transaction failed'));
      }});
    }}

    async function getFullsize(url) {{
      // 1. In-memory blob URL
      if (fullsizeMemCache.has(url)) return fullsizeMemCache.get(url);
      // 2. IndexedDB — stored as ArrayBuffer, recreate blob URL
      try {{
        const db = await dbPromise;
        if (db && db.objectStoreNames.contains(STORE_FULLSIZE)) {{
          const record = await new Promise((res, rej) => {{
            const tx = db.transaction(STORE_FULLSIZE, 'readwrite');
            const store = tx.objectStore(STORE_FULLSIZE);
            const req = store.get(url);
            req.onsuccess = () => {{
              if (req.result) {{
                req.result.accessed = Date.now();
                store.put(req.result);
              }}
              tx.oncomplete = () => res(req.result || null);
            }};
            req.onerror = () => rej(req.error);
          }});
          if (record && record.buffer) {{
            const objUrl = URL.createObjectURL(new Blob([record.buffer], {{ type: record.mime || 'image/jpeg' }}));
            fullsizeMemCache.set(url, objUrl);
            return objUrl;
          }}
        }}
      }} catch (e) {{}}
      return null;
    }}

    async function putFullsize(url, blob) {{
      // Create session blob URL for immediate display
      const objUrl = URL.createObjectURL(blob);
      fullsizeMemCache.set(url, objUrl);
      // Persist as ArrayBuffer so it survives page reload
      try {{
        const db = await dbPromise;
        if (!db || !db.objectStoreNames.contains(STORE_FULLSIZE)) return objUrl;
        const buffer = await blob.arrayBuffer();
        const record = {{ url, buffer, mime: blob.type, size: blob.size, accessed: Date.now() }};
        await new Promise((res, rej) => {{
          const tx = db.transaction(STORE_FULLSIZE, 'readwrite');
          const store = tx.objectStore(STORE_FULLSIZE);
          store.put(record);
          tx.oncomplete = () => res();
          tx.onerror = () => rej(tx.error);
        }});
        persistentFullCount += 1;
        persistentFullBytes += blob.size;
        updateCacheStats();
        await evictFullsize();
      }} catch (e) {{
        console.warn('[cache] Failed to store fullsize image', e);
      }}
      return objUrl;
    }}

    async function evictFullsize() {{
      try {{
        const db = await dbPromise;
        if (!db || !db.objectStoreNames.contains(STORE_FULLSIZE)) return;
        const all = await new Promise((res, rej) => {{
          const tx = db.transaction(STORE_FULLSIZE, 'readonly');
          const req = tx.objectStore(STORE_FULLSIZE).index('accessed').getAll();
          req.onsuccess = () => res(req.result);
          req.onerror = () => rej(req.error);
        }});
        if (all.length <= FULLSIZE_MAX) return;
        // Sort oldest first (index already ordered but be safe)
        all.sort((a, b) => a.accessed - b.accessed);
        const toDelete = all.slice(0, all.length - FULLSIZE_MAX);
        await new Promise((res, rej) => {{
          const tx = db.transaction(STORE_FULLSIZE, 'readwrite');
          const store = tx.objectStore(STORE_FULLSIZE);
          toDelete.forEach((r) => {{
            store.delete(r.url);
            persistentFullCount = Math.max(0, persistentFullCount - 1);
            persistentFullBytes = Math.max(0, persistentFullBytes - (r.size || 0));
          }});
          tx.oncomplete = () => {{ updateCacheStats(); res(); }};
          tx.onerror = () => rej(tx.error);
        }});
        console.log(`[cache] Evicted ${{toDelete.length}} fullsize entries`);
      }} catch (e) {{
        console.warn('[cache] Eviction failed', e);
      }}
    }}

    async function prefetchNeighbours(index) {{
      if (isMobile()) return;
      if (USE_ORIGINAL_URL_FALLBACK) return;
      const neighbours = [
        (index - 1 + currentItems.length) % currentItems.length,
        (index + 1) % currentItems.length,
      ].filter(i => i !== index);
      for (const i of neighbours) {{
        const item = currentItems[i];
        if (!item) continue;
        const urls = resolvePreviewUrls(item.viewUrl);
        if (fullsizeMemCache.has(urls.primary)) continue;
        try {{
          const existing = await getFullsize(urls.primary);
          if (existing) continue;
          const response = await fetch(urls.primary, {{ mode: 'cors' }});
          if (!response.ok) continue;
          const blob = await response.blob();
          await putFullsize(urls.primary, blob);
          console.log(`[cache] prefetched ${{item.filename}}`);
        }} catch (e) {{
          // silently skip — prefetch is best-effort
        }}
      }}
    }}

    function resetZoom() {{
      zoomLevel = 1;
      panX = 0;
      panY = 0;
      zoomSlider.value = '1';
      updateTransform();
      updateCursor();
    }}

    function updateTransform() {{
      modalImage.style.transform = `translate(${{panX}}px, ${{panY}}px) scale(${{zoomLevel}})`;
    }}

    function updateCursor() {{
      if (zoomLevel > 1) {{
        modalImage.classList.add('can-pan');
      }} else {{
        modalImage.classList.remove('can-pan');
        modalImage.classList.remove('dragging');
      }}
    }}

    function clampPan() {{
      if (!imageStage) {{
        return;
      }}
      const width = imageStage.clientWidth || 0;
      const height = imageStage.clientHeight || 0;
      const maxX = (width * (zoomLevel - 1)) / 2;
      const maxY = (height * (zoomLevel - 1)) / 2;
      if (maxX <= 0) {{
        panX = 0;
      }} else {{
        panX = Math.min(maxX, Math.max(-maxX, panX));
      }}
      if (maxY <= 0) {{
        panY = 0;
      }} else {{
        panY = Math.min(maxY, Math.max(-maxY, panY));
      }}
    }}
  </script>
</body>
</html>
"""


def load_thumbnail_bundles(thumbnails_root: Path, output_parent: Path) -> List[dict]:
    bundles = []
    thumbnails_dir = thumbnails_root
    if not thumbnails_dir.exists():
        return bundles
    for manifest in sorted(thumbnails_dir.glob("thumbnails-*.tar.json")):
        try:
            data = json.loads(manifest.read_text())
        except Exception:
            continue
        bundle_name = data.get("bundle")
        files = data.get("files") or []
        if not bundle_name:
            continue
        bundle_path = Path(os.path.relpath(thumbnails_dir / bundle_name, output_parent)).as_posix()
        bundles.append(
            {
                "bundle": bundle_path,
                "files": files,
            }
        )
    return bundles


def derive_search_targets(metadata: Any, filename: str) -> dict:
    if isinstance(metadata, list):
        entry = metadata[0] if metadata else {}
    elif isinstance(metadata, dict):
        entry = metadata
    else:
        entry = {}

    brands_section = entry.get("brands-products") or {}
    brands = brands_section.get("brand") or []
    sub_brands = brands_section.get("sub_brands") or []
    watch_types = brands_section.get("watch_categories") or []

    text_ocr = entry.get("text_ocr") or {}
    objects = entry.get("objects") or []
    shapes = entry.get("case_shapes") or []
    summary = entry.get("summary") or ''

    return {
        "brand": _combine_terms(brands, sub_brands),
        "filename": filename.lower(),
        "objects": _combine_terms(objects),
        "summary": _combine_terms([summary]),
        "text": _combine_terms([
            text_ocr.get("translated_text_en"),
            text_ocr.get("original_text"),
        ]),
        "shape": _combine_terms(shapes),
        "watchType": _combine_terms(watch_types),
    }


def _combine_terms(*groups) -> str:
    terms = []
    for group in groups:
        if not group:
            continue
        if isinstance(group, str):
            terms.append(group.lower())
        elif isinstance(group, list):
            for item in group:
                if isinstance(item, str):
                    terms.append(item.lower())
    return " ".join(terms)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except RuntimeError as exc:
        print(f"! {exc}", file=sys.stderr)
        sys.exit(1)
