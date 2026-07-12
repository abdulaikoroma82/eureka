"""Choice-list normalization engine (deterministic; Module D9).

Purpose
-------
Documents routinely repeat the same answer scale under many questions
("Yes/No/Don't know" fifteen times, a satisfaction scale under every
service question). Compiling each occurrence into its own choice list
bloats the choices sheet and - worse - lets analysis treat identical
scales as different variables' domains.

This engine consolidates **exact duplicates only**: two lists merge when
their choices match in name, label and order, byte for byte. That
guarantee makes the merge provably safe - no question's answer domain
changes - so it can run automatically (and is logged per question in the
assumption log). Anything less than exact (same options reordered, one
option relabelled, an extra "Other") is *not* touched: the difference may
be deliberate, so the
:class:`~xlsform_studio.validation.consistency_validator.
ConsistencyValidator` flags those as near-identical for a human instead.

Inputs
------
A compiled :class:`~xlsform_studio.models.Questionnaire` (mutated in
place).

Outputs
-------
Notes describing every merge performed (empty when nothing merged).

Example
-------
>>> from xlsform_studio.models import (Choice, ChoiceList, Question,
...                                       Questionnaire)
>>> qn = Questionnaire(
...     questions=[Question(name="a", xlsform_type="select_one l1", list_name="l1"),
...                Question(name="b", xlsform_type="select_one l2", list_name="l2")],
...     choice_lists={"l1": ChoiceList("l1", [Choice("y", "Yes")]),
...                   "l2": ChoiceList("l2", [Choice("y", "Yes")])})
>>> notes = ChoiceNormalizer().normalize(qn)
>>> sorted(qn.choice_lists)
['l1']
>>> qn.questions[1].xlsform_type
'select_one l1'
"""

from __future__ import annotations

from typing import Dict, List, Tuple

from ..models import ChoiceList, Questionnaire


class ChoiceNormalizer:
    """Merge exactly-duplicate choice lists; leave everything else alone."""

    def normalize(self, questionnaire: Questionnaire) -> List[str]:
        canonical: Dict[Tuple, str] = {}       # fingerprint -> surviving list
        replaced: Dict[str, str] = {}          # dropped list -> survivor
        for list_name, cl in questionnaire.choice_lists.items():
            fp = self._fingerprint(cl)
            if fp in canonical:
                replaced[list_name] = canonical[fp]
            else:
                canonical[fp] = list_name

        if not replaced:
            return []

        notes: List[str] = []
        for q in questionnaire.questions:
            parts = (q.xlsform_type or "").split()
            if len(parts) >= 2 and parts[1] in replaced:
                survivor = replaced[parts[1]]
                q.xlsform_type = f"{parts[0]} {survivor}" + (
                    " " + " ".join(parts[2:]) if len(parts) > 2 else "")
                q.add_assumption(
                    f"Choice list '{parts[1]}' was identical to "
                    f"'{survivor}' and was consolidated into it (same "
                    f"options, same codes, same order - the answer domain "
                    f"is unchanged).")
            if q.list_name in replaced:
                q.list_name = replaced[q.list_name]

        for dropped, survivor in replaced.items():
            del questionnaire.choice_lists[dropped]
            notes.append(f"[choices] Consolidated duplicate choice list "
                        f"'{dropped}' into identical list '{survivor}'.")
        return notes

    @staticmethod
    def _fingerprint(cl: ChoiceList) -> Tuple:
        return tuple((c.name, c.label, tuple(sorted(c.extra.items())))
                     for c in cl.choices)
