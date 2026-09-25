"""
Deployment Script: Deploy jarvis-embedding to Cloud Run with scale-to-zero and wire IAM permissions.

Usage:
    uv run python -m scripts.deploy_embedding
    # or
    python backend/scripts/deploy_embedding.py
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path
from dotenv import dotenv_values

backend_dir = Path(__file__).resolve().parent.parent
repo_dir = backend_dir.parent
embedding_dir = repo_dir / "embedding"

PROJECT_ID = os.environ.get("GCP_PROJECT", "jarvis-agent-61947")
REGION = os.environ.get("GCP_EMBEDDING_REGION", "asia-south1")
BACKEND_REGION = os.environ.get("GCP_REGION", "asia-south1")
EMBEDDING_SERVICE = "jarvis-embedding"
BACKEND_SERVICE = "jarvis-backend"
BACKEND_SA = f"898516599131-compute@developer.gserviceaccount.com"


def run_cmd(cmd: list[str], check: bool = True) -> subprocess.CompletedProcess[str]:
    print(f"\n> {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.stdout:
        print(result.stdout.strip())
    if result.stderr:
        print(result.stderr.strip(), file=sys.stderr)
    if check and result.returncode != 0:
        raise RuntimeError(f"Command failed with exit code {result.returncode}: {' '.join(cmd)}")
    return result


def main() -> None:
    gcloud = shutil.which("gcloud")
    if not gcloud:
        print("Error: 'gcloud' CLI was not found in PATH.", file=sys.stderr)
        sys.exit(1)

    if not embedding_dir.exists():
        print(f"Error: Embedding directory not found at {embedding_dir}", file=sys.stderr)
        sys.exit(1)

    print(f"=== Deploying {EMBEDDING_SERVICE} to Cloud Run ===")
    print(f"Project: {PROJECT_ID}")
    print(f"Region:  {REGION}")
    print(f"Source:  {embedding_dir}")
    print("Specs: CPU only, 8GiB RAM, 4 vCPU, concurrency=2, min=0, max=2, timeout=300s")

    # 1. Deploy Cloud Run service
    deploy_cmd = [
        gcloud,
        "run",
        "deploy",
        EMBEDDING_SERVICE,
        f"--source={embedding_dir}",
        f"--project={PROJECT_ID}",
        f"--region={REGION}",
        "--platform=managed",
        "--memory=8Gi",
        "--cpu=4",
        "--gpu=0",
        "--cpu-throttling",
        "--concurrency=2",
        "--min-instances=0",
        "--max-instances=2",
        "--timeout=300",
        "--no-allow-unauthenticated",
        "--startup-probe=httpGet.path=/health,httpGet.port=8080,periodSeconds=10,timeoutSeconds=3,failureThreshold=24",
        "--quiet",
    ]
    run_cmd(deploy_cmd)

    # 2. Retrieve deployed URL
    url_res = run_cmd([
        gcloud,
        "run",
        "services",
        "describe",
        EMBEDDING_SERVICE,
        f"--project={PROJECT_ID}",
        f"--region={REGION}",
        "--format=value(status.url)",
    ])
    embedding_url = url_res.stdout.strip()
    print(f"\n[+] {EMBEDDING_SERVICE} URL: {embedding_url}")

    # 3. Grant IAM Invoker role to backend service account
    print(f"\n=== Binding IAM Run Invoker Role to {BACKEND_SA} ===")
    iam_cmd = [
        gcloud,
        "run",
        "services",
        "add-iam-policy-binding",
        EMBEDDING_SERVICE,
        f"--project={PROJECT_ID}",
        f"--region={REGION}",
        f"--member=serviceAccount:{BACKEND_SA}",
        "--role=roles/run.invoker",
        "--quiet",
    ]
    run_cmd(iam_cmd)
    print(f"[+] Successfully granted roles/run.invoker to {BACKEND_SA}")

    # 4. Update local backend/.env
    env_path = backend_dir / ".env"
    if env_path.exists():
        lines = env_path.read_text(encoding="utf-8").splitlines()
        found = False
        new_lines = []
        for line in lines:
            if line.startswith("EMBEDDING_URL="):
                new_lines.append(f"EMBEDDING_URL={embedding_url}")
                found = True
            else:
                new_lines.append(line)
        if not found:
            new_lines.append(f"EMBEDDING_URL={embedding_url}")
        env_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
        print(f"[+] Updated local backend/.env with EMBEDDING_URL")

    # 5. Update jarvis-backend on Cloud Run
    env_vars = [f"EMBEDDING_URL={embedding_url}"]
    local_env = dotenv_values(env_path) if env_path.exists() else {}
    secrets = []
    for key in ("CHROMA_HOST", "CHROMA_API_KEY", "CHROMA_TENANT", "CHROMA_DATABASE"):
        if local_env.get(key):
            # Credentials remain in Secret Manager, never command arguments or logs.
            secret = "jarvis-" + key.lower().replace("_", "-")
            secrets.append(f"{key}={secret}:latest")

    print(f"\n=== Updating {BACKEND_SERVICE} with EMBEDDING_URL & Chroma config ===")
    update_cmd = [
        gcloud,
        "run",
        "services",
        "update",
        BACKEND_SERVICE,
        f"--project={PROJECT_ID}",
        f"--region={BACKEND_REGION}",
        f"--update-env-vars={','.join(env_vars)}",
        f"--update-secrets={','.join(secrets)}",
        "--quiet",
    ]
    run_cmd(update_cmd)
    print(f"[+] Successfully updated {BACKEND_SERVICE} environment variables!")

    print("\n" + "=" * 60)
    print("DEPLOYMENT & INTEGRATION COMPLETE")
    print(f"Embedding Service: {embedding_url}")
    print("Scale-to-Zero:     Active (min-instances=0)")
    print(f"Backend Connected: {BACKEND_SERVICE}")
    print("=" * 60)


if __name__ == "__main__":
    main()
