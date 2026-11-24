"""Prepare a private V1.10 runtime using the user's original upgrade package."""
import argparse
import hashlib
import json
from pathlib import Path
import tempfile
import zlib

from machine import Machine, ROOT
from tools.install_probe import Link
from tools.make_font import build as build_font
from tools.upgrade_package import read_package, system_image

UPDATER_SHA = 'b9c4aa62cd9517859930620cdce5f7c6027120777926bb49e56989bb4e8d145c'
ROM_SHA = '1f020acdb26a3081839e89f89f325649c231b89e7541505f9fa01edc4d4533a1'
FONT_SOURCE = ROOT / 'vendor/fonts/unifont-18.0.01.hex.gz'


def export_nand(machine, destination):
    raw = machine.snapshot_nand()
    destination.write_bytes(zlib.compress(raw, 3))
    return hashlib.sha256(raw).hexdigest()


def demo_record(path):
    raw = path.read_bytes()
    if len(raw) != 32896 or raw[:9] != b'BJBBK.110':
        raise ValueError('扫雷传输包格式错误')
    payload = raw[128:]
    if raw[26:28] != b'\x09\x01' or int.from_bytes(raw[100:104], 'little') != sum(payload):
        raise ValueError('扫雷传输包分类或校验错误')
    return dict(name=raw[32:96].split(b'\0')[0].decode('gbk'), flags=0x0109, data=payload)


def prepare(updater, target, demo=None, progress=print):
    updater = Path(updater)
    target = Path(target).resolve()
    if target.exists():
        raise FileExistsError(f'运行目录已存在：{target}')
    if hashlib.sha256(updater.read_bytes()).hexdigest() != UPDATER_SHA:
        raise ValueError('升级包 SHA-256 不符。请选择原厂朗文 7980 V1.00→V1.10 升级程序。')
    records = read_package(updater)
    firmware = system_image(records)
    if len(records) != 63 or hashlib.sha256(firmware).hexdigest() != ROM_SHA:
        raise ValueError('固件版本或安装记录不符')
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.7980-setup-', dir=target.parent) as staging:
        runtime = Path(staging) / 'runtime'
        runtime.mkdir()
        rom_path = runtime / 'syscode.bin'
        rom_path.write_bytes(firmware)
        progress('生成 Unifont 兼容字库…')
        font = build_font(FONT_SOURCE, runtime / 'font.bin')
        progress('原厂固件正在格式化虚拟 NAND…')
        machine = Machine(rom_path)
        machine.run(20_000_000)
        machine.lib.bbk_key(2, 0, 1)
        machine.run(400_000)
        machine.lib.bbk_key(2, 0, 0)
        machine.run(2_000_000_000)
        command, address, data = 0x504000, 0x502000, 0x500000
        machine.lib.bbk_phys_write(command, 0)
        for _ in range(4):
            machine.lib.bbk_phys_write(address, 0)
        marker = bytes(machine.lib.bbk_phys_read(data) for _ in range(16))
        if marker != b'BJBBK B100 V1.1 ':
            raise RuntimeError('虚拟 NAND 格式化未完成')
        machine.lib.bbk_reset()
        export_nand(machine, runtime / 'initialized-nand.bin.z')
        entries = [dict(name='font.bin', data=font, flags=0), *records[1:]]
        if demo is not None:
            entries.append(demo_record(Path(demo)))
        installed = []
        for index, entry in enumerate(entries):
            if index == 0 or index == 1 or (index - 1) % 16 == 0:
                machine.lib.bbk_reset()
                machine.run(100_000_000)
                link = Link(machine)
                link.connect()
            name = entry['name']
            progress(f'安装并读回 {index + 1}/{len(entries)}  {name}')
            link.put(name, entry['data'], entry['flags'])
            data = link.get(name)
            if data != entry['data']:
                raise RuntimeError(f'串口读回校验失败：{name}')
            installed.append(dict(name=name, size=len(data), sha256=hashlib.sha256(data).hexdigest()))
        nand_sha = export_nand(machine, runtime / 'installed-nand.bin.z')
        manifest = dict(updater_sha256=UPDATER_SHA, firmware_sha256=ROM_SHA,
                        nand_sha256=nand_sha, verified=installed)
        (runtime / 'installed-manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf8')
        runtime.rename(target)
    progress(f'已生成运行资料：{target}')
    return manifest


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('updater', type=Path)
    parser.add_argument('--runtime', type=Path, default=ROOT / 'runtime')
    parser.add_argument('--demo', type=Path, default=ROOT / 'build/demo/minesweeper.exe')
    args = parser.parse_args()
    prepare(args.updater, args.runtime, args.demo if args.demo.is_file() else None)
