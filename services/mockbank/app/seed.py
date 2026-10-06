"""Deterministic synthetic customers for the mock bank. No real people, IDs or card numbers."""
import random

FIRST = [("أحمد", "Ahmed"), ("محمد", "Mohamed"), ("منى", "Mona"), ("سارة", "Sara"), ("يوسف", "Youssef"),
         ("ليلى", "Laila"), ("عمر", "Omar"), ("نور", "Nour"), ("خالد", "Khaled"), ("هدى", "Hoda")]
LAST = [("حسن", "Hassan"), ("عبد الله", "Abdallah"), ("السيد", "El-Sayed"), ("مصطفى", "Mostafa"),
        ("إبراهيم", "Ibrahim"), ("فهمي", "Fahmy"), ("سليمان", "Soliman"), ("رمضان", "Ramadan")]
CITIES = ["القاهرة", "الإسكندرية", "الجيزة", "المنصورة", "أسيوط"]


def customers(n: int = 20, seed: int = 2026):
    rng = random.Random(seed)
    out = []
    for i in range(1, n + 1):
        (fa, fe), (la, le) = rng.choice(FIRST), rng.choice(LAST)
        cid = f"C{i:04d}"
        cards = [{"last4": f"{rng.randint(0, 9999):04d}", "type": t}
                 for t in rng.sample(["debit", "credit", "prepaid"], k=rng.choice([1, 2]))]
        out.append({
            "id": cid,
            "name_ar": f"{fa} {la}", "name_en": f"{fe} {le}",
            "phone": f"+20 10{rng.randint(0, 9)} XXX {rng.randint(1000, 9999)}",  # masked, fictitious
            "city": rng.choice(CITIES),
            "balance": round(rng.uniform(1_500, 450_000), 2),
            "cards": cards,
        })
    return out
