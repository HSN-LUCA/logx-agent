"""Iteration 8: Gap & Capability Analysis (additive, read-only).

Given a business capability question ("Can our ERP measure customer churn?"),
this module determines whether the CONNECTED database can support it, grounded
in the actually-discovered schema.

Division of responsibility (matches the project's core principle):

    LLM   : interprets the business capability and proposes the *required data
            concepts* (e.g. "customer identity", "activity/status history over
            time", "explicit churn flag"), each with keyword hints. The LLM does
            NOT assert what the database contains.

    CODE  : deterministically matches each required concept against the
            discovered schema (tables + columns). Availability is decided here,
            from real schema evidence -- never invented by the model.

    LLM   : writes the business-impact explanation and recommendation, using
            only the deterministic availability facts as input.

This is read-only by construction: it inspects already-discovered schema
metadata and never builds or executes SQL. There is no code path that can
modify the database.
"""

import json
import re
from dataclasses import dataclass, field

from dotenv import load_dotenv

from src.schema_tools import discover_schema, render_schema_summary
from src.business_context import render_business_context

load_dotenv()


# Status vocabulary.
SUPPORTED = "SUPPORTED"
PARTIALLY = "PARTIALLY SUPPORTED"
NOT_SUPPORTED = "NOT SUPPORTED"
UNCERTAIN = "UNCERTAIN"


@dataclass
class RequiredConcept:
    """A data concept the capability needs, proposed by the LLM."""
    name: str
    keywords: list          # hints used to search the schema
    essential: bool = True  # essential vs. nice-to-have

    # Filled deterministically by the matcher:
    available: bool = False
    evidence: list = field(default_factory=list)  # ["table.column", ...]


@dataclass
class GapReport:
    capability: str
    status: str
    available: list = field(default_factory=list)     # [{name, evidence}]
    missing: list = field(default_factory=list)        # [{name, essential}]
    evidence_summary: str = ""
    business_impact: str = ""
    recommendation: str = ""
    confidence: str = "Medium"
    facts: list = field(default_factory=list)          # raw schema facts used
    error: str = ""


# --------------------------------------------------------------------------- #
# Deterministic schema matching
# --------------------------------------------------------------------------- #
def _schema_tokens(schema):
    """Flatten the discovered schema into a searchable list of (table, column,
    'table.column') tuples plus the table names themselves."""
    entries = []
    for table, info in schema["tables"].items():
        entries.append((table, None, table))
        for col in info["columns"]:
            entries.append((table, col["name"], f"{table}.{col['name']}"))
    return entries


def _match_concept(concept, schema_entries):
    """Deterministically decide whether a required concept is present in the
    schema. A concept is available if any of its keywords appears as a substring
    of a table or column name. Returns (available, evidence_list)."""
    evidence = []
    for kw in concept.keywords:
        kw_l = kw.lower().strip()
        if not kw_l:
            continue
        for table, column, label in schema_entries:
            target = (column or table).lower()
            # word-ish containment either direction (handles plural/singular).
            if kw_l in target or target in kw_l:
                if label not in evidence:
                    evidence.append(label)
    return (len(evidence) > 0, evidence)


def _decide_status(concepts):
    """Deterministic status from concept availability.

    - all essential available            -> SUPPORTED
    - some (but not all) essential avail. -> PARTIALLY SUPPORTED
    - no essential available              -> NOT SUPPORTED
    """
    essential = [c for c in concepts if c.essential]
    if not essential:
        return UNCERTAIN
    avail = [c for c in essential if c.available]
    if len(avail) == len(essential):
        return SUPPORTED
    if len(avail) == 0:
        return NOT_SUPPORTED
    return PARTIALLY


