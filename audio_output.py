"""CoreAudio PCM playback for the emulated PSG.

The device queue lives in the native core (src/audio_macos.c) so the realtime
callback never re-enters Python.
"""
class AudioOutput:
    def __init__(self, lib):
        self.lib=lib
        self.available=hasattr(lib,'bbk_out_open') and lib.bbk_out_open()==0

    def write(self,pcm):
        if self.available and pcm:
            self.lib.bbk_out_write(pcm,len(pcm)//2)

    def clear(self):
        if self.available:
            self.lib.bbk_out_clear()

    def close(self):
        if self.available:
            self.lib.bbk_out_close()
            self.available=False
