"""Capture actual stock firmware game screens through keyboard matrix input."""
from pathlib import Path
import sys
import json
import hashlib
from PIL import Image
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from machine import Machine,ROOT
from keyboard import KEYS

PALETTE=[235,241,220,153,169,131,83,105,65,26,45,25]+[0]*756
OUT=ROOT/'runtime/games'

def save(machine,name):
    im=Image.frombytes('P',(240,120),machine.frame());im.putpalette(PALETTE)
    path=OUT/name;im.resize((960,480),Image.Resampling.NEAREST).convert('RGB').save(path)
    return path

def tap(machine,code,settle=5_000_000):
    machine.lib.bbk_key(code//8,code%8,1);machine.run(300_000)
    machine.lib.bbk_key(code//8,code%8,0);machine.run(settle)

def menu(machine):
    machine.lib.bbk_reset();machine.run(80_000_000)
    for _ in range(8):tap(machine,43)

if __name__=='__main__':
    OUT.mkdir(exist_ok=True)
    machine=Machine();machine.load_nand(ROOT/'runtime/installed-nand.bin.z');menu(machine)
    save(machine,'00-menu.png')
    report=[]
    for index,name in enumerate(['bomb-boy','submarine','pacman','reversi','gomoku','thunder-fighter']):
        menu(machine);tap(machine,index,20_000_000)
        save(machine,f'{index+1:02d}-{name}-title.png')
        before=hashlib.sha256(machine.frame()).hexdigest()
        if index==5:tap(machine,55,3_000_000) # The stock help page, not combat.
        elif index!=4:tap(machine,KEYS['Return'],3_000_000)
        save(machine,f'{index+1:02d}-{name}-play.png')
        state=machine.state();report.append(dict(name=name,state=state,status='gameplay-screen' if index<4 else 'side-selection' if index==4 else 'help-only',title_sha256=before,play_sha256=hashlib.sha256(machine.frame()).hexdigest()))
        print(name,state)
    (OUT/'capture-report.json').write_text(json.dumps(report,indent=2),encoding='utf8')
