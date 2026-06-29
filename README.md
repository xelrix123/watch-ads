# Watch ads OCR and Search

Free text OCR, translation to english and search for watch advertisements build on Vision Models.

Vibe coded. Mostly. There's no tests either. This is the new way.

## Preparations

Clone this repository. Download pre-built or compile, and install latest [llama.cpp](https://github.com/ggml-org/llama.cpp) under <this-repsitory>/llama.cpp/.

NOTE: On OSX, to force reset quarantine bit on llama.cpp 'xattr -dr com.apple.quarantine . or run ./00_clear_quarantine_llamacpp.sh.

Then init python venc and download models from HuggingFace. Qwen is required. Gemma is optional but recommeded. Models will take ~72GB of disk space in aggregate.

```
$ ./05_install_python_deps.sh
[INFO] install Python deps for Python 3.12 (requires Python 3.12)
 - version: Python 3.12.13
....
Successfully installed json-repair-0.58.7 xxhash-3.6.0
[INFO] Success. Now initialize venv by typing:
       'source venv/bin/activate'
$ source venv/bin/activate
((venv) ) $
((venv) ) $ ./09_download_models_1st_qwen.sh
[INFO] Download Qwen3.6-35B-A3B-UD-Q8_K_XL.gguf + vision projectors (~52GB) from unsloth
[INFO] Download base: https://huggingface.co/unsloth/Qwen3.6-35B-A3B-GGUF/resolve/main
[INFO] Files will be downloaded to: ./models
((venv) ) $ ./09_download_models_2nd_gemma./sh
...
```

## Run analysis 

```
$ source venv/bin/activate
$ python3 ./10_llamacpp_ocr_runner.py --input-dir test-images/ --force-reanalysis
....
[INFO] test-images/xyz-random-pattern-not-an-ad.png processed in 35.02s
[STATS] Total time: 220.42s | Attempted: 4 | Successful: 4 | Skipped: 0 | Avg per attempted: 55.10s

# run /w '--remove-invalid-sidecars' if sus > 0
$ ./11_sanity_check.py --input-dir test-images/
Checked 4 sidecar(s). Suspicious: 0
...

$ python3 15_build_gallery_index.py --input-dir test-images/ --output ./gallery-index.json --web-image-root "./test-images" --must-have-sidecar --web-image-ext webp
...

$ python3 20_build_gallery.py --http-json gallery-index.json --thumbnails-root ./tb --output index.html --statistics stats.html --favicon-svg ./assets/basic_clock.svg --html-title "Watch Ad Search Tool"
...

$ python3 20_build_stats.py --metadata metadata.json.gz --favicon-svg assets/basic_stats.svg --output stats.html 
Wrote stats.html (80,463 bytes)
...

$ python3 21_bundle_assets.py --overwrite --input-dir ./tb/ --metadata ./metadata.json.gz
```

## 

Because of the CORS restrictions, the `file://...` url cannot be used to view index.html. Instead, serve via web server. Python3 build-in server example provided below.

Point the browser to local python web server at http://localhost:8000

```
$ python3 -m http.server --bind 127.0.0.1
Serving HTTP on :: port 8000 (http://[::]:8000/) ...
```
