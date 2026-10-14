import json, sys
sys.path.insert(0, "/w"); from check_tts import asr
idx = json.load(open("/w/tts_en/index.json"))
for k in sys.argv[1:]:
    print(k, "|", idx[k]["text"], "\n   heard:", asr(f"/w/tts_en/{k}.wav", "en"), flush=True)
