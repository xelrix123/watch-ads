#!/usr/bin/env python3
"""Run the single-ad prompt for each PNG and write per-file JSON sidecars."""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Iterable, List, Optional
import xxhash

ROOT_DIR = Path(__file__).resolve().parent

# ANSI color helpers (disabled when not a tty)
def _supports_color() -> bool:
    return hasattr(sys.stderr, "isatty") and sys.stderr.isatty()

def _c(code: str, text: str) -> str:
    if not _supports_color():
        return text
    return f"\033[{code}m{text}\033[0m"

def blue(text: str) -> str:   return _c("34", text)
def green(text: str) -> str:  return _c("32", text)
def yellow(text: str) -> str: return _c("33", text)
def red(text: str) -> str:    return _c("31", text)

def tag(color_fn, label: str, rest: str) -> str:
    return f"[{color_fn(label)}]{rest}"
DEFAULT_PROMPT = ROOT_DIR / "prompts" / "prompt-watch-ad-ocr-single.txt"
DEFAULT_MODEL = ROOT_DIR / "models" / "Qwen3.6-35B-A3B-UD-Q8_K_XL.gguf"
DEFAULT_MMPROJ = ROOT_DIR / "models" / "mmproj-Qwen36-F32.gguf"
DEFAULT_LLAMA_BIN = ROOT_DIR / "llama.cpp" / "llama-mtmd-cli"
DEFAULT_GEMMA_MODEL = ROOT_DIR / "models" / "gemma-4-31B-it-Q8_0.gguf"
DEFAULT_GEMMA_MMPROJ = ROOT_DIR / "models" / "mmproj-gemma-4-31B-it-Q8_0.gguf"

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run llama-mtmd-cli for each PNG under --input-dir and emit per-file JSON sidecars."
        )
    )
    parser.add_argument("--input-dir", required=True, type=Path, help="Folder that holds input PNG files")
    parser.add_argument("--model", type=Path, default=DEFAULT_MODEL, help="Path to Qwen 3.5 GGUF model")
    parser.add_argument("--mmproj", type=Path, default=DEFAULT_MMPROJ, help="Path to matching mmproj file")
    parser.add_argument("--llama-bin", type=Path, default=DEFAULT_LLAMA_BIN, help="Path to llama-mtmd-cli executable")
    parser.add_argument("--prompt", type=Path, default=DEFAULT_PROMPT, help="Prompt file to feed into the model")
    parser.add_argument("--batch-size", type=int, default=4096)
    parser.add_argument("--max-tokens", type=int, default=16384, help="Max tokens to generate per call")
    parser.add_argument("--ctx-size", type=int, default=32768)
    parser.add_argument("--temp", type=float, default=0.0)
    parser.add_argument("--top-k", type=int, default=1)
    parser.add_argument("--top-p", type=float, default=1.0)
    parser.add_argument("--repeat-penalty", type=float, default=1.1, help="Repetition penalty (1.0 = disabled)")
    parser.add_argument("--ngl", default="all", help="Value for -ngl flag")
    parser.add_argument("--gemma-model", type=Path, default=DEFAULT_GEMMA_MODEL, help="Path to Gemma GGUF model (fallback)")
    parser.add_argument("--gemma-mmproj", type=Path, default=DEFAULT_GEMMA_MMPROJ, help="Path to Gemma mmproj file")
    parser.add_argument(
        "--extensions",
        nargs="+",
        default=[".png",".webp"],
        help="Image extensions to include (case-insensitive)",
    )
    parser.add_argument(
        "--force-reanalysis",
        action="store_true",
        help="Re-run inference even if a valid JSON sidecar already exists",
    )
    parser.add_argument(
        "--compact",
        action="store_true",
        help="Write compact (single-line) JSON sidecars instead of pretty-printed",
    )
    return parser.parse_args()


def check_llama_bin(llama_bin: Path) -> None:
    if not llama_bin.exists() or not os.access(llama_bin, os.X_OK):
        print(f"[ERROR] llama binary not found or not executable: {llama_bin}", file=sys.stderr)
        sys.exit(1)
    try:
        proc = subprocess.run(
            [str(llama_bin), "--version"],
            check=False,
            capture_output=True,
        )
        output = (proc.stdout + proc.stderr).decode("utf-8", errors="ignore").strip()
        version_line = next((l for l in output.splitlines() if "version" in l.lower()), output.splitlines()[0] if output else "unknown")
        print(f"[INFO] llama binary: {llama_bin} ({version_line.strip()})", file=sys.stderr)
    except Exception as exc:
        print(f"[WARN] Could not determine llama binary version: {exc}", file=sys.stderr)


