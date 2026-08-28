# AI Data Analyst Agent for Business Databases

**A self-verifying agent that answers natural-language business questions over a
relational database, and adapts to different schemas instead of memorizing one.**

Ask *"Which branch had the highest revenue growth from June to July?"* and get a
verified, business-readable answer with the SQL and data source as evidence, whether
the data lives in an ERP schema or a completely different point-of-sale schema.

---

## The user and the bottleneck

**Who has the problem.** A non-technical business user, an operations lead, a
finance analyst, a sales manager, who needs answers that live inside a business
database (ERP, POS, CRM, accounting, inventory) but cannot write SQL.

**The bottleneck today.** Every ad-hoc question becomes a ticket to IT or the data
team. The user waits, and often the first query misses the intent, so it iterates.
The gap is between a *business question* and a *correct, trustworthy SQL result*.

**Why solving it matters.** Faster decisions, fewer analyst hours spent on one-off
pulls, and answers a manager can trust without reading SQL. The hard part is not
generating *some* SQL, it is generating SQL that is *correct* and knowing when it
is not.

---

## What existed before vs. what was added

This project started as **LogX**, a basic Streamlit natural-language-to-SQL demo
(single LangChain `SQLDatabaseChain` over a two-table SQLite database, with voice
input and text-to-speech). That original app is the honest starting point.

**Added for this hackathon:**

- A schema-agnostic agent (`src/analyst_agent.py`) with individually toggleable
  capabilities so each improvement can be measured on its own.
- Runtime **schema discovery** (`src/schema_tools.py`) and **business context**
  (`src/business_context.py`) so the agent adapts to any supported schema.
- A **read-only SQL guard**, an LLM **result-verification** step, and a
  **self-correction** loop.
- A reproducible **ERP database** (`data/erp_database.py`) and a structurally
  different **POS database** (`data/pos_database.py`) for the generalization test.
- A fixed **evaluation set** with verified ground truth and an **automated scoring
  harness** (`eval/`).

---

## How it works

```
question
  -> schema discovery + business context      (adapt to this database)
  -> SQL generation (LLM)
  -> read-only validation                     (SELECT-only guard)
  -> execute
  -> result verification                      (does this answer the question?)
  -> self-correction on failure (capped)       (diagnose + retry)
  -> business-analysis formatting             (headline + evidence)
  -> answer + SQL + data source
```

Each bracketed step is a flag on `AnalystAgent`, so the evaluation harness can run
the agent with iterations turned on cumulatively and measure the contribution of
each one.

### Why it is "agentic" and not just a text-to-SQL chatbot

The agent does not just translate a question to SQL and hope. It **grounds** itself
in the live schema, **validates** what it wrote, **verifies** that the result
actually answers the question, and **recovers** when it does not. Verification and
self-correction are the difference between "produced some SQL" and "produced a
trustworthy answer."

---

## The generalization idea

The reframed goal is not "an ERP tool" but a **data analyst for business
databases**. The claim is deliberately bounded and testable:

> Adapts dynamically to supported relational schemas via schema discovery and
> business context, demonstrated across two structurally different schemas.

The same business questions are asked against two databases with different table
and column names (ERP `invoices/invoice_lines/line_total` vs. POS
`sales_receipts/basket_items/amount`, and POS has no category table at all). If the
agent answers correctly on both, it understands the *question*, not one schema.

---

## Evaluation

- **Same 12 questions, same scoring, every runner** (`eval/evaluate.py`).
- **Categories:** simple, aggregation, ranking, multi-table, comparison, and one
  engineered **challenge case** (a product with three consecutive months of
  declining sales while its stock rises).
- **Primary metric:** answer accuracy. **Secondary:** SQL validity, execution
  errors, self-corrections, response time.
- **Ground truth cannot drift:** every expected answer is computed from the
  database itself (`eval/ground_truth.py`).
- **Reproducible:** databases are seeded and use a fixed date window (2026-01 to
  2026-08), so the numbers are identical on any machine.

---

## Improvement Changelog

All numbers below are measured on the fixed 12-question set (model
`gpt-3.5-turbo`, seeded databases) and reproduced by the commands in
[docs/REPRODUCTION.md](docs/REPRODUCTION.md). Accuracy is answer accuracy.

