"""Explicit maintenance wipe of this personal Jarvis project's application data.

Supply an authorized Google access token on stdin. Never print the token or
document contents. Pause writers and background jobs before --execute.
"""
import argparse
import json
import sys

from google.cloud import firestore, storage
from google.oauth2.credentials import Credentials

PROJECT = 'jarvis-agent-61947'
BUCKET = 'jarvis-agent-61947-recordings'


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--execute', action='store_true')
    args = parser.parse_args()
    token = sys.stdin.read().strip()
    if not token:
        raise SystemExit('An access token is required on stdin')
    credentials = Credentials(token)
    db = firestore.Client(project=PROJECT, credentials=credentials)
    cloud = storage.Client(project=PROJECT, credentials=credentials)
    collections = list(db.collections())
    objects = list(cloud.list_blobs(BUCKET, versions=True))
    retained_objects = list(cloud.list_blobs(BUCKET, soft_deleted=True))
    print(json.dumps({'project': PROJECT, 'collections': [c.id for c in collections],
                      'recording_objects': len(objects),
                      'soft_deleted_recording_objects': len(retained_objects),
                      'soft_delete_expiries': [
                          blob._properties.get('hardDeleteTime')
                          for blob in retained_objects
                      ]}), flush=True)
    if not args.execute:
        return
    for collection in collections:
        # Includes nested user timelines, sessions, command runs, notifications,
        # devices and libraries, even below a missing ancestor document.
        deleted = db.recursive_delete(collection)
        print(json.dumps({'collection': collection.id, 'deleted': deleted}), flush=True)
    for blob in objects:
        blob.delete(if_generation_match=blob.generation)
    remaining = list(db.collections())
    remaining_objects = list(cloud.list_blobs(BUCKET, versions=True))
    print(json.dumps({'remaining_collections': [c.id for c in remaining],
                      'remaining_recording_objects': len(remaining_objects)}), flush=True)
    if remaining or remaining_objects:
        raise SystemExit('Wipe verification found remaining application data')


if __name__ == '__main__':
    main()
