"""The game (game/*.js) is tested in Node: tests/game/game.test.js, run here when Node is installed."""
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


@unittest.skipUnless(shutil.which("node"), "Node.js is not installed")
class Game(unittest.TestCase):
    def test_node(self):
        r = subprocess.run(["node", "--test", "tests/game/game.test.js"], cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout[-4000:] + r.stderr[-2000:])


if __name__ == "__main__":
    unittest.main()
