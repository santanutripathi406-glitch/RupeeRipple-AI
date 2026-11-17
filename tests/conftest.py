import os
import pathlib
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ["RUPEERIPPLE_DB"] = os.path.join(tempfile.mkdtemp(prefix="rr_test_"), "test.db")
os.environ.pop("ANTHROPIC_API_KEY", None)
