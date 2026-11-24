"""BBK7980 desktop emulator for macOS; the screen is rendered by stock firmware."""
import argparse
from datetime import datetime
import json
from pathlib import Path
import sys
import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk, filedialog, messagebox, simpledialog
from PIL import Image, ImageTk
from machine import Machine, ROOT, default_runtime, ensure_runtime
from keyboard import KEYS, PANEL_ROWS, PANEL_FUNCTIONS, host_key, host_key_source
from audio_output import AudioOutput
import file_transfer
from prepare import prepare

PALETTE=[235,241,220,153,169,131,83,105,65,26,45,25]+[0]*756
PREFERRED_FONTS=('PingFang SC','Hiragino Sans GB','Helvetica Neue')


def configure_fonts(window):
    """Use the system Chinese UI font instead of Tk's X11-style default."""
    families=set(tkfont.families(window))
    family=next((name for name in PREFERRED_FONTS if name in families),None)
    if family is None:return
    for name in ('TkDefaultFont','TkTextFont','TkMenuFont','TkHeadingFont',
                 'TkCaptionFont','TkSmallCaptionFont','TkTooltipFont'):
        try:tkfont.nametofont(name).configure(family=family)
        except tk.TclError:pass


class ExportFileDialog(simpledialog.Dialog):
    def __init__(self, parent, files):
        self.files = files
        super().__init__(parent, title='选择要导出的机内文件')

    def body(self, parent):
        ttk.Label(parent, text='点击选择，可多选。').grid(row=0, column=0, sticky='w')
        self.selection = tk.Listbox(parent, selectmode=tk.MULTIPLE, exportselection=False,
                                    width=52, height=16, font=tkfont.nametofont('TkTextFont'))

        scroll = ttk.Scrollbar(parent, command=self.selection.yview)
        self.selection.configure(yscrollcommand=scroll.set)
        self.selection.grid(row=1, column=0, sticky='nsew')
        scroll.grid(row=1, column=1, sticky='ns')
        for name, size in self.files:
            self.selection.insert(tk.END, f'{name}   ({size:,} 字节)')
        return self.selection

    def buttonbox(self):
        row = ttk.Frame(self, padding=(6, 0, 6, 6))
        row.pack()
        ttk.Button(row, text='选择保存目录…', command=self.ok).pack(side='left', padx=4)
        ttk.Button(row, text='取消', command=self.cancel).pack(side='left', padx=4)
        self.bind('<Return>', self.ok)
        self.bind('<Escape>', self.cancel)

    def validate(self):
        if not self.selection.curselection():
            self.bell()
            return False
        return True

    def apply(self):
        self.result = [self.files[index][0] for index in self.selection.curselection()]


