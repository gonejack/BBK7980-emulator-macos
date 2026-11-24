"""Convert plain text to the ebook format used by the BBK7980 V1.10 reader."""

import argparse
import codecs
from pathlib import Path
import re
import struct

from file_transfer import validate_name, write_export


HEADER_SIZE = 64
HEADER_FIELDS_OFFSET = 14
BOOKMARK_RECORD_SIZE = 108
BOOKMARK_MAGIC = b'\xa5\x5a'
SCREEN_WIDTH = 240
# The reader multiplies the page index by four in a 16-bit temporary.
MAX_PAGES = 0x10000 // 4
ASCII_WORD = re.compile(rb'[A-Za-z]+')
CONTROL_CHAR = re.compile(r'[\x00-\x09\x0b-\x1f\x7f]')

# V1.10's default font advances for printable ASCII (0x20 through 0x7e).
# The header and page tables use the order 24 px, 16 px, 12 px.
FONT_LAYOUTS = (
    (24, 4, bytes.fromhex(
        '0c06070e0c140f070707090d030a06080c070c0c0c0c0c0c0c0c03030c0c0c0c'
        '17100e100f0e0d110e050a0f0b100e120e120f0f0f0e101810110f0508050b'
        '0f050c0c0b0c0c080c0b03060b03110b0c0c0c070b080b0c120c0b0b0703070d'
    )),
    (16, 6, bytes.fromhex(
        '0803050a080d0a05040406080307050508050808080808080808030308080808'
        '100a0a0b0b0a090b0a04070a080c0a0b0a0b0a0a0a0a0a100c0a0a04050408'
        '0a030808070808050807020408020c0708080805070507080c08080806020609'
    )),
    (12, 8, bytes.fromhex(
        '06030408060a0804040406060305040406040606060606060606030306070606'
        '0c080708080706080804060807080808070808070808080c08080803040306'
        '08030606050606050606020306020a0606060604060406060a06060604020407'
    )),
)
HALF_WIDTH_GBK = (
    (0xA456, 0xA45C), (0xA468, 0xA471), (0xA474, 0xA483), (0xA48C, 0xA491),
    (0xAAA1, 0xAABF), (0xAAE1, 0xAAFE), (0xABA1, 0xABB3), (0xABC0, 0xABC7),
    (0xABCD, 0xABD7), (0xABDC, 0xABFE), (0xACA1, 0xACFE), (0xADA1, 0xADC3),
    (0xAFCB, 0xAFF2),
)


def read_text(path, encoding=None):
    data = path.read_bytes()
    if encoding is not None:
        return data.decode(encoding).removeprefix('\ufeff')
    if data.startswith((codecs.BOM_UTF32_LE, codecs.BOM_UTF32_BE)):
        return data.decode('utf-32')
    if data.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
        return data.decode('utf-16')
    if data.startswith(codecs.BOM_UTF8):
        return data.decode('utf-8-sig')
    try:
        return data.decode('utf-8')
    except UnicodeDecodeError:
        return data.decode('gb18030')


def line_end(body, start, font_size, ascii_widths):
    position = start
    width = 0
    keep_words = True
    while position < len(body):
        byte = body[position]
        if byte == 0x0A:
            return position + 1
        if byte >= 0x81:
            end = position + 2
            code = (byte << 8) | body[position + 1]
            half_width = any(first <= code <= last for first, last in HALF_WIDTH_GBK)
            advance = font_size // 2 if half_width else font_size
        else:
            # The reader tries a whole ASCII word (up to 99 bytes). If it
            # cannot fit on an empty line, it measures one character at a time.
            word = ASCII_WORD.match(body, position, position + 99) if keep_words else None
            end = word.end() if word else position + 1
            advance = sum(ascii_widths[char - 0x20] for char in body[position:end])
        if width + advance > SCREEN_WIDTH:
            if position != start:
                return position
            keep_words = False
            continue
        width += advance
        position = end
    return position


