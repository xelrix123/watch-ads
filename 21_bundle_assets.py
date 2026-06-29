#!/usr/bin/env python3
"""Bundle files from a directory into .tar packages with sidecar JSON manifests."""

import argparse
import glob
import gzip
import json
import os
import sys
import tarfile
import xxhash


def get_existing_bundles(input_dir, prefix="thumbnails"):
    tars = sorted(glob.glob(os.path.join(input_dir, f"{prefix}-[0-9][0-9].tar")))
    jsons = sorted(glob.glob(os.path.join(input_dir, f"{prefix}-[0-9][0-9].tar.json")))
    hashes = glob.glob(os.path.join(input_dir, "asset-hashes.txt"))
    return tars + jsons + hashes


def xxhash_file(path: str) -> str:
    h = xxhash.xxh64()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def main():
    parser = argparse.ArgumentParser(description="Bundle files into .tar packages with JSON sidecars.")
    parser.add_argument("--input-dir", required=True, help="Directory containing files to bundle")
    parser.add_argument("--metadata", required=True, help="Path to metadata.json[.gz] to determine display order and update with bundle info")
    parser.add_argument("--bundle-size", type=int, default=500, help="Files per tar bundle (default: 500)")
    parser.add_argument("--first-bundle-size", type=int, default=25, help="Number of files in the first bundle for fast initial load (default: 25)")
    parser.add_argument("--overwrite", action="store_true", help="Remove existing bundles before creating new ones")
    args = parser.parse_args()

    input_dir = args.input_dir
    if not os.path.isdir(input_dir):
        print(f"Error: {input_dir} is not a directory", file=sys.stderr)
        sys.exit(1)

    # Load metadata to get display order
    try:
        opener = gzip.open if args.metadata.endswith(".gz") else open
        with opener(args.metadata, "rt") as f:
            metadata = json.load(f)
    except FileNotFoundError:
        print(f"Error: metadata file not found: {args.metadata}", file=sys.stderr)
        sys.exit(1)
    entries = metadata.get("entries", [])
    if not entries:
        print("Error: no entries found in metadata.json", file=sys.stderr)
        sys.exit(1)

    # Build ordered list of thumbnail basenames from metadata display order
    ordered = []
    seen = set()
    for entry in entries:
        thumb = entry.get("thumb", "")
        basename = os.path.basename(thumb)
        if basename and basename not in seen:
            ordered.append(basename)
            seen.add(basename)

    # Any files in input_dir not referenced in metadata go at the end
    all_files_set = set(
        f for f in os.listdir(input_dir)
        if os.path.isfile(os.path.join(input_dir, f))
        and not f.startswith("thumbnails-")
        and f != "asset-hashes.txt"
    )
    extras = sorted(all_files_set - seen)
    ordered = [f for f in ordered if f in all_files_set] + extras

    if not ordered:
        print("No files found to bundle.", file=sys.stderr)
        sys.exit(1)

    # Check for existing bundles
    existing = get_existing_bundles(input_dir)
    if existing:
        if not args.overwrite:
            print("Error: existing bundle files found:", file=sys.stderr)
            for f in existing:
                print(f"  {f}", file=sys.stderr)
            print("\nUse --overwrite to remove them first.", file=sys.stderr)
            sys.exit(1)
        else:
            for f in existing:
                os.remove(f)
                print(f"Removed {f}")

    # Chunk into bundles: first bundle uses --first-bundle-size, rest use --bundle-size
    chunks = []
    first = ordered[:args.first_bundle_size]
    rest = ordered[args.first_bundle_size:]
    if first:
        chunks.append(first)
    chunks += [rest[i:i + args.bundle_size] for i in range(0, len(rest), args.bundle_size)]

    print(f"Bundling {len(ordered)} files into {len(chunks)} tar packages (first bundle: {args.first_bundle_size}, rest: {args.bundle_size}/bundle)")

    for idx, chunk in enumerate(chunks):
        tar_name = f"thumbnails-{idx:02d}.tar"
        json_name = f"{tar_name}.json"
        tar_path = os.path.join(input_dir, tar_name)
        json_path = os.path.join(input_dir, json_name)

        with tarfile.open(tar_path, "w") as tar:
            for filename in chunk:
                tar.add(os.path.join(input_dir, filename), arcname=filename)

        manifest = {"bundle": tar_name, "files": chunk}
        with open(json_path, "w") as f:
            json.dump(manifest, f, indent=2)

        tar_size = os.path.getsize(tar_path)
        print(f"  {tar_name}: {len(chunk)} files, {tar_size / 1024:.0f} KB")

    # Write asset-hashes.txt
    hashes_path = os.path.join(input_dir, "asset-hashes.txt")
    with open(hashes_path, "w") as f:
        for idx in range(len(chunks)):
            tar_name = f"thumbnails-{idx:02d}.tar"
            tar_path = os.path.join(input_dir, tar_name)
            digest = xxhash_file(tar_path)
            f.write(f"thumbnails/{tar_name}:{digest}\n")
    print(f"  asset-hashes.txt written ({len(chunks)} entries)")

    # Update metadata.json / metadata.json.gz with the new bundle list
    bundles = []
    metadata_dir = os.path.dirname(os.path.abspath(args.metadata))
    for idx, chunk in enumerate(chunks):
        tar_name = f"thumbnails-{idx:02d}.tar"
        rel_path = os.path.relpath(os.path.join(input_dir, tar_name), metadata_dir).replace(os.sep, "/")
        bundles.append({"bundle": rel_path, "files": chunk})
    metadata["bundles"] = bundles
    metadata_text = json.dumps(metadata, ensure_ascii=False, separators=(",", ":"))
    # Write both .json and .json.gz alongside wherever --metadata pointed
    base = args.metadata
    if base.endswith(".gz"):
        base = base[:-3]
    json_path = base if base.endswith(".json") else base + ".json"
    gz_path = json_path + ".gz"
    with open(json_path, "w", encoding="utf-8") as f:
        f.write(metadata_text)
    with gzip.open(gz_path, "wb") as f:
        f.write(metadata_text.encode("utf-8"))
    print(f"  metadata updated with {len(bundles)} bundle(s) -> {os.path.basename(json_path)} + {os.path.basename(gz_path)}")

    print("Done.")


if __name__ == "__main__":
    main()
