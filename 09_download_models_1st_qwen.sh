#!/bin/bash

DIR="./models"

#BASE="https://huggingface.co/unsloth/Qwen3.5-35B-A3B-GGUF/resolve/main"
BASE="https://huggingface.co/unsloth/Qwen3.6-35B-A3B-GGUF/resolve/main"

#FILE_1="Qwen3.5-35B-A3B-UD-Q8_K_XL.gguf"
FILE_1="Qwen3.6-35B-A3B-UD-Q8_K_XL.gguf"
FILE_2="mmproj-BF16.gguf"
FILE_3="mmproj-F32.gguf"

#MMVER="Qwen35"
MMVER="Qwen36"

echo "[INFO] Download $FILE_1 + vision projectors (~52GB) from unsloth"
echo "[INFO] Download base: $BASE"
echo "[INFO] Files will be downloaded to: $DIR"

mkdir -p "$DIR"
wget --no-verbose --show-progress -c -P "$DIR" "$BASE/$FILE_1" 2>&1 
wget --no-verbose --show-progress -c -O "$DIR/mmproj-$MMVER-BF16.gguf" "$BASE/$FILE_2" 2>&1 
wget --no-verbose --show-progress -c -O "$DIR/mmproj-$MMVER-F32.gguf" "$BASE/$FILE_3" 2>&1 
ls -l ./models
