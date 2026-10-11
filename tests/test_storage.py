"""Storage transfers repair only files they actually moved; all test files are temporary."""
import json
import sqlite3
from pathlib import Path

import pytest

import clipbot.storage as S
from clipbot.config import PRODUCT, Settings, resolve_paths, storage_role_folder


def setup(tmp_path, monkeypatch):
    settings = Settings()
    settings.app.data_dir = str(tmp_path / 'data')
    paths = resolve_paths(settings)
    paths.ensure()
    control = tmp_path / 'control'
    control.mkdir()
    monkeypatch.setattr(S, 'pending_path', lambda: control / 'pending_moves.json')
    return settings, paths


def put_candidates(db, records):
    db.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db)
    try:
        conn.execute('CREATE TABLE candidates(id TEXT PRIMARY KEY, json TEXT NOT NULL)')
        conn.executemany('INSERT INTO candidates VALUES(?,?)',
                         [(key, json.dumps(record)) for key, record in records.items()])
        conn.commit()
    finally:
        conn.close()


def candidates(db):
    conn = sqlite3.connect(db)
    try:
        return {key: json.loads(raw) for key, raw in conn.execute('SELECT id,json FROM candidates')}
    finally:
        conn.close()


def test_move_repairs_raw_and_final_exactly_and_preserves_unrelated_files(tmp_path, monkeypatch):
    settings, paths = setup(tmp_path, monkeypatch)
    raw, final = paths.work / 'raw.mp4', paths.clips / 'final.mp4'
    raw.write_bytes(b'raw'); final.write_bytes(b'final')
    unrelated = paths.clips / 'personal-notes.txt'
    unrelated.write_text('stay')
    absent = paths.clips / 'absent.mp4'
    put_candidates(paths.db, {'one': {'raw_path': str(raw), 'final_path': str(final), 'stage': 'scheduled'},
                              'absent': {'raw_path': '', 'final_path': str(absent)}})
    work, clips = tmp_path / 'new-work', tmp_path / 'new-clips'
    S.queue_move('work', paths.work, work); S.queue_move('clips', paths.clips, clips)
    settings.app.work_dir = str(work); settings.app.clips_dir = str(clips)
    notes = S.apply_pending(settings)
    saved = candidates(paths.db)
    assert saved['one']['raw_path'] == str(work / raw.name)
    assert saved['one']['final_path'] == str(clips / final.name)
    assert saved['one']['stage'] == 'scheduled'
    assert saved['absent']['final_path'] == str(absent)
    assert (work / raw.name).read_bytes() == b'raw'
    assert (clips / final.name).read_bytes() == b'final'
    assert unrelated.read_text() == 'stay'
    assert not (clips / unrelated.name).exists()
    assert not S.load_pending() and len(notes) == 2


def test_collision_keeps_original_path_and_pending_move_for_retry(tmp_path, monkeypatch):
    settings, paths = setup(tmp_path, monkeypatch)
    source = paths.clips / 'final.mp4'; source.write_bytes(b'original')
    dest = tmp_path / 'new-clips'; dest.mkdir()
    collision = dest / source.name; collision.write_bytes(b'other')
    put_candidates(paths.db, {'one': {'raw_path': '', 'final_path': str(source)}})
    S.queue_move('clips', paths.clips, dest)
    settings.app.clips_dir = str(dest)
    S.apply_pending(settings)
    assert candidates(paths.db)['one']['final_path'] == str(source)
    assert source.read_bytes() == b'original' and collision.read_bytes() == b'other'
    assert len(S.load_pending()) == 1
    collision.unlink()  # Only this test's temporary collision file.
    S.apply_pending(settings)
    assert candidates(paths.db)['one']['final_path'] == str(dest / source.name)
    assert not S.load_pending()


