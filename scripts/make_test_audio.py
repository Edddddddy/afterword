#!/usr/bin/env python3
"""Create a small binary file large enough to trigger mock transcription."""
import sys
from pathlib import Path

path = Path(sys.argv[1] if len(sys.argv) > 1 else "/tmp/test-chunk.webm")
path.write_bytes(b"\x1a\x45\xdf\xa3" + b"\x00" * 512)
print(path)