def check_magick() -> None:
    if shutil.which("magick") is None:
        print("[ERROR] 'magick' (ImageMagick) not found in PATH — required for non-PNG conversion", file=sys.stderr)
        sys.exit(1)


def file_xxhash(path: Path) -> str:
    return xxhash.xxh64(path.read_bytes()).hexdigest()


IMAGE_MAX_PIXELS = 4_194_304  # matches load_hparams: image_max_pixels in the model


def convert_to_png(image_path: Path, tmp_dir: str, resize: bool = False) -> Path:
    """Convert image_path to a temporary PNG and return its path."""
    out = Path(tmp_dir) / (image_path.stem + "_conv.png")
    cmd = ["magick", str(image_path)]
    if resize:
        cmd += ["-resize", f"{IMAGE_MAX_PIXELS}@>"]
    cmd.append(str(out))
    proc = subprocess.run(cmd, check=False, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(
            f"magick conversion failed for {image_path}: {proc.stderr.strip()}"
        )
    return out


def load_prompt(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def list_images(root: Path, extensions: Iterable[str]) -> List[Path]:
    normalized = {ext.lower() for ext in extensions}
    paths: List[Path] = []
    for entry in sorted(root.rglob("*")):
        if entry.is_file() and entry.suffix.lower() in normalized:
            paths.append(entry)
    return paths


ModelOverride = Optional[dict]  # keys: model, mmproj, jinja (bool)


def build_command(args: argparse.Namespace, image_path: Path, prompt: str,
                  temp: Optional[float] = None, top_k: Optional[int] = None,
                  top_p: Optional[float] = None,
                  model_override: ModelOverride = None) -> List[str]:
    model = model_override["model"] if model_override else args.model
    mmproj = model_override["mmproj"] if model_override else args.mmproj
    use_jinja = model_override["jinja"] if model_override else False
    cmd = [
        str(args.llama_bin),
        "--no-warmup",
        "--batch-size",
        str(args.batch_size),
        "-m",
        str(model),
        "--mmproj",
        str(mmproj),
        "-ngl",
        str(args.ngl),
        "--ctx-size",
        str(args.ctx_size),
        "--image",
        str(image_path),
        "-p",
        prompt,
        "--temp",
        str(temp if temp is not None else args.temp),
        "--top-k",
        str(top_k if top_k is not None else args.top_k),
        "--top-p",
        str(top_p if top_p is not None else args.top_p),
        "--repeat-penalty",
        str(args.repeat_penalty),
        "-n",
        str(args.max_tokens),
    ]
    if use_jinja:
        cmd.append("--jinja")
    return cmd


def run_model(args: argparse.Namespace, image_path: Path, prompt: str,
              temp: Optional[float] = None, top_k: Optional[int] = None,
              top_p: Optional[float] = None,
              model_override: ModelOverride = None) -> Optional[tuple[str, str]]:
    cmd = build_command(args, image_path, prompt, temp=temp, top_k=top_k, top_p=top_p,
                        model_override=model_override)
    try:
        proc = subprocess.run(
            cmd,
            check=False,
            capture_output=True,
        )
    except FileNotFoundError:
        print(f"[ERROR] llama executable not found at {args.llama_bin}", file=sys.stderr)
        return None
    if proc.returncode != 0:
        print(
            f"[ERROR] llama-mtmd-cli failed for {image_path} (exit {proc.returncode}): {proc.stderr.decode('utf-8', errors='ignore').strip()}",
            file=sys.stderr,
        )
        return None
    return (
        proc.stdout.decode("utf-8", errors="ignore"),
        proc.stderr.decode("utf-8", errors="ignore"),
    )


def clean_output(raw: str) -> str:
    # Strip <think>...</think> blocks (Qwen style)
    text = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL | re.IGNORECASE)
    # Strip <|channel>thought ... <channel|> blocks (Gemma style, asymmetric closing tag)
    text = re.sub(r"<\|channel>thought.*?<channel\|>", "", text, flags=re.DOTALL | re.IGNORECASE)
    lines = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        low = stripped.lower()
        if "think>" in low or "channel>" in low or "<|channel" in low or "<channel|" in low:
            continue
        if low.startswith("json"):
            continue
        if stripped.startswith("```"):
            continue
        lines.append(line)
    return "\n".join(lines)


def _extract_token_count(stderr_text: str, label: str) -> Optional[int]:
    pattern = re.compile(
        rf"{re.escape(label)}\s*=\s*.*?/\s*(\d+)\s+(?:tokens?|runs?)\b",
        flags=re.IGNORECASE,
    )
    match = pattern.search(stderr_text)
    if not match:
        return None
    return int(match.group(1))


def parse_token_usage(stderr_text: str) -> Optional[dict]:
    input_tokens = _extract_token_count(stderr_text, "prompt eval time")
    output_tokens = _extract_token_count(stderr_text, "eval time")
    total_tokens = _extract_token_count(stderr_text, "total time")

    if input_tokens is None and output_tokens is None and total_tokens is None:
        return None
    if total_tokens is None and input_tokens is not None and output_tokens is not None:
        total_tokens = input_tokens + output_tokens
    if input_tokens is None or output_tokens is None or total_tokens is None:
        return None

    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
    }