def test_partial_failure_repairs_successes_and_retries_only_failed_files(tmp_path, monkeypatch):
    settings, paths = setup(tmp_path, monkeypatch)
    good = paths.clips / 'good.mp4'; bad = paths.clips / 'bad.mp4'
    good.write_bytes(b'good'); bad.write_bytes(b'bad')
    put_candidates(paths.db, {'good': {'final_path': str(good)}, 'bad': {'final_path': str(bad)}})
    dest = tmp_path / 'new-clips'
    S.queue_move('clips', paths.clips, dest); settings.app.clips_dir = str(dest)
    original = S.shutil.move
    def move(source, target):
        if Path(source).name == bad.name:
            raise OSError('test transfer failure')
        return original(source, target)
    monkeypatch.setattr(S.shutil, 'move', move)
    S.apply_pending(settings)
    assert candidates(paths.db)['good']['final_path'] == str(dest / good.name)
    assert candidates(paths.db)['bad']['final_path'] == str(bad)
    assert S.load_pending()[0]['moved_files'] == [{'from': str(good), 'to': str(dest / good.name)}]
    monkeypatch.setattr(S.shutil, 'move', original)
    S.apply_pending(settings)
    assert candidates(paths.db)['bad']['final_path'] == str(dest / bad.name)
    assert not S.load_pending()


def test_db_failure_retains_exact_success_map_for_next_start(tmp_path, monkeypatch):
    settings, paths = setup(tmp_path, monkeypatch)
    source = paths.clips / 'final.mp4'; source.write_bytes(b'video')
    put_candidates(paths.db, {'one': {'final_path': str(source)}})
    dest = tmp_path / 'new-clips'
    S.queue_move('clips', paths.clips, dest); settings.app.clips_dir = str(dest)
    original = S._rewrite_candidate_paths
    def broken(*args):
        raise sqlite3.OperationalError('test busy database')
    monkeypatch.setattr(S, '_rewrite_candidate_paths', broken)
    S.apply_pending(settings)
    assert not source.exists() and (dest / source.name).exists()
    assert candidates(paths.db)['one']['final_path'] == str(source)
    assert S.load_pending()[0]['moved_files']
    monkeypatch.setattr(S, '_rewrite_candidate_paths', original)
    S.apply_pending(settings)
    assert candidates(paths.db)['one']['final_path'] == str(dest / source.name)
    assert not S.load_pending()


def test_data_move_repairs_following_roles_in_new_database_and_preserves_profile(tmp_path, monkeypatch):
    settings, paths = setup(tmp_path, monkeypatch)
    raw, final = paths.work / 'raw.mp4', paths.clips / 'final.mp4'
    raw.write_bytes(b'raw'); final.write_bytes(b'final')
    put_candidates(paths.db, {'one': {'raw_path': str(raw), 'final_path': str(final)}})
    for name in ('settings.json', 'profiles.json', 'sessions.json', 'personal.txt'):
        (paths.data / name).write_text('stay')
    (paths.data / 'research.json').write_text('{}')
    dest = tmp_path / 'new-data'
    S.queue_move('data', paths.data, dest); settings.app.data_dir = str(dest)
    S.apply_pending(settings)
    saved = candidates(dest / 'clipbot.db')['one']
    assert saved['raw_path'] == str(dest / 'work' / raw.name)
    assert saved['final_path'] == str(dest / 'clips' / final.name)
    assert (dest / 'research.json').is_file()
    for name in ('settings.json', 'profiles.json', 'sessions.json', 'personal.txt'):
        assert (paths.data / name).read_text() == 'stay'
        assert not (dest / name).exists()
    assert not S.load_pending()


def test_db_repair_targets_existing_active_database_not_colliding_old_database(tmp_path, monkeypatch):
    settings, paths = setup(tmp_path, monkeypatch)
    old_data = paths.data
    old_clip = old_data / 'clips' / 'final.mp4'; old_clip.write_bytes(b'video')
    put_candidates(paths.db, {'old': {'final_path': str(old_clip)}})
    new_data = tmp_path / 'new-data'
    active_db = new_data / 'clipbot.db'
    put_candidates(active_db, {'active': {'final_path': str(old_clip)}})
    S.queue_move('data', old_data, new_data); settings.app.data_dir = str(new_data)
    S.apply_pending(settings)
    assert candidates(active_db)['active']['final_path'] == str(new_data / 'clips' / old_clip.name)
    assert candidates(paths.db)['old']['final_path'] == str(old_clip)
    assert S.load_pending()  # The old DB collision remains pending, never overwrites active data.