def page_offsets(body, font_size, lines_per_page, ascii_widths):
    offsets = []
    position = 0
    while position < len(body):
        if len(offsets) == MAX_PAGES:
            raise ValueError('正文超过 7980 的单本分页容量，请把 TXT 分成几册再转换。')
        offsets.append(position)
        for _ in range(lines_per_page):
            position = line_end(body, position, font_size, ascii_widths)
            if position == len(body):
                break
    return offsets


def encode_ebk(text):
    # The reader treats CR and LF as separate line breaks.
    text = text.replace('\r\n', '\n').replace('\r', '\n').replace('\t', '    ')
    # GBK encodes the fullwidth form of the yen sign.
    text = text.replace('¥', '￥')
    if not text:
        raise ValueError('TXT 没有正文。')
    control = CONTROL_CHAR.search(text)
    if control:
        raise ValueError(f'正文含阅读器无法显示的控制字符 U+{ord(control[0]):04X}。')
    try:
        body = text.encode('gbk')
    except UnicodeEncodeError as error:
        char = text[error.start]
        line = text.count('\n', 0, error.start) + 1
        raise ValueError(f'第 {line} 行含 GBK 无法表示的字符 {char!r}（U+{ord(char):04X}）。') from None

    pages = [page_offsets(body, *layout) for layout in FONT_LAYOUTS]
    counts = [len(offsets) for offsets in pages]
    tables = [struct.pack(f'<{len(offsets)}I', *offsets) for offsets in pages]
    table_positions = []
    position = HEADER_SIZE + len(body)
    for table in tables:
        table_positions.append(position)
        position += len(table)

    # Table positions are absolute. Entries are relative to the start of
    # the GBK body.
    header = bytearray(HEADER_SIZE)
    struct.pack_into('<I3H3I', header, HEADER_FIELDS_OFFSET, len(body), *counts, *table_positions)
    book = b''.join((header, body, *tables))
    # The reader checks 108 bytes from EOF for its bookmark marker. If
    # the body or an index happens to match it, shift the check by one byte.
    marker_position = len(book) - BOOKMARK_RECORD_SIZE
    if marker_position >= 0 and book.startswith(BOOKMARK_MAGIC, marker_position):
        book += b'\0'
    return book


def main():
    parser = argparse.ArgumentParser(description='将 TXT 转成步步高 7980 V1.10 可阅读的 EBK。')
    parser.add_argument('input', type=Path, help='源 TXT 文件')
    parser.add_argument('output', type=Path, nargs='?', help='目标 .ebk 文件，默认与 TXT 同目录同名')
    parser.add_argument('--encoding', help='源 TXT 编码，默认尝试 UTF-8、带 BOM 的 Unicode 和 GB18030')
    parser.add_argument('--force', action='store_true', help='覆盖现有的目标 EBK')
    args = parser.parse_args()
    try:
        source = args.input.expanduser()
        output = args.output.expanduser() if args.output else source.with_suffix('.ebk')
        if output.suffix != '.ebk':
            raise ValueError('7980 书架要求文件名以小写 .ebk 结尾。')
        validate_name(output.name)
        if source.resolve() == output.resolve() or (output.exists() and source.samefile(output)):
            raise ValueError('输入和输出指向同一个文件。')
        data = encode_ebk(read_text(source, args.encoding))
        if args.force:
            write_export(output, data)
        else:
            result = output.open('xb')
            try:
                with result:
                    result.write(data)
            except OSError:
                output.unlink(missing_ok=True)
                raise
    except FileExistsError:
        parser.exit(1, f'转换失败：目标文件已存在。请指定另一个文件名，或使用 --force 覆盖。\n')
    except UnicodeDecodeError as error:
        parser.exit(1, f'转换失败：无法解码 TXT（{error}）。请用 --encoding 指定源文件编码。\n')
    except (OSError, LookupError, RuntimeError, ValueError) as error:
        parser.exit(1, f'转换失败：{error}\n')
    print(f'已生成 {output}')


if __name__ == '__main__':
    main()
