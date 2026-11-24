"""Run the original 65C02 glyph lookup/read routine for a diagnostic glyph."""
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from machine import Machine,ROOT

def setup_call(machine,code,size):
    lib=machine.lib
    lib.bbk_reset();machine.run(80_000_000)
    # A real RTS target in internal RAM; all glyph calculations and file reads
    # below execute the unmodified original firmware.
    for address,value in [(0x300,0xdb),(0x17e,0xff),(0x17f,0x02),
            (0x32,5),(0x33,0),(0x34,0x93),(0x35,0),(0x1f5,code&255),
            (0x1f6,code>>8),(0x1f9,0),(0x1fa,0x28),(0x1fb,size),(0x9ef3,0)]:
        lib.bbk_write(address,value)
    for register,value in [(0,0x721d),(2,0xa0),(4,0x7d),(5,0x24)]:lib.bbk_setreg(register,value)
    lib.bbk_irq(5);machine.run(1) # Wake a firmware WAI after the debugger changes PC.
    lib.bbk_write(0x3e,0);lib.bbk_write(0x3f,0)

def guest_offset(machine,code,size):
    setup_call(machine,code,size);lib=machine.lib
    for _ in range(2000):
        sp=lib.bbk_reg(4)
        ret=lib.bbk_read(0x100+((sp+1)&255))|(lib.bbk_read(0x100+((sp+2)&255))<<8)
        if lib.bbk_pc()==0x86ee and ret==0x7506:
            return sum(lib.bbk_read(0x1e7+i)<<(8*i) for i in range(4))
        machine.run(1)
    raise RuntimeError('Original glyph routine did not reach the file service')

def guest_glyph(machine,code,size,remap=False):
    setup_call(machine,code,size)
    if remap:machine.lib.bbk_write(0x9ef3,1)
    machine.run(5_000_000)
    if not machine.lib.bbk_flags()&2:raise RuntimeError('Original glyph routine did not return')
    length={12:24,16:32,24:72}[size]
    return bytes(machine.lib.bbk_read(0x2800+i) for i in range(length))

if __name__=='__main__':
    m=Machine();m.load_nand(ROOT/'runtime/installed-nand.bin.z')
    for size in (12,16,24):
        code=int.from_bytes('中'.encode('gbk'),'big')
        print(size,hex(guest_offset(m,code,size)),guest_glyph(m,code,size).hex())
