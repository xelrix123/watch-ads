#!/bin/bash
set -e
echo "[INFO] install Python deps for Python 3.12 (requires Python 3.12)"
echo -n " - version: "
python3.12 --version
echo -n " - binary: "
which python3.12

if [ -d "./venv" ]; then
    echo "[ERROR] ./venv directory already exists. Aborting. to continue with clean install do"
    echo "        'deactivate || rm -rf ./venv'"
    exit
fi

echo "[INDO] Initializing Python virtual environment under ./venv"
python3.12 -m venv venv
# shellcheck source=/dev/null
source venv/bin/activate
echo "[INFO] upgrading pip"
pip install --upgrade pip

echo "[INFO] venv Python version"
echo -n " - version: "
python3.12 --version
echo -n " - binary: "
which python3.12
echo -n " - pip version: "
pip --version


PIPPACKAGES=(json-repair xxhash)
echo "[INFO] installing python3 packages with pip: ${PIPPACKAGES[*]}"
sleep 3
pip install "${PIPPACKAGES[@]}"

echo "==========================================================="
echo "[INFO] Success. Now initialize venv by typing:"
echo "       'source venv/bin/activate'"
