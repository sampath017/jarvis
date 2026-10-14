from scripts.evaluate_motion import evaluate


def test_without_human_labels_accuracy_is_unknown():
    result = evaluate([{'source': 'local_motion', 'candidate': 'STILL', 'delivery_delay_ms': 0}])
    assert result['detectors']['local_motion']['accuracy_when_classified'] is None


def test_unknown_predictions_count_against_coverage_and_overall_accuracy():
    rows = [{'source': 'user_label', 'candidate': 'WALKING', 'label_end_at': '2026-10-12T12:01:00Z',
             'boot_count': 1, 'observed_elapsed_ms': 0, 'received_elapsed_ms': 60_000}]
    rows += [{'source': 'local_motion', 'candidate': candidate, 'boot_count': 1,
              'observed_elapsed_ms': i*15_000, 'features': {'span_ms': 10_000}}
             for i, candidate in enumerate(['ON_FOOT', 'UNKNOWN', 'STILL'], 1)]
    result = evaluate(rows)['detectors']['local_motion']
    assert result['labelled_observations'] == 3
    assert result['classification_coverage'] == 2/3
    assert result['accuracy_including_unknown'] == 1/3
    assert result['accuracy_when_classified'] == 1/2


def test_ambiguous_label_overlaps_and_boot_changes_are_not_ground_truth():
    label = {'source': 'user_label', 'candidate': 'STILL', 'label_end_at': '2026-10-12T12:01:00Z',
             'boot_count': 1, 'observed_elapsed_ms': 0, 'received_elapsed_ms': 60_000}
    candidate = {'source': 'local_motion', 'candidate': 'STILL', 'boot_count': 1, 'observed_elapsed_ms': 30_000}
    assert evaluate([label, label, candidate])['detectors']['local_motion']['labelled_observations'] == 0
    assert evaluate([label, {**candidate, 'boot_count': 2}])['detectors']['local_motion']['labelled_observations'] == 0


def test_sensor_windows_crossing_a_label_boundary_are_excluded():
    rows = [{'source': 'user_label', 'candidate': 'STILL', 'label_end_at': '2026-10-12T12:01:00Z',
             'boot_count': 1, 'observed_elapsed_ms': 25_000, 'received_elapsed_ms': 60_000},
            {'source': 'local_motion', 'candidate': 'STILL', 'boot_count': 1,
             'observed_elapsed_ms': 30_000, 'features': {'span_ms': 15_000}}]
    assert evaluate(rows)['detectors']['local_motion']['labelled_observations'] == 0