class JsonRepairer:
    def __init__(self) -> None:
        try:
            from json_repair import repair_json  # type: ignore import
            self._repair = repair_json
        except Exception:
            self._repair = None

    def _trim_to_array(self, payload: str) -> Optional[str]:
        start = payload.find("[")
        end = payload.rfind("]")
        if start == -1 or end == -1 or end <= start:
            return None
        return payload[start : end + 1]

    def parse(self, payload: str) -> Optional[object]:
        text = payload.strip()
        if not text:
            return None
        candidates = [text]
        trimmed = self._trim_to_array(text)
        if trimmed and trimmed not in candidates:
            candidates.append(trimmed)
            compact = trimmed.replace(",]", "]")
            if compact not in candidates:
                candidates.append(compact)
        if text.startswith("{") and text.endswith("}"):
            wrapped = f"[{text}]"
            if wrapped not in candidates:
                candidates.append(wrapped)
        if self._repair:
            try:
                repaired = self._repair(text)
            except Exception:
                repaired = None
            if repaired:
                candidates.append(repaired)
        for candidate in candidates:
            try:
                return json.loads(candidate)
            except json.JSONDecodeError:
                continue
        return None


def normalize_results(raw: object, image_path: Path) -> List[dict]:
    if isinstance(raw, dict):
        items = [raw]
    elif isinstance(raw, list):
        items = raw
    else:
        print(f"[WARN] Unexpected JSON root for {image_path}: {type(raw).__name__}", file=sys.stderr)
        return []
    normalized: List[dict] = []
    for idx, item in enumerate(items):
        if not isinstance(item, dict):
            print(
                f"[WARN] Skipping non-object entry #{idx} for {image_path}",
                file=sys.stderr,
            )
            continue
        normalized.append(item)
    return normalized


SUMMARY_MIN_LEN = 10


def has_valid_summary(entry: dict) -> bool:
    summary = entry.get("summary", "")
    return isinstance(summary, str) and len(summary.strip()) >= SUMMARY_MIN_LEN


def filter_valid_entries(entries: List[dict], image_path: Path) -> List[dict]:
    valid = [e for e in entries if has_valid_summary(e)]
    rejected = len(entries) - len(valid)
    if rejected:
        print(
            f"[WARN] Rejected {rejected} entr{'y' if rejected == 1 else 'ies'} with missing/short summary for {image_path}",
            file=sys.stderr,
        )
    return valid


def load_crop_sidecar(image_path: Path) -> Optional[dict]:
    crop_path = image_path.with_suffix(image_path.suffix + ".crop.json")
    if not crop_path.exists():
        return None
    try:
        return json.loads(crop_path.read_text(encoding="utf-8"))
    except Exception:
        return None


def get_llama_version(llama_bin: Path) -> str:
    try:
        proc = subprocess.run([str(llama_bin), "--version"], check=False, capture_output=True)
        output = (proc.stdout + proc.stderr).decode("utf-8", errors="ignore")
        for line in output.splitlines():
            if "version" in line.lower():
                return line.strip()
    except Exception:
        pass
    return "unknown"


def get_llama_devices(llama_bin: Path) -> list:
    try:
        proc = subprocess.run([str(llama_bin), "--list-devices"], check=False, capture_output=True)
        output = (proc.stdout + proc.stderr).decode("utf-8", errors="ignore")
        devices = []
        for line in output.splitlines():
            if line.startswith("  ") and line.strip():
                devices.append(line.strip())
        return devices
    except Exception:
        return []