# --------------------------------------------------------------------------- #
# GapAnalyzer
# --------------------------------------------------------------------------- #
class GapAnalyzer:
    def __init__(self, engine, schema_id="", llm=None):
        self.engine = engine
        self.schema_id = schema_id
        self.schema = discover_schema(engine)
        self.schema_summary = render_schema_summary(self.schema, include_samples=False)
        self.context_text = render_business_context(schema_id) if schema_id else ""
        self.schema_entries = _schema_tokens(self.schema)
        self._llm = llm

    @property
    def llm(self):
        if self._llm is None:
            import os
            from langchain_openai import ChatOpenAI

            self._llm = ChatOpenAI(
                temperature=0,
                model=os.getenv("OPENAI_MODEL", "gpt-3.5-turbo"),
                openai_api_key=os.getenv("OPENAI_API_KEY"),
            )
        return self._llm

    def _chat(self, prompt):
        resp = self.llm.invoke(prompt)
        return getattr(resp, "content", str(resp))

    # ---- step 1: LLM proposes required concepts (not DB facts) ----------- #
    def _required_concepts_prompt(self, capability):
        return (
            "You are a data architect. A business stakeholder asks whether a "
            "database can support a capability. List the DATA CONCEPTS that such "
            "a capability would REQUIRE in general -- do NOT look at or assume any "
            "specific database. For each concept give 3-6 lowercase keyword hints "
            "(column/table name fragments) that would indicate its presence, and "
            "whether it is essential.\n"
            "Return ONLY JSON: a list of objects with keys "
            '"name", "keywords" (list), "essential" (true/false). '
            "No markdown, no prose.\n\n"
            f"CAPABILITY: {capability}\n\nJSON:"
        )

    def _parse_concepts(self, raw):
        text = raw.strip()
        text = re.sub(r"^```(?:json)?", "", text, flags=re.IGNORECASE).strip()
        text = re.sub(r"```$", "", text).strip()
        m = re.search(r"\[.*\]", text, re.DOTALL)
        if m:
            text = m.group(0)
        data = json.loads(text)
        concepts = []
        for item in data:
            concepts.append(RequiredConcept(
                name=str(item.get("name", "")).strip(),
                keywords=[str(k) for k in item.get("keywords", [])],
                essential=bool(item.get("essential", True)),
            ))
        return [c for c in concepts if c.name and c.keywords]

    # ---- step 3: LLM writes impact + recommendation from FACTS ----------- #
    def _narrative_prompt(self, capability, status, available, missing):
        avail_txt = "; ".join(
            f"{a['name']} (evidence: {', '.join(a['evidence'])})" for a in available
        ) or "none"
        miss_txt = "; ".join(m["name"] for m in missing) or "none"
        return (
            "You are advising a business stakeholder. Based ONLY on the facts "
            "below (which were determined deterministically from the real database "
            "schema), write a short business impact and a practical recommendation. "
            "Do NOT claim any data exists beyond the facts. Do NOT present the "
            "recommendation as existing functionality.\n"
            "Return ONLY JSON with keys "
            '"business_impact" (1-2 sentences), "recommendation" (1-2 sentences), '
            '"confidence" ("High"/"Medium"/"Low"). No markdown.\n\n'
            f"CAPABILITY: {capability}\n"
            f"STATUS: {status}\n"
            f"AVAILABLE (facts from schema): {avail_txt}\n"
            f"MISSING (not found in schema): {miss_txt}\n\nJSON:"
        )

    def _parse_narrative(self, raw):
        text = raw.strip()
        text = re.sub(r"^```(?:json)?", "", text, flags=re.IGNORECASE).strip()
        text = re.sub(r"```$", "", text).strip()
        m = re.search(r"\{.*\}", text, re.DOTALL)
        if m:
            text = m.group(0)
        return json.loads(text)

    # ---- orchestration --------------------------------------------------- #
    def analyze(self, capability):
        # Step 1: LLM proposes required concepts (schema-independent).
        try:
            concepts = self._parse_concepts(self._chat(self._required_concepts_prompt(capability)))
        except Exception as e:
            return GapReport(
                capability=capability, status=UNCERTAIN,
                evidence_summary="Could not determine the required data concepts.",
                business_impact="", recommendation="",
                confidence="Low", error=f"concept parsing failed: {e}",
            )

        if not concepts:
            return GapReport(
                capability=capability, status=UNCERTAIN,
                evidence_summary="No required data concepts could be identified.",
                confidence="Low",
            )

        # Step 2: DETERMINISTIC matching against the discovered schema.
        for c in concepts:
            c.available, c.evidence = _match_concept(c, self.schema_entries)

        status = _decide_status(concepts)

        available = [{"name": c.name, "evidence": c.evidence}
                     for c in concepts if c.available]
        missing = [{"name": c.name, "essential": c.essential}
                   for c in concepts if not c.available]

        facts = [f"{c.name}: {'FOUND ' + ', '.join(c.evidence) if c.available else 'NOT FOUND'}"
                 for c in concepts]

        # Step 3: LLM writes narrative from the deterministic facts only.
        impact, recommendation, confidence = "", "", "Medium"
        try:
            nar = self._parse_narrative(
                self._chat(self._narrative_prompt(capability, status, available, missing))
            )
            impact = str(nar.get("business_impact", "")).strip()
            recommendation = str(nar.get("recommendation", "")).strip()
            confidence = str(nar.get("confidence", "Medium")).strip() or "Medium"
        except Exception:
            # Narrative is advisory; a parse failure does not invalidate the
            # deterministic status/evidence. Provide a safe generic note.
            impact = ("The database's support for this capability is summarized "
                      "by the status and evidence above.")
            recommendation = ("Review the missing concepts and consider adding the "
                              "corresponding data before relying on this capability.")
            confidence = "Medium"

        evidence_summary = (
            f"{len([c for c in concepts if c.available])} of {len(concepts)} required "
            f"concept(s) were found in the discovered schema."
        )

        return GapReport(
            capability=capability, status=status,
            available=available, missing=missing,
            evidence_summary=evidence_summary,
            business_impact=impact, recommendation=recommendation,
            confidence=confidence, facts=facts,
        )
