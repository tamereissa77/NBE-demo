"""Cut the take: speed up the model waits, lay the narration on its captions, write the final MP4.
    python edit.py [--offset 0.75] [--out name.mp4]
"""
import json, subprocess, sys
from pathlib import Path

W = Path("/w"); OUT = W / "out"
args = dict(zip(sys.argv[1::2], sys.argv[2::2]))
OFFSET = float(args.get("--offset", 0.75))        # raw video time of event t=0 (ffmpeg started ~1 s before the clock)
NAME = args.get("--out", "CDM_AI_Demos_AR.mp4")
VOICE = W / ("tts_en" if args.get("--voice") == "en" else "tts")
ev = json.load(open(OUT / "events.json"))
end = next(e["end"] for e in ev if "end" in e)
fasts = sorted(e["fast"] for e in ev if "fast" in e)
says = [e for e in ev if "clip" in e]

# Segments over event time: (start, end, speed)
segs, t = [], 0.0
for a, b in fasts:
    if a > t:
        segs.append((t, a, 1.0))
    dur = b - a
    target = min(6.0, max(2.5, dur / 8))       # a 45 s wait plays in about 5.6 s
    segs.append((a, b, max(1.0, dur / target)))
    t = b
segs.append((t, end, 1.0))


def out_time(x):
    """Where event time x lands in the edited video."""
    acc = 0.0
    for a, b, s in segs:
        if x <= b:
            return acc + (max(x, a) - a) / s
        acc += (b - a) / s
    return acc


total = out_time(end)
for e in says:                                  # a clip must never start inside a sped-up stretch
    assert all(not (a < e["t"] < b) for a, b in fasts), e

TMP = OUT / "parts"; TMP.mkdir(exist_ok=True)
run = lambda *c: subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *c], check=True)
print(f"segments {len(segs)}, waits sped up {len(fasts)}, clips {len(says)}; raw {end:.0f}s -> {total:.0f}s ({total / 60:.1f} min)", flush=True)
REUSE = (TMP / "video.mp4").exists() and args.get("--reuse") == "1"
# 1. each piece on its own (seeking the input keeps memory flat), sped up where the model was working
for i, (a, b, s) in enumerate([] if REUSE else segs):
    run("-ss", f"{a + OFFSET:.3f}", "-to", f"{b + OFFSET:.3f}", "-i", str(OUT / "raw.mkv"), "-an",
        "-vf", f"setpts=PTS/{s:.4f},fps=30", "-c:v", "libx264", "-preset", "fast", "-crf", "16", "-pix_fmt", "yuv420p", str(TMP / f"s{i:02d}.mp4"))
(TMP / "list.txt").write_text("".join(f"file 's{i:02d}.mp4'\n" for i in range(len(segs))))
REUSE or run("-f", "concat", "-safe", "0", "-i", str(TMP / "list.txt"), "-c", "copy", str(TMP / "video.mp4"))
# 2. the narration, each clip at its caption
inputs, parts, labels = [], [], []
for k, e in enumerate(says):
    inputs += ["-i", str(VOICE / f"{e['clip']}.wav")]
    nxt = next((out_time(x["t"]) for x in says if x["t"] > e["t"]), total) - out_time(e["t"]) - 0.4
    import wave; w = wave.open(str(VOICE / f"{e['clip']}.wav")); d = w.getnframes() / w.getframerate()
    if d > nxt:
        print(f"  !! {e['clip']} is {d:.1f}s but has {nxt:.1f}s before the next caption", flush=True)
    ms = int(out_time(e["t"]) * 1000) + 250
    parts.append(f"[{k}:a]aresample=48000,aformat=channel_layouts=mono,adelay={ms}|{ms}[a{k}]"); labels.append(f"[a{k}]")
parts.append(f"{''.join(labels)}amix=inputs={len(labels)}:normalize=0:dropout_transition=0,apad,atrim=0:{total:.2f},"
             f"loudnorm=I=-16:TP=-1.5:LRA=11,aformat=channel_layouts=stereo[aout]")
run(*inputs, "-filter_complex", ";".join(parts), "-map", "[aout]", "-ar", "48000", str(TMP / f"voice_{VOICE.name}.wav"))
# 3. together, with a fade in and out
run("-i", str(TMP / "video.mp4"), "-i", str(TMP / f"voice_{VOICE.name}.wav"), "-vf", f"fade=t=in:st=0:d=0.8,fade=t=out:st={total - 1.2:.2f}:d=1.2",
    "-c:v", "libx264", "-preset", "slow", "-crf", "20", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-shortest",
    "-movflags", "+faststart", str(OUT / NAME))
chapters = [(e["scene"], out_time(e["t"])) for e in ev if "scene" in e]
print("chapters:", ", ".join(f"{n} {int(t // 60)}:{int(t % 60):02d}" for n, t in chapters))
json.dump({"duration": total, "chapters": chapters}, open(OUT / "chapters.json", "w"))
