#!/bin/bash
set -e
echo "[INFO] On OSX: clear quarantine bit for files under: ./llama.cpp/*"

if [ ! -f ./llama.cpp/llama-mtmd-cli ]; then
    echo "[ERROR] './llama.cpp/llama-mtmd-cli' NOT found. Please make sure llama.cpp is installed."
    exit 1
fi

echo "[INFO] CTRL+C now to abort..."
sleep 5
xattr -dr com.apple.quarantine ./llama.cpp/
echo "[INFO] Success."
