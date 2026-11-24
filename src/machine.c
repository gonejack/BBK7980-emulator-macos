/* BBK7980 board model, GPL-3.0-or-later. */
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#define API __attribute__((visibility("default")))
typedef struct { uint16_t pc; uint8_t ac, ix, iy, sp, status; } s6502_t;
#define S6502_CPU_TYPE_DEFINED
static s6502_t cpu;
static uint8_t nor[0x80000], ram[128 * 1024], iram[0x4000], io[128];
static uint8_t pins[7], keys[8], irq_service, waiting, stopped, flash_id;
static uint64_t clocks, instructions, irq_count, io_reads[128], io_writes[128];
static uint64_t next_base[5], next_timer[2], next_lcd;
static uint16_t history[64];
static uint32_t history_pos;
static int16_t audio_ring[262144];
static uint32_t audio_head,audio_tail;
static uint64_t audio_position,audio_phase[2];
static void audio_sync(void);
static uint64_t ext_reads[2048];
#ifdef BBK_TRACE
typedef struct {uint32_t pc,addr;uint8_t val,write;} trace_item;
static trace_item trace_items[200000];
static uint32_t trace_count;
static uint16_t pclog[65536];
static uint32_t pclog_count;
typedef struct {uint16_t caller;uint8_t bank,a,x,y,params[8];} call_item;
static call_item call_items[40000];
static uint32_t call_count;
#define TRACE_MEM(a,v,w) do {} while(0)
#define TRACE_PC() do {} while(0)
#define TRACE_CALL() do {if(cpu.pc==0x86ee&&call_count<40000){uint8_t sp=(uint8_t)(cpu.sp+1);uint16_t ret=(uint16_t)(iram[0x100+sp]|(iram[0x100+(uint8_t)(sp+1)]<<8));call_items[call_count].caller=(uint16_t)(ret-2);call_items[call_count].bank=(uint8_t)(io[0x32]|((io[0x33]&15)<<8));call_items[call_count].a=cpu.ac;call_items[call_count].x=cpu.ix;call_items[call_count].y=cpu.iy;for(int _i=0;_i<8;_i++)call_items[call_count].params[_i]=iram[0x9c3+_i];call_count++;}} while(0)
#else
#define TRACE_MEM(a,v,w) do {} while(0)
#define TRACE_PC() do {} while(0)
#define TRACE_CALL() do {} while(0)
#endif
static uint8_t uart_rx[65536], uart_tx[65536], uart_latch, uart_ready, uart_busy;
static uint32_t rx_head, rx_tail, tx_head, tx_tail;
static uint64_t next_rx, next_tx;
/* Samsung-compatible 64 MiB, small page: 131072 * (512 + 16).
 * The stock formatter creates a 4096-entry block map. */
