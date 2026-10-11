"""Offline ownership/plan tests. Native verification is separately retained."""
import json
from contextlib import closing
from array import array
import math
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
import wave

import reaper_pipeline as r


class ReaperTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.app = Path(self.temp.name) / "app"
        self.app.mkdir()
        self.patchers = [patch.object(r, "APP", self.app), patch.object(r, "ROOT", self.app / "reaper/projects"),
                         patch.object(r, "RENDERS", self.app / "renders"), patch.object(r, "STUDIO_DATA", self.app / "studio/data"),
                         patch.dict(r.CONFIG, {"sample_rate": 4000})]
        for p in self.patchers:
            p.start()
        self.addCleanup(self.temp.cleanup)
        for p in reversed(self.patchers):
            self.addCleanup(p.stop)

    def project(self):
        return r.create_project({"bars": 1, "bpm": 240, "tracks": [{"instrument": "kick", "steps": [0, 4, 8, 12]}]})

    def test_original_pattern_has_audio_midi_and_no_source_mutation(self):
        p = self.project()
        folder = r._folder(p["id"])
        self.assertEqual(p["duration_seconds"], 1)
        with wave.open(str(folder / "media/beat-1-kick.wav")) as w:
            self.assertEqual(w.getnframes(), 4000)
            self.assertTrue(any(w.readframes(4000)))
        self.assertTrue((folder / "media/beat-1-kick.mid").read_bytes().startswith(b"MThd"))
        self.assertIn("Beat 1 - kick", (folder / "session.rpp").read_text())
        self.assertEqual(r.get_project(p["id"])["notes"], p["notes"])

    def test_inputs_reject_nonfinite_code_paths_and_excess_work(self):
        for p in ({"bpm": float("nan")}, {"bars": True}, {"file": "C:/other.wav"}, {"key": "bad"},
                  {"tracks": [{"instrument": "kick", "steps": [0, 0]}]}, {"tracks": [{"instrument": "shell", "steps": []}]},
                  {"producer_brief": "x\x00"}, {"bars": 65, "bpm": 40}):
            with self.subTest(p=p), self.assertRaises(r.ReaperError):
                r.validate_create(p)
        with self.assertRaises(r.ReaperError) as e:
            r.create_project({"replace_backing": True})
        self.assertEqual(e.exception.status, 409)

    def test_read_only_library_and_reference_projection(self):
        media = r.STUDIO_DATA / "media"
        media.mkdir(parents=True)
        ident = "11111111-1111-1111-1111-111111111111"
        audio = media / "master.wav"
        audio.write_bytes(b"retained-original")
        with closing(sqlite3.connect(r.STUDIO_DATA / "library.sqlite")) as con:
            con.execute("CREATE TABLE songs (id,title,audio_path,source,replay_request_json,generation_settings_json,metadata_json)")
            con.execute("INSERT INTO songs VALUES (?,?,?,?,?,?,?)", (ident, "Source", str(audio), "local_generation", '{"abc":"Q:1/4=90"}', '{}', '{"duration_seconds":1}'))
            con.commit()
        p = r.create_project({"song_id": ident, "bpm": 240, "bars": 1, "tracks": [{"instrument": "kick", "steps": [0]}]})
        self.assertEqual(audio.read_bytes(), b"retained-original")
        self.assertEqual((r._folder(p["id"]) / "score.abc").read_text(), "Q:1/4=90")
        self.assertFalse(p["tracks"][0]["mute"])

    def test_replacement_preserves_dry_vocals_and_mutes_backing(self):
        ident = "22222222-2222-2222-2222-222222222222"
        folder = r.RENDERS / ident
        folder.mkdir(parents=True)
        (folder / "stems/htdemucs/source").mkdir(parents=True)
        for name in ("master.wav", "converted-vocal.wav", "stems/htdemucs/source/vocals.wav", "stems/htdemucs/source/no_vocals.wav"):
            (folder / name).write_bytes(b"original-retained-asset")
        (folder / "job.json").write_text(json.dumps({"id": ident, "status": "completed", "output": {"duration_seconds": 1}}))
        p = r.create_project({"render_id": ident, "replace_backing": True, "bars": 1, "bpm": 240})
        tracks = {t["name"]: t for t in p["tracks"]}
        self.assertTrue(tracks["Generated backing"]["mute"])
        self.assertTrue(tracks["Original dry vocal"]["mute"])
        self.assertFalse(tracks["Converted dry vocal"]["mute"])
        self.assertEqual((folder / "converted-vocal.wav").read_bytes(), b"original-retained-asset")

    def test_edit_plan_requires_named_tracks_bounded_values_and_allowlist(self):
        ident = self.project()["id"]
        valid = {"summary": "balance", "actions": [{"type": "set_track", "track": "Beat 1 - kick", "volume_db": -12, "pan": .1}]}
        self.assertTrue(r.validate_plan(ident, valid)["validated"])
        self.assertTrue(r.validate_plan(ident, r.validate_plan(ident, valid))["validated"])
        melody = {"type": "replace_pattern", "track": "Beat 1 - kick", "instrument": "kick", "notes": [{"step": .125, "note": 40, "velocity": 80, "length_steps": .5}]}
        self.assertEqual(r.validate_plan(ident, {"actions": [melody]})["actions"][0]["notes"][0]["note"], 40)
        for a in ({"type": "execute", "lua": "os.execute('bad')"}, {"type": "set_track", "track": "absent", "mute": True},
                  {"type": "set_tempo", "bpm": float("inf")}, {"type": "set_track", "track": "Beat 1 - kick", "volume_db": 100},
                  {"type": "add_stock_fx", "track": "Beat 1 - kick", "fx": "arbitrary"},
                  {"type": "replace_pattern", "track": "Beat 1 - kick", "instrument": "bass", "steps": [0]},
                  {"type": "arrange_item", "track": "Beat 1 - kick", "start_seconds": 599, "length_seconds": 20}):
            with self.subTest(a=a), self.assertRaises(r.ReaperError):
                r.validate_plan(ident, {"actions": [a]})
        escaped = r._lua('"; os.execute("bad"); --')
        self.assertNotIn("os.execute", escaped)

    def test_only_completed_managed_audio_can_be_streamed(self):
        p = self.project()
        rid = "33333333-3333-3333-3333-333333333333"
        path = r._folder(p["id"]) / f"revision-{rid}.wav"
        path.write_bytes(b"not-ready")
        with self.assertRaises(r.ReaperError):
            r.media_path(p["id"], rid)
        p["revisions"] = [{"id": rid, "status": "completed", "audio_url": "/owned"}]
        r._save(r._folder(p["id"]) / "project.json", p)
        self.assertEqual(r.media_path(p["id"], rid), path)
        with self.assertRaises(r.ReaperError):
            r.media_path(p["id"], "../bad")

    def test_stale_native_job_is_failed_without_losing_sources(self):
        p = self.project()
        p["revisions"] = [{"id": "old", "status": "rendering"}]
        r._save(r._folder(p["id"]) / "project.json", p)
        self.assertEqual(r.get_project(p["id"])["revisions"][0]["status"], "failed")
        self.assertTrue((r._folder(p["id"]) / "session.rpp").is_file())

    @unittest.skipUnless(r.shutil.which("ffmpeg") and r.shutil.which("ffprobe"), "FFmpeg tools unavailable")
    def test_stereo_quality_does_not_cancel_phase_opposed_audio(self):
        path = self.app / "opposed.wav"
        samples = array("h")
        for i in range(4800):
            value = int(math.sin(i * 2 * math.pi * 440 / 48000) * 16000)
            samples.extend([value, -value])
        with wave.open(str(path), "wb") as w:
            w.setparams((2, 2, 48000, 4800, "NONE", "none"))
            w.writeframes(samples.tobytes())
        result = r._qc(path)
        self.assertTrue(result["non_silent"])
        self.assertGreater(result["peak"], .48)
        self.assertTrue(result["review_required"])


if __name__ == "__main__":
    unittest.main()
