#!/usr/bin/env python3
"""Download the OpenCV Zoo face models (Apache-2.0) into ./models and verify them.

    python scripts/download_models.py            # download if missing
    python scripts/download_models.py --force    # re-download

Models:
  * YuNet face detector   face_detection_yunet_2023mar.onnx
  * SFace face recognizer face_recognition_sface_2021dec.onnx

Source: https://github.com/opencv/opencv_zoo (files are stored with Git LFS, so
we download from media.githubusercontent.com and fall back to the raw URL).

Verification:
  1. the file is not a Git-LFS pointer, has a plausible size and the pinned SHA-256,
  2. it loads in OpenCV (cv2.FaceDetectorYN / cv2.FaceRecognizerSF),
  3. a dummy inference runs and returns the expected output shape.
The SHA-256 of each file is printed at the end.
"""

from __future__ import annotations

import argparse
import hashlib
import sys
import tempfile
import urllib.request
from pathlib import Path

ZOO_PATHS = {
    "face_detection_yunet_2023mar.onnx": "models/face_detection_yunet/face_detection_yunet_2023mar.onnx",
    "face_recognition_sface_2021dec.onnx": "models/face_recognition_sface/face_recognition_sface_2021dec.onnx",
}
URL_TEMPLATES = (
    "https://media.githubusercontent.com/media/opencv/opencv_zoo/main/{path}",
    "https://github.com/opencv/opencv_zoo/raw/main/{path}",
)
# Pinned SHA-256 of the official files (verified against opencv_zoo main).
EXPECTED_SHA256 = {
    "face_detection_yunet_2023mar.onnx": "8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4",
    "face_recognition_sface_2021dec.onnx": "0ba9fbfa01b5270c96627c4ef784da859931e02f04419c829e83484087c34e79",
}
# Sanity bounds in bytes (YuNet ≈ 230 KB, SFace ≈ 37 MB).
SIZE_BOUNDS = {
    "face_detection_yunet_2023mar.onnx": (100_000, 2_000_000),
    "face_recognition_sface_2021dec.onnx": (20_000_000, 60_000_000),
}

DEFAULT_DIR = Path(__file__).resolve().parent.parent / "models"


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def download(url: str, dest: Path) -> None:
    req = urllib.request.Request(url, headers={"User-Agent": "eventlens-model-downloader"})
    with urllib.request.urlopen(req, timeout=120) as resp, open(dest, "wb") as out:
        total = int(resp.headers.get("Content-Length") or 0)
        done = 0
        while True:
            chunk = resp.read(1 << 16)
            if not chunk:
                break
            out.write(chunk)
            done += len(chunk)
            if total:
                print(f"\r    {done / 1e6:6.1f} / {total / 1e6:.1f} MB", end="", flush=True)
    print()


def check_file(name: str, path: Path, verify_hash: bool = True) -> None:
    """Raise ValueError if the file looks wrong (LFS pointer, wrong size, wrong hash)."""
    with open(path, "rb") as fh:
        head = fh.read(64)
    if head.startswith(b"version https://git-lfs"):
        raise ValueError("received a Git-LFS pointer instead of the model")
    lo, hi = SIZE_BOUNDS[name]
    size = path.stat().st_size
    if not lo <= size <= hi:
        raise ValueError(f"unexpected size {size} bytes (expected {lo}-{hi})")
    if verify_hash:
        digest = sha256(path)
        if digest != EXPECTED_SHA256[name]:
            raise ValueError(f"SHA-256 mismatch: got {digest}, expected {EXPECTED_SHA256[name]}")


def verify_with_opencv(models_dir: Path) -> None:
    import cv2
    import numpy as np

    det = cv2.FaceDetectorYN.create(
        str(models_dir / "face_detection_yunet_2023mar.onnx"), "", (320, 320), 0.7, 0.3, 5000
    )
    blank = np.zeros((320, 320, 3), dtype=np.uint8)
    det.setInputSize((320, 320))
    det.detect(blank)  # must not raise; no faces expected

    rec = cv2.FaceRecognizerSF.create(str(models_dir / "face_recognition_sface_2021dec.onnx"), "")
    feat = rec.feature(np.zeros((112, 112, 3), dtype=np.uint8))
    if feat.size != 128:
        raise ValueError(f"SFace produced {feat.size}-d features, expected 128")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dir", type=Path, default=DEFAULT_DIR, help="target directory (default: backend/models)")
    ap.add_argument("--force", action="store_true", help="re-download even if present")
    ap.add_argument(
        "--skip-hash-check",
        action="store_true",
        help="accept files whose SHA-256 differs from the pinned value (only if upstream changed)",
    )
    args = ap.parse_args()

    models_dir: Path = args.dir
    models_dir.mkdir(parents=True, exist_ok=True)

    for name, zoo_path in ZOO_PATHS.items():
        dest = models_dir / name
        if dest.exists() and not args.force:
            try:
                check_file(name, dest, not args.skip_hash_check)
                print(f"[ok]   {name} already present")
                continue
            except ValueError as exc:
                print(f"[warn] {name} present but invalid ({exc}); re-downloading")

        last_error: Exception | None = None
        for template in URL_TEMPLATES:
            url = template.format(path=zoo_path)
            print(f"[get]  {name}\n    from {url}")
            with tempfile.NamedTemporaryFile(dir=models_dir, delete=False, suffix=".part") as tmp:
                tmp_path = Path(tmp.name)
            try:
                download(url, tmp_path)
                check_file(name, tmp_path, not args.skip_hash_check)
                tmp_path.replace(dest)
                last_error = None
                break
            except Exception as exc:  # network error, LFS pointer, bad size...
                last_error = exc
                print(f"[fail] {exc}")
                tmp_path.unlink(missing_ok=True)
        if last_error is not None:
            print(f"ERROR: could not download {name}: {last_error}", file=sys.stderr)
            return 1

    try:
        verify_with_opencv(models_dir)
    except Exception as exc:
        print(f"ERROR: OpenCV failed to load/run the models: {exc}", file=sys.stderr)
        return 1

    print("\nModels verified with OpenCV. SHA-256:")
    for name in ZOO_PATHS:
        print(f"  {sha256(models_dir / name)}  {name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
