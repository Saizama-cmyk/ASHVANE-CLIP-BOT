"""Keep narration/captions synchronized and honor creator-supplied scene artwork."""
import asyncio
import json
import sys
from types import SimpleNamespace

import numpy as np
from PIL import Image
import pytest

from clipbot.config import Settings
from clipbot.story_render import StoryRenderer, write_captions
from clipbot.story_voice import narrate, narration_sentences, spoken_text, validate_spoken_text


def test_measured_sentence_captions_never_fill_the_breath_or_next_sentence(tmp_path):
    target = tmp_path / "captions.ass"
    write_captions("Wait here. Never open it.", 9, target, 7, 720, 1280, "Test Font", 42,
                   [{"text": "Wait here.", "start": 0, "end": 2},
                    {"text": "Never open it.", "start": 4, "end": 9}], 230)
    lines = [line for line in target.read_text().splitlines() if line.startswith("Dialogue:")]
    assert len(lines) == 2
    assert "00:00:00.00,00:00:02.00" in lines[0]
    assert "00:00:04.00,00:00:09.00" in lines[1]
    assert lines[0].endswith("Wait here.")
    assert lines[1].endswith("Never open it.")
    assert ",230,1" in target.read_text()


def test_spoken_formatting_and_caption_markup_are_not_read_as_literal_emphasis(tmp_path):
    assert spoken_text("It wanted to *correct* me, **not** help.") == "It wanted to correct me, not help."
    assert narration_sentences("At 2.17 I waited. Then I ran!") == ["At 2.17 I waited.", "Then I ran!"]
    target = tmp_path / "captions.ass"
    write_captions("A {\\pos(0,0)} <voice> *shadow*.", 3, target, 7, 720, 1280, "Font", 42)
    dialogue = target.read_text().split("Dialogue:")[-1]
    assert "{" not in dialogue and "<" not in dialogue and "*shadow*" not in dialogue


def test_neural_reading_saves_real_sentence_boundaries_and_configured_breath(tmp_path, monkeypatch):
    model, voices = tmp_path / "model.onnx", tmp_path / "voices.bin"
    model.write_bytes(b"test")
    with voices.open("wb") as output:
        np.savez(output, am_adam=np.zeros((1, 2)))
    calls = []
    class Narrator:
        def create(self, text, **kwargs):
            calls.append((text, kwargs))
            return np.ones(100, dtype=np.float32) / 10, 100
    monkeypatch.setitem(sys.modules, "onnxruntime", SimpleNamespace(SessionOptions=lambda: SimpleNamespace(), InferenceSession=lambda *a, **kw: None))
    monkeypatch.setitem(sys.modules, "kokoro_onnx", SimpleNamespace(Kokoro=SimpleNamespace(from_session=lambda *a: Narrator())))
    result = narrate({"root": str(tmp_path), "model_path": str(model), "voices_path": str(voices),
                      "voice": "am_adam", "speed": 0.92, "lang": "en-us", "threads": 2,
                      "sentence_pause_s": 0.3, "clause_pause_s": 0.1,
                      "scenes": [{"text": "Wait here. Then run.", "path": "out.wav"}]})
    timing = json.loads((tmp_path / "out.timings.json").read_text())
    assert result["duration_s"] == 2.3
    assert timing["segments"] == [{"text": "Wait here.", "start": 0, "end": 1}, {"text": "Then run.", "start": 1.3, "end": 2.3}]
    assert [row[0] for row in calls] == ["Wait here.", "Then run."]
    assert calls[0][1]["clause_pause"] == 0.1


def test_supplied_complete_artwork_is_used_without_an_unrelated_character(tmp_path):
    source = tmp_path / "creator-art.png"
    Image.new("RGB", (32, 32), (180, 20, 40)).save(source)
    renderer = StoryRenderer(Settings(), None, asyncio.Lock())
    scene = {"visual_prompt": "My original haunted kitchen", "asset_path": str(source), "visual": {"setting": "room", "subject": "figure"}}
    layers = asyncio.run(renderer._illustrate(scene, tmp_path / "scene-0", 256, 256, Settings()))
    with Image.open(layers["background"]) as img:
        assert img.getpixel((128, 128)) == (180, 20, 40)
    assert layers["full_frame"] is True
    assert "figure" not in layers and "fog" not in layers
    outside = tmp_path.parent / "outside.png"
    Image.new("RGB", (32, 32)).save(outside)
    with pytest.raises(ValueError, match="inside this project"):
        asyncio.run(renderer._illustrate({**scene, "asset_path": str(outside)}, tmp_path / "scene-1", 256, 256, Settings()))


@pytest.mark.parametrize("direction", ["The camera pulls back — the room is empty.", "I stood still. The final shot reveals the monster.", "Fade to black.", "Scene 2: the hallway."])
def test_production_directions_cannot_be_sent_to_the_narrator(direction):
    with pytest.raises(ValueError, match="Production directions"):
        validate_spoken_text(direction)


def test_cameras_and_gunshots_remain_legal_story_content():
    validate_spoken_text("I checked the security camera. Its lens turned toward me. The final shot hit the lock, but the door stayed shut.")
