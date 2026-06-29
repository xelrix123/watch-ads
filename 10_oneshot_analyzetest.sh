#!/bin/bash
set -e
echo "[INFO] run llama-mtmd-cli on a file and save to ./test.json (overwrites)"
echo "[INFO] llama.cpp -- https://github.com/ggml-org/llama.cpp"


## json repair
## pip install json-repair

if [ $# -lt 1 ]; then
  echo "Usage: $0 <input.png> [QWEN|GEMMA|MODEL_NAME]"
  exit 1
fi

echo "[INFO] testing json_repair is present..."
json_repair -h > /dev/null

echo "[INFO] testing Image Magick is present..."
magick -version > /dev/null
identify -version > /dev/null

LLAMACPPBASE=./llama.cpp
INPUTFILE="$1"
MODEL_NAME="${2:-QWEN}"
MODEL_NAME="$(printf '%s' "$MODEL_NAME" | tr '[:lower:]' '[:upper:]')"

MODEL_QWEN="models/Qwen3.6-35B-A3B-UD-Q8_K_XL.gguf"
MMPROJ_QWEN="models/mmproj-Qwen36-F32.gguf"
MODEL_GEMMA="models/gemma-4-31B-it-Q8_0.gguf"
MMPROJ_GEMMA="models/mmproj-gemma-4-31B-it-Q8_0.gguf"

MODEL_VAR="MODEL_${MODEL_NAME}"
MMPROJ_VAR="MMPROJ_${MODEL_NAME}"
MODEL="${!MODEL_VAR}"
MMPROJ="${!MMPROJ_VAR}"

if [ -z "$MODEL" ] || [ -z "$MMPROJ" ]; then
    echo "[ERROR] Unknown model family '$MODEL_NAME'. Expected matching $MODEL_VAR and $MMPROJ_VAR variables."
    exit 1
fi

JINJA="--jinja"

PROMPTFILE="./prompts/prompt-watch-ad-ocr-single.txt"

BATCH_SIZE=4096
MAXUSETOKENS=16384

## 0 all the context on qwen (n_ctx = 262144) but slower init. Force smaller context for faster init.
CTX_SIZE=0
#CTX_SIZE=32768


## test that input is png; if not make it so...
MIME=$(file --brief --mime-type "$1")
MKTEMP=0
if [[ "$MIME" != image/* ]]; then
    echo "[ERROR] '$FILE' is not an image (detected: $MIME). Aborting."
    exit 1
fi

echo "[INFO] $(identify "$INPUTFILE")"
if [[ "$MIME" != "image/png" ]]; then
    echo "[INFO] input file type is $MIME. Converting to image/png"
    PNGFILE="$(mktemp).png"
    magick "$INPUTFILE" "$PNGFILE"
    INPUTFILE="$PNGFILE"
    MKTEMP=1
    echo "[INFO] temp input file: $INPUTFILE"
fi


echo "[INFO] llama.cpp details:"
$LLAMACPPBASE/llama-mtmd-cli --version 2>&1 | tail -2
$LLAMACPPBASE/llama-mtmd-cli --list-devices 2>&1 | grep -v "^ggml"
echo "model family: $MODEL_NAME"
echo "models: $MODEL + $MMPROJ"
echo "prompt: $PROMPTFILE"
sleep 5

TMPFILE1="$(mktemp)"

## notes:
## --no-warmup -> warmup is a throwaway forward pass on a tiny dummy batch (a couple of tokens like BOS/EOS) that llama.cpp runs at startup. Its only job is to force the one-time setup costs to happen up front — allocating compute buffers, loading/JIT-compiling backend kernels (especially relevant on CUDA), spinning up memory pools, 

$LLAMACPPBASE/llama-mtmd-cli --no-warmup "$JINJA" --batch-size "$BATCH_SIZE" -m "$MODEL" --mmproj "$MMPROJ" -ngl all  --ctx-size "$CTX_SIZE"  --image "$INPUTFILE"  -p "$(cat $PROMPTFILE)"   --temp 0 --top-k 1 --top-p 1 --repeat-penalty 1.1 -n "$MAXUSETOKENS" | grep -v "think>" | grep -v json > "$TMPFILE1"

if [ "$MKTEMP" -eq 1 ]; then
    echo "[INFO] rm temp input: $INPUTFILE"
    rm -f "$INPUTFILE"
fi

TOTALT=$SECONDS
echo "$TOTALT" > ./test.totaltime

iconv -f utf-8 -t utf-8 -c "$TMPFILE1" > "${TMPFILE1}.clean" && mv "${TMPFILE1}.clean" "$TMPFILE1"
json_repair "$TMPFILE1" -o "./test.json"
echo "$TMPFILE1"
#rm -f "$TMPFILE1"
jq . < "./test.json"
ls -l "./test.json" "./test.totaltime"

echo "[INFO] TOTAL TIME: $TOTALT"
