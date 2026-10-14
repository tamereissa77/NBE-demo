import json, subprocess, sys
sys.path.insert(0, "/w"); from lines import L; from check_tts import asr
ev = json.load(open("/w/out/events.json")); end = next(e["end"] for e in ev if "end" in e)
fasts = sorted(e["fast"] for e in ev if "fast" in e); segs, t = [], 0.0
for a, b in fasts:
    if a > t: segs.append((t, a, 1.0))
    segs.append((a, b, max(1.0, (b - a) / min(6.0, max(2.5, (b - a) / 8))))); t = b
segs.append((t, end, 1.0))
def ot(x):
    acc = 0.0
    for a, b, s in segs:
        if x <= b: return acc + (max(x, a) - a) / s
        acc += (b - a) / s
says = {e["clip"]: e for e in ev if "clip" in e}
for k in ["intro1", "d1c", "d3d", "d4f", "d5c", "d7c", "outro"]:
    e = says[k]; st = ot(e["t"])
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-ss", f"{st:.2f}", "-t", f"{e["dur"] + 0.6:.2f}", "-i", "/w/out/CDM_AI_Demos_EN.mp4", "-vn", "-ac", "1", "-ar", "16000", "/tmp/s.wav"], check=True)
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-ss", f"{st + 1:.2f}", "-i", "/w/out/CDM_AI_Demos_EN.mp4", "-frames:v", "1", "-vf", "crop=1920:200:0:860,scale=960:-1", f"/w/out/sync_{k}.png"], check=True)
    print(f"{k} @ {int(st // 60)}:{st % 60:04.1f}\n  caption: {L[k][1]}\n  heard:   {asr('/tmp/s.wav', 'en')}", flush=True)
