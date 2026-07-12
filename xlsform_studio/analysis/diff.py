"""Questionnaire difference engine (deterministic; Module D3).

Purpose
-------
Compare two compiled questionnaires - typically last round's form and this
round's - and report exactly what changed, so review effort goes to the
delta instead of re-reading the whole instrument, and so longitudinal
analysts learn about renamed/retyped variables *before* their merge breaks.

Detected changes
----------------
* Added / removed questions (matched by variable name).
* **Renames** - a removed and an added question with the same label are
  reported as one rename, not two changes.
* Per-question field changes: label, type, required, relevant (skip
  logic), constraint, calculation, section.
* Choice lists: added/removed lists; per-list added/removed options and
  relabelled codes.
* Settings: title / id / version changes.

Inputs
------
Two :class:`~xlsform_studio.models.Questionnaire` objects (old, new).
Callers compile both through the same pipeline first, so the comparison is
between what would actually deploy.

Outputs
-------
A :class:`QuestionnaireDiff` with typed change lists, ``has_changes``, and
``to_markdown()`` for the change-report artefact.

Example
-------
>>> from xlsform_studio.models import Questionnaire, Question
>>> old = Questionnaire(questions=[Question(name="age", label="Age",
...                                         xlsform_type="integer")])
>>> new = Questionnaire(questions=[Question(name="age", label="Age",
...                                         xlsform_type="integer"),
...                                Question(name="sex", label="Sex",
...                                         xlsform_type="text")])
>>> QuestionnaireDiff.compare(old, new).added
['sex']
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Tuple

from ..models import Questionnaire

#: Question fields compared one-by-one, with the label shown in reports.
_TRACKED_FIELDS: Tuple[Tuple[str, str], ...] = (
    ("label", "label"),
    ("xlsform_type", "type"),
    ("required", "required"),
    ("relevant", "skip logic"),
    ("constraint", "constraint"),
    ("calculation", "calculation"),
    ("section", "section"),
)


@dataclass
class FieldChange:
    question: str
    field: str
    old: str
    new: str


@dataclass
class ChoiceListChange:
    list_name: str
    added_options: List[str] = field(default_factory=list)
    removed_options: List[str] = field(default_factory=list)
    relabelled: List[Tuple[str, str, str]] = field(default_factory=list)  # (code, old, new)


@dataclass
class QuestionnaireDiff:
    """Everything that changed between two questionnaire versions."""

    added: List[str] = field(default_factory=list)
    removed: List[str] = field(default_factory=list)
    renamed: List[Tuple[str, str]] = field(default_factory=list)   # (old, new)
    field_changes: List[FieldChange] = field(default_factory=list)
    lists_added: List[str] = field(default_factory=list)
    lists_removed: List[str] = field(default_factory=list)
    list_changes: List[ChoiceListChange] = field(default_factory=list)
    settings_changes: List[FieldChange] = field(default_factory=list)

    @property
    def has_changes(self) -> bool:
        return any((self.added, self.removed, self.renamed,
                    self.field_changes, self.lists_added, self.lists_removed,
                    self.list_changes, self.settings_changes))

    # ------------------------------------------------------------------
    @classmethod
    def compare(cls, old: Questionnaire, new: Questionnaire) -> "QuestionnaireDiff":
        diff = cls()
        old_q = {q.name: q for q in old.questions
                 if q.name and not q.is_structural}
        new_q = {q.name: q for q in new.questions
                 if q.name and not q.is_structural}

        added = [n for n in new_q if n not in old_q]
        removed = [n for n in old_q if n not in new_q]

        # A removed+added pair with the same label is a rename.
        removed_by_label = {(old_q[n].label or old_q[n].raw_label): n
                            for n in removed}
        for name in list(added):
            label = new_q[name].label or new_q[name].raw_label
            old_name = removed_by_label.get(label)
            if label and old_name:
                diff.renamed.append((old_name, name))
                added.remove(name)
                removed.remove(old_name)
                del removed_by_label[label]
                diff.field_changes.extend(
                    cls._field_diff(name, old_q[old_name], new_q[name],
                                    skip=("label",)))
        diff.added = added
        diff.removed = removed

        for name in new_q:
            if name in old_q:
                diff.field_changes.extend(
                    cls._field_diff(name, old_q[name], new_q[name]))

        cls._compare_lists(old, new, diff)

        for attr, label in (("form_title", "form title"),
                            ("form_id", "form id"), ("version", "version")):
            before = getattr(old.settings, attr)
            after = getattr(new.settings, attr)
            if before != after:
                diff.settings_changes.append(
                    FieldChange("(settings)", label, before, after))
        return diff

    @staticmethod
    def _field_diff(name, old_q, new_q, skip=()) -> List[FieldChange]:
        out = []
        for attr, label in _TRACKED_FIELDS:
            if attr in skip:
                continue
            before, after = getattr(old_q, attr), getattr(new_q, attr)
            if before != after:
                out.append(FieldChange(name, label, str(before), str(after)))
        return out

    @classmethod
    def _compare_lists(cls, old: Questionnaire, new: Questionnaire,
                       diff: "QuestionnaireDiff") -> None:
        diff.lists_added = [n for n in new.choice_lists
                            if n not in old.choice_lists]
        diff.lists_removed = [n for n in old.choice_lists
                              if n not in new.choice_lists]
        for name in new.choice_lists:
            if name not in old.choice_lists:
                continue
            old_c = {c.name: c.label for c in old.choice_lists[name].choices}
            new_c = {c.name: c.label for c in new.choice_lists[name].choices}
            change = ChoiceListChange(
                list_name=name,
                added_options=[f"{c}={new_c[c]}" for c in new_c
                               if c not in old_c],
                removed_options=[f"{c}={old_c[c]}" for c in old_c
                                 if c not in new_c],
                relabelled=[(c, old_c[c], new_c[c]) for c in new_c
                            if c in old_c and old_c[c] != new_c[c]])
            if (change.added_options or change.removed_options
                    or change.relabelled):
                diff.list_changes.append(change)

    # ------------------------------------------------------------------
    def to_markdown(self) -> str:
        lines = ["# XLSForm Studio - Change Report", ""]
        if not self.has_changes:
            lines.append("_No differences: the two versions compile to the "
                         "same form._")
            return "\n".join(lines)

        if self.settings_changes:
            lines += ["## Form settings", ""]
            for c in self.settings_changes:
                lines.append(f"- **{c.field}**: `{c.old or '(empty)'}` → "
                             f"`{c.new or '(empty)'}`")
            lines.append("")
        if self.added:
            lines += ["## Added questions", ""]
            lines += [f"- `{n}`" for n in self.added] + [""]
        if self.removed:
            lines += ["## Removed questions", ""]
            lines += [f"- `{n}` ⚠️ *breaks longitudinal comparison with "
                      f"earlier rounds*" for n in self.removed] + [""]
        if self.renamed:
            lines += ["## Renamed variables", ""]
            lines += [f"- `{a}` → `{b}` ⚠️ *update analysis scripts*"
                      for a, b in self.renamed] + [""]
        if self.field_changes:
            lines += ["## Changed questions", "",
                      "| Question | Field | Before | After |",
                      "| --- | --- | --- | --- |"]
            for c in self.field_changes:
                lines.append(f"| `{c.question}` | {c.field} | "
                             f"`{c.old or '(empty)'}` | `{c.new or '(empty)'}` |")
            lines.append("")
        if self.lists_added or self.lists_removed or self.list_changes:
            lines += ["## Choice lists", ""]
            lines += [f"- Added list `{n}`" for n in self.lists_added]
            lines += [f"- Removed list `{n}`" for n in self.lists_removed]
            for ch in self.list_changes:
                for opt in ch.added_options:
                    lines.append(f"- `{ch.list_name}`: added option `{opt}`")
                for opt in ch.removed_options:
                    lines.append(f"- `{ch.list_name}`: removed option "
                                 f"`{opt}` ⚠️ *existing data uses this code*")
                for code, before, after in ch.relabelled:
                    lines.append(f"- `{ch.list_name}`: option `{code}` "
                                 f"relabelled '{before}' → '{after}'")
            lines.append("")
        return "\n".join(lines).rstrip() + "\n"
