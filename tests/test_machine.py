import ctypes as C
import json
import os
from pathlib import Path
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from machine import Machine,ROOT
from install_probe import Link
from make_font import glyph_offset,SECTIONS
from probe_font import guest_offset,guest_glyph
from keyboard import KEYS
from capture_games import tap,menu

RUNTIME = Path(os.environ.get('BBK7980_TEST_RUNTIME', ROOT / 'runtime'))

class HardwareTests(unittest.TestCase):
    def setUp(self):self.m=Machine(bytes([0xea]) * 0x80000);self.lib=self.m.lib
    def poke(self,address,data):
        for i,value in enumerate(data):self.lib.bbk_write(address+i,value)

    def test_cmos_decimal_and_bit_instructions(self):
        # 45 + 55 = 00 carry in packed BCD; then exercise CMOS-only opcodes.
        self.poke(0x200,bytes.fromhex('f8 18 a9 45 69 55 8d 00 03 d8 64 80 87 80 a7 80 80 02 a9 ff db'))
        self.lib.bbk_setreg(0,0x200);self.m.run(100)
        self.assertEqual(self.lib.bbk_read(0x300),0)
        self.assertEqual(self.lib.bbk_read(0x80),5)
        self.assertEqual(self.lib.bbk_reg(1),0)
        self.assertEqual(self.lib.bbk_reg(5)&1,1)
        self.assertEqual(self.lib.bbk_flags()&2,2)

    def test_irq_uses_inverted_program_bank_and_rti_restores_it(self):
        rom=bytearray([0xea])*0x80000
        rom[0x7ffc:0x7ffe]=b'\x00\x02'
        vector=0xfffe-((11+3)<<1)
        rom[0xc000+(vector&0x3fff):0xc002+(vector&0x3fff)]=b'\x00\x40'
        rom[0xc000:0xc006]=bytes.fromhex('a9 5a 8d 01 03 40')
        buf=(C.c_uint8*len(rom)).from_buffer_copy(rom);self.lib.bbk_load(buf,len(rom));self.lib.bbk_reset()
        self.poke(0x200,bytes.fromhex('cb 80 fd'))
        self.lib.bbk_write(0x30,2);self.lib.bbk_write(0x31,2)
        self.lib.bbk_write(0x3f,8);self.lib.bbk_setreg(5,0x20)
        self.m.run(20);self.assertTrue(self.lib.bbk_flags()&1)
        self.lib.bbk_irq(11);self.m.run(100)
        self.assertEqual(self.lib.bbk_read(0x301),0x5a)
        self.assertEqual(self.lib.bbk_flags()&4,0)
        self.assertTrue(self.lib.bbk_flags()&1)

    def test_nand_spare_program_does_not_change_page_data(self):
        command=0x504000;address=0x502000;data=0x500000
        self.lib.bbk_phys_write(command,0x50);self.lib.bbk_phys_write(command,0x80)
        for value in (0,4,0,0):self.lib.bbk_phys_write(address,value)
        self.lib.bbk_phys_write(data,0x77);self.lib.bbk_phys_write(command,0x10)
        self.lib.bbk_phys_write(command,0)
        for value in (0,4,0,0):self.lib.bbk_phys_write(address,value)
        self.assertEqual(self.lib.bbk_phys_read(data),0xff)
        self.lib.bbk_phys_write(command,0x50)
        for value in (0,4,0,0):self.lib.bbk_phys_write(address,value)
        self.assertEqual(self.lib.bbk_phys_read(data),0x77)

    def test_external_sram_has_128_kib_before_mirroring(self):
        base, size = 0x480000, 128 * 1024
        for offset, value in ((0, 0x15), (size // 2, 0x32), (size - 1, 0x83)):
            self.lib.bbk_phys_write(base + offset, value)
            self.assertEqual(self.lib.bbk_phys_read(base + size + offset), value)
        self.lib.bbk_phys_write(base + size, 0x47)
        self.assertEqual(self.lib.bbk_phys_read(base), 0x47)
        self.assertEqual(self.lib.bbk_phys_read(base + size // 2), 0x32)
        self.assertEqual(self.lib.bbk_phys_read(base + size - 1), 0x83)


@unittest.skipUnless(all((RUNTIME / name).is_file() for name in
                         ('syscode.bin', 'initialized-nand.bin.z', 'installed-nand.bin.z', 'font.bin')),
                     'Run prepare.py with the original V1.10 updater for guest tests')
class GuestTests(unittest.TestCase):
    def setUp(self):self.m=Machine(RUNTIME/'syscode.bin');self.lib=self.m.lib

    def test_original_firmware_formats_nand(self):
        self.m.run(20_000_000);initial=self.m.frame()
        self.lib.bbk_key(2,0,1);self.m.run(400_000);self.lib.bbk_key(2,0,0)
        self.m.run(2_000_000_000)
        command=0x504000;address=0x502000;data=0x500000
        self.lib.bbk_phys_write(command,0)
        for value in (0,0,0,0):self.lib.bbk_phys_write(address,value)
        self.assertEqual(bytes(self.lib.bbk_phys_read(data) for _ in range(16)),b'BJBBK B100 V1.1 ')
        self.assertTrue(initial!=self.m.frame())

    def test_guest_serial_filesystem_roundtrip(self):
        self.m.load_nand(RUNTIME/'initialized-nand.bin.z');self.m.run(100_000_000)
        link=Link(self.m);link.connect()
        payload=bytes(range(256))*65+b'last partial NAND page'
        link.put('roundtrip.bin',payload)
        self.assertEqual(link.get('roundtrip.bin'),payload)

    def test_guest_serial_distinguishes_empty_and_missing_file(self):
        self.m.load_nand(RUNTIME/'installed-nand.bin.z')
        from file_transfer import connect
        link = connect(self.m)
        link.put('空文件.txt', b'')
        self.assertEqual(link.get('空文件.txt'), b'')
        with self.assertRaises(FileNotFoundError):
            connect(self.m).get('不存在的文件.txt')

    def test_export_list_reads_live_nand_without_deleted_entries(self):
        from file_transfer import connect, list_files
        self.m.load_nand(RUNTIME/'installed-nand.bin.z')
        manifest = json.loads((RUNTIME/'installed-manifest.json').read_text(encoding='utf8'))
        original = dict(list_files(self.m))
        for file in manifest['verified']:
            self.assertEqual(original[file['name']], file['size'])
        link = connect(self.m)
        name = '导出列表测试.txt'
        link.put(name, b'old contents')
        link.put(name, b'new')
        self.assertEqual(list_files(self.m).count((name, 3)), 1)
        self.assertNotIn((name, 12), list_files(self.m))
        self.assertEqual(link.get(name), b'new')

    def test_stock_menu_changes_on_keypress(self):
        self.m.load_nand(RUNTIME/'installed-nand.bin.z');self.m.run(80_000_000)
        before=self.m.frame();self.assertEqual(set(before),{0,1,2,3})
        self.lib.bbk_key(5,3,1);self.m.run(3_000_000);self.lib.bbk_key(5,3,0)
        self.assertTrue(before!=self.m.frame(),'Native menu did not respond to a page key')

    def test_game_enter_escape_and_home_controls(self):
        self.m.load_nand(RUNTIME/'installed-nand.bin.z');menu(self.m)
        entertainment=self.m.frame();tap(self.m,0,20_000_000)
        self.assertEqual(self.lib.bbk_read(0xa564),6) # Original game's title phase.
        tap(self.m,KEYS['Return'],3_000_000)
        self.assertEqual(self.lib.bbk_read(0xa564),1) # Original game's running phase.
        tap(self.m,KEYS['Escape'],3_000_000)
        self.assertEqual(self.lib.bbk_read(0xa564),3) # Original game's end phase.
        tap(self.m,KEYS['Home'],20_000_000)
        self.assertTrue(self.m.frame()==entertainment,'Home did not return to Entertainment')

    def test_four_directions_follow_axes_in_original_tools_menu(self):
        self.m.load_nand(RUNTIME/'installed-nand.bin.z')
        self.m.run(80_000_000)
        for _ in range(9): tap(self.m, KEYS['Next'])
        # The note editor is the center tile in the stock 3-by-3 Tools grid.
        tap(self.m, KEYS['5'], 40_000_000)
        tap(self.m, KEYS['Escape'], 30_000_000)

        def assert_selection(column, row):
            frame = self.m.frame()
            # A pixel in the upper-right background of each tile is shade 1
            # when the stock firmware highlights that tile, and shade 0 otherwise.
            samples = [frame[y*240 + x] for y in (10, 49, 89) for x in (105, 161, 217)]
            expected = [0]*9
            expected[row*3 + column] = 1
            self.assertEqual(samples, expected)

        assert_selection(1, 1)
        for direction, column, row in [('Up', 1, 0), ('Down', 1, 1), ('Down', 1, 2),
                                        ('Up', 1, 1), ('Left', 0, 1), ('Right', 1, 1),
                                        ('Right', 2, 1), ('Left', 1, 1)]:
            with self.subTest(direction=direction, destination=(column, row)):
                tap(self.m, KEYS[direction])
                assert_selection(column, row)

    def test_backspace_and_help_in_original_calculator(self):
        self.m.load_nand(RUNTIME/'installed-nand.bin.z')
        self.m.run(80_000_000)
        for _ in range(7): tap(self.m, KEYS['Next'])
        tap(self.m, KEYS['1'], 30_000_000)
        tap(self.m, KEYS['1']);tap(self.m, KEYS['2'])
        twelve = self.m.frame()
        for key in ('BackSpace', 'Delete'):
            with self.subTest(key=key):
                tap(self.m, KEYS['3'])
                self.assertNotEqual(self.m.frame(), twelve)
                tap(self.m, KEYS[key])
                self.assertEqual(self.m.frame(), twelve)
        tap(self.m, KEYS['F6'])
        self.assertNotEqual(self.m.frame(), twelve)
        tap(self.m, KEYS['Escape'])
        self.assertEqual(self.m.frame(), twelve)

    def test_original_glyph_offsets_match_generated_layout(self):
        self.m.load_nand(RUNTIME/'installed-nand.bin.z')
        for code in (0x8140,0x817f,0x8240,0xd6d0,0xfefe):
            for size in (12,16,24):
                self.assertEqual(guest_offset(self.m,code,size),glyph_offset(code,size))

    def test_original_firmware_reads_all_three_substitute_glyph_sizes(self):
        self.m.load_nand(RUNTIME/'installed-nand.bin.z')
        font=(RUNTIME/'font.bin').read_bytes()
        for character in ('中','字'):
            code=int.from_bytes(character.encode('gbk'),'big')
            for size in (12,16,24):
                offset=glyph_offset(code,size);length=SECTIONS[size][1]
                expected=font[offset:offset+length]
                self.assertTrue(any(expected))
                self.assertEqual(guest_glyph(self.m,code,size),expected)
        code=int.from_bytes('中'.encode('gbk'),'big');offset=glyph_offset(code,16)
        self.assertEqual(guest_glyph(self.m,code,16,remap=True),font[offset:offset+32])

    def test_minesweeper_cursor_follows_four_directions(self):
        manifest = json.loads((RUNTIME/'installed-manifest.json').read_text(encoding='utf8'))
        if not any(record['name'] == '扫雷.exe' for record in manifest['verified']):
            self.skipTest('Prepare a runtime with the SDK example')
        self.m.load_nand(RUNTIME/'installed-nand.bin.z')
        menu(self.m)
        tap(self.m, KEYS['7'], 30_000_000)

        def assert_cursor(column, row):
            frame = self.m.frame()
            # The top-left cursor mark darkens the second pixel of the closed tile.
            marked = [(x, y) for y in range(8) for x in range(12)
                      if frame[(21 + 12*y)*240 + 5 + 12*x] == 3]
            self.assertEqual(marked, [(column, row)])

        assert_cursor(0, 0)
        for key, column, row in [('Right', 1, 0), ('Down', 1, 1),
                                 ('Left', 0, 1), ('Up', 0, 0)]:
            with self.subTest(key=key):
                tap(self.m, KEYS[key])
                assert_cursor(column, row)

if __name__=='__main__':unittest.main()
