# Strategy: AI Data Analyst Agent for Business Databases

A build plan to take this project from a working baseline to a competition-grade,
schema-generalizing agent. Every iteration is designed to move a specific
judging criterion and to be backed by evidence from the evaluation harness.

---

## 1. Positioning

**Product:** AI Data Analyst Agent for Business Databases.

**Claim (bounded and defensible):** "Adapts dynamically to supported relational
schemas via schema discovery and business context, demonstrated across multiple
database schemas." We do **not** claim "works with any database."

**Anchor demo:** an ERP schema (where the domain expertise is strongest).
**Generalization proof:** the same agent answering the same *business questions*
against a second schema (POS) whose tables and columns are structurally different.

**The one-line insight we are chasing (our Hot Take):**
> Does the agent understand the user's *question*, or has it memorized *one schema*?

---

## 2. Intended user and bottleneck (for the README / Problem & User Value, 15 pts)

- **User:** a non-technical business user (operations, finance, sales manager)
  who needs answers that live in a business database but cannot write SQL.
- **Bottleneck today:** they file a request with IT/data, wait, and often iterate
  because the first query missed the intent. The gap is between a business
  question and a correct, trustworthy SQL result.
- **Why it matters:** faster decisions, fewer analyst hours spent on ad-hoc pulls,
  and answers a manager can trust without reading SQL.

---

## 3. Baseline (already built and measured)

- **Runner:** `KeywordBaseline` in `evaluate.py` — no schema context, no
  verification, keyword-to-SQL only. An honestly weak baseline.
- **Measured result (erp.db, 12 cases):** 25.0% answer accuracy (3/12),
  41.7% SQL valid, 7 execution errors.
- This is the fixed starting point every iteration is measured against.

A second, fairer baseline to capture once the API key is rotated:
- **LLM baseline:** `--runner agent` as it stands today (single LangChain
  SQLDatabaseChain, schema passed but no verification/self-correction). This is
  the "one general-purpose agent with basic tools" baseline the brief describes.

---

## 4. Evaluation contract (the backbone)

- **Same cases, same scoring, every runner.** `evaluate.py` scores any runner
  with a `.query()` method against `ground_truth.json`.
- **Primary metric:** answer accuracy (correct answers / total).
- **Secondary metrics:** SQL validity %, execution errors, avg response time,
  and (added later) self-corrected errors.
- **Ground truth cannot drift:** answers are computed from the database itself
  via `ground_truth.py`.
- **Reproducibility:** databases are seeded (`seed=42`) and use a fixed date
  window (2026-01..2026-08), so numbers are identical on any machine.

---

## 5. Iteration roadmap

Each iteration is a separate, measurable step. After building each one, re-run
`evaluate.py` and record the delta in the changelog (Section 7). Keep only the
changes that actually move the metric.

### Iteration 1 — Schema discovery + business context
**Why:** the biggest single lever for text-to-SQL accuracy is grounding the
model in the real schema (tables, columns, relationships) plus a short business
glossary (what "revenue", "branch", "segment" mean here).
**Build:** introspect the target DB at runtime, format a compact schema summary
+ a small business-context note, inject into the prompt.
**Expected effect:** large jump in correct SQL on multi-table and ranking cases.
**Metric to watch:** answer accuracy, SQL validity.

### Iteration 2 — SQL validation before execution
**Why:** catch broken or unsafe SQL before it hits the database.
**Build:** a lightweight validator — parse/dry-run (`EXPLAIN`) the generated SQL,
and reject statements that are not read-only `SELECT`s.
**Expected effect:** fewer execution errors; sets up the self-correction loop.
**Metric to watch:** execution errors, SQL validity.

### Iteration 3 — Result verification (the star)
**Why:** a query can run and still not answer the question. A second check asks
"does this result actually answer what was asked?" using the question, the SQL,
and the returned rows.
**Build:** a verification step that inspects the result shape/content against the
question intent and flags mismatches (empty result, wrong granularity, wrong
column).
**Expected effect:** fewer confidently-wrong answers; this is the core
differentiator vs. a plain text-to-SQL chatbot.
**Metric to watch:** answer accuracy, especially on comparison/challenge cases.

### Iteration 4 — Self-correction loop
**Why:** when validation or verification fails, don't give up — diagnose and retry.
**Build:** on failure, feed the error (or verification complaint) back with the
schema and ask for a corrected query; cap retries (e.g. 2) to bound cost/time.
**Expected effect:** recovers difficult cases the first attempt misses.
**Metric to watch:** self-corrected errors (new metric), accuracy on challenge case.

### Iteration 5 — Business analysis layer
**Why:** End-to-End Quality (20 pts) rewards output a human would sign their name
to. Turn raw values into a short, business-readable answer with evidence.
**Build:** format the final answer as a headline number + brief interpretation +
the SQL and data source as evidence (matches the mockup in the original idea).
**Expected effect:** no accuracy change, but a real quality lift for judges.
**Metric to watch:** qualitative; keep accuracy from regressing.

