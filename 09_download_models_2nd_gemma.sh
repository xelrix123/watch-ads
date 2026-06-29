#!/usr/bin/env bash
set -euo pipefail

## NOTE: This is dense / largest version of this model, and (because dense vs. MoE) much slower

REPO="ggml-org/gemma-4-31B-it-GGUF"
REVISION="main"
DEST="./models/gemma-4-31B-it-GGUF"

MODEL_FILE="gemma-4-31B-it-Q8_0.gguf"
PROJECTOR_FILE="mmproj-gemma-4-31B-it-Q8_0.gguf"

mkdir -p "$DEST"

download_file() {
  local file="$1"
  local url="https://huggingface.co/${REPO}/resolve/${REVISION}/${file}?download=true"
  local out="${DEST}/${file}"

  echo "Downloading: $file"
  echo "To: $out"

  if [[ -n "${HF_TOKEN:-}" ]]; then
    curl \
      -fL \
      -C - \
      --retry 10 \
      --retry-delay 5 \
      --retry-all-errors \
      -H "Authorization: Bearer ${HF_TOKEN}" \
      -o "$out" \
      "$url"
  else
    curl \
      -fL \
      -C - \
      --retry 10 \
      --retry-delay 5 \
      --retry-all-errors \
      -o "$out" \
      "$url"
  fi
}

download_file "$MODEL_FILE"
download_file "$PROJECTOR_FILE"

echo
echo "Done:"
ls -lh "$DEST"/*.gguf