class Emulator:
    def __init__(self, window, options):
        self.window=window;self.options=options;self.running=True;self.pressed={}
        self.window.title('步步高 7980 模拟器')
        self.window.resizable(False,False)
        self.machine=Machine(options.runtime/'syscode.bin')
        self.data_dir=options.runtime/'data';self.data_dir.mkdir(exist_ok=True)
        self.audio_output=AudioOutput(self.machine.lib)
        self.save_path=self.data_dir/'nand.bin';self.closed=False
        self.smoke_error = None
        preset=options.runtime/'installed-nand.bin.z'
        source=Path(options.nand) if options.nand else self.save_path if self.save_path.exists() else preset
        self.machine.load_nand(source)
        outer=ttk.Frame(window,padding=(16,12));outer.pack()
        self.display_scale = 2 if window.winfo_screenheight() < 900 else 3
        ttk.Label(outer,text='BBK 7980',font=('Helvetica Neue',22,'bold')).pack(anchor='w')
        ttk.Label(outer,text='原厂 V1.10 系统 · 240 × 120 · 四级灰度').pack(anchor='w',pady=(0,12))
        self.screen=tk.Label(outer,bg='#35462d',bd=8,relief='sunken');self.screen.pack()
        self.screen.bind('<Button-1>',lambda event:self.window.focus_force())
        self.font_notice=tk.StringVar(value='正在检查中文字库…')
        ttk.Label(outer,textvariable=self.font_notice,foreground='#805127').pack(pady=8)
        self.build_keypad(outer)
        row=ttk.Frame(outer);row.pack(pady=8)
        for label,action in [('暂停 / 继续',self.pause),('重启',self.reset),('保存',self.save),('截图',self.screenshot),('载入 NAND',self.open_nand),('按键矩阵',self.matrix)]:
            ttk.Button(row,text=label,command=action).pack(side='left',padx=3)
        files = ttk.Frame(outer)
        files.pack()
        ttk.Button(files, text='导入文件', command=self.import_file).pack(side='left', padx=3)
        ttk.Button(files, text='导出文件', command=self.export_file).pack(side='left', padx=3)
        self.status=tk.StringVar(value='正在启动…');ttk.Label(outer,textvariable=self.status).pack(anchor='w',pady=(8,0))
        self.build_menu()
        window.bind('<KeyPress>',self.key_down);window.bind('<KeyRelease>',self.key_up)
        window.bind('<FocusOut>',lambda event:self.release_all())
        window.protocol('WM_DELETE_WINDOW',self.close)
        window.createcommand('tk::mac::Quit',self.close)
        for sequence,action in [('<Command-s>',self.save),('<Command-Shift-S>',self.screenshot),
                                ('<Command-p>',self.pause),('<Command-r>',self.reset),
                                ('<Command-w>',self.close)]:
            window.bind(sequence,self.shortcut(action))
        self.machine.run(80_000_000);self.update_font_notice()
        if options.minesweeper:self.launch_minesweeper()
        if hasattr(self.machine.lib,'bbk_audio_clear'):self.machine.lib.bbk_audio_clear()
        self.last_frame=None;self.render()
        window.after(16,self.step)
        if options.smoke_test:window.after(500,self.run_smoke_test)

    def shortcut(self, action):
        def handler(event=None):
            action()
            return 'break'
        return handler

    def build_menu(self):
        menubar=tk.Menu(self.window)
        files=tk.Menu(menubar,tearoff=False)
        files.add_command(label='导入文件…',command=self.import_file)
        files.add_command(label='导出文件…',command=self.export_file)
        files.add_separator()
        files.add_command(label='保存 NAND',accelerator='⌘S',command=self.save)
        files.add_command(label='截图…',accelerator='⇧⌘S',command=self.screenshot)
        files.add_separator()
        files.add_command(label='关闭',accelerator='⌘W',command=self.close)
        menubar.add_cascade(label='文件',menu=files)
        machine=tk.Menu(menubar,tearoff=False)
        machine.add_command(label='暂停 / 继续',accelerator='⌘P',command=self.pause)
        machine.add_command(label='重启',accelerator='⌘R',command=self.reset)
        machine.add_command(label='载入 NAND…',command=self.open_nand)
        machine.add_separator()
        machine.add_command(label='按键矩阵',command=self.matrix)
        menubar.add_cascade(label='模拟器',menu=machine)
        self.window.configure(menu=menubar)


    def build_keypad(self, parent):
        panel = ttk.Frame(parent, padding=(0, 0, 0, 4))
        panel.pack(fill='x')
        panel.columnconfigure(tuple(range(22)), weight=1, uniform='half_key')

        def place(label, code, row, column, span=2, rows=1):
            button = self.key_button(panel, label, code, width=1)
            button.grid(row=row, column=column, columnspan=span, rowspan=rows,
                        sticky='nsew', padx=2, pady=2)

        for row, keys in enumerate(PANEL_ROWS):
            margin = 11 - len(keys)
            for index, (label, code) in enumerate(keys):
                place(label, code, row, margin + 2 * index)

        column = 1
        for index, (label, code) in enumerate(PANEL_FUNCTIONS):
            span = 2 if index < 7 else 3
            place(label, code, 4, column, span)
            column += span

        place('Esc', KEYS['Escape'], 6, 5, 3)
        place('Enter', KEYS['Return'], 5, 8, 4, 2)
        place('↑', KEYS['Up'], 5, 14)
        place('←', KEYS['Left'], 6, 12)
        place('↓', KEYS['Down'], 6, 14)
        place('→', KEYS['Right'], 6, 16)
        place('上翻页', KEYS['Prior'], 5, 19, 3)
        place('下翻页', KEYS['Next'], 6, 19, 3)

    def key_button(self,parent,label,code,width=None):
        button=ttk.Button(parent,text=label,width=width if width is not None else max(5,len(label)+1),takefocus=False)
        button.bind('<ButtonPress-1>',lambda event:self.press(code,button))
        button.bind('<ButtonRelease-1>',lambda event:self.release(code,button))
        return button

    def press(self, code, source=None):
        source = ('direct', code) if source is None else source
        if source in self.pressed:
            return
        if code not in self.pressed.values():
            self.machine.lib.bbk_key(code//8, code%8, 1)
        self.pressed[source] = code

    def release(self, code, source=None):
        source = ('direct', code) if source is None else source
        released = self.pressed.pop(source, None)
        if released is not None and released not in self.pressed.values():
            self.machine.lib.bbk_key(released//8, released%8, 0)

    def release_all(self):
        for code in set(self.pressed.values()):
            self.machine.lib.bbk_key(code//8, code%8, 0)
        self.pressed.clear()

    def key_down(self,event):
        code = host_key(event)
        if code is not None:
            self.press(code, host_key_source(event))

    def key_up(self,event):
        source = host_key_source(event)
        self.release(self.pressed.get(source), source)

    def frame_image(self):
        im=Image.frombytes('P',(240,120),self.display_frame());im.putpalette(PALETTE)
        return im.convert('RGB')

    def display_frame(self):
        # V1.10 sets the LCD control stop bit when the power key puts it to sleep.
        return bytes(240 * 120) if self.machine.lib.bbk_read(0x47) & 0x80 else self.machine.frame()

    def render(self):
        frame=self.display_frame()
        if frame!=self.last_frame:
            self.last_frame=frame;im=Image.frombytes('P',(240,120),frame);im.putpalette(PALETTE)
            size=(240*self.display_scale,120*self.display_scale)
            self.photo=ImageTk.PhotoImage(im.resize(size,Image.Resampling.NEAREST));self.screen.configure(image=self.photo)

    def step(self):
        if self.closed:return
        if self.running:self.machine.run(66_667)
        self.audio_output.write(self.machine.audio())
        self.render();s=self.machine.state()
        self.status.set(f'{"运行中" if self.running else "已暂停"} · PC {s["pc"]:04X} · {s["cycles"]/4_000_000:.1f} 秒 · 方向键 / Enter / Esc / F1–F5')
        self.window.after(16,self.step)

    def pause(self):
        self.running=not self.running;self.release_all()
        if not self.running:self.audio_output.clear()
    def update_font_notice(self):
        text='兼容中文字库已启用。' if self.machine.lib.bbk_read(0x9eca)!=0xff else '当前镜像缺少中文字库，部分汉字显示为方块。'
        self.font_notice.set(text+(' CoreAudio 声音输出已启用；PSG 旋律可播放，语音尚未实现。' if self.audio_output.available else ' 未找到可用的音频输出设备。'))

    def reset(self):
        self.release_all();self.machine.lib.bbk_reset();self.machine.run(80_000_000);self.update_font_notice()
        if self.options.minesweeper:self.launch_minesweeper()
        self.audio_output.clear()
        if hasattr(self.machine.lib,'bbk_audio_clear'):self.machine.lib.bbk_audio_clear()

    def launch_minesweeper(self):
        # Drive the real shell and loader, including their normal file checks.
        for code in [43]*8+[6]:
            self.machine.lib.bbk_key(code//8,code%8,1);self.machine.run(300_000)
            self.machine.lib.bbk_key(code//8,code%8,0);self.machine.run(30_000_000 if code==6 else 5_000_000)

    def save(self):
        try:self.machine.save_nand(self.save_path);self.status.set('已保存到 '+str(self.save_path))
        except OSError as exc:messagebox.showerror('保存失败',str(exc))

    def screenshot(self):
        name=f'BBK7980-{datetime.now():%Y%m%d-%H%M%S}.png'
        path=filedialog.asksaveasfilename(initialfile=name,defaultextension='.png',
                                          filetypes=[('PNG 图片','*.png')])
        if path:self.frame_image().resize((960,480),Image.Resampling.NEAREST).save(path)

    def open_nand(self):
        path=filedialog.askopenfilename(filetypes=[('NAND 镜像','*.bin *.z'),('所有文件','*')])
        if not path:return
        try:self.machine.load_nand(path);self.reset()
        except (OSError,ValueError) as exc:messagebox.showerror('载入失败',str(exc))

    def transfer(self, status, operation, *, write=False):
        self.release_all()
        self.audio_output.clear()
        self.status.set(status)
        self.window.configure(cursor='watch')
        self.window.update_idletasks()
        try:
            snapshot = self.machine.snapshot_nand() if write else None
            try:
                result = operation(file_transfer.connect(self.machine))
                if write:
                    self.machine.save_nand(self.save_path)
                return result
            except (OSError, ValueError, RuntimeError):
                if snapshot is not None:
                    self.machine.restore_nand(snapshot)
                raise
            finally:
                self.reset()
                self.render()
        finally:
            self.window.configure(cursor='')

    def import_file(self):
        paths = filedialog.askopenfilenames(parent=self.window, title='选择要导入 7980 的文件')
        if not paths:
            return
        try:
            records = []
            names = set()
            total = 0
            for path in paths:
                name, data, flags = file_transfer.read_import(path)
                if name in names:
                    raise ValueError(f'所选文件都要使用机内名称「{name}」，请分开导入。')
                total += len(data)
                if total > file_transfer.MAX_FILE_SIZE:
                    raise ValueError('所选文件的总大小超过虚拟 NAND 容量。')
                names.add(name)
                records.append((name, data, flags))
            if not messagebox.askokcancel(
                '导入文件', f'将导入 {len(records)} 个文件。传输会重启模拟器，请先保存当前应用进度。\n'
                '机内如有同名文件，将用此次导入的文件替换。', parent=self.window
            ):
                return

            def install(link):
                for index, (name, data, flags) in enumerate(records):
                    link.put(name, data, flags)
                    if link.get(name) != data:
                        raise RuntimeError(f'「{name}」读回校验失败，已恢复导入前的 NAND。')
                    # V1.10 leaves PC-link after a zero-length reply.
                    if not data and index + 1 < len(records):
                        link = file_transfer.connect(self.machine)

            self.transfer(f'正在导入并校验 {len(records)} 个文件…', install, write=True)
            messagebox.showinfo('导入完成', f'{len(records)} 个文件已导入并保存。', parent=self.window)
        except (OSError, ValueError, RuntimeError) as error:
            messagebox.showerror('导入失败', str(error), parent=self.window)

    def export_file(self):
        try:
            files = file_transfer.list_files(self.machine)
            if not files:
                messagebox.showinfo('导出文件', '当前 NAND 中没有可导出的文件。', parent=self.window)
                return
            names = ExportFileDialog(self.window, files).result
            if not names:
                return
            directory = filedialog.askdirectory(parent=self.window, title='选择导出的保存目录',
                                                mustexist=True)
            if not directory:
                return
            paths = file_transfer.export_paths(directory, names)
            conflicts = sum(path.exists() for path in paths)
            prompt = f'将导出 {len(names)} 个文件。传输会重启模拟器，请先保存当前应用进度。'
            if conflicts:
                prompt += f'\n保存目录中有 {conflicts} 个同名文件。继续会覆盖它们。'
            if not messagebox.askokcancel('导出文件', prompt, parent=self.window):
                return

            def download(link):
                payloads = []
                for index, name in enumerate(names):
                    data = link.get(name)
                    payloads.append(data)
                    if not data and index + 1 < len(names):
                        link = file_transfer.connect(self.machine)
                return payloads

            payloads = self.transfer(f'正在读取 {len(names)} 个文件…', download)
            for path, data in zip(paths, payloads):
                file_transfer.write_export(path, data)
            messagebox.showinfo('导出完成', f'已保存 {len(paths)} 个文件。', parent=self.window)
        except (OSError, ValueError, RuntimeError) as error:
            messagebox.showerror('导出失败', str(error), parent=self.window)

    def matrix(self):
        panel=tk.Toplevel(self.window);panel.title('7980 原始按键矩阵')
        ttk.Label(panel,text='Y = 16；Esc = 49；Enter = 50；帮助 = 55；Delete = 56。').grid(row=0,column=0,columnspan=8,padx=10,pady=10)
        for code in range(64):self.key_button(panel,f'{code:02d}',code).grid(row=code//8+1,column=code%8,padx=3,pady=3)

    def smoke_test(self):
        before=self.machine.frame()
        code=50 if self.options.minesweeper else 43
        self.press(code);self.machine.run(8_000_000);self.release(code);self.render()
        if before==self.machine.frame():raise RuntimeError('Guest did not respond to its input')
        target=Path(self.options.smoke_test);target.parent.mkdir(parents=True,exist_ok=True)
        self.frame_image().save(target)
        self.window.update()
        try:
            from PIL import ImageGrab
            x,y=self.window.winfo_rootx(),self.window.winfo_rooty()
            width,height=self.window.winfo_width(),self.window.winfo_height()
            ImageGrab.grab(bbox=(x,y,x+width,y+height)).save(target.with_name(target.stem+'-window.png'))
        except Exception as error:
            # Screen Recording permission is optional; the framebuffer dump above is enough.
            print(f'window screenshot skipped: {error}',file=sys.stderr)

    def run_smoke_test(self):
        try:
            self.smoke_test()
        except Exception as error:
            self.smoke_error = error
        finally:
            self.audio_output.close()
            self.closed = True
            self.window.quit()

    def close(self):
        if self.closed:return
        self.release_all()
        try:self.machine.save_nand(self.save_path)
        except OSError as exc:
            messagebox.showerror('保存失败',str(exc));return
        self.audio_output.close();self.closed=True;self.window.destroy()

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--version', action='version', version=(ROOT/'VERSION').read_text().strip())
    parser.add_argument('--runtime', type=Path, default=default_runtime())
    parser.add_argument('--prepare', type=Path, metavar='UPDATER')
    parser.add_argument('--nand', type=Path)
    parser.add_argument('--smoke-test', type=Path)
    parser.add_argument('--minesweeper', action='store_true')
    args = parser.parse_args()
    args.runtime = ensure_runtime(args.runtime)
    window = tk.Tk()
    configure_fonts(window)
    window.withdraw()
    try:
        if args.prepare or not (args.runtime/'installed-nand.bin.z').is_file():
            run_setup(window, args)
            if not (args.runtime/'installed-nand.bin.z').is_file():
                window.destroy()
                return
        if args.minesweeper:
            manifest = json.loads((args.runtime/'installed-manifest.json').read_text(encoding='utf8'))
            if not any(record['name'] == '扫雷.exe' for record in manifest['verified']):
                raise ValueError('当前运行镜像未安装扫雷。请用带有扫雷示例的发行包重新初始化。')
        emulator = Emulator(window, args)
        window.deiconify()
        window.lift()
        window.focus_force()
        window.mainloop()
        if emulator.smoke_error:
            raise emulator.smoke_error
        if args.smoke_test:
            window.destroy()
    except (OSError, ValueError, RuntimeError) as error:
        if args.smoke_test:
            window.destroy()
            raise
        messagebox.showerror('步步高 7980 模拟器', str(error), parent=window)
        window.destroy()



def run_setup(window, args):
    updater = args.prepare or filedialog.askopenfilename(
        parent=window, title='选择步步高 7980 V1.10 官网升级包',
        filetypes=[('步步高升级包', '*.exe'), ('所有文件', '*')])
    if not updater:
        return
    window.title('初始化步步高 7980')
    window.protocol('WM_DELETE_WINDOW', lambda: None)
    panel = ttk.Frame(window, padding=24)
    panel.pack()
    status = tk.StringVar()
    ttk.Label(panel, width=48, textvariable=status).pack()
    window.deiconify()

    def progress(message):
        status.set(message)
        window.update_idletasks()

    demo_paths = (ROOT/'demo/minesweeper.exe', ROOT/'build/demo/minesweeper.exe')
    demo = next((path for path in demo_paths if path.is_file()), None)
    try:
        prepare(updater, args.runtime, demo, progress)
    finally:
        panel.destroy()


if __name__ == '__main__':
    main()
