# Reproduction Guide

Written for someone starting from a clean environment. Every command is exact and
every expected output below was produced by this project.

**Run all commands from the project root** (the folder containing `app.py` and
`paths.py`). The modules are invoked with `python -m` so imports resolve correctly.

---

## 1. Environment

- **Python:** 3.12 (developed and tested on 3.12.10).
- **OS:** platform-independent; commands shown work on Windows PowerShell, macOS
  and Linux (the Python commands are identical).
- **Dependencies:** pinned in `requirements.txt`.

```bash
python -m venv .venv
# Windows PowerShell:
.venv\Scripts\Activate.ps1
# macOS / Linux:
# source .venv/bin/activate

pip install -r requirements.txt
```

For the **baseline evaluation you do not need an API key**. For the LLM runs
(`llm_baseline`, `it1`..`it4`, `final`) you do.

---

## 2. API key

The evaluation's LLM runs use OpenAI (default model `gpt-3.5-turbo`).

1. Create a key at <https://platform.openai.com/api-keys>.
2. Put it in a `.env` file in the project root:

```
OPENAI_API_KEY=sk-your-real-key
OPENAI_MODEL=gpt-3.5-turbo
```

`.env` is gitignored. Do not commit a real key.

---

## 3. Build the databases and ground truth

The databases are seeded and use a fixed date window (2026-01 to 2026-08), so the
generated data, and therefore every expected answer, is identical on any machine.

```bash
python -m data.erp_database                 # -> erp.db
python -m data.pos_database                 # -> pos.db
python -m eval.ground_truth --schema erp    # -> ground_truth.json
python -m eval.ground_truth --schema pos    # -> ground_truth_pos.json
```

Expected (ERP ground truth, abbreviated):

```
Wrote ground_truth.json with 12 ground-truth answers (schema=erp).
  Q01 ... -> 6
  Q02 ... -> 244870.0
  Q03 ... -> 2577880.0
  Q05 ... -> ['UltraSlim Laptop', 'ProBook Laptop', '34in Ultrawide']
  Q12 ... -> ['Docking Station']
```

Expected (POS ground truth): the **labels match** ERP (same business facts) while
the **numbers differ** (different line mix), e.g. `Q02 -> 277230.0`,
`Q03 -> 2153740.0`, `Q12 -> ['Docking Station']`.

---

## 4. Run the baseline (no API key required)

```bash
python -m eval.evaluate --runner baseline --schema-id erp
python -m eval.evaluate --runner baseline --schema-id pos
```

Expected summary:

```
ERP baseline:  total_cases 12, correct 3, answer_accuracy_pct 25.0, sql_validity_pct 41.7
POS baseline:  total_cases 12, correct 1, answer_accuracy_pct 8.3,  exec_errors 7
```

This is the generalization contrast: the ERP-tuned keyword baseline collapses on
POS because its hard-coded SQL references ERP-only table names.

Each run writes `results_<runner>.json` (full per-case detail) and
`results_<runner>.md` (a readable table).

---

## 5. Run the agent iterations (API key required)

Each runner turns on one more capability than the previous, so the accuracy delta
between consecutive runners isolates that iteration's contribution.

```bash
python -m eval.evaluate --runner llm_baseline # plain LangChain chain, schema only
python -m eval.evaluate --runner it1          # + schema discovery + business context
python -m eval.evaluate --runner it2          # + read-only SQL validation
python -m eval.evaluate --runner it3          # + result verification
python -m eval.evaluate --runner it4          # + self-correction
python -m eval.evaluate --runner final        # + business-analysis output (full agent)
```

Then the **generalization run** on the second schema:

```bash
python -m eval.evaluate --runner final --schema-id pos
```

Read the `answer_accuracy_pct` from each summary and record it in the README
Improvement Changelog. The headline result is a two-row comparison:

| Runner | ERP accuracy | POS accuracy |
|--------|:-----------:|:------------:|
| baseline (keyword) | 25.0% | 8.3% |
| final (agent) | TBD | TBD |

The hypothesis: the agent holds high accuracy on **both** schemas while the
baseline collapses on POS.

---

## 5b. Gap & Capability Analysis evaluation (Iteration 8)

This is a **separate** evaluation from the Data Analysis set above. It checks
whether the agent correctly determines if a database can support a business
capability. It is read-only and does not modify the database.

```bash
python -m eval.gap_evaluate --schema erp
python -m eval.gap_evaluate --schema pos
```

Expected: **5/5 status correct** on both schemas, for example:

```
Gap Analysis evaluation (erp): 5/5 status correct (100.0%)
  [OK ] G1 Can the ERP measure customer churn?      expected=PARTIALLY SUPPORTED
  [OK ] G3 Can we measure supplier delivery ...     expected=NOT SUPPORTED
  [OK ] G4 Can we calculate customer lifetime value expected=SUPPORTED
  [OK ] G5 Can we measure inventory turnover?       expected=SUPPORTED
```

Each status is decided deterministically by matching required data concepts
against the discovered schema, so the result is reproducible without an API key.
(The Streamlit UI's Gap Analysis mode additionally uses the LLM to phrase the
required concepts and the recommendation; the evaluation isolates the
deterministic grounding.)

---

## 6. What output to expect

`evaluate.py` prints a JSON summary and writes two files per runner:

- `results_<runner>.json` — summary plus every case: question, expected answer,
  the agent's answer, the SQL it ran, correct/sql_valid/exec_error flags, and
  response time.
- `results_<runner>.md` — the same as a table you can paste into a report.

Tie every changelog claim back to these files.

---

## 7. Approximate runtime and cost

- **Baseline runs:** instant (< 1 second each), no API cost.
- **LLM runs:** roughly 12-40 model calls per run depending on how many
  self-corrections and verifications fire (1 generation + up to 1 verification +
  up to 2 retries + 1 analysis per question). On `gpt-3.5-turbo` this is a few US
  cents per run; the full set of 7 runs is well under one dollar.
- **Wall-clock:** typically 1-3 minutes per LLM run, dominated by API latency.

Actual cost/time vary with the model and account rate limits. Record the figures
you observe in the changelog for full transparency.

---

## 8. Verifying safety

The agent is read-only. To confirm the guard, note that any generated statement
that is not a single `SELECT`/`WITH` is rejected before execution
(`validate_read_only` in `src/analyst_agent.py`). Non-SELECT statements never reach
the database.
