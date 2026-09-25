"""Register the installed Android signing certificate through Firebase Management.

Uses the already signed-in gcloud account. Never prints credentials or API keys.
"""
import base64
import json
import os
from pathlib import Path
import subprocess
import time
import urllib.request
import urllib.error


def main():
    config_file = Path(__file__).resolve().parents[2] / 'mobile/android/app/google-services.json'
    config = json.loads(config_file.read_text())
    project = config['project_info']['project_id']
    app = next(c for c in config['client'] if c['client_info']['android_client_info']['package_name'] == 'com.jarvis.jarvis_collector')
    app_id = app['client_info']['mobilesdk_app_id']
    sdk = Path(os.environ['LOCALAPPDATA']) / 'Google/google-cloud-sdk/bin/gcloud.cmd'
    token = subprocess.run([str(sdk), 'auth', 'print-access-token'], capture_output=True, text=True, check=True).stdout.strip()

    def request(path, data=None):
        req = urllib.request.Request('https://firebase.googleapis.com/v1beta1/' + path,
            data=None if data is None else json.dumps(data).encode(),
            headers={'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json', 'X-Goog-User-Project': project})
        try:
            with urllib.request.urlopen(req, timeout=30) as response:
                return json.load(response)
        except urllib.error.HTTPError as error:
            details = json.loads(error.read()).get('error', {})
            raise SystemExit(f"Firebase Management returned {error.code}: {details.get('message', 'Access denied')}")

    apps = request(f'projects/{project}/androidApps?showDeleted=true').get('apps', [])
    print('Registered Android packages: ' + ', '.join(a.get('packageName', '') + ' (' + a.get('state', '') + ')' for a in apps))
    actual = next((a for a in apps if a.get('packageName') == 'com.jarvis.jarvis_collector'), None)
    if actual:
        app_id = actual['appId']
        if actual.get('state') == 'DELETED':
            request(actual['name'] + ':undelete', {})
            print('Restored the Jarvis Android app registration required for Google authorization.')
    else:
        operation = request(f'projects/{project}/androidApps', {'packageName': 'com.jarvis.jarvis_collector', 'displayName': 'Jarvis'})
        for _ in range(20):
            operation = request(operation['name'])
            if operation.get('done'):
                if operation.get('error'):
                    raise SystemExit(operation['error'].get('message', 'Android app registration failed'))
                app_id = operation['response']['appId']
                print('Registered Jarvis Android package in the existing Firebase project.')
                break
            time.sleep(2)
        else:
            raise SystemExit('Android registration is still in progress. Run this script again shortly.')
    parent = f'projects/{project}/androidApps/{app_id}'
    fingerprint = 'F366EB41B32280D3793EBEDD4C1DBFAA1DF4EA7F'
    existing = request(parent + '/sha').get('certificates', [])
    if not any(c.get('shaHash', '').replace(':', '').upper() == fingerprint for c in existing):
        request(parent + '/sha', {'shaHash': fingerprint, 'certType': 'SHA_1'})
        print('Android signing certificate registered.')
    else:
        print('Android signing certificate already registered.')
    refreshed = json.loads(base64.b64decode(request(parent + '/config')['configFileContents']))
    clients = [oauth for c in refreshed['client'] for oauth in c.get('oauth_client', []) if oauth['client_type'] == 1]
    if clients:
        config_file.write_text(json.dumps(refreshed, indent=2) + '\n')
        print(f'Firebase configuration refreshed: {len(clients)} Android OAuth client(s) available.')
    else:
        print('No Android OAuth client returned. Create one in Google Auth Platform using the documented package and SHA-1.')


if __name__ == '__main__':
    main()
