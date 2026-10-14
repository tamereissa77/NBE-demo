# Customers

One folder per bank the demos are presented to. `make customer NAME=<folder>` makes it the active one: the portal
shows its logo, colours and names, and every demo uses its country's data, currency, dialect and rules.

```
make customers                 # list them (* = active)
make customer NAME=oasis-demo  # switch; reloads the running stack (about 3 minutes)
```

## Adding a customer

1. `cp -r customers/_template customers/<name>`
2. Put the bank's logo in the folder as `logo.png` (PNG, ideally on a transparent background, wide is fine).
   Optional: `mark.png`, a square emblem for the round avatars (D4's phone, the demo pages). Without it the
   logo is shrunk into a square.
3. Edit `customer.json`:

| Field | |
|---|---|
| `id` | short lowercase id (also the portal's brand id) |
| `short` | the name used in running text and labels: "NBE", "Riyad Bank" |
| `name.en`, `name.ar` | the full name in English and Arabic |
| `country` | `EG`, `SA`, `AE` or `MA` (see below) |
| `font` | `cairo` or `plex` (IBM Plex Sans Arabic): the two fonts bundled in the portal |
| `colors` | empty: taken from the logo. Or set any of `brand`, `accent`, `brand-dark`, `accent-light`, `accent-deep`, `on-accent`, `canvas`, `ink`, `ink-soft`, `line`, `status-review`, `status-stop`, `status-ok` as `#rrggbb` |
| `facts` | what D6 may state in a drafted letter without being told (call centre, website, e-mail) |
| optional | `assistant`, `appTitle`, `agentName`, `heroTitle` (`{"en", "ar"}`), `heroChips` (false hides the PoC chips), `bannerPalette` (the colours in words for D3's image model), `website` |

4. `python3 scripts/apply_customer.py <name> --colors-only` previews the colours picked from the logo.
5. `make customer NAME=<name>`.

Logos and names of real banks are for that customer's demonstration only.

## Countries

| Code | Country | Currency | Dialect (D4, D3, D2) | ID (D1) | Corpus |
|---|---|---|---|---|---|
| EG | Egypt | EGP, جنيه | Egyptian | 14-digit national ID, decoded | `data/seed/EG` |
| SA | Saudi Arabia | SAR, ريال | Saudi (white dialect) | 10-digit national ID / iqama | `data/seed/SA` |
| AE | United Arab Emirates | AED, درهم | Emirati | 15-digit Emirates ID (784) | `make author` once |
| MA | Morocco | MAD, درهم | Darija | CIN (letters + digits) | `make author` once |

A country is two modules with the same names in each: `packages/nbe_core/nbe_core/countries/<cc>.py` (names,
cities, merchants, currency, ID rules, D4 dialect, D6 glossary, portal locale) and
`data/generators/countries/<cc>.py` (the fact sheets the corpus is written from: procedures, contract clauses,
rulings, complaint topics). `tests/test_countries.py` checks that they match. The corpus in `data/seed/<CC>` is
written once by the on-box LLM (`make author`, about 25 minutes, with the stack up) and committed; its
`bank.json` records the bank it was written for, and `make customer` swaps in the active bank's name.

All of it is synthetic: invented people, companies, fees and rules in the style of a retail bank in that country.

Known limits: the D4 voice (VoiceTut-TTS) is an Egyptian voice, so Gulf and Moroccan replies are written in the
local dialect but spoken with an Egyptian accent and Egyptian number words; D1's document reader is fine-tuned on
Egyptian documents; D2's scanned circulars exist only for Egypt.
