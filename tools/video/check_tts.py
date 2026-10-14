import difflib, json, re, sys, urllib.request, uuid
sys.path.insert(0, "/w"); from lines import L
def norm(s): s = re.sub(r"[ً-ًٌٍَُِّْْ،,.:!؟?\-–«»()]", " ", s); s = re.sub("[إأآ]", "ا", s).replace("ة", "ه").replace("ى", "ي"); return " ".join(s.split())
def asr(f, lang="ar"):
    b = uuid.uuid4().hex; data = open(f, "rb").read()
    body = (f'--{b}\r\nContent-Disposition: form-data; name="language"\r\n\r\n{lang}\r\n--{b}\r\nContent-Disposition: form-data; name="file"; filename="a.wav"\r\nContent-Type: audio/wav\r\n\r\n').encode() + data + f'\r\n--{b}--\r\n'.encode()
    r = urllib.request.Request("http://nbe-asr:8000/transcribe", data=body, headers={"Content-Type": f"multipart/form-data; boundary={b}"})
    return json.loads(urllib.request.urlopen(r, timeout=300).read())["text"]
def main():
  for k in (sys.argv[1:] or list(L)):
    ar, en, say = L[k]; ref = say or ar; got = asr(f"/w/tts/{k}.wav")
    r = difflib.SequenceMatcher(None, norm(ref).split(), norm(got).split()).ratio()
    print(f"{k:6s} {r:.2f}" + ("" if r > 0.75 else f"\n   REF {ref}\n   GOT {got}"), flush=True)

if __name__ == "__main__": main()
