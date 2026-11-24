# Hardware and protocol research

These are observations and working hypotheses, not a complete hardware specification.

## CPU and mapping

65C02 instruction execution is shared with GAM4980. Program window 4000–7fff:
`((PRR ^ 1) << 14) | (address & 0x3fff)`. During IRQ service with SYS bit 1 set,
IRR replaces PRR. Vector fetches also use this program mapping, even for fffx.
Data window 8000–ffff uses `DRR << 15 | (address & 0x7fff)`.
IREQ/IENA are 3c–3f. IRQ priority takes the high byte first, then its lowest set bit.
IRQ N vector is `fffe - 2*(N+3)`. RTI leaves interrupt-bank service.

NOR mirrors 512 KiB below 400000. The emulator mirrors 128 KiB of external
SRAM in 400000–7fffff, except the 500000 NAND window. V1.10 writes to SRAM
in 480000–49ffff. The stock calendar keeps 64 KiB of program banks and
3,848 bytes of heap allocations live at the same time. The tested 128 KiB
configuration boots and runs the stock menus, games and serial file service.
Physical SRAM decoding and on-chip RAM capacity still require hardware checks.

## Keyboard

The V1.10 firmware table at NOR offset `0xfd67` gives two bytes per matrix position.
Letters, digits and space use event type `02`. Function keys use type `05`.
Tools menu movement confirms matrix 51/58/57/59 as Up/Down/Left/Right.
The calculator confirms matrix 56 deletes the last digit and 55 opens Help.

The user-provided open-lid photo shows the following physical groups. Matrix
numbers below follow the legends from left to right within each group.

| Physical keys | Matrix positions |
| --- | --- |
| `1`–`0`, power | 0–9, 10 |
| `QWERTYUIOP`, 字体 | 11–20, 33 |
| `ASDFGHJKL`, 帮助 | 23–31, 55 |
| Shift, `ZXCVBNM`, 空格, Caps, 发音 | 21, 35–41, 34, 32, 22 |
| 目录, 删除, F1–F5, 输入法, 中英符 | 52, 56, 44–48, 54, 53 |
| Esc, Enter, arrow cluster, page pair | 49, 50, up/down/left/right 51/58/57/59, page up/down 42/43 |

Pressing 10 toggles the V1.10 LCD power control. Position 33 cycles the glyph
size in the stock custom-lexicon dialog. Position 22 with Shift opens the
stock volume dialog, matching the main menu help's Shift + 发音 shortcut.
Position 32 toggles case in the stock dictionary search. PC Caps Lock and the
legacy Ctrl shortcut send position 32. PC Backspace sends 56.

Position 53 (中英符) translates to `29`: the V1.10 handler at `0A:6677`
changes the input category in the low nibble of `$9e4f`. In dictionary search,
matrix 53 changes `$9e4f` from `01` to `12`. Position 54 (输入法) translates to
`2a`: the handler at `0A:67fc` cycles the method in the high nibble in Chinese
input categories. Dictionary search still fails to reach a usable input
screen after switching to Chinese in the emulator.
Positions 60–63 translate to `00 00`. The photo shows a separate recessed RESET
switch. The photo does not establish which circuit the reset switch uses.

## LCD and NAND

Stock LCD: 240×120, four shades. Registers 40–49 select framebuffer, pitch and depth.
Boot uses base 0be0, LVPW=15, LCTR=4, giving 60 bytes per scanline at 2 bpp.

NAND: 64 MiB, 131072 pages, each 512 data +16 spare; 32 pages per erase block.
Physical 500000 is data, 502000 address, 504000 command. ID currently ec76.
Read-area commands 00/01/50 select columns 0/256/512 and persist through program 80.
ECC, busy delays, bad blocks and electrical timing are simplified.

The V1.10 export picker reads the active file directory from a NAND snapshot.
The volume header's three block numbers at byte 20 select rotating copies of
the block map. The active copy starts with `11`, followed by little-endian
block numbers. The first four numbers select the primary directory. Each
512-byte data area holds four 128-byte directory entries. A live entry has
`55` at byte 96, a NUL-terminated name at byte 2, and a little-endian file
size at byte 92. File contents are still read through the original UART service.

## Serial download

UART data=64; RX source=11, TX completion=10. Emulated receive is back-pressured
at its hardware latch; the host transport leaves a short gap before packet headers
and payloads, allowing the firmware to switch between ring and direct receive modes.

