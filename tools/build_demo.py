"""Build the open Minesweeper demo from a pinned Windows SDK release."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
from urllib.request import urlretrieve
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
SDK = 'BBK7980-SDK-1.1.1'
SDK_URL = f'https://github.com/HelloClyde/BBK7980-sdk/releases/download/v1.1.1/{SDK}-win64.zip'
SDK_SHA = 'e742fb3df72e41fc111d69986c90186dcebb298c08fe8e19eddb02580a713271'
SDK_COMMIT = '6dc8a74d0d3c50589804a49d9f7b06531befdd8e'
KEYS = {'UP': (57, 51), 'DOWN': (59, 58), 'LEFT': (51, 57), 'RIGHT': (58, 59)}


def build(archive):
    build_dir = ROOT / 'build'
    build_dir.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='demo-sdk-', dir=build_dir) as temp:
        temp = Path(temp)
        if archive is None:
            archive = temp / 'sdk.zip'
            urlretrieve(SDK_URL, archive)
        if hashlib.sha256(archive.read_bytes()).hexdigest() != SDK_SHA:
            raise ValueError('SDK archive SHA-256 mismatch')
        with ZipFile(archive) as sdk_zip:
            sdk_zip.extractall(temp)
        sdk = temp / SDK
        demo = sdk / 'examples/minesweeper'
        header = sdk / 'include/bbk7980.h'
        text = header.read_text(encoding='utf8')
        for key, (previous, corrected) in KEYS.items():
            text, count = re.subn(rf'(?m)^#define BBK_KEY_{key} {previous}$',
                                  f'#define BBK_KEY_{key} {corrected}', text)
            if count != 1:
                raise ValueError(f'Unexpected SDK key definition for {key}')
        header.write_text(text, encoding='utf8')
        main = demo / 'main.c'
        text = main.read_text(encoding='utf8')
        for key, (previous, _) in KEYS.items():
            text, count = re.subn(rf'\bkey=={previous}(?= &&)', f'key==BBK_KEY_{key}', text)
            if count != 1:
                raise ValueError(f'Unexpected Minesweeper direction handler for {key}')
        main.write_text(text, encoding='utf8')
        subprocess.run([sys.executable, '-X', 'utf8', 'tools/build.py', 'examples/minesweeper'],
                       cwd=sdk, check=True)
        executable, = (demo / 'build').rglob('*.exe')
        output = build_dir / 'demo/minesweeper.exe'
        output.parent.mkdir(exist_ok=True)
        shutil.copyfile(executable, output)
        source = build_dir / 'demo-source'
        if source.exists():
            shutil.rmtree(source)
        for directory in ('include', 'src', 'cfg', 'third_party'):
            shutil.copytree(sdk / directory, source / directory)
        for name in ('LICENSE', 'THIRD_PARTY.md', 'SDK.json', 'tools/build.py', 'tools/convert_icon.py'):
            destination = source / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(sdk / name, destination)
        shutil.copytree(demo, source / 'examples/minesweeper', ignore=shutil.ignore_patterns('build'))
        metadata = dict(sdk_commit=SDK_COMMIT, sdk_url=SDK_URL, sdk_sha256=SDK_SHA,
                        direction_key_codes={key: pair[1] for key, pair in KEYS.items()},
                        demo_sha256=hashlib.sha256(output.read_bytes()).hexdigest())
        (source / 'BUILD.json').write_text(json.dumps(metadata, indent=2) + '\n', encoding='utf8')
    print(output)
    return output


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sdk-archive', type=Path)
    build(parser.parse_args().sdk_archive)
