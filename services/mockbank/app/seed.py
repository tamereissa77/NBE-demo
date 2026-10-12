"""Deterministic synthetic customers for the mock bank. No real people, IDs or card numbers.
Names, cities, phone format and balances come from the locale pack (nbe_core.locale)."""
import random

from nbe_core import locale as L


def customers(n: int = 20, seed: int = 2026):
    rng = random.Random(seed)
    out = []
    for i in range(1, n + 1):
        (fa, fe), (la, le) = rng.choice(L.MOCKBANK_FIRST), rng.choice(L.MOCKBANK_LAST)
        cid = f"C{i:04d}"
        cards = [{"last4": f"{rng.randint(0, 9999):04d}", "type": t}
                 for t in rng.sample(["debit", "credit", "prepaid"], k=rng.choice([1, 2]))]
        out.append({
            "id": cid,
            "name_ar": f"{fa} {la}", "name_en": f"{fe} {le}",
            "phone": L.PHONE_MASK.format(d=rng.randint(0, 9), n4=rng.randint(1000, 9999)),  # masked, fictitious
            "city": rng.choice(L.MOCKBANK_CITIES),
            "balance": round(rng.uniform(*L.BALANCE_RANGE), 2),
            "cards": cards,
        })
    return out
