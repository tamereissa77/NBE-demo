import json, re, sys, urllib.request, wave
sys.path.insert(0, "/w"); from lines import L
def spoken(t):
    t = re.sub(r"\(?(\d[\d,]*) MAD\)?", r"\1 dirhams", t)
    t = t.replace("A/B", "A B").replace("CDM's", "C D M's").replace("→", "to").replace("(", ", ").replace(")", ",")
    return re.sub(r"\s+,", ",", t)
SAY = {
 "d1c": "Flagged: the name doesn't match the ID, and the letter's salary, sixteen thousand three hundred dirhams, doesn't match the statement, nine thousand eight hundred dirhams.",
 "outro": "Seven use cases, on one machine, fully offline, prepared for Crédit du Maroc. Thank you.",
 "home": "The portal, in C D M's brand. And Moroccan data: amounts in dirhams, Moroccan names and cities, and the Darija dialect.",
 "intro2": "Everything runs on one Dell Pro Max with G B ten, fully offline, on synthetic data.",
}
ONLY = sys.argv[1:]
out = json.load(open("/w/tts_en/index.json")) if ONLY else {}
for k, (ar, en, _) in L.items():
    if ONLY and k not in ONLY: continue
    text = SAY.get(k) or spoken(en)
    r = urllib.request.Request("http://nbe-tts:8000/tts", data=json.dumps({"text": text, "lang": "en"}).encode(), headers={"Content-Type": "application/json"})
    f = f"/w/tts_en/{k}.wav"; open(f, "wb").write(urllib.request.urlopen(r, timeout=120).read())
    w = wave.open(f); out[k] = {"dur": round(w.getnframes() / w.getframerate(), 2), "text": text}
json.dump(out, open("/w/tts_en/index.json", "w"), indent=1)
print({k: out[k]["dur"] for k in (ONLY or out)})
print("total", round(sum(v["dur"] for v in out.values())), "s")
