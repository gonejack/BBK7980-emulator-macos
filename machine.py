"""ctypes interface to the 65C02/ST2xxx board model (macOS)."""
from pathlib import Path
import ctypes as C
import os
import shutil
import sys
import zlib

ROOT = Path(__file__).resolve().parent
# PyInstaller puts the executable and bundled data next to each other; inside
# a .app the interpreter lives in Contents/MacOS while data lives in
# Contents/Frameworks, exported by sys._MEIPASS.
RESOURCE_DIR = Path(getattr(sys, '_MEIPASS', ROOT))
APP_DIR = Path(sys.executable).parent if getattr(sys, 'frozen', False) else ROOT
LIBRARY_NAME = 'bbk7980.dylib'
DATA_HOME = Path.home() / 'Library/Application Support/BBK7980'


def library_path():
    for directory in (RESOURCE_DIR, ROOT, APP_DIR, Path(__file__).resolve().parent):
        candidate = directory / LIBRARY_NAME
        if candidate.is_file():
            return candidate
    return RESOURCE_DIR / LIBRARY_NAME


def default_runtime():
    """Writable runtime directory; an explicit override wins everywhere."""
    override = os.environ.get('BBK7980_RUNTIME')
    if override:
        return Path(override).expanduser()
    if getattr(sys, 'frozen', False):
        return DATA_HOME / 'runtime'
    return ROOT / 'runtime'


def ensure_runtime(runtime):
    """Seed the writable runtime from the copy inside the app bundle.

    The bundle is treated as read-only: saves and regenerated runtimes must
    never be written inside BBK7980.app (Gatekeeper may even run it from a
    randomized read-only location).
    """
    runtime = Path(runtime).expanduser()
    bundled = RESOURCE_DIR / 'runtime'
    if not getattr(sys, 'frozen', False) or not bundled.is_dir():
        return runtime
    if runtime.resolve() == bundled.resolve():
        return runtime
    runtime.mkdir(parents=True, exist_ok=True)
    for name in ('syscode.bin', 'installed-nand.bin.z', 'installed-manifest.json',
                 'initialized-nand.bin.z', 'font.bin'):
        source, target = bundled / name, runtime / name
        if source.is_file() and not target.is_file():
            temporary = target.with_suffix(target.suffix + '.tmp')
            shutil.copyfile(source, temporary)
            temporary.replace(target)
    return runtime


class Machine:
    def __init__(self, firmware=None):
        self.lib = C.CDLL(str(library_path()))
        for name in ("bbk_run", "bbk_clocks", "bbk_instructions", "bbk_irqs", "bbk_iocount"):
            getattr(self.lib, name).restype = C.c_uint64
        self.lib.bbk_read.restype = self.lib.bbk_phys_read.restype = C.c_uint8
        self.lib.bbk_load.argtypes = [C.POINTER(C.c_uint8), C.c_uint32]
        self.lib.bbk_lcd.argtypes = [C.POINTER(C.c_uint8)]
        for name in ('bbk_nand_export',):
            getattr(self.lib,name).argtypes = [C.POINTER(C.c_uint8)]
        for name in ('bbk_nand_import','bbk_uart_send','bbk_uart_receive'):
            getattr(self.lib,name).argtypes = [C.POINTER(C.c_uint8),C.c_uint32]
        if hasattr(self.lib,'bbk_audio_read'):
            self.lib.bbk_audio_read.argtypes=[C.POINTER(C.c_int16),C.c_uint32]
        if hasattr(self.lib,'bbk_out_write'):
            self.lib.bbk_out_write.argtypes=[C.c_char_p,C.c_uint32]
        if isinstance(firmware, bytes):
            self.load_bytes(firmware)
        else:
            self.load(Path(firmware) if firmware else ROOT / "runtime/syscode.bin")

    def load(self, path):
        self.load_bytes(path.read_bytes())

    def load_bytes(self, data):
        buf = (C.c_uint8 * len(data)).from_buffer_copy(data)
        if self.lib.bbk_load(buf, len(data)) != 0:
            raise ValueError("System image must be exactly 524288 bytes")
        self.lib.bbk_reset()

    def run(self, cycles):
        if not 0 <= cycles <= 0xffffffff:
            raise ValueError('Cycle budget must fit an unsigned 32-bit value')
        return self.lib.bbk_run(cycles)

    def state(self):
        d = dict(zip(("pc", "a", "x", "y", "sp", "p"),
                     (self.lib.bbk_reg(i) for i in range(6))))
        d.update(cycles=self.lib.bbk_clocks(), instructions=self.lib.bbk_instructions(),
                 interrupts=self.lib.bbk_irqs(), flags=self.lib.bbk_flags())
        return d

    def frame(self):
        pixels = (C.c_uint8 * (240 * 120))()
        self.lib.bbk_lcd(pixels)
        return bytes(pixels)

    def audio(self):
        if not hasattr(self.lib,'bbk_audio_read'):return b''
        samples=(C.c_int16*32768)();count=self.lib.bbk_audio_read(samples,len(samples))
        return bytes(samples)[:count*2]

    def snapshot_nand(self):
        size = self.lib.bbk_nand_size()
        data = (C.c_uint8 * size)()
        self.lib.bbk_nand_export(data)
        return data

    def restore_nand(self, data):
        if self.lib.bbk_nand_import(data, len(data)):
            raise ValueError("Invalid NAND size; expected 64 MiB plus 16-byte spare per page")

    def save_nand(self, path):
        data = self.snapshot_nand()
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_bytes(bytes(data))
        temporary.replace(path)

    def load_nand(self, path):
        data = Path(path).read_bytes()
        if str(path).endswith('.z'):data=zlib.decompress(data)
        buf = (C.c_uint8 * len(data)).from_buffer_copy(data)
        self.restore_nand(buf)


if __name__ == "__main__":
    import argparse
    import json
    parser = argparse.ArgumentParser()
    parser.add_argument("--cycles", type=int, default=4_000_000)
    args = parser.parse_args()
    m = Machine()
    m.run(args.cycles)
    print(json.dumps(m.state(), indent=2))
    print("IO", {f"{a:02x}": [m.lib.bbk_read(a), m.lib.bbk_iocount(a, 0), m.lib.bbk_iocount(a, 1)]
                 for a in range(128) if m.lib.bbk_iocount(a, 0) or m.lib.bbk_iocount(a, 1)})
    print("history", [f"{m.lib.bbk_history(i):04x}" for i in range(20)])