static uint8_t nand_data[0x4200000], nand_cmd, nand_addr[5], nand_id_pos;
static uint32_t nand_addr_count, nand_pos, nand_row, nand_column, nand_area;
static void nand_position(void) {
    nand_column=nand_addr[0] + nand_area;
    nand_row=nand_addr[1] | ((uint32_t)nand_addr[2]<<8) | ((uint32_t)nand_addr[3]<<16);
    nand_pos=((nand_row&131071)*528+nand_column)%sizeof(nand_data);
}
static uint8_t nand_read(void) {
    if (nand_cmd==0x70) return 0xc0;
    if (nand_cmd==0x90) {const uint8_t id[]={0xec,0x76,0,0};return id[(nand_id_pos++)&3];}
    return nand_data[(nand_pos++)%sizeof(nand_data)];
}
static void nand_write(uint32_t a,uint8_t v) {
    if (a&0x4000) {
        if (v==0x10) return;
        if (v==0xd0) {uint32_t row=nand_addr[0]|((uint32_t)nand_addr[1]<<8)|((uint32_t)nand_addr[2]<<16);memset(nand_data+((row&~31)&131071)*528,0xff,528*32);return;}
        if(v==0 || v==1 || v==0x50)nand_area=v==0x50?512:v==1?256:0;
        nand_cmd=v;nand_addr_count=nand_id_pos=0;memset(nand_addr,0,sizeof(nand_addr));
    } else if (a&0x2000) {
        if(nand_addr_count<5)nand_addr[nand_addr_count++]=v;
        nand_position();
    } else if(nand_cmd==0x80) nand_data[(nand_pos++)%sizeof(nand_data)]&=v;
}
static const uint32_t hz = 4000000;
static uint32_t physical(uint16_t a, int vector) {
    if ((a < 0x8000 && a >= 0x4000) || vector) {
        uint16_t bank = (irq_service && (io[0x30] & 2)) ? io[0x31] : (io[0x32] | ((io[0x33] & 15) << 8));
        return ((uint32_t)(bank ^ 1) << 14) | (a & 0x3fff);
    }
    return ((uint32_t)(io[0x34] | ((io[0x35] & 7) << 8)) << 15) | (a & 0x7fff);
}
static uint8_t ext_read(uint32_t a) {
    ext_reads[(a>>15)&2047]++;
    if ((a&0xff0000)==0x500000) return nand_read();
    if (a < 0x400000) {
        if (flash_id) return (a & 1) ? 0xa4 : 0x01;
        return nor[a & 0x7ffff];
    }
    if (a < 0x800000) {uint8_t v=ram[(a - 0x400000) & (sizeof ram - 1)];TRACE_MEM(a,v,0);return v;}
    return 0xff;
}
static void ext_write(uint32_t a, uint8_t v) {
    if ((a&0xff0000)==0x500000) {nand_write(a,v);return;}
    if (a >= 0x400000 && a < 0x800000) {TRACE_MEM(a,v,1);ram[(a - 0x400000) & (sizeof ram - 1)] = v;}
    else if (a < 0x400000) {
        if (v == 0x90) flash_id = 1;
        if (v == 0xf0) flash_id = 0;
    }
}
static uint8_t rd(uint16_t a) {
    if (a < 128) {
        io_reads[a]++;
        if (a < 5) {
            uint8_t dir = io[8+a];
            uint8_t input=pins[a];
            if(a==0)for(int row=0;row<8;row++)if(!(io[1]&(1<<row)))input&=~keys[row];
            return (io[a] & dir) | (input & (uint8_t)~dir);
        }
        if (a == 0x30) return io[a] | 1;
        if (a == 0x23) return (uint8_t)(clocks / 256);
        if (a == 0x39) return 0;
        if (a == 0x61) return io[a] | 0x10;
        if (a == 0x64) { uart_ready=0; next_rx=clocks+400; return uart_latch; }
        return io[a];
    }
    if (a < 0x4000) return iram[a];
    return ext_read(physical(a, 0));
}
static void wr(uint16_t a, uint8_t v);
static void dma(uint8_t low) {
    uint16_t src=io[0x28] | (io[0x29]<<8), dst=io[0x2a] | (io[0x2b]<<8);
    uint32_t count=(((io[0x2d]&15)<<8)|low)+1;
    uint16_t bank=io[0x36] | ((io[0x37]&7)<<8);
    for (uint32_t n=0;n<count;n++) {
        uint8_t v=src>=0x8000 ? ext_read(((uint32_t)bank<<15)|(src&0x7fff)) : rd(src);
        wr(dst,v);
        if(src++==0xffff){src=0x8000;bank=(bank+1)&0x7ff;}
        if(!(io[0x2d]&16))dst++;
    }
    io[0x28]=src;io[0x29]=src>>8;io[0x2a]=dst;io[0x2b]=dst>>8;io[0x36]=bank;io[0x37]=bank>>8;
}
static void wr(uint16_t a, uint8_t v) {
    if (a < 128) {
        if ((a>=0x10 && a<=0x14) || a==0x16 || a==0x17) {
            audio_sync();
            if(a==0x16)for(int ch=0;ch<2;ch++)if((v&(2<<ch)) && !(io[a]&(2<<ch)))audio_phase[ch]=0;
        }
        io_writes[a]++;
        if (a == 0x3c || a == 0x3d) { io[a] &= v; return; }
        if (a == 0x21) { if (v&128) io[a]=0; return; }
        if (a == 0x64) { uart_tx[tx_tail++&65535]=v; uart_busy=1; next_tx=clocks+400; }
        io[a]=v;
        if (a == 0x2c) dma(v);
        return;
    }
    if (a < 0x4000) iram[a]=v;
    else ext_write(physical(a,0),v);
}
static uint16_t r16(uint16_t a) { return rd(a) | (rd((uint16_t)(a+1))<<8); }
static uint16_t r16z(uint8_t a) { return rd(a) | (rd((uint8_t)(a+1))<<8); }
static uint16_t vec(uint16_t a) { return ext_read(physical(a,1)) | (ext_read(physical(a+1,1))<<8); }
#define READ8(a) rd((uint16_t)(a))
#define READX8(a) rd((uint16_t)(a))
#define READX16(a) r16((uint16_t)(a))
#define READ16(a) r16((uint16_t)(a))
#define READ16W(a) r16z((uint8_t)(a))
#define sys_halt_p() 0
#define WRITE8(a,v) wr((uint16_t)(a),(uint8_t)(v))
#define BRK_HOOK do { pc++; PUSH(pc>>8); PUSH(pc); PUSH(status|0x30); status=(status|4)&~8; irq_service=1; pc=vec(0xfffe); } while(0)
#define BBK_RTI_HOOK (irq_service=0)
#define BBK_WAIT_HOOK (waiting=1)
#define BBK_STOP_HOOK (stopped=1)
#include "../vendor/s6502.c"
static void request_irq(int n) { io[0x3c+(n>>3)] |= 1<<(n&7); }
/* Tone mode follows the native PSG register interface. No music player HLE. */
static void audio_sync(void) {
    const uint32_t rate=22050;
    uint64_t until=clocks*rate;
    while(audio_position+hz<=until) {
        audio_position+=hz;
        int mixed=0;
        unsigned select=(io[0x16]>>4)&7;
        uint32_t psg_clock=select==7?32768:select<4?hz>>(select+1):hz;
        if(!(io[0x16]&1))for(int ch=0;ch<2;ch++) {
            if(!(io[0x16]&(2<<ch)) || (ch==1 && (io[0x16]&8)))continue;
            uint32_t preload=io[0x10+ch*2]|((io[0x11+ch*2]&15)<<8);
            uint64_t period=(uint64_t)(4096-preload)*2*rate;
            audio_phase[ch]=(audio_phase[ch]+psg_clock)%period;
            int volume=(io[0x17]>>(ch*4))&15;
            mixed+=(audio_phase[ch]<period/2?1:-1)*volume*900;
        }
        if(audio_tail-audio_head>=262144)audio_head++;
        audio_ring[audio_tail++&262143]=(int16_t)mixed;
    }
}
static void tick(void) {
    if (uart_busy && clocks>=next_tx) {uart_busy=0; request_irq(10);}
    if (!uart_ready && rx_head!=rx_tail && clocks>=next_rx) {
        uart_latch=uart_rx[rx_head++&65535]; uart_ready=1; request_irq(11);
    }
    if (uart_ready) request_irq(11);
    const uint32_t divs[5]={16384,4096,512,128,16};
    for (int i=0;i<5;i++) if (clocks>=next_base[i]) {
        uint32_t period=(uint64_t)hz*divs[i]/32768;
        next_base[i]=clocks+period;
        io[0x21] |= 1<<i;
        if (io[0x20]&(1<<i)) request_irq(5);
    }
    for (int i=0;i<2;i++) if (clocks>=next_timer[i]) {
        next_timer[i]=clocks+hz/100;
        if (io[0x24+i*2]&7) request_irq(2+i);
    }
    if (clocks>=next_lcd) { next_lcd=clocks+hz/60; if (!(io[0x47]&128)) request_irq(6); }
}
static int interrupt(void) {
    uint16_t active=(io[0x3c] | (io[0x3d]<<8)) & (io[0x3e] | (io[0x3f]<<8));
    if (!active) return 0;
    waiting=0;
    if (cpu.status&4) return 0;
    int level=0;
    /* High byte first, lowest set bit within each byte (ST2xxx priority). */
    int begin=(active&0xff00)?8:0;
    for(level=begin;level<begin+8;level++) if (active&(1<<level)) break;
    wr(0x100|cpu.sp--,cpu.pc>>8);wr(0x100|cpu.sp--,cpu.pc);wr(0x100|cpu.sp--,(cpu.status|32)&~16);
    cpu.status=(cpu.status|4)&~8;irq_service=1;
    cpu.pc=vec(0xfffe - ((level+3)<<1));
    io[0x3c+(level>>3)] &= ~(1<<(level&7));
    clocks+=7;irq_count++;return 1;
}
API int bbk_load(const uint8_t *data,uint32_t size) {
    if (size!=sizeof(nor)) return -1;
    memcpy(nor,data,size);memset(nand_data,0xff,sizeof(nand_data));return 0;
}
API void bbk_reset(void) {
    memset(io,0,sizeof(io));memset(iram,0,sizeof(iram));memset(ram,0,sizeof(ram));
    memset(pins,0xff,sizeof(pins));memset(keys,0,sizeof(keys));memset(io_reads,0,sizeof(io_reads));memset(io_writes,0,sizeof(io_writes));
    memset(ext_reads,0,sizeof(ext_reads));
    irq_service=waiting=stopped=flash_id=0;clocks=instructions=irq_count=history_pos=0;
    rx_head=rx_tail=tx_head=tx_tail=uart_ready=uart_busy=0;next_rx=next_tx=0;
    nand_cmd=nand_addr_count=nand_id_pos=nand_pos=nand_area=0;
    cpu=(s6502_t){0,0,0,0,0xfd,0x24};cpu.pc=vec(0xfffc);
    audio_head=audio_tail=0;audio_position=audio_phase[0]=audio_phase[1]=0;
    io[0x47]=0x80;next_lcd=0;
    memset(next_base,0,sizeof(next_base));memset(next_timer,0,sizeof(next_timer));
}
API uint64_t bbk_run(uint32_t budget) {
    uint64_t end=clocks+budget;
    while (clocks<end && !stopped) {
        tick(); if (interrupt()) continue;
        if (waiting) { clocks+=64; continue; }
        TRACE_CALL();
        history[history_pos++&63]=cpu.pc;
        clocks+=s6502_exec(&cpu,1);instructions++;
    }
    audio_sync();return clocks;
}
API uint32_t bbk_audio_read(int16_t *data,uint32_t size) {
    uint32_t n=audio_tail-audio_head;if(n>size)n=size;
    for(uint32_t i=0;i<n;i++)data[i]=audio_ring[audio_head++&262143];
    return n;
}
API void bbk_audio_clear(void) {audio_head=audio_tail;}
API uint8_t bbk_read(uint32_t a) { return rd((uint16_t)a); }
API void bbk_write(uint32_t a,uint32_t v) { wr((uint16_t)a,v); }
API uint8_t bbk_phys_read(uint32_t a) { return ext_read(a); }
API uint32_t bbk_nand_size(void) {return sizeof(nand_data);}
API void bbk_nand_export(uint8_t *data) {memcpy(data,nand_data,sizeof(nand_data));}
API int bbk_nand_import(const uint8_t *data,uint32_t size) {if(size!=sizeof(nand_data))return -1;memcpy(nand_data,data,size);return 0;}
API void bbk_phys_write(uint32_t a,uint32_t v) { ext_write(a,v); }
#ifdef BBK_TRACE
API void bbk_trace_reset(void) {trace_count=0;}
API uint32_t bbk_trace_count(void) {return trace_count;}
API uint32_t bbk_trace_get(uint32_t i,uint32_t *pc,uint32_t *addr,uint32_t *val,uint32_t *write) {if(i>=trace_count)return 0;*pc=trace_items[i].pc;*addr=trace_items[i].addr;*val=trace_items[i].val;*write=trace_items[i].write;return 1;}
API void bbk_call_reset(void) {call_count=0;}
API uint32_t bbk_call_count(void) {return call_count;}
API uint32_t bbk_call_get(uint32_t i,uint32_t *out) {if(i>=call_count)return 0;out[0]=call_items[i].caller;out[1]=call_items[i].a;out[2]=call_items[i].x;out[3]=call_items[i].y;for(int j=0;j<8;j++)out[4+j]=call_items[i].params[j];out[12]=call_items[i].bank;return 1;}
#endif
API uint32_t bbk_pc(void) {return cpu.pc;}
API uint64_t bbk_clocks(void) {return clocks;}
API uint64_t bbk_instructions(void) {return instructions;}
API uint64_t bbk_irqs(void) {return irq_count;}
API uint32_t bbk_flags(void) {return waiting | (stopped<<1) | (irq_service<<2);}
API uint32_t bbk_reg(int n) {uint32_t r[]={cpu.pc,cpu.ac,cpu.ix,cpu.iy,cpu.sp,cpu.status};return (n>=0&&n<6)?r[n]:0;}
API void bbk_setreg(int n,uint32_t v) {switch(n){case 0:cpu.pc=v;break;case 1:cpu.ac=v;break;case 2:cpu.ix=v;break;case 3:cpu.iy=v;break;case 4:cpu.sp=v;break;case 5:cpu.status=v;}}
API uint64_t bbk_iocount(int a,int write) {return a>=0&&a<128?(write?io_writes[a]:io_reads[a]):0;}
API uint64_t bbk_extcount(int bank) {return bank>=0&&bank<2048?ext_reads[bank]:0;}
API uint32_t bbk_history(int back) {return history[(history_pos-1-back)&63];}
API void bbk_pin(int port,uint32_t value) {if(port>=0&&port<7){if(pins[port]!=value){pins[port]=value;if(port==0)request_irq(4);}}}
API void bbk_key(int row,int col,int down) {if(row>=0&&row<8&&col>=0&&col<8){if(down)keys[row]|=1<<col;else keys[row]&=~(1<<col);request_irq(4);}}
API void bbk_irq(int n) {if(n>=0&&n<16)request_irq(n);}
API int bbk_uart_send(const uint8_t *data,uint32_t size) {
    if (size>65536-(rx_tail-rx_head)) return -1;
    for(uint32_t i=0;i<size;i++)uart_rx[rx_tail++&65535]=data[i];
    return 0;
}
API uint32_t bbk_uart_receive(uint8_t *data,uint32_t size) {
    uint32_t n=tx_tail-tx_head;if(n>size)n=size;
    for(uint32_t i=0;i<n;i++)data[i]=uart_tx[tx_head++&65535];
    return n;
}
API void bbk_lcd(uint8_t *pixels) {
    uint32_t base=io[0x40]|(io[0x41]<<8),bpp=1<<((io[0x47]>>2)&3),pitch=io[0x42]*2*bpp;
    if (!pitch) pitch=240*bpp/8;
    for (uint32_t y=0;y<120;y++)for(uint32_t x=0;x<240;x++) {
        uint32_t bit=x*bpp;uint8_t b=rd(base+y*pitch+(bit>>3));
        pixels[y*240+x]=(b>>(8-bpp-(bit&7)))&((1<<bpp)-1);
    }
}
