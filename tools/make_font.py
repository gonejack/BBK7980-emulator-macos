"""Build the guest's flat GBK 12/16/24-dot font.bin from BBK or Unifont glyphs.

7980Compat is an open-font substitute. BBK9288-7980-compat uses original BBK
glyphs with their original rights. Neither is a verified recovery of 7980's font.
"""
from pathlib import Path
import argparse
import gzip
import hashlib
import json
from PIL import Image

ROOT=Path(__file__).resolve().parents[1]
SECTIONS={12:(0,24),16:(0x8d030,32),24:(0x149070,72)}
SLOTS=126*191
MAP_OFFSET=0x2f4000

def glyph_offset(code,size):
    high,low=code>>8,code&255
    if not 0x81<=high<=0xfe or not 0x40<=low<=0xfe:raise ValueError('Not a double-byte GBK slot')
    base,length=SECTIONS[size]
    return base+((high-0x81)*191+low-0x40)*length

def load_hex(path):
    result={}
    with gzip.open(path,'rt',encoding='ascii') as source:
        for line in source:
            code,bits=line.strip().split(':');raw=bytes.fromhex(bits)
            result[int(code,16)]=(len(raw)//2,raw)
    return result

def build(source,target):
    glyphs=load_hex(source)
    output=bytearray(MAP_OFFSET+72*94*2)
    valid=missing=0
    for high in range(0x81,0xff):
        for low in range(0x40,0xff):
            code=(high<<8)|low
            try:character=bytes((high,low)).decode('gbk')
            except UnicodeDecodeError:continue
            valid+=1;entry=glyphs.get(ord(character))
            if entry is None:missing+=1;continue
            width,bits=entry
            image=Image.frombytes('1',(width,16),bits).convert('L')
            if width!=16:
                canvas=Image.new('L',(16,16));canvas.paste(image,((16-width)//2,0));image=canvas
            for size in SECTIONS:
                if size==16:scaled=image
                elif size==12:
                    # Area resampling retains thin strokes that nearest-neighbor shrinking loses.
                    scaled=image.resize((12,12),Image.Resampling.BOX).point(lambda p:255 if p>=96 else 0)
                else:scaled=image.resize((24,24),Image.Resampling.NEAREST)
                packed=scaled.convert('1',dither=Image.Dither.NONE).tobytes()
                offset=glyph_offset(code,size);output[offset:offset+len(packed)]=packed
    # Optional GB2312 remapping area. Identity mapping preserves characters when
    # the language flag selects this table; it does not implement S->T conversion.
    for high in range(0xb0,0xf8):
        for low in range(0xa1,0xff):
            index=(high-0xb0)*94+low-0xa1
            output[MAP_OFFSET+2*index:MAP_OFFSET+2*index+2]=bytes((high,low))
    target=Path(target);target.write_bytes(output)
    metadata=dict(name='7980Compat',source='GNU Unifont 18.0.01',
                  source_url='https://unifoundry.com/pub/unifont/unifont-18.0.01/font-builds/unifont-18.0.01.hex.gz',
                  source_sha256=hashlib.sha256(Path(source).read_bytes()).hexdigest(),
                  sizes=[12,16,24],gbk_slots=SLOTS,valid_gbk_characters=valid,missing_source_glyphs=missing,
                  file_size=len(output),sha256=hashlib.sha256(output).hexdigest(),
                  license='Unifont dual font license: SIL OFL 1.1 / GPL-2.0-or-later with font exception',
                  notes='16-dot glyphs retained; 12-dot downsampled; 24-dot enlarged; language remap is identity')
    target.with_suffix('.json').write_text(json.dumps(metadata,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps(metadata,indent=2));return bytes(output)

def build_bbk(source,target):
    """Reorder original BBK 9288 HZK_LIB glyphs; no resampling or font drawing."""
    raw=Path(source).read_bytes()
    digest=hashlib.sha256(raw).hexdigest()
    if digest!='db8b0697ab93c8defab6f54e407c3df9778a42aacc56a8dc2b9d30a64aef5fa2':
        raise ValueError('Unsupported HZK_LIB.BIN version; refusing to assume its layout')
    bases={12:0x1a84b0,16:0x2354f8,24:0}
    output=bytearray(MAP_OFFSET+72*94*2)
    for high in range(0x81,0xff):
        for low in range(0x40,0xff):
            if low==0x7f:continue
            index=(high-0x81)*190+low-0x40-(low>0x7f)
            for size in SECTIONS:
                length=SECTIONS[size][1];offset=bases[size]+index*length
                destination=glyph_offset((high<<8)|low,size)
                output[destination:destination+length]=raw[offset:offset+length]
    for high in range(0xb0,0xf8):
        for low in range(0xa1,0xff):
            index=(high-0xb0)*94+low-0xa1
            output[MAP_OFFSET+2*index:MAP_OFFSET+2*index+2]=bytes((high,low))
    target=Path(target);target.write_bytes(output)
    metadata=dict(name='BBK9288-7980-compat',source='BBK 9288 HZK_LIB.BIN',
                  source_sha256=digest,sizes=[12,16,24],gbk_slots=SLOTS,
                  file_size=len(output),sha256=hashlib.sha256(output).hexdigest(),
                  license='Original BBK font data; original rights retained; not an open-licensed font',
                  notes='Native 12/16/24-dot bitmaps copied byte-for-byte, reordered from 190 to 191 slots per lead byte; identity language map')
    target.with_suffix('.json').write_text(json.dumps(metadata,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps(metadata,indent=2));return bytes(output)

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--source',type=Path,default=ROOT/'vendor/fonts/unifont-18.0.01.hex.gz')
    parser.add_argument('--bbk-hzk',type=Path,help='Use original BBK 9288 HZK_LIB.BIN native bitmaps instead')
    parser.add_argument('--output',type=Path,default=ROOT/'runtime/font.bin');args=parser.parse_args()
    (build_bbk(args.bbk_hzk,args.output) if args.bbk_hzk else build(args.source,args.output))
