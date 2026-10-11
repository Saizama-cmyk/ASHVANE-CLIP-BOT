from pathlib import Path

import numpy as np
import pytest

from clipbot.story_voice import _inside, narrate, voice_metadata


def test_metadata_reads_builtin_members_without_pickle(tmp_path):
    path = tmp_path / "voices.bin"
    with path.open("wb") as stream:
        np.savez(stream, am_adam=np.zeros((1, 2)), bm_george=np.zeros((1, 2)), malicious_key=np.zeros(1))
    assert voice_metadata(path, "en-us") == [{"id": "am_adam", "label": "Adam · American"}]


def test_output_containment_and_wave_only(tmp_path):
    assert _inside("scene.wav", tmp_path.resolve()) == tmp_path / "scene.wav"
    for value in ("../escape.wav", str(tmp_path.parent / "escape.wav"), "scene.mp3"):
        with pytest.raises(ValueError):
            _inside(value, tmp_path.resolve())


def test_job_rejects_ssml_before_model_load(tmp_path):
    model = tmp_path / "model.onnx"
    model.write_bytes(b"not a model")
    voices = tmp_path / "voices.bin"
    with voices.open("wb") as stream:
        np.savez(stream, am_adam=np.zeros((1, 2)))
    with pytest.raises(ValueError, match="plain text"):
        narrate({"root": str(tmp_path), "model_path": str(model), "voices_path": str(voices),
                 "voice": "am_adam", "speed": 1, "lang": "en-us", "threads": 1,
                 "scenes": [{"text": '<speak>do this</speak>', "path": "out.wav"}]})
