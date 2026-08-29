# AI Data Analyst Agent for Business Databases

**A self-verifying agent that turns plain-language business questions into
verified analysis over a real database — and adapts to different schemas instead
of memorizing one.**

Ask *"Which branch had the highest revenue growth from June to July?"* and get a
verified, business-readable answer with the SQL and data as evidence — whether the
data lives in an ERP schema or a completely different point-of-sale schema. Or ask
*"Can our ERP measure customer churn?"* and get a schema-grounded assessment of
what the database can and cannot support.

**Live app:** deployed on Streamlit Community Cloud · **Repo:** github.com/HSN-LUCA/logx-agent

---

## Problem

Non-technical business users — an operations lead, a finance analyst, a sales
manager — need answers that live inside a business database (ERP, POS, CRM,
accounting, inventory) but **cannot write SQL**. Today every ad-hoc question
becomes a ticket to the data team; the user waits, and the first query often
misses the intent. The gap is between a *business question* and a *correct,
trustworthy result*. The hard part isn't generating *some* SQL — it's generating
SQL that is **correct**, and knowing when it isn't.

## Solution

An **AI Data Analyst Agent** that:

1. **Discovers the schema** of whatever database it's connected to, at runtime.
2. **Translates natural language into verified analysis** — generating SQL,
   validating it as read-only, executing it, and checking the result actually
   answers the question.
3. **Handles complex questions through planning** — decomposing multi-step
   questions into simple sub-queries and computing the answer deterministically.
4. **Identifies capability gaps** — telling a stakeholder whether the database can
   support a capability (e.g. churn), with evidence and a recommendation.

Guiding principle throughout: **the AI understands and plans; verified data
provides the facts; deterministic code computes and presents them.** The model is
never allowed to invent or rewrite a verified result.

## Measured results

Measured on a fixed 12-question evaluation set (model `gpt-3.5-turbo`, seeded
databases), fully reproducible from a clean clone (see
[docs/REPRODUCTION.md](docs/REPRODUCTION.md)).

### Data Analysis — accuracy across two different schemas

| Runner | ERP | POS |
|--------|:---:|:---:|
| Keyword baseline | 25.0% | 8.3% |
| Schema-aware agent (no planning) | 91.7% | 91.7% |
| **Final agent (with query planning)** | **100%** | **100%** |

The keyword baseline **collapses** on the second schema (25% → 8.3%) because its
SQL is tied to one set of table names. The final agent scores **100% on both** —
evidence that it understands the *question*, not one schema.

### Gap & Capability Analysis

| Metric | ERP | POS |
|--------|:---:|:---:|
| Capability-status accuracy (5 cases) | **5/5** | **5/5** |

Status decisions (SUPPORTED / PARTIALLY / NOT SUPPORTED) are grounded in the
discovered schema; adding this mode left the Data Analysis result **unchanged at
100%/100%**.

