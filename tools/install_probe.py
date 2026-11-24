"""Reverse-engineering harness; uses the stock download service over UART."""
import ctypes as C
import struct

BLOCK_SIZE = 8192

class Link:
    def __init__(self, m):self.m=m;self.buffer=bytearray()
    def send(self, data):
        buf=(C.c_uint8*len(data)).from_buffer_copy(data)
        if self.m.lib.bbk_uart_send(buf,len(data)):raise RuntimeError('UART queue full')
    def read(self, size):
        for _ in range(1000):
            if len(self.buffer)>=size:
                result=bytes(self.buffer[:size]);del self.buffer[:size];return result
            self.m.run(50_000)
            buf=(C.c_uint8*65536)();n=self.m.lib.bbk_uart_receive(buf,len(buf))
            self.buffer.extend(buf[:n])
        raise TimeoutError(f'UART: expected {size}, have {self.buffer.hex()}, PC={self.m.state()}')
    def input(self, data):
        marker=self.read(1)
        if marker!=b'U':raise RuntimeError(f'Expected input request, got {marker.hex()}')
        self.m.run(20_000)
        self.send(struct.pack('<HH',len(data),sum(data)&65535))
        self.m.run(20_000) # Allow the guest to switch its RX destination after the header.
        self.send(data)
    def output(self):
        size,checksum=struct.unpack('<HH',self.read(4));self.send(b'U');data=self.read(size)
        if sum(data)&65535!=checksum:raise RuntimeError('Guest packet checksum mismatch')
        return data
    def expect(self, actual, expected):
        if actual != expected:
            raise RuntimeError(f'原厂串口服务应答异常：{actual.hex()}')
    def connect(self):
        self.send(b'U');self.expect(self.read(1), b'\xaa')
        self.send(b'B100HOST\0');self.expect(self.read(9), b'B100HOST\0')
        print('Device:',self.read(10).hex())
        self.send(b'\x02\0');self.input(struct.pack('<HH',0xe000,BLOCK_SIZE))
        self.expect(self.output(), struct.pack('<H',BLOCK_SIZE))
    def put(self,name,data,flags=0):
        encoded = name.encode('gb18030')
        if not 0 < len(encoded) < 64 or b'\0' in encoded:
            raise ValueError('文件名须在 1 到 63 字节之间')
        self.input(b'\x11');self.expect(self.output(), b'\x11')
        self.input(b'\0') # Empty host-supplied progress message.
        count = (len(data) + BLOCK_SIZE - 1) // BLOCK_SIZE
        meta=encoded.ljust(64,b'\0')+struct.pack('<II IHH',0,0,count,sum(data)&65535,flags)
        self.input(meta)
        for start in range(0,len(data),BLOCK_SIZE):self.input(data[start:start+BLOCK_SIZE])
        self.expect(self.output(), b'\x11')

    def get(self,name):
        encoded = name.encode('gb18030')
        if not 0 < len(encoded) < 64 or b'\0' in encoded:
            raise ValueError('文件名须在 1 到 63 字节之间')
        self.input(b'\x10');self.expect(self.output(), b'\x10');self.input(b'\0')
        self.input(encoded.ljust(64,b'\0'))
        header = self.output()
        if len(header) != 8:
            raise RuntimeError('原厂串口服务返回的文件长度无效')
        count,size=struct.unpack('<II',header)
        if size > self.m.lib.bbk_nand_size() or count != (size + BLOCK_SIZE - 1) // BLOCK_SIZE:
            raise RuntimeError('原厂串口服务返回的文件大小或分块数无效')
        if count == 0:
            # V1.10 returns zero blocks for both an empty file and a failed lookup.
            # Wait for the original ROM to leave the handler and report lookup status.
            self.m.run(1_000_000)
            if self.m.lib.bbk_read(0x96b7) == 1:
                raise FileNotFoundError(f'机内没有文件「{name}」。请核对文件名、大小写和扩展名。')
        data=b''.join(self.output() for _ in range(count))
        if len(data)!=size:raise RuntimeError('Guest file length mismatch')
        return data