def build_model_meta(args: argparse.Namespace) -> dict:
    """Build the 'model' metadata dict: filename + llama.cpp params (no prompt)."""
    def rel(p: Path) -> str:
        try:
            return str(p.relative_to(ROOT_DIR))
        except ValueError:
            return str(p)

    params = [
        rel(args.llama_bin),
        "--batch-size", str(args.batch_size),
        "-m", rel(args.model),
        "--mmproj", rel(args.mmproj),
        "-ngl", str(args.ngl),
        "--ctx-size", str(args.ctx_size),
        "--temp", str(args.temp),
        "--top-k", str(args.top_k),
        "--top-p", str(args.top_p),
        "--repeat-penalty", str(args.repeat_penalty),
        "-n", str(args.max_tokens),
    ]
    return {
        "filename": args.model.name,
        "prompt": args.prompt.name,
        "llama.cpp.params": " ".join(params),
        "llama.cpp.version": get_llama_version(args.llama_bin),
        "llama.cpp.devices": get_llama_devices(args.llama_bin),
    }


def attach_file_meta(entries: List[dict], image_path: Path, model_meta: Optional[dict] = None,
                     nonstd_params: Optional[str] = None,
                     crop_info: Optional[dict] = None) -> None:
    digest = file_xxhash(image_path)
    meta: dict = {
        "filename": image_path.name,
        "path": str(image_path),
        "xxhash": digest,
    }
    if nonstd_params is not None:
        meta["llama_nonstd_params"] = nonstd_params
    if crop_info is not None:
        meta["crop_info"] = crop_info
    for entry in entries:
        entry["file_meta"] = meta
        if model_meta is not None:
            entry["model"] = model_meta


# Each entry: model="qwen"|"gemma", resize=True means pixel-area cap before inference.
# Order: Qwen greedy → Gemma greedy → Qwen resized greedy → Gemma resized greedy
#        → Qwen resized+mild → Gemma resized+mild → Qwen resized+aggressive → Gemma resized+aggressive
_RETRY_PARAMS = [
    {"model": "qwen",  "resize": False, "temp": None,  "top_k": None, "top_p": None},
    {"model": "gemma", "resize": False, "temp": None,  "top_k": None, "top_p": None},
    {"model": "qwen",  "resize": True,  "temp": None,  "top_k": None, "top_p": None},
    {"model": "gemma", "resize": True,  "temp": None,  "top_k": None, "top_p": None},
    {"model": "qwen",  "resize": True,  "temp": 0.15,  "top_k": 40,   "top_p": 0.9},
    {"model": "gemma", "resize": True,  "temp": 0.15,  "top_k": 40,   "top_p": 0.9},
    {"model": "qwen",  "resize": True,  "temp": 0.3,   "top_k": 40,   "top_p": 0.9},
    {"model": "gemma", "resize": True,  "temp": 0.3,   "top_k": 40,   "top_p": 0.9},
]


def _retry_param_str(params: dict) -> Optional[str]:
    parts = [params["model"]]
    if params["resize"]:
        parts.append("resize=True")
    if params["temp"] is not None:
        parts.append(f"temp={params['temp']} top_k={params['top_k']} top_p={params['top_p']}")
    return " ".join(parts)


REJECTED_DIR = Path(tempfile.gettempdir()) / "watchad_rejected"


def _save_rejected(image_path: Path, attempt: int, params: dict, raw: str, cleaned: str) -> None:
    REJECTED_DIR.mkdir(parents=True, exist_ok=True)
    slug = image_path.stem
    model_label = "fallback" if params["model"] == "gemma" else "primary"
    out = REJECTED_DIR / f"{slug}-{model_label}-attempt-{attempt}.txt"
    out.write_text(f"=== RAW ===\n{raw}\n\n=== CLEANED ===\n{cleaned}\n", encoding="utf-8")
    print(f"[WARN] Rejected output saved to: {out}", file=sys.stderr)


def _format_token_usage(token_usage: dict) -> str:
    return (
        f"input={token_usage['input_tokens']} "
        f"output={token_usage['output_tokens']} "
        f"total={token_usage['total_tokens']}"
    )


