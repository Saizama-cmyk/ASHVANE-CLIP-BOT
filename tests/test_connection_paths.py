import os
from pathlib import Path

import pytest

from clipbot.config import PRODUCT, Settings, resolve_paths


@pytest.mark.skipif(os.name != 'nt', reason='Windows drive-root behavior')
def test_selecting_one_drive_keeps_buffer_work_clips_and_logs_separate():
    settings = Settings()
    for role in ('buffer', 'work', 'clips', 'logs'):
        setattr(settings.app, role + '_dir', 'E:\\')
    paths = resolve_paths(settings)
    folders = [getattr(paths, role) for role in ('buffer', 'work', 'clips', 'logs')]
    assert len(set(folders)) == 4
    assert paths.clips == Path('E:/') / PRODUCT / 'clips'
    assert all(path.parent == Path('E:/') / PRODUCT for path in folders)


def test_explicit_custom_role_folder_is_preserved(tmp_path):
    settings = Settings()
    settings.app.clips_dir = str(tmp_path / 'my-finished-videos')
    assert resolve_paths(settings).clips == tmp_path / 'my-finished-videos'
