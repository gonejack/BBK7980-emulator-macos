"""7980 matrix positions from the stock firmware table at NOR offset 0xfd67."""
KEYS={'Up':51,'Down':58,'Left':57,'Right':59,'Return':50,'Escape':49,
      'Prior':42,'Next':43,'F1':44,'F2':45,'F3':46,'F4':47,'F5':48,'F6':55,
      'Delete':56,'BackSpace':56,'Home':52,'space':34,'Shift_L':21,'Shift_R':21,
      'Caps_Lock':32,'Control_L':32,'Control_R':32}
for text,start in [('1234567890',0),('qwertyuiop',11),('asdfghjkl',23),('zxcvbnm',35)]:
    for index,character in enumerate(text):
        KEYS[character]=start+index
        if character.isalpha():KEYS[character.upper()]=start+index
for index,character in enumerate('0123456789'):
    KEYS['KP_'+character]=index
KEYS['KP_Enter']=KEYS['Return']


PANEL_ROWS = (
    tuple((n, KEYS[n]) for n in '1234567890') + (('电源', 10),),
    tuple((c, KEYS[c]) for c in 'QWERTYUIOP') + (('字体', 33),),
    tuple((c, KEYS[c]) for c in 'ASDFGHJKL') + (('帮助', KEYS['F6']),),
    (('Shift', KEYS['Shift_L']),) + tuple((c, KEYS[c]) for c in 'ZXCVBNM')
    + (('空格', KEYS['space']), ('Caps', KEYS['Caps_Lock']), ('发音', 22)),
)

PANEL_FUNCTIONS = (
    ('目录', KEYS['Home']), ('删除', KEYS['Delete']),
    *((f'F{i}', KEYS[f'F{i}']) for i in range(1, 6)),
    ('输入法', 54), ('中英符', 53),
)

# Tk on macOS reports Command as Mod1 and Option as Mod2. Those combinations
# belong to the menu bar or extended input, so they must not reach the guest.
MAC_MODIFIERS = 0x8 | 0x10
SHIFTED_DIGITS = {'!':'1','@':'2','#':'3','$':'4','%':'5',
                  '^':'6','&':'7','*':'8','(':'9',')':'0'}
SHIFTED_KEYSYMS = {'exclam':'1','at':'2','numbersign':'3','dollar':'4',
                   'percent':'5','asciicircum':'6','ampersand':'7',
                   'asterisk':'8','parenleft':'9','parenright':'0'}


def host_key(event):
    if event.state & MAC_MODIFIERS:
        return None
    shifted = SHIFTED_DIGITS.get(event.char) or SHIFTED_KEYSYMS.get(event.keysym)
    if shifted is not None:
        return KEYS[shifted]
    return KEYS.get(event.keysym)


def host_key_source(event):
    modifier = event.keysym if event.keysym in ('Shift_L', 'Shift_R', 'Control_L', 'Control_R') else None
    return ('keyboard', event.keycode, modifier)
