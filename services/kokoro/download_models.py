"""
Run this script once to download Kokoro model files into /app/models (or a local path).
Usage:
    python download_models.py
    python download_models.py --output ./my-models
"""
import argparse
import os
import urllib.request

BASE_URL = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0"
FILES = [
    "kokoro-v1.0.onnx",
    "voices-v1.0.bin",
]


def download(output_dir: str):
    os.makedirs(output_dir, exist_ok=True)
    for filename in FILES:
        dest = os.path.join(output_dir, filename)
        if os.path.exists(dest):
            print(f"  {filename} already exists, skipping.")
            continue
        url = f"{BASE_URL}/{filename}"
        print(f"Downloading {filename} from {url} …")
        urllib.request.urlretrieve(url, dest)
        size_mb = os.path.getsize(dest) / 1_000_000
        print(f"  → {dest} ({size_mb:.1f} MB)")
    print("Done.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default=os.getenv("MODELS_DIR", "/app/models"))
    args = parser.parse_args()
    download(args.output)
