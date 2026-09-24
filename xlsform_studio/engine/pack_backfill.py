"""Domain-pack bound backfill for AI-authored forms.

Domain rule packs (``knowledge/packs/*.yaml``) carry realistic value bounds
- MUAC in mm, praziquantel tablets per dose, eggs per gram - that the
deterministic rule engine applies while compiling.  The AI-first author
(:mod:`xlsform_studio.ai.form_author`) drafts constraints itself and never
reads the packs, so without this step a pack chosen in the UI or via
``--packs`` would have no effect on the shipped pipeline.

This step runs after AI authoring and fills gaps only:

* a question is considered only when its type is numeric for the matching
  template (the template's ``applies_to``) and it has **no** constraint -
  anything the AI wrote, even a looser bound, is kept;
* only the loaded packs' own templates are used, never the neutral rules,
  so a run with no packs is unchanged;
* every bound applied is recorded as a question decision (and so in the
  assumption log) naming the pack, plus one summary note for the run.

Example
-------
>>> PackBackfill(KnowledgeBase.load(packs=["ntd"])).apply(qn)  # doctest: +SKIP
['[Domain pack] Applied 1 pack bound(s) the AI left unbounded: ...']
"""

from __future__ import annotations

from typing import List

from ..models import Questionnaire
from .constraint_engine import ConstraintEngine
from .knowledge_base import KnowledgeBase


class PackBackfill:
    """Fill AI-unbounded numeric questions from the loaded domain packs."""

    def __init__(self, knowledge: KnowledgeBase) -> None:
        self.templates = knowledge.pack_constraints

    def apply(self, questionnaire: Questionnaire) -> List[str]:
        """Apply pack bounds in place; return the run's summary notes."""
        if not self.templates:
            return []
        filled: List[str] = []
        for q in questionnaire.questions:
            if q.constraint:
                continue  # the AI's constraint always wins
            base_type = q.base_type
            # Match the source wording first, as the rule engine does; fall
            # back to the AI's label if the parser captured none.
            label = (q.raw_label or q.label or "").lower()
            for pack, tpl in self.templates:
                applies = tpl.get("applies_to", [])
                if not applies or base_type not in applies:
                    continue
                if not ConstraintEngine._matches(label, tpl.get("match", [])):
                    continue
                q.constraint = tpl["constraint"]
                q.constraint_message = tpl.get("message", "")
                q.add_decision(
                    "constraint", q.constraint, "medium",
                    f"Bound from the '{pack}' domain pack "
                    f"({', '.join(tpl['match'])}); the AI left this "
                    f"{base_type} question unbounded. Please review.")
                filled.append(f"{q.name} ({pack})")
                break
        if not filled:
            return []
        return [f"[Domain pack] Applied {len(filled)} pack bound(s) the AI "
                f"left unbounded: {', '.join(filled)}."]
