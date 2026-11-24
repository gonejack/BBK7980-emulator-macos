"""Read the original updater's resource without executing the Windows updater."""
import hashlib
from pathlib import Path
import struct

def read_package(path):
    import pefile
    pe=pefile.PE(str(path));payload=None
    for kind in pe.DIRECTORY_ENTRY_RESOURCE.entries:
        if not hasattr(kind,'directory'):continue
        for item in kind.directory.entries:
            if str(item.name)=='RC_PKG':
                entry=item.directory.entries[0].data.struct
                payload=pe.get_data(entry.OffsetToData,entry.Size)
    pe.close()
    if payload is None:raise ValueError('RC_PKG resource was not found')
    records=[];offset=0
    while payload[offset:offset+9]==b'BJBBK.110':
        size,checksum,header=struct.unpack_from('<III',payload,offset+96)
        if header!=128 or offset+header+size>len(payload):raise ValueError('Invalid package record')
        raw=payload[offset:offset+128+size];data=raw[128:]
        if sum(data)&0xffffffff!=checksum:raise ValueError('Package checksum mismatch')
        name=raw[32:96].split(b'\0',1)[0].decode('gb18030')
        records.append(dict(name=name,data=data,flags=int.from_bytes(raw[26:28],'little')))
        offset+=128+size
    if payload[offset:offset+8]!=b'7980UPG!':raise ValueError('Invalid package trailer')
    return records

def system_image(records):
    data=records[0]['data'];offset,length=struct.unpack_from('<II',data)
    # Offset in the complete .upg file includes its 128-byte outer header.
    image=data[offset-128:offset-128+length]
    if len(image)!=524288:raise ValueError('Unexpected system image length')
    return image

if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('updater');args=parser.parse_args()
    records=read_package(args.updater);image=system_image(records)
    print(len(records),'records; system SHA256',hashlib.sha256(image).hexdigest())