@pytest.mark.parametrize('kind', ['data', 'buffer', 'work', 'clips', 'logs', 'models'])
def test_drive_root_destination_matches_resolver_without_touching_drive(tmp_path, monkeypatch, kind):
    settings, paths = setup(tmp_path, monkeypatch)
    root = Path(tmp_path.anchor)
    expected = root / PRODUCT / kind
    assert storage_role_folder(root, kind) == expected
    S.queue_move(kind, paths.clips, root)
    assert Path(S.load_pending()[0]['to']) == expected
    assert not (paths.clips / 'unknown').exists()


@pytest.mark.parametrize('relative', ['relative-source', 'relative-dest'])
def test_queue_rejects_relative_paths(tmp_path, monkeypatch, relative):
    settings, paths = setup(tmp_path, monkeypatch)
    src = Path('relative') if relative == 'relative-source' else paths.clips
    dest = Path('relative') if relative == 'relative-dest' else tmp_path / 'new'
    with pytest.raises(ValueError, match='absolute'):
        S.queue_move('clips', src, dest)
    assert not S.load_pending()


def test_root_source_and_overlapping_paths_are_rejected_without_moves(tmp_path, monkeypatch):
    settings, paths = setup(tmp_path, monkeypatch)
    with pytest.raises(ValueError, match='drive root'):
        S.queue_move('clips', Path(tmp_path.anchor), tmp_path / 'new')
    for dest in (paths.clips / 'nested', paths.data):
        with pytest.raises(ValueError, match='overlap'):
            S.queue_move('clips', paths.clips, dest)
    assert not S.load_pending()


def test_legacy_unsafe_pending_move_is_retained_without_io(tmp_path, monkeypatch):
    settings, paths = setup(tmp_path, monkeypatch)
    invalid = {'kind': 'clips', 'from': str(Path(tmp_path.anchor)), 'to': str(tmp_path / 'new')}
    S.pending_path().write_text(json.dumps([invalid]))
    notes = S.apply_pending(settings)
    assert 'drive root' in notes[0]
    assert S.load_pending() == [invalid]
    assert not (tmp_path / 'new').exists()


def test_missing_source_stays_pending_and_candidate_path_is_unchanged(tmp_path, monkeypatch):
    settings, paths = setup(tmp_path, monkeypatch)
    absent_source = tmp_path / 'missing'
    source_file = absent_source / 'clip.mp4'
    put_candidates(paths.db, {'one': {'final_path': str(source_file)}})
    S.queue_move('clips', absent_source, tmp_path / 'new')
    S.apply_pending(settings)
    assert candidates(paths.db)['one']['final_path'] == str(source_file)
    assert len(S.load_pending()) == 1



def test_clips_queued_before_data_repairs_paths_in_moved_active_database(tmp_path, monkeypatch):
    settings, paths = setup(tmp_path, monkeypatch)
    final = paths.clips / 'final.mp4'; final.write_bytes(b'video')
    put_candidates(paths.db, {'one': {'raw_path': '', 'final_path': str(final), 'stage': 'scheduled'}})
    new_clips, new_data = tmp_path / 'new-clips', tmp_path / 'new-data'
    S.queue_move('clips', paths.clips, new_clips)
    S.queue_move('data', paths.data, new_data)
    settings.app.clips_dir = str(new_clips)
    settings.app.data_dir = str(new_data)
    S.apply_pending(settings)
    saved = candidates(new_data / 'clipbot.db')['one']
    assert saved['final_path'] == str(new_clips / final.name)
    assert Path(saved['final_path']).read_bytes() == b'video'
    assert saved['stage'] == 'scheduled'
    assert not S.load_pending()


