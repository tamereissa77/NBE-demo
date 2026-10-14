import hashlib, json, os, sys, time, urllib.request, wave
sys.path.insert(0, "/w"); from lines import L, LEXICON
out = {}
cache = json.load(open("/w/tts/index.json")) if os.path.exists("/w/tts/index.json") else {}
for k, (ar, en, say) in L.items():
    text = say or ar
    h = hashlib.sha1(json.dumps([text, LEXICON]).encode()).hexdigest()[:12]
    f = f"/w/tts/{k}.wav"
    if cache.get(k, {}).get("h") != h or not os.path.exists(f):
        req = urllib.request.Request("http://nbe-voicetut:8000/tts", data=json.dumps({"text": text, "lang": "ar", "careful": True, "lexicon": LEXICON}).encode(),
                                     headers={"Content-Type": "application/json"})
        open(f, "wb").write(urllib.request.urlopen(req, timeout=600).read())
    w = wave.open(f); d = w.getnframes() / w.getframerate()
    out[k] = {"h": h, "dur": round(d, 2)}
    print(f"{k:7s} {d:5.1f}s", flush=True)
json.dump(out, open("/w/tts/index.json", "w"), indent=1)
print("total narration", round(sum(v["dur"] for v in out.values())), "s")
