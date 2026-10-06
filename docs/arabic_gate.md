# Arabic gate: scoring guide

The Arabic gate decides which models the seven NBE demos run on. Five models answered the same 30 NBE-style prompts. Your blind scores decide the result; an LLM judge has pre-scored every answer, but it is only a second opinion.

## How to score

1. Open **http://<gb10>:8200/eval** (the GB10 must be running: `make up`).
2. Enter your name or initials. Several people can score; each scorer's results are kept separately.
3. For each prompt, read the task and the box **"What a good answer contains"**, then score every answer from 1 to 5 on:

| Scale | Ask yourself | 5 | 1 |
|---|---|---|---|
| **Correctness** | Are the facts, numbers and actions right, and taken only from the sources given? | Fully correct | Wrong, invented or harmful |
| **Arabic quality** | Is the language fluent and natural? Did it understand the Egyptian dialect? Is the register right for a bank? | Native quality | Hard to read or wrong register |
| **Format** | Did it do what the task asked: length, JSON, bullet count, citation, required phrase, one answer rather than several, no unrequested preamble? | Every instruction followed | Ignored the instructions |

4. Scores save automatically once all three scales are set for an answer. The optional note is useful for anything surprising.
5. After you score every answer to a prompt, the judge's scores appear under each answer. Use them to spot something you missed, not to change your view.

**Blind scoring.** Answers are shuffled and labelled A, B, C differently for every scorer and prompt. Model names appear only on the results page; please don't look at it until you have finished.

**"auto-check pass/fail"** on an answer is an automatic test: for example, whether the model called the OTP tool before blocking a card, or whether the JSON fields are right. It is objective, so take it into account under Correctness or Format.

**Two sets.** "3 candidate models" (the default) covers the models that could actually run the demos: 90 answers, about 1.5 to 2 hours. "All 5 models" adds two references, including Mistral-7B from NBE's original model list.

## What happens next

- **Results:** http://<gb10>:8200/eval/results shows the scores per model and per dialect, speeds, and a recommendation from a rule fixed before any scores existed:
  - **Workhorse:** the best-scoring model that runs at 20 tokens/s or more.
  - **Gemma 4 31B (quality model):** kept only if it beats the workhorse by at least 0.5 on the legal (D5) prompts.
- The recommendation uses human scores once at least 80% of answers have them; until then it is marked provisional and uses the judge.
- `make models-lock` writes the decision to `config/models.lock`; that file is committed as the frozen model stack (target: **16 Oct**).
- **Download CSV** on the results page exports every answer with every score, for sharing or offline review.