1. Host sends 55; guest replies aa.
2. Host sends `B100HOST\0`; guest echoes nine bytes and sends ten information bytes.
3. Host sends `02 00` to enter the built-in file service.
4. A guest input request is byte 55. Host supplies u16 length, u16 additive checksum,
   then payload. A guest output packet sends the same four-byte header, waits for
   host acknowledgment 55, then sends payload.
5. Configure with `<u16 buffer_address=e000, u16 block_size=8192>`; guest echoes size.
6. Command 11 downloads a file; 10 uploads it. Commands themselves are one-byte packets,
   echoed in guest output packets. A host progress-message request can be answered
   with a single zero byte.
7. Download metadata: filename[64] GB18030, reserved[8], u32 packet count,
   u16 whole-file additive checksum, u16 classification/order attributes.
8. Send each data block; successful download returns output payload 11.
   Upload accepts a 64-byte filename and returns u32 packet count + u32 file length,
   followed by output data packets.

Official package record: 128-byte BJBBK.110 header, size/checksum/header-size at
offsets 96/100/104. Payload sums wrap at 32 bits. File category/order are bytes 26/27.
The code.upg payload has a 32-byte inner image header; its image offset includes
the outer 128-byte header. The system starts at original .upg offset 160.

## Native application packaging

The original shell loads 16 KiB program banks and checks each with the ADC carry
chain at fixed-kernel address 89ce. Starting with A=0/C=0, perform ADC for every
byte; the final accumulator must be zero. Original nonempty banks finish C=1.
The app builder reserves/fixes the final byte of each 16 KiB block. This check
is independent of the UART packet sum and the PC container's 32-bit payload sum.

For the single-entry 32 KiB example, device offset 4000 holds an eight-byte,
space-padded GBK desktop caption within a 16-byte field, followed at 4010 by a
32×32 two-bit icon (256 bytes). Native menu attributes 0109 mean one entry in
the Entertainment category. The example's entry runs from CPU 4000 and links
all code/constants below 8000. It saves/restores zero-page state and the caller's
processor status, uses BSS a800–afff and a C software stack below b7f0, and
returns to the actual caller with RTS. See the pinned 7980 SDK Minesweeper
source included in the release archive.

## External Chinese font

The firmware contains the string `font.bin` at system-image offset 0xfd58.
Startup copies that name into a temporary filename buffer and obtains its file
handle; the cached handle is at CPU address 9eca (ff when unavailable).

The original glyph read function is CPU 721d in program bank 5. For a two-byte
GBK code with high byte H and low byte L, the glyph slot is
`(H-0x81)*191 + (L-0x40)`. Rows include the unused 7f trail slot. There are
126*191=24066 slots, of which Python's GBK decoder recognizes 21791 characters.

| Size | File base | Bytes/glyph | Bitmap arrangement |
| --- | --- | --- | --- |
| 12×12 | 000000 | 24 | 12 rows, 2 bytes/row, high bits first, 4 low padding bits |
| 16×16 | 08d030 | 32 | 16 rows, 2 bytes/row, high bits first |
| 24×24 | 149070 | 72 | 24 rows, 3 bytes/row, high bits first |

Glyph data ends at 2f0100. When language flag 9ef3 is 1, eligible B0–F7/A1–FE
GB2312 codes first pass through a two-byte big-endian mapping table at 2f4000;
its index is `((H-0xb0)*94 + L-0xa1)*2`. The current substitute appends an
identity table, preserving the requested code rather than doing S/T conversion.

tools/probe_font.py executes the original routine and original NAND file service
to verify offsets and returned glyph bytes. It changes diagnostic CPU state to
call the routine, without replacing its address calculation or read operation.
The normal emulator does not intercept or replace font drawing.

The optional converter for a locally supplied 9288 HZK_LIB.BIN uses source bases
12-dot=1a84b0, 16-dot=2354f8, 24-dot=0. The source uses 190 trail slots per
lead byte (skipping 7f); conversion inserts that unused slot for the 7980.
The accepted source SHA256 is db8b0697ab93c8defab6f54e407c3df9778a42aacc56a8dc2b9d30a64aef5fa2.
No resizing, thresholding or font rendering is applied to this source. This
establishes source provenance, not identity with the unknown original 7980 font.

The default 7980Compat is generated by tools/make_font.py from GNU Unifont 18.0.01. Its
16-dot glyphs are the source bitmaps; 12-dot glyphs are area-resampled and
thresholded; 24-dot glyphs are enlarged. The result is a substitute, not a
reconstruction of the original BBK shapes. The firmware's recovery UI also
contains embedded glyphs independent of this external file.
