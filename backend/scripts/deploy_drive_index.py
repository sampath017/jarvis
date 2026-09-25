"""Deploy private staging and the Drive index worker alongside the backend.

Run from the backend environment: python -m scripts.deploy_drive_index
Chroma secrets must already exist in Secret Manager.
"""
import os
import shutil
import subprocess
from pathlib import Path


def main():
    project = os.getenv('GCP_PROJECT', 'jarvis-agent-61947')
    region = os.getenv('GCP_REGION', 'asia-south1')
    bucket = os.getenv('INDEX_STAGING_BUCKET', 'jarvis-drive-index-staging-' + project)
    gcloud = shutil.which('gcloud')
    if not gcloud:
        raise RuntimeError('gcloud is required')
    backend = Path(__file__).resolve().parents[1]

    def run(args, regional=False, check=True):
        command = [gcloud, *args, '--project=' + project, '--quiet']
        if regional:
            command += ['--region=' + region]
        result = subprocess.run(command, cwd=backend, capture_output=True, text=True)
        if check and result.returncode:
            raise RuntimeError(result.stderr.strip())
        return result

    number = run(['projects', 'describe', project, '--format=value(projectNumber)']).stdout.strip()
    identity = number + '-compute@developer.gserviceaccount.com'
    if run(['storage', 'buckets', 'describe', 'gs://' + bucket], check=False).returncode:
        run(['storage', 'buckets', 'create', 'gs://' + bucket, '--location=' + region,
            '--uniform-bucket-level-access', '--public-access-prevention'])
    run(['storage', 'buckets', 'add-iam-policy-binding', 'gs://' + bucket,
        '--member=serviceAccount:' + identity, '--role=roles/storage.objectAdmin'])
    run(['run', 'deploy', 'jarvis-backend', '--source=.', '--update-env-vars=INDEX_STAGING_BUCKET=' + bucket], regional=True)
    image = run(['run', 'services', 'describe', 'jarvis-backend',
        '--format=value(spec.template.spec.containers[0].image)'], regional=True).stdout.strip()
    url = run(['run', 'services', 'describe', 'jarvis-embedding', '--format=value(status.url)'], regional=True).stdout.strip()
    secrets = ','.join(f'{key}=jarvis-{key.lower().replace("_", "-")}:latest'
        for key in ('CHROMA_API_KEY', 'CHROMA_TENANT', 'CHROMA_DATABASE', 'CHROMA_HOST'))
    run(['run', 'jobs', 'deploy', 'jarvis-drive-indexer', '--image=' + image,
        '--cpu=2', '--memory=4Gi', '--tasks=1', '--parallelism=1', '--max-retries=1', '--task-timeout=604800s',
        '--command=python', '--args=-m,src.services.drive_index_queue',
        '--set-env-vars=EMBEDDING_URL=' + url + ',INDEX_STAGING_BUCKET=' + bucket,
        '--set-secrets=' + secrets, '--service-account=' + identity,
        '--add-volume=mount-path=/sources,type=cloud-storage,bucket=' + bucket + ',readonly=true'], regional=True)
    run(['run', 'jobs', 'add-iam-policy-binding', 'jarvis-drive-indexer',
        '--member=serviceAccount:' + identity, '--role=roles/run.developer'], regional=True)
    print('Backend and Drive index worker deployed in ' + region)


if __name__ == '__main__':
    main()
