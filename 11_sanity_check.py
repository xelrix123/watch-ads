#!/usr/bin/env python3
"""Sanity-check JSON sidecars produced by 10_run_watchad_batch.py."""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import List, Tuple


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Check JSON sidecars for suspicious entries (zero watches, empty OCR)."
    )
    parser.add_argument("--input-dir", required=True, type=Path, help="Directory to scan for .json sidecar files")
    parser.add_argument("--remove-invalid-sidecars", action="store_true", help="Delete suspicious sidecar files")
    parser.add_argument("--filename-check", action="store_true", help="Warn if filename doesn't match <string>-<4digityear>-<string>-<string>-<twodigitnumber>.<extension>")
    return parser.parse_args()


FILENAME_PATTERN = re.compile(r'^.+-\d{4}-.+-.+-\d{2}\.[^.]+$')


def check_filename(path: Path) -> bool:
    """Return True if filename matches the expected pattern."""
    return bool(FILENAME_PATTERN.match(path.name))


def is_suspicious(entries: list) -> Tuple[bool, List[str]]:
    """Return (suspicious, reasons) for a sidecar's entries list."""
    if not entries:
        return True, ["empty entries list"]
    reasons = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        zero_watches = entry.get("count_watches") == 0
        ocr = entry.get("text_ocr", {})
        empty_ocr = isinstance(ocr, dict) and ocr.get("original_text") == ""
        if zero_watches and empty_ocr:
            reasons.append("count_watches is 0 and text_ocr.original_text is empty")
    return bool(reasons), reasons


def main() -> None:
    args = parse_args()
    args.input_dir = args.input_dir.expanduser()
    if not args.input_dir.exists():
        print(f"[ERROR] {args.input_dir} does not exist", file=sys.stderr)
        sys.exit(1)

    all_json = sorted(args.input_dir.rglob("*.json"))
    crop_sidecars = [f for f in all_json if f.name.endswith(".crop.json")]
    sidecar_files = [f for f in all_json if not f.name.endswith(".crop.json")]
    if not sidecar_files:
        print("[INFO] No JSON sidecar files found.")
        if crop_sidecars:
            print(f"[INFO] {len(crop_sidecars)} .crop.json sidecar(s) ignored.")
        return

    suspicious: List[Tuple[Path, List[str]]] = []
    multi_entry: List[Path] = []
    missing_sources: List[Path] = []
    bad_filenames: List[Path] = []

    for sidecar in sidecar_files:
        source = sidecar.with_suffix("")  # strip .json to get foo.mp4
        if args.filename_check:
            if not source.exists():
                missing_sources.append(source)
                print(f"[WARN] source file missing: {source}")
            elif not check_filename(source):
                bad_filenames.append(source)
                print(f"[WARN] filename mismatch: {source}")
        try:
            data = json.loads(sidecar.read_text(encoding="utf-8"))
        except Exception as e:
            suspicious.append((sidecar, [f"invalid JSON: {e}"]))
            continue
        if not isinstance(data, list):
            suspicious.append((sidecar, ["root is not a list"]))
            continue
        if len(data) > 1:
            multi_entry.append(sidecar)
            print(f"[WARN] {sidecar}: has {len(data)} entries (expected 1)")
        flag, reasons = is_suspicious(data)
        if flag:
            suspicious.append((sidecar, reasons))

    if suspicious:
        print()
        for sidecar, reasons in suspicious:
            print(f"  {sidecar}")
            for r in reasons:
                print(f"    - {r}")

    if args.remove_invalid_sidecars:
        print()
        for sidecar, _ in suspicious:
            sidecar.unlink()
            print(f"[REMOVED] {sidecar}")

    if args.filename_check:
        n_ok = len(sidecar_files) - len(missing_sources) - len(bad_filenames)
        print(f"\nFilename check: {n_ok} match, {len(bad_filenames)} mismatch, {len(missing_sources)} source file(s) missing (+ {len(crop_sidecars)} .crop.json ignored).")

    print(f"Checked {len(sidecar_files)} sidecar(s). Suspicious: {len(suspicious)}. Multi-entry: {len(multi_entry)}. Ignored: {len(crop_sidecars)} .crop.json sidecar(s).")


if __name__ == "__main__":
    main()
