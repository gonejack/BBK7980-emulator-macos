"""Build the native CPU/board library for macOS."""
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parent


def build():
    compiler = shutil.which('clang') or '/usr/bin/clang'
    out = ROOT / 'bbk7980.dylib'
    subprocess.run([compiler, '-O2', '-std=gnu11', '-dynamiclib',
                    '-fvisibility=hidden', '-Wall', '-Wextra',
                    '-mmacosx-version-min=11.0',
                    str(ROOT / 'src/machine.c'),
                    str(ROOT / 'src/audio_macos.c'),
                    '-framework', 'AudioToolbox', '-o', str(out)],
                   check=True, cwd=ROOT)
    print(out)


if __name__ == "__main__":
    build()
