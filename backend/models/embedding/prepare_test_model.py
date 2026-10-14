"""Explicit one-time download; normal local tests use cached weights offline."""
import importlib.util
import os
from pathlib import Path
import sys


def main():
    root = Path(__file__).resolve().parents[3]
    os.environ.setdefault("HF_HOME", str(root / "backend/models/huggingface"))
    from huggingface_hub import snapshot_download

    spec = importlib.util.spec_from_file_location("embedding_contract", Path(__file__).resolve().parent / "app.py")
    contract = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = contract
    spec.loader.exec_module(contract)
    path = snapshot_download(contract.MODEL, revision=contract.REVISION)
    print(f"Pinned embedding weights cached at {path}")


if __name__ == "__main__":
    main()