def process_image(args: argparse.Namespace, image_path: Path, prompt: str, repairer: JsonRepairer,
                  model_meta: Optional[dict] = None,
                  gemma_override: ModelOverride = None) -> Optional[tuple[List[dict], Optional[dict]]]:
    """Run inference on image_path with retries, converting to PNG first if needed.
    Returns entries plus token usage on success, or None if all attempts failed."""
    is_png = image_path.suffix.lower() == ".png"
    tmp_dir = tempfile.mkdtemp(prefix="watchad_") if not is_png else None
    try:
        for attempt, params in enumerate(_RETRY_PARAMS):
            if params["model"] == "gemma" and gemma_override is None:
                continue
            if attempt > 0:
                desc = _retry_param_str(params)
                print(
                    tag(yellow, "INFO", f" Retry {attempt}/{len(_RETRY_PARAMS) - 1} for {image_path} ({desc})"),
                    file=sys.stderr,
                )
            override = gemma_override if params["model"] == "gemma" else None
            if not is_png:
                try:
                    infer_path = convert_to_png(image_path, tmp_dir, resize=params["resize"])
                except RuntimeError as exc:
                    print(f"[ERROR] {exc}", file=sys.stderr)
                    continue
            else:
                infer_path = image_path

            model_result = run_model(
                args, infer_path, prompt,
                temp=params["temp"],
                top_k=params["top_k"],
                top_p=params["top_p"],
                model_override=override,
            )
            if model_result is None:
                continue
            raw, stderr_text = model_result
            cleaned = clean_output(raw)
            parsed = repairer.parse(cleaned)
            if parsed is None:
                print(f"[WARN] Could not parse JSON for {image_path} (attempt {attempt})", file=sys.stderr)
                _save_rejected(image_path, attempt, params, raw, cleaned)
                continue
            entries = filter_valid_entries(normalize_results(parsed, image_path), image_path)
            if entries:
                nonstd = _retry_param_str(params)
                crop_info = load_crop_sidecar(image_path)
                attach_file_meta(entries, image_path, model_meta=model_meta, nonstd_params=nonstd, crop_info=crop_info)
                return entries, parse_token_usage(stderr_text)
            print(
                f"[WARN] No valid entries for {image_path} (attempt {attempt})",
                file=sys.stderr,
            )
            _save_rejected(image_path, attempt, params, raw, cleaned)
    finally:
        if tmp_dir:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    return None


def build_sidecar_path(image_path: Path) -> Path:
    return image_path.with_suffix(image_path.suffix + ".json")


def write_sidecar(image_path: Path, entries: List[dict], compact: bool = False) -> None:
    payload = entries if entries else []
    sidecar_path = build_sidecar_path(image_path)
    text = json.dumps(payload) if compact else json.dumps(payload, indent=2)
    sidecar_path.write_text(text, encoding="utf-8")


def sidecar_is_valid(image_path: Path) -> bool:
    sidecar = build_sidecar_path(image_path)
    if not sidecar.exists():
        return False
    try:
        json.loads(sidecar.read_text(encoding="utf-8"))
    except Exception:
        return False
    return True


