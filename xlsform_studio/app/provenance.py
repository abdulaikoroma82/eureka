"""Durable model snapshot - the provenance sidecar.

Purpose
-------
An XLSForm workbook can carry a form's *facts* (types, names, labels, logic,
choice lists), but it has no column for the tool's *provenance*: how sure it
was about each field (:class:`~xlsform_studio.models.Decision` confidence)
and why it chose what it did (the ``assumptions`` audit log). That
provenance lives only on the in-memory model.

To make **round-trip editing** possible - export an XLSForm, edit it in
Excel or a platform's form builder, then re-import it *without losing that
provenance* - every run also writes the complete model to a JSON sidecar
(``<form_id>_model.json``) next to the workbook. Re-importing an edited form
reconciles it against this snapshot (see
:mod:`~xlsform_studio.app.roundtrip`).

Why a separate loader
---------------------
:meth:`Questionnaire.to_dict` is already a faithful dump -
``dataclasses.asdict`` captures ``decisions``, ``assumptions`` and the
``extra`` passthrough columns. What is missing is a faithful *reader*:
:meth:`Questionnaire.from_dict` reads the friendly **input** format
(``{"question": ...}``) and deliberately drops internal provenance. The
functions here reverse ``to_dict`` exactly instead, so a model survives a
write/read cycle byte-for-byte.
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path
from typing import Any, Dict, Union

from ..models import (Choice, ChoiceList, Decision, FormSettings, Question,
                      Questionnaire)

#: Suffix appended to the form id for the sidecar file name.
SIDECAR_SUFFIX = "_model.json"

#: Schema marker + version stamped into every snapshot, so a future format
#: change can be detected and migrated rather than silently mis-read.
_SCHEMA = "xlsform-studio/model"
_SCHEMA_VERSION = 1

_QUESTION_FIELDS = {f.name for f in dataclasses.fields(Question)}
_SETTINGS_FIELDS = {f.name for f in dataclasses.fields(FormSettings)}


def model_to_snapshot(qn: Questionnaire) -> Dict[str, Any]:
    """Serialise a questionnaire to a faithful, JSON-ready dict.

    Builds on :meth:`Questionnaire.to_dict` (already faithful) and stamps a
    schema marker so the loader can validate what it is reading.
    """
    snap = qn.to_dict()
    snap["_schema"] = _SCHEMA
    snap["_schema_version"] = _SCHEMA_VERSION
    return snap


def snapshot_to_model(data: Dict[str, Any]) -> Questionnaire:
    """Reconstruct a questionnaire from a snapshot dict, provenance intact.

    The inverse of :func:`model_to_snapshot`: every ``Question`` field
    (including ``decisions`` and ``assumptions``) and every choice list -
    with its passthrough ``extra`` columns - is restored exactly.
    """
    settings_d = data.get("settings", {}) or {}
    settings = FormSettings(**{k: v for k, v in settings_d.items()
                               if k in _SETTINGS_FIELDS})
    qn = Questionnaire(settings=settings,
                       category=data.get("category", "general"))

    for qd in data.get("survey", []):
        qn.questions.append(_question_from_snapshot(qd))

    for list_name, ld in (data.get("choices", {}) or {}).items():
        raw = ld.get("choices", []) if isinstance(ld, dict) else ld
        cl = ChoiceList(
            list_name=(ld.get("list_name", list_name)
                       if isinstance(ld, dict) else list_name))
        for ch in raw or []:
            extra = {k: str(v) for k, v in ch.items()
                     if k not in ("name", "label") and v is not None}
            cl.choices.append(Choice(name=str(ch.get("name", "")),
                                     label=str(ch.get("label",
                                                       ch.get("name", ""))),
                                     extra=extra))
        qn.add_choice_list(cl)
    return qn


def _question_from_snapshot(qd: Dict[str, Any]) -> Question:
    q = Question()
    for key, val in qd.items():
        if key == "decisions":
            q.decisions = [Decision(**d) for d in (val or [])]
        elif key in _QUESTION_FIELDS and not key.startswith("_"):
            setattr(q, key, val)
    return q


def write_model_sidecar(qn: Questionnaire, path: Union[str, Path]) -> Path:
    """Write the model snapshot to *path* (pretty-printed JSON)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(model_to_snapshot(qn), indent=2,
                               ensure_ascii=False), encoding="utf-8")
    return path


def read_model_sidecar(path: Union[str, Path]) -> Questionnaire:
    """Load a model snapshot written by :func:`write_model_sidecar`.

    Raises
    ------
    ValueError
        If the file is not a recognised model snapshot.
    """
    path = Path(path)
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("_schema") != _SCHEMA:
        raise ValueError(
            f"{path} is not an XLSForm Studio model snapshot "
            f"(expected a '{SIDECAR_SUFFIX}' file written by a previous run).")
    return snapshot_to_model(data)