### Iteration 6 — Schema generalization (POS schema)
**Why:** proves the agent understands questions, not one schema. This is the
headline of the reframed project.
**Build:** add `pos_database.py` (seeded, fixed window) with a structurally
different schema (e.g. `transactions`, `sale_items`, `outlets`). Map the same
core business questions onto it with per-schema `reference_sql` for ground truth.
Run the *same* agent against both DBs.
**Evidence:** a "same question, different schema" table showing the agent answers
correctly on both while the baseline (tuned to ERP keywords) collapses on POS.
**Metric to watch:** accuracy on ERP vs POS for the shared question set.

---

## 5a. How to run each stage (actual commands)

The harness scores every stage on the same 12 cases and ground truth.

```bash
python -m data.erp_database                    # build the seeded ERP database
python -m eval.ground_truth --schema erp       # verified answers -> ground_truth.json

python -m eval.evaluate --runner baseline      # keyword baseline (no API key needed)
python -m eval.evaluate --runner llm_baseline  # plain LLM chain      (needs API key)
python -m eval.evaluate --runner it1           # + schema context     (needs API key)
python -m eval.evaluate --runner it2           # + read-only validation
python -m eval.evaluate --runner it3           # + result verification
python -m eval.evaluate --runner it4           # + self-correction
python -m eval.evaluate --runner final         # full agent (+ business analysis)
```

Generalization run against the second schema (Iteration 6, POS):

```bash
python -m data.pos_database                                  # build seeded POS DB
python -m eval.ground_truth --schema pos                     # POS ground truth
python -m eval.evaluate --runner baseline --schema-id pos    # ERP-tuned baseline (collapses)
python -m eval.evaluate --runner final --schema-id pos       # full agent on POS (needs key)
```

**Generalization evidence already captured (no key needed):** the keyword
baseline scores 25.0% on ERP but only 8.3% on POS, because its canned SQL is tied
to ERP table names. The hypothesis to confirm with the LLM agent: the
schema-aware `final` agent holds high accuracy on *both* schemas by reading the
schema + business context, proving it understands the question rather than one
schema.

Each run writes `results_<runner>.json` and `results_<runner>.md`. The accuracy
delta between consecutive runners isolates that iteration's contribution.

---

## 6. Build order (to always have a submittable project)

1. Rotate the OpenAI key (user action) — unblocks the agent runner.
2. Capture the **LLM baseline** number (`--runner agent`, current agent).
3. Iteration 1 (schema context) -> re-evaluate -> changelog entry.
4. Iteration 3 (result verification) -> re-evaluate -> changelog entry.
   (Do the star early; if time runs short it is the most important improvement.)
5. Iteration 4 (self-correction) -> re-evaluate -> changelog entry.
6. Iteration 2 (SQL validation) -> fold in -> re-evaluate.
7. Iteration 5 (business analysis) -> polish End-to-End Quality.
8. Iteration 6 (POS generalization) -> the generalization proof.
9. Final combined run on all schemas; write reproduction guide + record video.

Rule: never start breadth (more schemas) before there is one complete,
measured end-to-end result. Working baseline first, generalization second.

---

## 7. Improvement changelog (fill with real numbers as we go)

| Stage | What we tried and why | Evidence | Decision / learning |
|-------|-----------------------|----------|---------------------|
| Baseline (keyword) | Keyword-to-SQL, no context/verification | ERP 25.0% acc / 41.7% SQL valid; POS 8.3% acc / 7 errors (12 cases each) | Established starting point; baseline does NOT generalize to a second schema |
| Baseline (LLM) | Single LangChain chain, schema only | TBD | TBD |
| Iteration 1 | Added schema discovery + business context | TBD | TBD |
| Iteration 2 | Added SQL validation (read-only, dry-run) | TBD | TBD |
| Iteration 3 | Added result verification | TBD | TBD |
| Iteration 4 | Added self-correction loop | TBD | TBD |
| Iteration 5 | Added business-analysis output | TBD | TBD |
| Iteration 6 | Ran same questions on POS schema | TBD | TBD |
| Final | Combined the changes that worked | TBD | Main contribution |

---

## 8. Mapping to judging criteria (100 pts)

| Criterion | Pts | How this strategy scores it |
|-----------|-----|-----------------------------|
| Problem & User Value | 15 | Clear non-technical user + IT-bottleneck framing (Section 2) |
| Agent Solution & Engineering | 30 | Purposeful capabilities: schema context, validation, verification, self-correction, and generalization — each justified and measured |
| End to End Quality | 20 | Business-analysis layer + evidence-backed answers (Iteration 5) |
| Measured Improvement | 15 | Same-harness baseline-vs-final deltas per iteration (Section 7) |
| Reproducibility | 15 | Seeded fixed-window DBs, ground truth from data, exact commands |
| Hot Take / Insights | 5 | "Understands the question or memorized one schema?" answered with ERP-vs-POS evidence |

---

## 9. Known risks and guardrails

- **Scope creep:** three schemas before a working baseline. Mitigation: build
  order in Section 6, two schemas is enough to prove generalization.
- **Ground-truth cost per schema:** reuse the same business questions across
  schemas rather than authoring new ones.
- **Weak eval case (Q09):** "customers who bought Displays" resolves to all 6
  customers — a poor discriminator. Consider replacing with a more selective join.
- **Cost/latency of self-correction:** cap retries; log them for the metric.
- **Safety (ground rule #4):** the agent must be read-only. Enforce SELECT-only
  in the validator so it cannot mutate a business database.
