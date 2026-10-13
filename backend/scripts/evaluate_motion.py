"""Evaluate exported shadow telemetry against user labels; never self-label training.

Usage: python -m scripts.evaluate_motion history.json
"""
import argparse
from collections import Counter
import json
import math
from pathlib import Path


def broad(value):
    return 'ON_FOOT' if value in {'WALKING', 'RUNNING', 'ON_FOOT'} else value


def percentile(values, fraction):
    return None if not values else sorted(values)[max(0, math.ceil(len(values)*fraction)-1)]


def evaluate(records):
    labels = [r for r in records if r.get('source') == 'user_label' and r.get('label_end_at')]
    result = {}
    for source in ('local_motion', 'google_activity'):
        rows = [r for r in records if r.get('source') == source]
        pairs = []
        for row in rows:
            # Local candidates describe a sensor window ending at timestamp.
            # Require the full window to lie inside an annotation, avoiding boundaries.
            matching = []
            for label in labels:
                if row.get('boot_count') == label.get('boot_count'):
                    point = row['observed_elapsed_ms']
                    left = point-(row.get('features', {}).get('span_ms') or 0)
                    end = label['received_elapsed_ms']
                    if label['observed_elapsed_ms'] <= left and point < end:
                        matching.append(label)
            if len(matching) == 1:
                pairs.append((broad(matching[0]['candidate']), broad(row['candidate'])))
        confusion = Counter(f'{actual}->{predicted}' for actual, predicted in pairs)
        known = [(a, p) for a, p in pairs if p != 'UNKNOWN']
        delays = [r['delivery_delay_ms']/1000 for r in rows if r.get('delivery_delay_ms') is not None]
        uploads = [r['upload_delay_ms']/1000 for r in rows if r.get('upload_delay_ms') is not None]
        result[source] = {
            'observations': len(rows), 'labelled_observations': len(pairs),
            'confusion': dict(confusion),
            'classification_coverage': len(known)/len(pairs) if pairs else None,
            'accuracy_including_unknown': sum(a == p for a, p in pairs)/len(pairs) if pairs else None,
            'accuracy_when_classified': sum(a == p for a, p in known)/len(known) if known else None,
            'delivery_seconds_p50': percentile(delays, .5), 'delivery_seconds_p95': percentile(delays, .95),
            'upload_seconds_p95': percentile(uploads, .95),
            'usable_sensor_windows': sum(r.get('features', {}).get('usable') is True for r in rows),
        }
    return {'user_labels': len(labels), 'detectors': result,
            'interpretation': 'Candidate accuracy and callback delay are separate. Missing labels cannot establish accuracy. '
                              'These are observation-weighted metrics, not proof of continuous activity or guaranteed reaction latency.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('history', type=Path)
    args = parser.parse_args()
    data = json.loads(args.history.read_text(encoding='utf-8-sig'))
    print(json.dumps(evaluate(data['records'] if isinstance(data, dict) else data), indent=2))


if __name__ == '__main__':
    main()
