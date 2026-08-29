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
# Domain-general synonym groups. Business databases name the same concept
# differently (a customer is a "shopper" in POS, an invoice is a "receipt").
# When any term in a group is searched, all terms in the group are tried, so a
# concept keyword like "customer" also matches a "shoppers" table. This is a
# small, general business vocabulary -- NOT specific to any one capability.
_SYNONYM_GROUPS = [
    {"customer", "shopper", "client", "buyer", "account"},
    {"invoice", "receipt", "transaction", "sale", "order", "bill"},
    {"product", "item", "sku", "article", "goods"},
    {"branch", "outlet", "store", "location", "shop"},
    {"supplier", "vendor"},
    {"category", "dept", "department", "class", "type"},
    {"quantity", "qty", "units", "amount", "volume"},
    {"stock", "inventory", "onhand"},
    {"date", "time", "timestamp", "period", "day", "month"},
    {"revenue", "amount", "total", "value", "price", "sales"},
    {"status", "state", "flag", "lifecycle", "stage"},
]

# Very common words that must not be used as match terms (they would match too
# much or nothing meaningful).
_STOPWORDS = {
    "record", "records", "history", "data", "information", "field", "fields",
    "details", "id", "identifier", "the", "a", "an", "of", "and", "or", "per",
    "value", "values", "list", "entity", "entities",
}


def _expand_terms(term):
    """Return the term plus any synonyms from the vocabulary groups."""
    t = term.lower().strip()
    out = {t}
    for group in _SYNONYM_GROUPS:
        if t in group:
            out |= group
    return out


def _tokenize_name(name):
    """Split a concept name into meaningful lowercase tokens (drop stopwords)."""
    raw = re.split(r"[^a-zA-Z]+", name.lower())
    return [w for w in raw if w and w not in _STOPWORDS and len(w) > 2]


def _schema_tokens(schema):
    """Flatten the discovered schema into a searchable list of (table, column,
    'table.column') tuples plus the table names themselves."""
    entries = []
    for table, info in schema["tables"].items():
        entries.append((table, None, table))
        for col in info["columns"]:
            entries.append((table, col["name"], f"{table}.{col['name']}"))
    return entries


def _term_hits(term, schema_entries):
    """Evidence labels where `term` (or a synonym) matches a table/column name."""
    hits = []
    for search in _expand_terms(term):
        if len(search) <= 2 or search in _STOPWORDS:
            continue
        for table, column, label in schema_entries:
            target = (column or table).lower()
            if search in target or target in search:
                if label not in hits:
                    hits.append(label)
    return hits


# Generic entity nouns: they identify WHICH record a concept is about, but on
# their own do not prove a specific ATTRIBUTE exists.
_GENERIC_ENTITY_TERMS = {
    "customer", "shopper", "client", "buyer", "account",
    "product", "item", "sku",
    "branch", "outlet", "store",
    "supplier", "vendor",
}

# Attribute-signal words: when a concept is ABOUT one of these, a match on the
# generic entity alone is not enough -- an attribute-specific term must match a
# real column. This is what stops "Customer status field" from being marked
# available just because a customer table exists, while still letting entity
# concepts like "Customer records" or "Transaction history" match normally.
# These are general business-data attribute words, not tied to any capability.
_ATTRIBUTE_SIGNAL_TERMS = {
    "status", "state", "flag", "lifecycle", "stage", "churn", "cancelled",
    "active", "inactive", "activity", "delivery", "shipment", "performance",
    "rating", "score",
}


def _match_concept(concept, schema_entries):
    """Deterministically decide whether a required concept is present in the
    schema. Search terms come from BOTH the LLM keyword hints and the concept
    name tokens, each expanded through the domain-general synonym map.

    Two match modes, chosen deterministically from the concept's own words:

    * ATTRIBUTE concept (its name/keywords contain an attribute-signal word such
      as 'status', 'flag', 'activity', 'delivery'): requires a match on an
      attribute-specific term. A generic entity match alone is NOT enough. This
      prevents claiming e.g. a churn/status field exists just because a customer
      table exists.
    * ENTITY concept (everything else, e.g. 'Customer records', 'Transaction
      history'): any term match (including a generic entity, via synonyms) is
      sufficient.

    Availability is only ever asserted from actual schema evidence.
    Returns (available, evidence)."""
    kw_terms = {k.lower().strip() for k in concept.keywords if k and k.strip()}
    name_terms = set(_tokenize_name(concept.name))
    all_terms = kw_terms | name_terms

    is_attribute_concept = bool(all_terms & _ATTRIBUTE_SIGNAL_TERMS)

    if is_attribute_concept:
        # Only the attribute-signal terms count as proof for this concept.
        proof_terms = all_terms & _ATTRIBUTE_SIGNAL_TERMS
    else:
        # Entity/history concept: any term (generic or specific) is proof.
        proof_terms = all_terms

    evidence = []
    for term in proof_terms:
        for label in _term_hits(term, schema_entries):
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
            "database can support a capability. Identify the underlying DATA "
            "REQUIREMENTS: the kinds of business data a database would need to "
            "STORE to support this capability.\n"
            "\n"
            "Each requirement must be a business DATA ENTITY or DATA ATTRIBUTE "
            "(something that would appear as a table or column), for example: "
            "'Customer records', 'Order/transaction history', 'Delivery dates', "
            "'Product status field'.\n"
            "\n"
            "STRICT RULES:\n"
            "- Do NOT use the question's action or context words as requirements. "
            "Words like 'measure', 'track', 'calculate', 'analyze', 'support', "
            "'ERP', 'system', 'database', 'report' are NOT data requirements.\n"
            "- Do NOT restate the capability topic as a single word; express what "
            "data it needs. (E.g. for 'churn', the requirements are things like "
            "customer records, transaction/activity history, and a customer "
            "status/lifecycle or churn-classification field -- not the word "
            "'churn' by itself.)\n"
            "- Do NOT look at or assume any specific database.\n"
            "- Give 3-6 lowercase keyword hints per requirement that are plausible "
            "TABLE or COLUMN name fragments (e.g. 'customer', 'invoice', 'status', "
            "'order_date'), not English topic words.\n"
            "\n"
            "WORKED EXAMPLE (different domain, for shape only):\n"
            "Capability: 'Can we measure employee attendance?'\n"
            "[\n"
            '  {"name": "Employee records", "keywords": ["employee", "staff", "person"], "essential": true},\n'
            '  {"name": "Attendance/check-in events", "keywords": ["attendance", "check_in", "clock", "shift"], "essential": true},\n'
            '  {"name": "Event timestamps", "keywords": ["date", "time", "timestamp"], "essential": true}\n'
            "]\n"
            "\n"
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
