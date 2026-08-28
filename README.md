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

Baseline numbers are measured and final. Rows marked **TBD** require an OpenAI API
key and are produced by the commands in [docs/REPRODUCTION.md](docs/REPRODUCTION.md).

| Stage | What was tried and why | Evidence | Decision / learning |
|-------|------------------------|----------|---------------------|
| Baseline (keyword) | Keyword-to-SQL, no schema context or verification | **ERP 25.0%** (3/12), 41.7% SQL valid; **POS 8.3%** (1/12), 7 exec errors | Starting point. The baseline does **not** generalize: SQL tied to ERP table names collapses on POS. |
| Baseline (LLM) | Single LangChain chain, schema passed, no verification | TBD | TBD |
| Iteration 1 | Added schema discovery + business context | TBD | TBD |
| Iteration 2 | Added read-only SQL validation (SELECT-only, single statement) | TBD | TBD |
| Iteration 3 | Added result verification (does the result answer the question?) | TBD | TBD |
| Iteration 4 | Added self-correction loop (diagnose error, retry, capped) | TBD | TBD |
| Iteration 5 | Added business-analysis output with evidence | TBD | TBD |
| Iteration 6 | Ran the same questions against the POS schema | TBD | TBD |
| Final | Full agent on ERP and POS | TBD | Main contribution |

**Main failure mode (hot take placeholder):** the keyword baseline already shows
the failure this project targets, a system that encodes one schema's structure
breaks the moment the schema changes. The open question the LLM runs will answer:
does result verification actually catch confidently-wrong answers, or does the
verifier rubber-stamp them? Fill this in with the observed evidence after running.

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