**The single biggest lever** was schema discovery + business context (LLM baseline
58% → 92%). **Query planning** closed the last gap (92% → 100%). Full
iteration-by-iteration evidence is in the [Improvement Changelog](#improvement-changelog).

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
- A **read-only SQL guard**, an LLM **result-verification** step, a
  **self-correction** loop, and a **query planner** that decomposes multi-step
  questions and computes their answers deterministically.
- A reproducible **ERP database** (`data/erp_database.py`) and a structurally
  different **POS database** (`data/pos_database.py`) for the generalization test.
- A fixed **evaluation set** with verified ground truth and an **automated scoring
  harness** (`eval/`).
- A **Gap & Capability Analysis** mode (`src/gap_analysis.py`) that determines
  whether the connected database can support a business capability, grounded in
  the discovered schema (read-only; analysis only).

---

## Two modes

- **Data Analysis** — ask a business question, get a verified, evidence-backed
  answer (chart / table / value).
- **Gap & Capability Analysis** — ask whether the database can support a
  capability ("Can our ERP measure customer churn?"). The agent inspects the
  actual schema and reports what is available, what is missing, the evidence, the
  business impact, and a recommendation. It never modifies the database.

In Gap Analysis the LLM proposes the *data concepts a capability requires*, but
**deterministic code decides what actually exists** by matching those concepts
against the discovered schema. The model never asserts what the database
contains; availability is always grounded in real schema evidence.

---

## Architecture

The agent has two modes. A business question flows through the **Data Analysis**
pipeline; a capability question flows through **Gap Analysis**.

```
                 Data Analysis                              Gap Analysis
                 =============                              ============

   User question (business question)              Capability question
            |                                       ("Can we measure churn?")
            v                                                |
        AI Agent                                             v
            |                                         Schema Analysis
            v                                                |
     Schema Discovery                                        v
            |                                          Gap Detection
            v                                     (required data vs. schema,
      Query Planning                              decided deterministically)
      (SIMPLE / COMPLEX)                                     |
            |                                                v
            v                                            Evidence
     SQL Generation (LLM)                          (real tables / columns)
            |                                                |
            v                                                v
   Read-only Validation                             Recommendation
      (SELECT-only guard)                        (impact + what to add)
            |
            v
        Execution
            |
            v
    Result Verification
   (does it answer the question?)
            |
            v
   Answer / Visualization
   (verified value, table or chart)
```

**Complex questions** (e.g. "which product declined for three months while stock
rose?") take a branch inside Query Planning: the agent decomposes them into simple
sub-queries, runs each through the pipeline, collects the **verified data frames**,
and computes the final answer in **deterministic Python** — never letting the LLM
synthesize the result.

Every pipeline step is a toggleable flag on `AnalystAgent`, so the evaluation
harness can turn capabilities on cumulatively and measure each one's contribution.

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
| Iteration 5a | Business-analysis output via **LLM rephrasing** of the answer | 75.0% (9/12) | **Removed.** Rephrasing into prose *dropped* the exact values on Q9 and Q10 that were previously correct. A quality feature that silently hurt correctness. |
| Iteration 5b | Business presentation via a **deterministic formatter** that wraps the exact verified values in readable text | **91.7% (11/12)** | **Kept.** Human-friendly output with zero accuracy loss. Presentation formats around the verified value; it never replaces it. |
| Iteration 6 | Same questions against the POS schema | **91.7% (11/12)** | **Generalization confirmed.** Identical accuracy to ERP on a schema with different table/column names and no category table. |
| Iteration 7 | Query planning: route multi-step questions to sub-queries + **deterministic** computation over verified data frames | **100% (12/12)** | **Kept.** Solved the challenge case (Q12). The single-query agent produced invalid window-function SQL; decomposing into simple sub-queries and computing the trend in Python fixes it with zero execution errors. |
| Final | Grounding + validation + verification + self-correction + deterministic presentation + query planning | ERP **100%**, POS **100%** | Main contribution: schema-aware grounding that generalizes across schemas, human-readable output that preserves exact values, and decomposition for multi-step questions. |
| Iteration 8 | Added Gap & Capability Analysis (separate mode): LLM proposes required data concepts, deterministic code matches them to the discovered schema to decide SUPPORTED / PARTIALLY / NOT SUPPORTED | Gap status accuracy **5/5** on both ERP and POS; Data Analysis result **unchanged at 100%/100%** | Additive and read-only. Extends the project from answering questions to assessing what a database *cannot* yet answer, with schema-grounded evidence. |

### Headline comparison

| Runner | ERP accuracy | POS accuracy |
|--------|:-----------:|:------------:|
| Keyword baseline | 25.0% | 8.3% |
| Schema-aware agent (no planning) | 91.7% | 91.7% |
| Final agent (with planning) | **100%** | **100%** |

**Main failure mode + hot take.** Two findings the evidence forced on us:

1. *Generalization is real, and it comes from grounding, not cleverness.* The
   keyword baseline collapses from 25% to 8.3% when the schema changes; the
   schema-aware agent holds 91.7% on both. A system that encodes one schema's
   structure breaks the moment the schema changes; one that reads the schema at
   runtime does not.
2. *Never let a language model rewrite a verified answer.* An LLM
   business-analysis layer rephrased verified results into prose and dropped the
   exact figures on two questions (Q9's customer list, Q10's -43.7%), taking
   accuracy from 91.7% to 75.0%. Replacing it with a **deterministic formatter**
   that wraps the exact verified value in readable text restored 91.7% while
   keeping the human-friendly output. The rule: a step placed *after* a verified
   result must preserve that value and format around it, never regenerate it.
3. *Hard questions need decomposition, not a cleverer single query.* The
   challenge case (Q12: three consecutive months of decline while stock rises)
   was the only miss at 91.7%. The single-query agent kept producing invalid
   `LAG()`-in-`HAVING` SQL that the database rejected, and self-correction could
   not recover because every retry was another variant of the same over-complex
   query. Routing it to a planner that asks two simple sub-questions (monthly
   units, monthly stock) and computes the trend deterministically in Python
   solved it and took the agent to 100% on both schemas. The same value-preserving
   principle as (2): reason over verified data in code, not in the model.

---

## Project layout

| Path | Role |
|------|------|
| `app.py` | Streamlit UI (run from root) |
| `paths.py` | Central path resolution (databases, artifacts) |
| `src/analyst_agent.py` | The self-verifying, schema-agnostic agent (all iterations) |
| `src/schema_tools.py` | Runtime schema discovery (tables, columns, keys, samples) |
| `src/business_context.py` | Per-schema business glossary/notes |
| `src/query_planner.py` | Decomposition patterns + deterministic computation for multi-step questions |
| `src/gap_analysis.py` | Gap & Capability Analysis (schema-grounded, read-only) |
| `eval/gap_questions.py` / `eval/gap_evaluate.py` | Separate Gap Analysis evaluation set + harness |
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
  modify data, matching the hackathon's controlled-action rule. Gap Analysis is
  read-only by construction (it inspects schema metadata and executes no SQL).
- All data is **synthetic and seeded**; no private data is used.
- Keep credentials in `.env` (gitignored). Never commit API keys.

## Known limitations / future improvements

- **Gap Analysis keyword coverage.** In Gap Analysis the LLM proposes the data
  concepts a capability requires, each with keyword hints; deterministic code
  then matches those hints against the discovered schema. The deterministic
  matcher is accurate (5/5 on the curated evaluation for both schemas), but the
  LLM's free-form keyword hints can be narrower than ideal, occasionally causing
  a SUPPORTED capability to be reported as PARTIALLY SUPPORTED. The status
  remains schema-grounded and never invents data; it is simply conservative. A
  future improvement would feed the schema's own vocabulary into the concept step
  to widen keyword coverage. This is documented rather than patched to avoid
  scope creep.
- **Large schemas.** Very large real schemas (hundreds of tables) would benefit
  from schema-scoping (feeding only relevant tables to the LLM) to stay within
  context limits.
- **Business context is per-schema.** A brand-new database works out of the box on
  structure; domain-specific accuracy improves with a short business-context note.
