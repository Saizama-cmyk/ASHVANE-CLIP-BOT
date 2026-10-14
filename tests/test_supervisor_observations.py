"""Evidence privacy and bounded collection, including busy runtime observations."""
import json
import logging
from types import SimpleNamespace

from clipbot.config import Settings
from clipbot.supervisor_observations import RuntimeObservations


def test_fault_metadata_never_formats_or_retains_private_content(monkeypatch):
    settings = Settings()
    settings.supervisor.enabled = True
    handler = RuntimeObservations(settings)
    monkeypatch.setattr('clipbot.supervisor_observations.time.time', lambda: 1000)

    class PrivateMessage:
        def __str__(self):
            raise AssertionError('Log contents must never be formatted')

    handler.start()
    try:
        for _ in range(3):
            record = logging.LogRecord('clipbot.capture', logging.WARNING, 'C:/private-user/token.json', 99,
                                       PrivateMessage(), ('password=private-secret',), None)
            handler.handle(record)
        handler.handle(logging.LogRecord('clipbot.private-secret', logging.ERROR, '', 1, 'secret', (), None))
        snapshot = handler.snapshot(SimpleNamespace(), False)
        assert snapshot['fault_events'] == 3
        assert snapshot['faults'] == [{'source': 'capture', 'line': 99, 'severity': 'warning',
                                      'exception': '', 'count': 3, 'first_at': 1000, 'last_at': 1000}]
        assert 'private' not in json.dumps(snapshot) and 'secret' not in json.dumps(snapshot)
    finally:
        handler.stop()


def test_evidence_bounds_age_resize_and_stop(monkeypatch):
    settings = Settings()
    settings.supervisor.enabled = True
    settings.supervisor.diagnostic_event_limit = 100
    now = [1000]
    monkeypatch.setattr('clipbot.supervisor_observations.time.time', lambda: now[0])
    handler = RuntimeObservations(settings)
    handler.start()
    try:
        record = logging.LogRecord('clipbot.pipeline', logging.ERROR, '', 2, 'ignored', (), None)
        for _ in range(130):
            handler.handle(record)
        result = handler.snapshot(SimpleNamespace(), False)
        assert result['fault_events'] == 100 and result['discarded_events'] == 30 and result['bounded_sample']
        now[0] += 3601
        assert handler.snapshot(SimpleNamespace(), False)['fault_events'] == 0
        handler.stop()
        handler.handle(record)
        assert handler.snapshot(SimpleNamespace(), False)['collecting'] is False
        assert len(handler.events) == 100
        assert handler not in logging.getLogger('clipbot').handlers
    finally:
        handler.stop()


def test_queue_and_gpu_are_aggregated_without_disk_or_private_identifiers(monkeypatch):
    monkeypatch.setattr('clipbot.supervisor_observations.time.time', lambda: 1000)
    settings = Settings()
    handler = RuntimeObservations(settings)
    pipe = SimpleNamespace(_latency={
        'private-candidate': {'created_at': 800, 'phase': 'assemble_wait', 'phase_started_at': 990,
                             'path': 'private-file', 'transcript': 'private-transcript'},
        'private-finished': {'created_at': 1, 'finished_at': 900, 'phase': 'edit'},
        'private-other': {'created_at': 950, 'phase': 'private-phase', 'phase_started_at': 990}},
        gpu={'name': 'private-name', 'util': 72, 'mem_used': 1600, 'mem_total': float('nan'), 'temp': 65},
        _ai_limit=SimpleNamespace(active=1, limit=2),
        snapshot=lambda: (_ for _ in ()).throw(AssertionError('No runtime or storage scans')))
    result = handler.snapshot(pipe, True)
    assert result['queue'] == {'active': 2, 'phases': {'assemble_wait': 1, 'other': 1},
                               'oldest_age_s': 200, 'longest_wait_s': 10}
    assert result['resources']['gpu'] == {'util': 72, 'mem_used': 1600, 'mem_total': None, 'temp': 65}
    assert result['resources']['slots']['ai'] == {'active': 1, 'limit': 2}
    assert result['inference_deferred'] is True
    assert 'private' not in json.dumps(result)
