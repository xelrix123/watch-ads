#!/usr/bin/env python3
"""Build a local-filesystem image index JSON for use with build_simple_gallery.py."""

from __future__ import annotations

import argparse
import json
import mimetypes
import sys
import time
from pathlib import Path

import xxhash

def log(msg: str) -> None:
    print(msg, file=sys.stderr)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Index local image files and produce a JSON manifest."
    )
    parser.add_argument(
        "--input-dir",
        type=Path,
        required=True,
        help="Root directory to scan for images",
    )
    parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="Output JSON file path",
    )
    parser.add_argument(
        "--web-image-root",
        required=True,
        help="Base URL under which the input-dir tree is served (no trailing slash)",
    )
    parser.add_argument(
        "--must-have-sidecar",
        action="store_true",
        help="Skip images that don't have a valid JSON sidecar (<image>.<ext>.json)",
    )
    parser.add_argument(
        "--web-image-ext",
        metavar="EXT",
        help="Replace image file extension with this one in web_filepath (e.g. webp)",
    )
    return parser.parse_args()


def xxhash_file(path: Path) -> str:
    h = xxhash.xxh64()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def guess_mime(path: Path) -> str:
    mime, _ = mimetypes.guess_type(path.name)
    return mime or "application/octet-stream"


IMAGE_EXTENSIONS = {"jpg", "jpeg", "avif", "webp", "png", "gif", "jxl", "tif", "tiff"}


def web_filepath_with_ext(filepath: str, new_ext: str) -> str:
    p = Path(filepath)
    if p.suffix.lstrip(".").lower() in IMAGE_EXTENSIONS:
        return str(p.with_suffix("." + new_ext.lstrip(".")))
    return filepath


def main() -> int:
    args = parse_args()

    input_dir = args.input_dir.resolve()
    if not input_dir.is_dir():
        print(f"! input-dir does not exist or is not a directory: {input_dir}", file=sys.stderr)
        return 1

    web_root = args.web_image_root.rstrip("/")

    log(f"Scanning {input_dir} ...")
    files = []
    max_depth = 0

    for path in sorted(input_dir.rglob("*")):
        if not path.is_file():
            continue

        rel = path.relative_to(input_dir)
        mime = guess_mime(path)

        if not mime.startswith("image/"):
            log(f"  skip (not image, {mime}): {rel.as_posix()}")
            continue

        if args.must_have_sidecar:
            sidecar = path.parent / (path.name + ".json")
            if not sidecar.is_file():
                log(f"  skip (no sidecar): {rel.as_posix()}")
                continue
            try:
                sidecar_data = json.loads(sidecar.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                log(f"  skip (invalid sidecar JSON): {rel.as_posix()}")
                continue
            if isinstance(sidecar_data, list) and len(sidecar_data) > 1:
                log(f"  [WARN] {sidecar.name}: has {len(sidecar_data)} objects in array (expected 1), using first")

        depth = len(rel.parts)  # file itself counts as depth 1
        if depth > max_depth:
            max_depth = depth

        filepath = rel.as_posix()
        digest = xxhash_file(path)
        sidecar_path = path.parent / (path.name + ".json")

        entry = {
            "filepath": filepath,
            "xxhash": digest,
            "mimeType": mime,
        }
        if args.web_image_ext:
            entry["web_filepath"] = web_filepath_with_ext(filepath, args.web_image_ext)
        if sidecar_path.is_file():
            entry["sidecar"] = str(sidecar_path)

        files.append(entry)

    index = {
        "webRoot": web_root,
        "inputDir": str(input_dir),
        "maxDepth": max_depth,
        "fileCount": len(files),
        "generatedAtEpoch": int(time.time()),
        "files": files,
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(index, ensure_ascii=False, indent=2))
    log(f"Indexed {len(files)} files -> {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
