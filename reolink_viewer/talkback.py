"""Push-to-talk adapter.

Reolink talkback is a proprietary Baichuan TCP media session, not an RTSP
feature. This module captures microphone PCM and pipes it to the Reolink CLI.
The command is configurable because CLI releases/device-profile syntax can
change. The user must install and configure the CLI separately.
"""
import subprocess
import threading
import sounddevice as sd
import numpy as np

class Talkback:
    def __init__(self, command, channel_index, sample_rate=16000,
                 channels=1, blocksize=320):
        self.command = [str(x).format(channel=channel_index) for x in command]
        self.sample_rate = int(sample_rate)
        self.channels = int(channels)
        self.blocksize = int(blocksize)
        self.process = None
        self.stream = None
        self.lock = threading.Lock()

    def start(self):
        with self.lock:
            if self.process is not None:
                return
            self.process = subprocess.Popen(
                self.command, stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                bufsize=0
            )
            try:
                self.stream = sd.InputStream(
                    samplerate=self.sample_rate, channels=self.channels,
                    dtype="int16", blocksize=self.blocksize,
                    callback=self._audio_callback
                )
                self.stream.start()
            except Exception:
                self.process.terminate()
                self.process = None
                raise

    def _audio_callback(self, indata, frames, time_info, status):
        with self.lock:
            process = self.process
            if process and process.stdin and process.poll() is None:
                try:
                    process.stdin.write(np.asarray(indata).tobytes())
                except (BrokenPipeError, OSError):
                    pass

    def stop(self):
        with self.lock:
            stream, process = self.stream, self.process
            self.stream = None
            self.process = None
        if stream:
            stream.stop()
            stream.close()
        if process:
            if process.stdin:
                try:
                    process.stdin.close()
                except OSError:
                    pass
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.terminate()
                process.wait(timeout=2)
