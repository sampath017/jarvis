"""Provision private server Google settings from an owner-supplied web OAuth JSON.

Never prints credentials. Run only after downloading a Web application OAuth
client JSON and registering the backend callback in Google Auth Platform.
"""
import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

from cryptography.fernet import Fernet
from urllib.request import urlopen


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--oauth-file', required=True, type=Path)
    parser.add_argument('--owner-hash')
    parser.add_argument('--prepare-only', action='store_true', help='Provision credentials before the phone pairing identifier is available.')
    parser.add_argument('--account', required=True)
    parser.add_argument('--project', default='jarvis-agent-61947')
    parser.add_argument('--region', default='asia-south1')
    args = parser.parse_args()
    if not args.prepare_only and not args.owner_hash:
        parser.error('Supply --owner-hash or use --prepare-only.')
    if args.owner_hash and not re.fullmatch(r'[a-f0-9]{64}', args.owner_hash):
        parser.error('Use the cloud setup identifier copied from Jarvis Settings, not the private session key.')
    profile = json.loads(args.oauth_file.read_text(encoding='utf-8')).get('web')
    if not profile or not profile.get('client_id') or not profile.get('client_secret'):
        parser.error('Supply the downloaded Web application OAuth client JSON.')
    if not re.fullmatch(r'[0-9]+-[a-z0-9]+\.apps\.googleusercontent\.com', profile['client_id']):
        parser.error('Invalid Google web OAuth client ID.')
    if profile.get('project_id') and profile['project_id'] != args.project:
        parser.error('Use a web OAuth client created in the Jarvis project.')
    if not re.fullmatch(r'[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}', args.account):
        parser.error('Specify the personal Google account email.')
    gcloud = shutil.which('gcloud.cmd') or shutil.which('gcloud')
    if not gcloud:
        parser.error('gcloud must be installed and signed in.')

    def run(command, check=True):
        result = subprocess.run([gcloud, *command, '--project='+args.project, '--quiet'],
                                capture_output=True, text=True, timeout=300)
        if check and result.returncode:
            # Do not echo command arguments or potentially credential-bearing responses.
            raise RuntimeError('Google Cloud operation failed. Check project permissions and APIs.')
        return result

    service = json.loads(run(['run', 'services', 'describe', 'jarvis-backend', '--region='+args.region, '--format=json']).stdout)
    url = service['status']['url']
    env = {item['name']: item.get('value') for item in service['spec']['template']['spec']['containers'][0].get('env', [])}
    public_url = env.get('JARVIS_SERVICE_URL') or url
    redirect = public_url.rstrip('/') + '/google-server/callback'
    if redirect not in profile.get('redirect_uris', []):
        parser.error('Add this authorized redirect URI to the Web OAuth client and download its JSON again: '+redirect)
    identity = service['spec']['template']['spec'].get('serviceAccountName')
    if not identity:
        parser.error('Set an explicit backend service account before provisioning private OAuth secrets.')
    run(['services', 'enable', 'secretmanager.googleapis.com', 'cloudscheduler.googleapis.com', 'forms.googleapis.com'])

    def secret(name, value, preserve=False):
        existing = run(['secrets', 'describe', name, '--format=value(name)'], check=False).returncode == 0
        if preserve and existing:
            run(['secrets', 'add-iam-policy-binding', name,
                 '--member=serviceAccount:'+identity, '--role=roles/secretmanager.secretAccessor'])
            return
        with tempfile.TemporaryDirectory(prefix='jarvis-google-') as folder:
            path = Path(folder) / 'value'
            path.write_bytes(value)
            if not existing:
                run(['secrets', 'create', name, '--replication-policy=automatic', '--data-file='+str(path)])
            else:
                run(['secrets', 'versions', 'add', name, '--data-file='+str(path)])
        run(['secrets', 'add-iam-policy-binding', name,
             '--member=serviceAccount:'+identity, '--role=roles/secretmanager.secretAccessor'])

    secret('jarvis-google-client-secret', profile['client_secret'].encode())
    secret('jarvis-google-token-key', Fernet.generate_key(), preserve=True)
    values = ['JARVIS_GOOGLE_CLIENT_ID='+profile['client_id'], 'JARVIS_GOOGLE_ALLOWED_EMAIL='+args.account]
    if args.owner_hash:
        values.append('JARVIS_GOOGLE_OWNER_HASH='+args.owner_hash)
    run(['run', 'services', 'update', 'jarvis-backend', '--region='+args.region, '--no-traffic', '--tag=google-config-check',
         '--update-env-vars='+','.join(values),
         '--update-secrets=JARVIS_GOOGLE_CLIENT_SECRET=jarvis-google-client-secret:latest,JARVIS_GOOGLE_TOKEN_KEY=jarvis-google-token-key:latest'])
    updated = json.loads(run(['run', 'services', 'describe', 'jarvis-backend', '--region='+args.region, '--format=json(status)']).stdout)['status']
    tagged = next(t for t in updated['traffic'] if t.get('tag') == 'google-config-check')
    if tagged['revisionName'] != updated['latestReadyRevisionName']:
        raise RuntimeError('The new Google configuration did not become ready; current traffic was preserved.')
    with urlopen(tagged['url']+'/health', timeout=60) as response:
        if json.load(response).get('status') != 'healthy':
            raise RuntimeError('The configuration health check failed; current traffic was preserved.')
    run(['run', 'services', 'update-traffic', 'jarvis-backend', '--region='+args.region,
         '--to-revisions='+tagged['revisionName']+'=100'])
    run(['run', 'services', 'update-traffic', 'jarvis-backend', '--region='+args.region, '--remove-tags=google-config-check'])
    task_account = env.get('JARVIS_TASK_SERVICE_ACCOUNT')
    if not task_account:
        raise RuntimeError('A Cloud Tasks callback identity is required for scheduler reconciliation.')
    name = 'jarvis-google-actions-reconcile'
    exists = run(['scheduler', 'jobs', 'describe', name, '--location='+args.region, '--format=value(name)'], check=False).returncode == 0
    run(['scheduler', 'jobs', 'update' if exists else 'create', 'http', name, '--location='+args.region,
         '--schedule=*/5 * * * *', '--uri='+public_url.rstrip('/')+'/internal/background/google-reconcile',
         '--http-method=POST', '--oidc-service-account-email='+task_account, '--oidc-token-audience='+public_url.rstrip('/')])
    print('Private Google credentials and schedule reconciliation are ready.')
    if not args.owner_hash:
        print('Phone pairing is still required. Cloud Google access remains inactive.')
    else:
        print('In Jarvis Settings > Cloud actions, connect Google and complete its consent page.')


if __name__ == '__main__':
    main()
