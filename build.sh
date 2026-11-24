#!/bin/bash
# Build BBK7980.app for macOS. Usage: ./build.sh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

[ "$(uname -s)" = "Darwin" ] || { echo "build.sh 仅支持 macOS" >&2; exit 1; }

find_tk_python() {
    local candidate path
    for candidate in python3.12 python3.11 python3.13 python3.10 python3; do
        path="$(command -v "$candidate" 2>/dev/null || true)"
        [ -n "$path" ] || continue
        if "$path" -c 'import tkinter' >/dev/null 2>&1; then
            printf '%s' "$path"
            return 0
        fi
    done
    return 1
}

if [ -n "${PYTHON:-}" ]; then
    if [ -x "$PYTHON" ]; then PY="$PYTHON"; else PY="$(command -v "$PYTHON" || true)"; fi
    [ -n "$PY" ] || { echo "PYTHON 指定的解释器不存在：$PYTHON" >&2; exit 1; }
elif [ -x "$ROOT/.venv/bin/python" ]; then
    PY="$ROOT/.venv/bin/python"
else
    BASE="$(find_tk_python || true)"
    [ -n "$BASE" ] || {
        echo "找不到带 tkinter 的 Python 3。请安装 python.org 版本，或运行 brew install python-tk。" >&2
        exit 1
    }
    echo "==> 创建 .venv（${BASE}）"
    "$BASE" -m venv "$ROOT/.venv"
    PY="$ROOT/.venv/bin/python"
fi

if ! "$PY" -c 'import tkinter' >/dev/null 2>&1; then
    echo "当前 Python 缺少 tkinter：$PY" >&2
    echo "Homebrew 可运行：brew install python-tk@3.12" >&2
    exit 1
fi

if ! "$PY" -c 'import PIL, pefile, PyInstaller' >/dev/null 2>&1; then
    echo "==> 安装构建依赖（首次运行需要联网）"
    "$PY" -m pip install -r "$ROOT/requirements.txt" -r "$ROOT/requirements-build.txt"
fi

echo "==> 编译原生核心"
"$PY" build.py

if [ ! -f "$ROOT/assets/BBK7980.icns" ]; then
    echo "==> 生成应用图标"
    "$PY" tools/make_icon.py
fi

STAGE="$ROOT/build/macos/runtime"
rm -rf "$STAGE"
if [ -f "$ROOT/runtime/syscode.bin" ]; then
    echo "==> 收集运行镜像"
    mkdir -p "$STAGE"
    for name in syscode.bin installed-nand.bin.z installed-manifest.json \
                initialized-nand.bin.z font.bin; do
        if [ -f "$ROOT/runtime/$name" ]; then
            cp "$ROOT/runtime/$name" "$STAGE/$name"
        fi
    done
else
    echo "==> 未找到 runtime/，打出的 app 首次启动时会要求选择官网升级包"
fi

echo "==> 生成 BBK7980.app"
mkdir -p "$ROOT/build/macos" "$ROOT/dist"
rm -rf "$ROOT/dist/BBK7980.app" "$ROOT/build/macos/output"
ARGS=(
    --noconfirm --clean --windowed
    --name BBK7980
    --distpath "$ROOT/dist"
    --workpath "$ROOT/build/macos/work"
    --specpath "$ROOT/build/macos"
    --osx-bundle-identifier org.bbk7980.emulator
    --icon "$ROOT/assets/BBK7980.icns"
    --add-binary "$ROOT/bbk7980.dylib:."
    --add-data "$ROOT/VERSION:."
    --add-data "$ROOT/vendor/fonts:vendor/fonts"
)
if [ -d "$STAGE" ]; then
    ARGS+=(--add-data "$STAGE:runtime")
fi
"$PY" -m PyInstaller "${ARGS[@]}" "$ROOT/app.py"

APP="$ROOT/dist/BBK7980.app"
echo "==> 补充文档、许可和 Info.plist"
"$PY" - "$APP" "$ROOT" <<'PY'
from importlib.metadata import PackageNotFoundError, distribution
from pathlib import Path
import plistlib
import shutil
import sys

app, root = Path(sys.argv[1]), Path(sys.argv[2])
version = (root / 'VERSION').read_text().strip()
resources = app / 'Contents/Resources'

docs = resources / 'docs'
docs.mkdir(parents=True, exist_ok=True)
for name in ('README.md', 'COPYING', 'THIRD_PARTY.md', 'hardware.md'):
    shutil.copyfile(root / name, docs / name)
shutil.copytree(root / 'assets', docs / 'assets', dirs_exist_ok=True)

licenses = resources / 'licenses'
licenses.mkdir(parents=True, exist_ok=True)
prefix = Path(sys.base_prefix).resolve()
for directory in (prefix, *prefix.parents):
    candidate = next((path for path in (directory / 'LICENSE.txt', directory / 'LICENSE')
                      if path.is_file()), None)
    if candidate is not None:
        shutil.copyfile(candidate, licenses / 'Python.txt')
        break
for name in ('Pillow', 'pefile', 'PyInstaller'):
    try:
        metadata = distribution(name)
    except PackageNotFoundError:
        continue
    license_file = next((file for file in metadata.files or ()
                         if file.name.lower() in ('license', 'license.txt', 'copying.txt')), None)
    if license_file is not None:
        shutil.copyfile(metadata.locate_file(license_file), licenses / f'{name}.txt')

info_path = app / 'Contents/Info.plist'
with info_path.open('rb') as source:
    info = plistlib.load(source)
info.update({
    'CFBundleDisplayName': '步步高 7980 模拟器',
    'CFBundleName': 'BBK7980',
    'CFBundleShortVersionString': version,
    'CFBundleVersion': version,
    'CFBundleGetInfoString': f'步步高 7980 模拟器 {version}',
    'LSApplicationCategoryType': 'public.app-category.entertainment',
    'LSMinimumSystemVersion': '11.0',
    'NSHighResolutionCapable': True,
    'NSHumanReadableCopyright': 'GPL-3.0-or-later · BBK7980-emulator contributors',
})
with info_path.open('wb') as target:
    plistlib.dump(info, target, sort_keys=False)
PY

rm -rf "$ROOT/dist/BBK7980"
echo "完成：$APP"