def main() -> None:
    args = parse_args()
    args.input_dir = args.input_dir.expanduser()
    args.model = args.model.expanduser()
    args.mmproj = args.mmproj.expanduser()
    args.llama_bin = args.llama_bin.expanduser()
    args.prompt = args.prompt.expanduser()
    args.gemma_model = args.gemma_model.expanduser()
    args.gemma_mmproj = args.gemma_mmproj.expanduser()
    check_llama_bin(args.llama_bin)

    # --- model availability check & summary ---
    qwen_model_ok   = args.model.exists()
    qwen_mmproj_ok  = args.mmproj.exists()
    gemma_model_ok  = args.gemma_model.exists()
    gemma_mmproj_ok = args.gemma_mmproj.exists()

    def _model_status(model_path: Path, mmproj_path: Path, model_ok: bool, mmproj_ok: bool) -> str:
        m = green(model_path.name) if model_ok else red(model_path.name + " [MISSING]")
        p = green(mmproj_path.name) if mmproj_ok else red(mmproj_path.name + " [MISSING]")
        return f"{m}  +  {p}"

    print(
        f"[INFO] Primary model  : {_model_status(args.model, args.mmproj, qwen_model_ok, qwen_mmproj_ok)}",
        file=sys.stderr,
    )

    gemma_override: ModelOverride = None
    if gemma_model_ok and gemma_mmproj_ok:
        gemma_override = {"model": args.gemma_model, "mmproj": args.gemma_mmproj, "jinja": True}
        fallback_str = _model_status(args.gemma_model, args.gemma_mmproj, True, True)
    else:
        fallback_str = red("none")
        if not gemma_model_ok:
            fallback_str += red(f"  ({args.gemma_model.name} missing)")
        if not gemma_mmproj_ok:
            fallback_str += red(f"  ({args.gemma_mmproj.name} missing)")
    print(f"[INFO] Fallback model : {fallback_str}", file=sys.stderr)

    if not qwen_model_ok or not qwen_mmproj_ok:
        print(red("[ERROR] Primary model or projector not found — cannot continue"), file=sys.stderr)
        sys.exit(1)

    non_png_exts = [e for e in args.extensions if e.lower() != ".png"]
    if non_png_exts:
        check_magick()
    if not args.input_dir.exists():
        print(f"[ERROR] Input directory {args.input_dir} does not exist", file=sys.stderr)
        sys.exit(1)
    images = list_images(args.input_dir, args.extensions)
    if not images:
        print("[WARN] No input images found", file=sys.stderr)
    else:
        print(
            f"[INFO] Starting batch: {len(images)} files from {args.input_dir}",
            file=sys.stderr,
        )
    print(
        "[INFO] Params: batch-size={batch} max-tokens={tok} ctx-size={ctx} temp={temp} "
        "top-k={topk} top-p={topp} ngl={ngl} extensions={ext}".format(
            batch=args.batch_size,
            tok=args.max_tokens,
            ctx=args.ctx_size,
            temp=args.temp,
            topk=args.top_k,
            topp=args.top_p,
            ngl=args.ngl,
            ext=",".join(args.extensions),
        ),
        file=sys.stderr,
    )
    prompt = load_prompt(args.prompt)
    repairer = JsonRepairer()
    model_meta = build_model_meta(args)
    attempted_files = 0
    processed_files = 0
    skipped_files = 0
    token_usage_rows: List[dict] = []
    file_counter = 0
    overall_start = time.perf_counter()
    for image in images:
        file_counter += 1
        if not args.force_reanalysis and sidecar_is_valid(image):
            print(
                f"[INFO] Skipping {image} (valid sidecar exists) ({file_counter})",
                file=sys.stderr,
            )
            skipped_files += 1
            continue
        attempted_files += 1
        print(tag(blue, "INFO", f" Processing {image} ({file_counter})"), file=sys.stderr)
        start = time.perf_counter()
        result = process_image(args, image, prompt, repairer, model_meta=model_meta,
                               gemma_override=gemma_override)
        elapsed = time.perf_counter() - start
        if result is None:
            print(tag(red, "ERROR", f" All attempts failed for {image}, skipping sidecar"), file=sys.stderr)
        else:
            entries, token_usage = result
            processed_files += 1
            write_sidecar(image, entries, compact=args.compact)
            summary_raw = entries[0].get("summary", "") if entries else ""
            summary_str = summary_raw.strip() if isinstance(summary_raw, str) else ""
            if summary_str:
                try:
                    cols = os.get_terminal_size().columns
                except OSError:
                    cols = 80
                prefix = "[INFO]   summary: "
                max_summary = cols - 5 - len(prefix)
                if max_summary < 1:
                    max_summary = 1
                summary_preview = summary_str[:max_summary] + ("..." if len(summary_str) > max_summary else "")
            else:
                summary_preview = "n/a"
            print(tag(blue, "INFO", f"   summary: {summary_preview}"), file=sys.stderr)
            if token_usage is not None:
                token_usage_rows.append(token_usage)
                print(tag(blue, "INFO", f"   tokens: {_format_token_usage(token_usage)}"), file=sys.stderr)
            else:
                print(tag(yellow, "WARN", "   tokens: unavailable from llama timing output"), file=sys.stderr)
            print(tag(green, "INFO", f"   {image} processed in {elapsed:.2f}s"), file=sys.stderr)
    overall_elapsed = time.perf_counter() - overall_start
    avg = overall_elapsed / attempted_files if attempted_files else 0.0
    if token_usage_rows:
        def _stats_line(key: str, label: str) -> str:
            values = [row[key] for row in token_usage_rows]
            avg_value = sum(values) / len(values)
            return f"{label} min={min(values)} max={max(values)} avg={avg_value:.1f}"

        print(
            "[STATS] Tokens: "
            + " | ".join([
                _stats_line("input_tokens", "input"),
                _stats_line("output_tokens", "output"),
                _stats_line("total_tokens", "total"),
            ]),
            file=sys.stderr,
        )
    print(
        (
            "[STATS] Total time: {total:.2f}s | Attempted: {attempted} | Successful: {processed} | "
            "Skipped: {skipped} | Avg per attempted: {avg:.2f}s"
        ).format(
            total=overall_elapsed,
            attempted=attempted_files,
            processed=processed_files,
            skipped=skipped_files,
            avg=avg,
        ),
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
