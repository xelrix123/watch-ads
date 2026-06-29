To analyze all images in this directory using both QWEN and GEMMA, run (in this directory): 

./run-all-test-images-oneshot.sh

This will record <imagename>.<model>.json and <imagename>.<model>.totaltime for each image in this directory.

Please note that ../10_oneshot_analyzetest.sh expects input to be .png (whereas files here are webp,
and ./run-all-test-images-oneshot.sh uses ImageMagick to convert them to .png).
