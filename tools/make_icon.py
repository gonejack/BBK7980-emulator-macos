"""Draw the BBK7980 LCD app icon and build assets/BBK7980.icns."""
from pathlib import Path
import shutil
import subprocess
import tempfile

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
SIZE = 1024
GLYPHS = {
    '7': ('11111', '00001', '00010', '00100', '01000', '01000', '01000'),
    '9': ('01110', '10001', '10001', '01111', '00001', '00010', '01100'),
    '8': ('01110', '10001', '10001', '01110', '10001', '10001', '01110'),
    '0': ('01110', '10001', '10011', '10101', '11001', '10001', '01110'),
}


def vertical_gradient(size, top, bottom):
    image = Image.new('RGB', (1, size))
    for y in range(size):
        ratio = y / max(size - 1, 1)
        color = tuple(round(top[i] + (bottom[i] - top[i]) * ratio) for i in range(3))
        image.putpixel((0, y), color)
    return image.resize((size, size))


def draw_digit(draw, character, x, y, scale, color):
    for row, bits in enumerate(GLYPHS[character]):
        for column, bit in enumerate(bits):
            if bit == '1':
                draw.rectangle((x + column * scale, y + row * scale,
                                x + (column + 1) * scale - 2, y + (row + 1) * scale - 2),
                               fill=color)


def build_icon():
    canvas = Image.new('RGBA', (SIZE, SIZE), (0, 0, 0, 0))
    mask = Image.new('L', (SIZE, SIZE), 0)
    ImageDraw.Draw(mask).rounded_rectangle((78, 78, 946, 946), radius=196, fill=255)

    body = vertical_gradient(SIZE, (66, 94, 70), (20, 33, 24)).convert('RGBA')
    canvas.paste(body, (0, 0), mask)
    draw = ImageDraw.Draw(canvas)

    # Device bezel and LCD.
    draw.rounded_rectangle((142, 222, 882, 706), radius=64, fill=(13, 22, 16, 255),
                          outline=(126, 148, 118, 255), width=5)
    screen_mask = Image.new('L', (SIZE, SIZE), 0)
    ImageDraw.Draw(screen_mask).rounded_rectangle((174, 254, 850, 674), radius=30, fill=255)
    screen = vertical_gradient(SIZE, (230, 237, 207), (188, 202, 161)).convert('RGBA')
    canvas.paste(screen, (0, 0), screen_mask)
    draw = ImageDraw.Draw(canvas)
    for y in range(258, 674, 10):
        draw.line((176, y, 848, y), fill=(54, 72, 48, 18), width=1)
    draw.rounded_rectangle((174, 254, 850, 674), radius=30, outline=(31, 50, 30, 255), width=3)

    # Four large LCD digits: 7980.
    scale, gap = 28, 18
    width = 5 * scale
    start = (SIZE - (4 * width + 3 * gap)) // 2
    top = 254 + (420 - 7 * scale) // 2
    for index, character in enumerate('7980'):
        draw_digit(draw, character, start + index * (width + gap), top, scale,
                   (29, 49, 30, 255))

    # A row of physical keys under the screen.
    keys, key_width, key_height, key_gap = 8, 74, 66, 18
    total = keys * key_width + (keys - 1) * key_gap
    left = (SIZE - total) // 2
    for index in range(keys):
        x = left + index * (key_width + key_gap)
        draw.rounded_rectangle((x, 786, x + key_width, 786 + key_height), radius=16,
                              fill=(213, 221, 198, 255), outline=(122, 139, 112, 255),
                              width=3)
        draw.line((x + 12, 794, x + key_width - 12, 794),
                  fill=(246, 249, 236, 255), width=3)
    draw.ellipse((770, 822, 796, 848), fill=(154, 193, 110, 255),
                outline=(73, 103, 58, 255), width=2)

    return canvas


def main():
    if not shutil.which('iconutil'):
        raise RuntimeError('iconutil is only available on macOS')
    icon = build_icon()
    target = ROOT / 'assets/BBK7980.icns'
    target.parent.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='bbk7980-icon-') as staging:
        iconset = Path(staging) / 'BBK7980.iconset'
        iconset.mkdir()
        for point in (16, 32, 128, 256, 512):
            for scale, suffix in ((1, ''), (2, '@2x')):
                size = point * scale
                icon.resize((size, size), Image.Resampling.LANCZOS).save(
                    iconset / f'icon_{point}x{point}{suffix}.png')
        subprocess.run(['iconutil', '-c', 'icns', str(iconset), '-o', str(target)],
                       check=True)
    print(target)


if __name__ == '__main__':
    main()