def test_failed_data_transfer_keeps_media_mapping_until_active_db_can_be_repaired(tmp_path, monkeypatch):
    settings, paths = setup(tmp_path, monkeypatch)
    final = paths.clips / 'final.mp4'; final.write_bytes(b'video')
    put_candidates(paths.db, {'one': {'final_path': str(final)}})
    new_clips, new_data = tmp_path / 'new-clips', tmp_path / 'new-data'
    S.queue_move('clips', paths.clips, new_clips)
    S.queue_move('data', paths.data, new_data)
    settings.app.clips_dir = str(new_clips)
    settings.app.data_dir = str(new_data)
    original = S.shutil.move
    def move(source, target):
        if Path(source).name == 'clipbot.db':
            raise OSError('test database transfer failure')
        return original(source, target)
    monkeypatch.setattr(S.shutil, 'move', move)
    with pytest.raises(S.StorageMoveIncomplete, match='original database'):
        S.apply_pending(settings)
    assert candidates(paths.db)['one']['final_path'] == str(final)
    assert (new_clips / final.name).is_file()
    assert {entry['kind'] for entry in S.load_pending()} == {'data', 'clips'}
    monkeypatch.setattr(S.shutil, 'move', original)
    S.apply_pending(settings)
    saved = candidates(new_data / 'clipbot.db')['one']
    assert saved['final_path'] == str(new_clips / final.name)
    assert Path(saved['final_path']).is_file()
    assert not S.load_pending()



def test_startup_does_not_create_empty_database_after_failed_data_transfer(tmp_path, monkeypatch):
    from clipbot.app import ClipBotApp
    import clipbot.app as app_module
    settings, paths = setup(tmp_path, monkeypatch)
    put_candidates(paths.db, {'one': {'final_path': str(paths.clips / 'scheduled.mp4')}})
    new_data = tmp_path / 'new-data'
    S.queue_move('data', paths.data, new_data)
    settings.app.data_dir = str(new_data)
    def failed_move(*args):
        raise OSError('test destination unavailable')
    def unexpected_pipeline(*args):
        raise AssertionError('Pipeline/Store must not open before a successful data move')
    monkeypatch.setattr(S.shutil, 'move', failed_move)
    monkeypatch.setattr(app_module, 'Pipeline', unexpected_pipeline)
    with pytest.raises(S.StorageMoveIncomplete, match='Startup stopped'):
        ClipBotApp(settings, dashboard=False)
    assert not (new_data / 'clipbot.db').exists()
    assert candidates(paths.db)['one']['final_path'] == str(paths.clips / 'scheduled.mp4')
    assert len(S.load_pending()) == 1



@pytest.mark.parametrize('mode', ['--window', '--headless'])
def test_entrypoint_reports_storage_startup_failure_and_releases_lock(tmp_path, monkeypatch, mode):
    import clipbot.__main__ as entry
    import clipbot.app as app_module
    import clipbot.desktop as desktop_module
    settings = Settings()
    settings.app.single_instance = True
    reports, locks = [], []
    class Lock:
        already_running = False
        def __init__(self):
            self.released = False
            locks.append(self)
        def release(self):
            self.released = True
    def blocked(*args, **kwargs):
        raise S.StorageMoveIncomplete('Original database remains pending; restart safely.')
    monkeypatch.setattr(entry, 'migrate_data_dir', lambda: False)
    monkeypatch.setattr(entry, 'load_settings', lambda: settings)
    monkeypatch.setattr(entry, 'settings_path', lambda: tmp_path / 'settings.json')
    monkeypatch.setattr(entry, 'is_frozen', lambda: False)
    monkeypatch.setattr(app_module, 'setup_logging', lambda *args, **kwargs: tmp_path / 'clipbot.log')
    monkeypatch.setattr(app_module, 'ClipBotApp', blocked)
    monkeypatch.setattr(desktop_module, 'Desktop', blocked)
    monkeypatch.setattr(desktop_module, 'SingleInstance', Lock)
    def fatal(message, windowed):
        reports.append((message, windowed))
        return 1
    monkeypatch.setattr(entry, '_fatal', fatal)
    assert entry.main([mode]) == 1
    assert reports == [('Original database remains pending; restart safely.', mode == '--window')]
    assert len(locks) == 1 and locks[0].released
