import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import launch


class RuntimeOwnershipTests(unittest.TestCase):
    def test_stale_or_different_process_is_never_killed(self):
        with tempfile.TemporaryDirectory() as temp:
            record = {"pid": 99999, "executable": str(launch.STUDIO_EXE), "created": 100}
            path = Path(temp) / "runtime-owned.json"
            path.write_text(json.dumps({"studio": record}))
            with patch.object(launch, "OWNERSHIP", path), patch.object(launch.subprocess, "run", side_effect=AssertionError("Must not kill an unowned process")):
                for actual in (None, {**record, "created": 101}, {**record, "executable": "C:/other.exe"}):
                    with self.subTest(actual=actual), patch.object(launch, "_process_identity", return_value=actual):
                        self.assertFalse(launch.stop_owned_studio())

    @unittest.skipUnless(os.name == "nt", "Windows process identity")
    def test_actual_process_identity_reads_creation_time_and_image(self):
        identity = launch._process_identity(os.getpid())
        self.assertEqual(identity["pid"], os.getpid())
        self.assertGreater(identity["created"], 0)
        self.assertTrue(Path(identity["executable"]).is_file())


if __name__ == "__main__":
    unittest.main()
