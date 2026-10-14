"""Dependency preflight that works even before pytest is installed locally."""
import importlib.util
import shutil
import sys


def main():
    modules = ("pytest", "httpx", "numpy", "fastapi", "torch", "torchvision",
               "sentence_transformers", "PIL", "soundfile", "torchcodec")
    missing = [name for name in modules if importlib.util.find_spec(name) is None]
    missing += [name for name in ("ffmpeg", "ffprobe") if not shutil.which(name)]
    if missing:
        print("Local embedding prerequisites unavailable: " + ", ".join(missing))
        print("Prepare backend/models/embedding/.venv using backend/models/embedding/README.md, or explicitly select a service fallback.")
        return 77
    return 0


if __name__ == "__main__":
    sys.exit(main())