| Stage | What was tried and why | Evidence (ERP) | Decision / learning |
|-------|------------------------|----------------|---------------------|
| Baseline (keyword) | Keyword-to-SQL, no schema context or verification | 25.0% (3/12); POS 8.3% | Starting point. Does **not** generalize: SQL tied to ERP table names collapses on POS. |
| Baseline (LLM) | Single LangChain chain, schema passed, no verification | 58.3% (7/12) | Big jump from keyword, but a third of answers still wrong. Kept as the fair LLM baseline. |
| Iteration 1 | Added schema discovery + business context | **91.7% (11/12)** | **The decisive lever** (+33.4 pts over LLM baseline). Grounding in the real schema + a business glossary fixes almost everything. Kept. |
| Iteration 2 | Added read-only SQL validation (SELECT-only, single statement) | 91.7% (11/12) | No accuracy change; enforces the read-only safety guarantee. Kept for safety, not for score. |
| Iteration 3 | Added result verification | 91.7% (11/12) | No accuracy change on this set: the agent was already right where it was confident. Kept; its value shows on failures, not on an already-correct set. |
| Iteration 4 | Added self-correction loop (diagnose error, retry, capped) | 91.7% (11/12) | No accuracy change here. Only Q12 (the challenge case) remains wrong, and it is a *reasoning* gap, not an error the retry can fix. Kept. |
| Iteration 5 | Added business-analysis output (prose answer) | 75.0% (9/12) | **Removed / revised.** Rephrasing into prose *dropped* the exact values on Q9 and Q10 that were previously correct. A quality feature that hurt measured accuracy. |
| Iteration 6 | Same questions against the POS schema | it4: **91.7% (11/12)** | **Generalization confirmed.** Identical accuracy to ERP on a schema with different table/column names and no category table. |
| Final | Best configuration = through Iteration 4 (no prose layer) | ERP 91.7%, POS 91.7% | Main contribution: schema-aware grounding + safety + verification, generalizing across schemas. |

### Headline comparison

| Runner | ERP accuracy | POS accuracy |
|--------|:-----------:|:------------:|
| Keyword baseline | 25.0% | 8.3% |
| Schema-aware agent (it4) | 91.7% | 91.7% |

**Main failure mode + hot take.** Two findings the evidence forced on us:

1. *Generalization is real, and it comes from grounding, not cleverness.* The
   keyword baseline collapses from 25% to 8.3% when the schema changes; the
   schema-aware agent holds 91.7% on both. A system that encodes one schema's
   structure breaks the moment the schema changes; one that reads the schema at
   runtime does not.
2. *A "nicer output" step can silently lower correctness.* The business-analysis
   layer rephrased verified answers into prose and dropped the exact figures on
   two questions (Q9's customer list, Q10's -43.7%), taking accuracy from 91.7%
   down to 75.0%. Lesson for building reliable agents: any step placed *after*
   a verified result must preserve the verified value, format around it, never
   replace it. We would re-add business framing only as an addition to the exact
   answer, not a rewrite of it.

The one case even the best config misses is Q12, the challenge case (three
consecutive months of decline while stock rises). The agent does not reliably
express that multi-step temporal reasoning in a single SQL query, which points at
the next iteration: query planning / decomposition for multi-step questions.

---

## Project layout

| Path | Role |
|------|------|
| `app.py` | Streamlit UI (run from root) |
| `paths.py` | Central path resolution (databases, artifacts) |
| `src/analyst_agent.py` | The self-verifying, schema-agnostic agent (all iterations) |
| `src/schema_tools.py` | Runtime schema discovery (tables, columns, keys, samples) |
| `src/business_context.py` | Per-schema business glossary/notes |
| `src/ai_agent.py` | Original single-chain agent, used as the plain-LLM baseline |
| `data/erp_database.py` / `data/pos_database.py` | Seeded, reproducible demo databases |
| `eval/eval_questions.py` / `eval/eval_questions_pos.py` | The fixed question sets |
| `eval/ground_truth.py` | Computes verified answers from the databases |
| `eval/evaluate.py` | Automated scoring harness (all runners, both schemas) |
| `docs/STRATEGY.md` | The build strategy and iteration roadmap |
| `docs/REPRODUCTION.md` | Clean-environment reproduction guide |

---

## Quick start

Run all commands from the project root. See
[docs/REPRODUCTION.md](docs/REPRODUCTION.md) for the full walkthrough.

```bash
pip install -r requirements.txt
python -m data.erp_database && python -m eval.ground_truth --schema erp
python -m eval.evaluate --runner baseline     # works with no API key
# add your OpenAI key to .env, then:
python -m eval.evaluate --runner final        # the full agent
```

## Safety and ground rules

- The agent is **read-only**: a SELECT-only guard blocks any statement that could
  modify data, matching the hackathon's controlled-action rule.
- All data is **synthetic and seeded**; no private data is used.
- Keep credentials in `.env` (gitignored). Never commit API keys.
