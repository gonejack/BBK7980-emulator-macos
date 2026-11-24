# Font sources and options

The emulator builds its default compatibility font locally from this
Unifont source when the user imports the official upgrade package.

7980Compat is a modified bitmap font created on 2026-11-20 from GNU Unifont
18.0.01. It is not an original BBK font. Font glyphs and derived font.bin retain
the Unifont dual font license: SIL OFL 1.1, or GPL-2.0-or-later with the font
embedding exception. See OFL-1.1.txt and LICENSE.txt.

GNU Unifont is the work of Roman Czyborra, Paul Hardy, Qianqian Fang/WenQuanYi,
and the many Unifont glyph contributors. Upstream copyright/author information:
https://unifoundry.com/unifont/ and the Unifont 18.0.01 distribution.

Original glyph source, preserved here without alteration:
https://unifoundry.com/pub/unifont/unifont-18.0.01/font-builds/unifont-18.0.01.hex.gz

SHA256: e66385c79a0b8b24a466f3129930e08a966a935b4bf3b28c6bb17a9df9bf791d

The builder is tools/make_font.py. Changes: glyphs are selected/reordered for
GBK; 16-dot source bitmaps are retained, 12-dot bitmaps are downsampled with
area filtering and a monochrome threshold, 24-dot bitmaps are enlarged with
nearest-neighbor sampling. Narrow glyphs are centered in full-width slots.
Unassigned GBK slots remain empty. An identity remapping table is appended;
it does not perform simplified-to-traditional character conversion.
