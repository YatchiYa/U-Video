"""Objective checks for music candidates: length, vocals (Whisper), loudness, build, rhythm, spectrum, ending."""
import sys
import numpy as np, soundfile as sf, torch
from pathlib import Path
from transformers import pipeline

M = Path(__file__).parent / "music"
asr = pipeline("automatic-speech-recognition", model="openai/whisper-large-v3-turbo", dtype=torch.float16, device="cuda")

def rms_db(x): return 20*np.log10(np.sqrt((x**2).mean())+1e-9)

for f in sorted(M.glob("cand*.wav")):
    x, sr = sf.read(f, dtype="float32"); mono = x.mean(1) if x.ndim > 1 else x
    dur = len(mono)/sr
    q = len(mono)//4; quarters = [round(rms_db(mono[i*q:(i+1)*q]),1) for i in range(4)]
    # onset envelope -> tempo regularity via autocorrelation peak strength
    hop = 512; frames = len(mono)//hop
    e = np.array([np.sqrt((mono[i*hop:(i+1)*hop]**2).mean()) for i in range(frames)])
    on = np.maximum(0, np.diff(e)); on = (on-on.mean())/(on.std()+1e-9)
    ac = np.correlate(on, on, "full")[len(on)-1:]; ac /= ac[0]
    lo, hi = int(0.3*sr/hop), int(1.2*sr/hop); k = lo+np.argmax(ac[lo:hi])
    bpm = 60*sr/hop/k; rhythm = ac[k]
    spec = np.abs(np.fft.rfft(mono[:sr*30])); fr = np.fft.rfftfreq(sr*30, 1/sr)
    band = lambda a,b: 10*np.log10((spec[(fr>=a)&(fr<b)]**2).sum()+1e-9)
    low, mid, high = band(20,250), band(250,4000), band(4000,16000)
    tail = rms_db(mono[-sr:]) - rms_db(mono[-5*sr:-2*sr])
    text = asr({"raw": mono[: sr*60].copy(), "sampling_rate": sr}, generate_kwargs={"task":"transcribe"}, return_timestamps=True)["text"].strip()
    print(f"{f.name}: {dur:.1f}s quarters dB {quarters} | tempo≈{bpm:.0f} rhythm {rhythm:.2f} | low-mid {low-mid:+.1f}dB high-mid {high-mid:+.1f}dB | ending {tail:+.1f}dB | peak {np.abs(x).max():.2f} | ASR: {text[:80]!r}")
