"""Survey Design Intelligence - the scientific-quality scorer (deterministic).

Purpose
-------
Where the validators check that a form is *well-formed* and the Form Quality
Index (:mod:`~xlsform_studio.analysis.quality_score`) checks that it is
well-*engineered*, this scores whether it is well-*designed as a measurement
instrument* - the judgement a principal investigator, M&E specialist or survey
methodologist brings. It answers "will this instrument produce valid data?",
not "will it compile?".

The **Survey Design Score** (0-100) aggregates ten methodological dimensions:

1. **question_order** - sensitive topics late, no forward dependencies.
2. **module_flow** - coherent, balanced sections.
3. **cognitive_burden** - open-ended load, long option lists, dense logic.
4. **recall_period_consistency** - recall windows present, bounded and
   standardised (the classic driver of recall bias).
5. **scale_consistency** - answer scales of one family share point count and
   direction.
6. **enumerator_burden** - skip/constraint density the interviewer manages.
7. **respondent_burden** - length and effort asked of the respondent.
8. **objective_coverage** - each study objective is measured (only assessed
   when objectives were supplied; otherwise reported "not assessed").
9. **redundancy_detection** - near-duplicate questions asking the same thing.
10. **measurement_validity** - double-barreled, leading, or escape-less items.

Design principles (matching the tool's architecture invariants)
--------------------------------------------------------------
* **Deterministic-first.** Every dimension is computed arithmetically from the
  form and the vocabularies in ``knowledge/design_intelligence.yaml``; the
  same form always scores the same. AI is never called from here - where a
  dimension benefits from the optional AI reviewers, their *existing* findings
  (already in the validation report) are folded in, so enabling AI enriches
  the score but is never required for it.
* **Honest about reach.** A dimension the tool cannot assess for this form
  (objective coverage with no objectives supplied) is marked *not assessed*
  and excluded from the weighted average, rather than guessed - the same
  ethos as the validator's confidence icons.

Inputs
------
A compiled :class:`~xlsform_studio.models.Questionnaire`, its
:class:`~xlsform_studio.validation.report_generator.ValidationReport`, and an
optional :class:`~xlsform_studio.analysis.duration.DurationEstimate` (reused
for the burden dimensions) plus an optional coverage-matrix markdown string.

Outputs
-------
A :class:`SurveyDesignScore` - overall score, per-dimension detail (score,
weight, basis, observations), and ``to_markdown()`` for the
``survey_design_report.md`` artefact.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Dict, List, Optional

import yaml

from ..app.config import KNOWLEDGE_DIR
from ..models import Questionnaire
from ..validation.report_generator import ValidationReport

# --- vocabulary loading ------------------------------------------------------
_BUILTIN: Dict = {
    "sensitive_terms": ["income", "hiv", "religion", "ethnicity", "political"],
    "screening_terms": ["consent", "eligible"],
    "recall_patterns": [
        {"pattern": r"\btoday\b", "days": 0},
        {"pattern": r"\byesterday\b", "days": 1},
        {"pattern": r"last week|past week|last 7 days", "days": 7},
        {"pattern": r"last month|past month|last 30 days", "days": 30},
        {"pattern": r"last (3|three) months|last 90 days", "days": 90},
        {"pattern": r"last (6|six) months", "days": 180},
        {"pattern": r"last year|last 12 months|past year", "days": 365},
        {"pattern": r"last (2|two) years", "days": 730},
        {"pattern": r"ever|in your lifetime", "days": 9999},
    ],
    "recall_max_safe_days": 365,
    "scale_families": {
        "agreement": ["strongly agree", "agree", "disagree", "strongly disagree"],
        "frequency": ["always", "often", "sometimes", "rarely", "never"],
    },
    "neutral_tokens": ["neutral", "neither", "undecided", "no opinion"],
    "dont_know_tokens": ["don't know", "not sure", "refused",
                         "prefer not to say"],
    "leading_phrases": ["don't you agree", "wouldn't you agree", "how good",
                        "obviously", "clearly"],
    "double_barrel_joins": [" and ", " or ", "/"],
}


@lru_cache(maxsize=4)
def _load_vocab(directory: Optional[str] = None) -> Dict:
    """Read design_intelligence.yaml (cached), falling back to built-ins for
    any section a custom file omits, so the scorer never hard-fails."""
    base = Path(directory) if directory else KNOWLEDGE_DIR
    path = base / "design_intelligence.yaml"
    data: Dict = {}
    if path.exists():
        with path.open("r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
    merged = dict(_BUILTIN)
    merged.update({k: v for k, v in data.items() if v})
    return merged


# --- data model --------------------------------------------------------------
@dataclass
class DimensionScore:
    """One methodological dimension of the Survey Design Score."""

    name: str
    #: 0-100, or None when the dimension could not be assessed for this form.
    score: Optional[int]
    weight: float
    #: How it was judged - "deterministic", "deterministic + AI findings", or
    #: "not assessed (...)". The honesty layer.
    basis: str
    observations: List[str] = field(default_factory=list)

    @property
    def assessed(self) -> bool:
        return self.score is not None

    def to_dict(self) -> Dict:
        return {"name": self.name, "score": self.score,
                "weight": self.weight, "basis": self.basis,
                "observations": list(self.observations)}


@dataclass
class SurveyDesignScore:
    """The methodological verdict for a form."""

    overall: int
    dimensions: List[DimensionScore]

    @property
    def rating(self) -> str:
        # A measurement instrument is only as sound as its weakest dimension,
        # so the label is gated by the worst assessed score, not just the
        # weighted mean - one serious methodological flaw shouldn't be diluted
        # away by everything else being clean.
        assessed = [d.score for d in self.dimensions if d.assessed]
        worst = min(assessed) if assessed else self.overall
        if self.overall >= 85 and worst >= 80:
            return "publication-ready"
        if self.overall >= 70 and worst >= 60:
            return "sound"
        if self.overall >= 50 and worst >= 40:
            return "needs methodological review"
        return "high measurement risk"

    def dimension(self, name: str) -> Optional[DimensionScore]:
        return next((d for d in self.dimensions if d.name == name), None)

    def to_dict(self) -> Dict:
        return {"overall": self.overall, "rating": self.rating,
                "dimensions": [d.to_dict() for d in self.dimensions]}

    # -- rendering -------------------------------------------------------
    _TITLES = {
        "question_order": "Question order",
        "module_flow": "Module flow",
        "cognitive_burden": "Cognitive burden",
        "recall_period_consistency": "Recall period consistency",
        "scale_consistency": "Scale consistency",
        "enumerator_burden": "Enumerator burden",
        "respondent_burden": "Respondent burden",
        "objective_coverage": "Objective coverage",
        "redundancy_detection": "Redundancy detection",
        "measurement_validity": "Measurement validity",
    }

    def to_markdown(self) -> str:
        lines = ["# XLSForm Studio - Survey Design Score", "",
                 f"## {self.overall}/100 - {self.rating}", "",
                 "_A deterministic assessment of the form as a measurement "
                 "instrument: not whether it compiles, but whether it will "
                 "produce valid data. Each dimension is computed from the form "
                 "and the editable methodology vocabulary in "
                 "`knowledge/design_intelligence.yaml`._", "",
                 "| Dimension | Score | Basis |", "| --- | --- | --- |"]
        for d in self.dimensions:
            title = self._TITLES.get(d.name, d.name)
            score = f"{d.score}/100" if d.assessed else "—"
            lines.append(f"| {title} | {score} | {d.basis} |")
        lines.append("")
        for d in self.dimensions:
            if not d.observations:
                continue
            lines.append(f"### {self._TITLES.get(d.name, d.name)}")
            lines.append("")
            for ob in d.observations:
                lines.append(f"- {ob}")
            lines.append("")
        return "\n".join(lines).rstrip() + "\n"


# --- scorer ------------------------------------------------------------------
#: Dimension weights (assessed dimensions are renormalised, so an unassessed
#: objective_coverage doesn't drag the score down).
_WEIGHTS: Dict[str, float] = {
    "question_order": 0.10,
    "module_flow": 0.08,
    "cognitive_burden": 0.12,
    "recall_period_consistency": 0.12,
    "scale_consistency": 0.10,
    "enumerator_burden": 0.10,
    "respondent_burden": 0.12,
    "objective_coverage": 0.10,
    "redundancy_detection": 0.08,
    "measurement_validity": 0.08,
}

_WORD = re.compile(r"[a-z0-9']+")
_BURDEN_RISK_BASE = {"low": 100, "moderate": 80, "high": 55, "severe": 30}


class DesignIntelligence:
    """Compute the deterministic Survey Design Score."""

    def __init__(self, vocab_dir: Optional[Path] = None) -> None:
        self.v = _load_vocab(str(vocab_dir) if vocab_dir else None)

    # ------------------------------------------------------------------
    def score(self, questionnaire: Questionnaire,
              report: Optional[ValidationReport] = None,
              duration=None, coverage_matrix: str = "") -> SurveyDesignScore:
        report = report or ValidationReport()
        real = [q for q in questionnaire.questions if not q.is_structural]

        dims = [
            self._question_order(questionnaire, real, report),
            self._module_flow(questionnaire, real),
            self._cognitive_burden(questionnaire, real),
            self._recall_consistency(real),
            self._scale_consistency(questionnaire),
            self._enumerator_burden(questionnaire, real, report),
            self._respondent_burden(real, duration),
            self._objective_coverage(coverage_matrix, report),
            self._redundancy(real, report),
            self._measurement_validity(questionnaire, real, report),
        ]
        assessed = [d for d in dims if d.assessed]
        total_w = sum(d.weight for d in assessed) or 1.0
        overall = round(sum(d.score * d.weight for d in assessed) / total_w)
        return SurveyDesignScore(overall=overall, dimensions=dims)

    # -- helpers --------------------------------------------------------
    @staticmethod
    def _text(q) -> str:
        return f"{q.label or q.raw_label} {q.hint}".lower()

    def _dim(self, name, score, obs, basis="deterministic") -> DimensionScore:
        return DimensionScore(name=name, score=score, weight=_WEIGHTS[name],
                              basis=basis, observations=obs)

    # -- 1. question order ---------------------------------------------
    def _question_order(self, qn, real, report) -> DimensionScore:
        obs: List[str] = []
        if not real:
            return self._dim("question_order", 100, obs)
        n = len(real)
        early_cut = max(1, round(n * 0.25))
        sensitive = self.v["sensitive_terms"]
        early_sensitive = [q for i, q in enumerate(real[:early_cut])
                           if self._matches_any(self._text(q), sensitive)]
        late_screen = [q for i, q in enumerate(real)
                       if i > n * 0.5
                       and self._matches_any(self._text(q),
                                             self.v["screening_terms"])]
        # forward references are already found by the consistency validator
        fwd = [f for f in report.findings if f.category == "consistency"
               and "forward" in f.message.lower()]
        score = 100
        if early_sensitive:
            ex = early_sensitive[0].name or early_sensitive[0].label
            obs.append(f"{len(early_sensitive)} sensitive question(s) appear "
                       f"in the first quarter (e.g. '{ex}'); placing them "
                       f"after rapport is built reduces non-response and "
                       f"break-off.")
            score -= min(40, 15 * len(early_sensitive))
        if late_screen:
            obs.append(f"{len(late_screen)} screening/consent item(s) appear "
                       f"past the halfway point; eligibility and consent "
                       f"belong at the very start.")
            score -= min(25, 12 * len(late_screen))
        if fwd:
            obs.append(f"{len(fwd)} question(s) depend on an answer collected "
                       f"later in the form (forward reference).")
            score -= min(30, 15 * len(fwd))
        return self._dim("question_order", max(0, score), obs)

    # -- 2. module flow -------------------------------------------------
    def _module_flow(self, qn, real) -> DimensionScore:
        obs: List[str] = []
        if len(real) < 8:
            return self._dim("module_flow", 100, obs)
        sections: Dict[str, int] = {}
        for q in real:
            sections[q.section or ""] = sections.get(q.section or "", 0) + 1
        named = {k: v for k, v in sections.items() if k}
        score = 100
        if not named:
            obs.append("A form this long has no sections; grouping into "
                       "modules helps flow, enumerator orientation and "
                       "analysis.")
            score -= 35
        else:
            biggest = max(named.values())
            if biggest / len(real) > 0.7 and len(named) > 1:
                obs.append("One section holds most of the questions while "
                           "others are tiny; more even modules read better in "
                           "the field.")
                score -= 15
            singletons = [k for k, v in named.items() if v == 1]
            if len(singletons) >= 3:
                obs.append(f"{len(singletons)} section(s) contain a single "
                           f"question; consider merging stray items.")
                score -= 10
        return self._dim("module_flow", max(0, score), obs)

    # -- 3. cognitive burden -------------------------------------------
    def _cognitive_burden(self, qn, real) -> DimensionScore:
        obs: List[str] = []
        if not real:
            return self._dim("cognitive_burden", 100, obs)
        n = len(real)
        open_ended = [q for q in real if q.base_type == "text"
                      and not q.references_choices]
        long_lists = []
        for q in real:
            if q.references_choices:
                cl = qn.choice_lists.get(q.choice_list_name)
                if cl and len(cl.choices) > 10 and "minimal" not in \
                        (q.appearance or "") and "search" not in \
                        (q.appearance or "") and "autocomplete" not in \
                        (q.appearance or ""):
                    long_lists.append(q)
        wordy = [q for q in real
                 if len(_WORD.findall((q.label or q.raw_label).lower())) > 25]
        dense_logic = [q for q in real
                       if (q.relevant or "").count(" and ")
                       + (q.relevant or "").count(" or ") >= 3]
        score = 100
        if open_ended:
            ratio = len(open_ended) / n
            obs.append(f"{len(open_ended)} open-ended text question(s) "
                       f"({ratio:.0%}); each costs the respondent effort and "
                       f"the analyst coding time.")
            score -= min(30, round(45 * ratio))
        if long_lists:
            obs.append(f"{len(long_lists)} question(s) offer >10 options "
                       f"without a search/minimal appearance, taxing recall "
                       f"and screen space.")
            score -= min(20, 5 * len(long_lists))
        if wordy:
            obs.append(f"{len(wordy)} question(s) exceed 25 words; long "
                       f"stems raise reading load and drop-off.")
            score -= min(15, 3 * len(wordy))
        if dense_logic:
            obs.append(f"{len(dense_logic)} relevance rule(s) combine 3+ "
                       f"conditions; complex visibility is hard to reason "
                       f"about.")
            score -= min(15, 5 * len(dense_logic))
        return self._dim("cognitive_burden", max(0, score), obs)

    # -- 4. recall period consistency (signature) ----------------------
    def _recall_consistency(self, real) -> DimensionScore:
        obs: List[str] = []
        windows: List[int] = []
        long_windows = []
        for q in real:
            days = self._recall_days(self._text(q))
            if days is None:
                continue
            windows.append(days)
            if days > self.v["recall_max_safe_days"]:
                long_windows.append((q.name or q.label, days))
        if not windows:
            return self._dim("recall_period_consistency", 100,
                             ["No explicit recall windows detected; verify "
                              "that time-referenced questions state their "
                              "period ('in the last 7 days')."])
        score = 100
        distinct = sorted(set(windows))
        if long_windows:
            worst = max(d for _, d in long_windows)
            human = "lifetime/ever" if worst >= 9999 else f"{worst} days"
            obs.append(f"{len(long_windows)} question(s) ask recall over "
                       f"{human}; windows beyond "
                       f"{self.v['recall_max_safe_days']} days invite recall "
                       f"bias for behaviours and events.")
            score -= min(45, 15 * len(long_windows))
        if len(distinct) >= 4:
            obs.append(f"{len(distinct)} different recall windows are in use "
                       f"({', '.join(self._humanize_days(d) for d in distinct)}); "
                       f"standardising them makes answers comparable across "
                       f"questions.")
            score -= min(25, 6 * (len(distinct) - 3))
        return self._dim("recall_period_consistency", max(0, score), obs)

    # -- 5. scale consistency ------------------------------------------
    def _scale_consistency(self, qn) -> DimensionScore:
        obs: List[str] = []
        families: Dict[str, List] = {}
        for name, cl in qn.choice_lists.items():
            fam = self._scale_family(cl)
            if fam:
                families.setdefault(fam, []).append((name, cl))
        if not families:
            return self._dim("scale_consistency", 100, obs)
        score = 100
        for fam, lists in families.items():
            counts = {len(cl.choices) for _, cl in lists}
            if len(counts) > 1:
                obs.append(f"The '{fam}' scale appears with different point "
                           f"counts ({sorted(counts)}); a mixed 4-/5-point "
                           f"scale for one construct isn't comparable.")
                score -= 20
            # direction: does the positive pole come first?
            directions = {self._scale_direction(cl, fam) for _, cl in lists}
            directions.discard(None)
            if len(directions) > 1:
                obs.append(f"The '{fam}' scale runs in both directions across "
                           f"the form; keep the positive pole consistently "
                           f"first (or last) to avoid coding errors.")
                score -= 15
        return self._dim("scale_consistency", max(0, score), obs)

    # -- 6. enumerator burden ------------------------------------------
    def _enumerator_burden(self, qn, real, report) -> DimensionScore:
        obs: List[str] = []
        if not real:
            return self._dim("enumerator_burden", 100, obs)
        n = len(real)
        skip = [q for q in real if q.relevant]
        repeats = [q for q in qn.questions if q.base_type == "begin repeat"]
        ai = [f for f in report.findings if f.category == "ai_review"
              and "enumerat" in f.message.lower()]
        basis = "deterministic + AI findings" if ai else "deterministic"
        score = 100
        skip_ratio = len(skip) / n
        if skip_ratio > 0.4:
            obs.append(f"{len(skip)} of {n} questions ({skip_ratio:.0%}) carry "
                       f"skip logic; dense branching is demanding to administer "
                       f"on paper and error-prone for new enumerators.")
            score -= min(25, round((skip_ratio - 0.4) * 80))
        if repeats:
            obs.append(f"{len(repeats)} roster(s) require the enumerator to "
                       f"manage repeat instances; ensure clear stop rules.")
            score -= min(15, 8 * len(repeats))
        for f in ai[:3]:
            obs.append(f"AI review: {f.message}")
            score -= 5
        return self._dim("enumerator_burden", max(0, score), obs, basis)

    # -- 7. respondent burden ------------------------------------------
    def _respondent_burden(self, real, duration) -> DimensionScore:
        obs: List[str] = []
        n = len(real)
        if duration is not None:
            score = _BURDEN_RISK_BASE.get(duration.burden_risk, 70)
            obs.append(f"Estimated ~{duration.typical_minutes:.0f} min across "
                       f"{n} question(s); respondent-burden risk "
                       f"'{duration.burden_risk}'.")
        else:
            # Fallback if no duration estimate was supplied.
            score = 100 if n <= 40 else max(30, 100 - (n - 40))
            obs.append(f"{n} question(s); long instruments raise fatigue and "
                       f"satisficing.")
        if n > 80:
            obs.append("Instruments over ~80 questions see marked data-quality "
                       "decline late in the interview; consider splitting or "
                       "sub-sampling modules.")
            score = min(score, 45)
        return self._dim("respondent_burden", max(0, score), obs)

    # -- 8. objective coverage -----------------------------------------
    def _objective_coverage(self, coverage_matrix, report) -> DimensionScore:
        if not coverage_matrix:
            return self._dim(
                "objective_coverage", None, [
                    "Not assessed: no study objectives were supplied. Provide "
                    "objectives (UI textarea or --ai-objectives) to score how "
                    "well the instrument measures each one."],
                basis="not assessed (needs objectives)")
        text = coverage_matrix.lower()
        # The coverage matrix flags uncovered objectives explicitly.
        gaps = text.count("no question") + text.count("gap") \
            + text.count("not covered") + text.count("uncovered")
        score = max(30, 100 - 20 * gaps)
        obs = [f"{gaps} objective coverage gap(s) flagged in the coverage "
               f"matrix." if gaps else
               "Every stated objective maps to at least one question in the "
               "coverage matrix."]
        return self._dim("objective_coverage", score, obs,
                         basis="deterministic + AI findings")

    # -- 9. redundancy detection ---------------------------------------
    def _redundancy(self, real, report) -> DimensionScore:
        obs: List[str] = []
        labels = [(q.name or q.label, self._tokens(q.label or q.raw_label))
                  for q in real if (q.label or q.raw_label)]
        pairs = []
        for i in range(len(labels)):
            for j in range(i + 1, len(labels)):
                a, b = labels[i][1], labels[j][1]
                if len(a) >= 3 and len(b) >= 3 and self._jaccard(a, b) >= 0.75:
                    pairs.append((labels[i][0], labels[j][0]))
        ai = [f for f in report.findings if f.category == "ai_review"
              and ("redundant" in f.message.lower()
                   or "duplicate" in f.message.lower())]
        basis = "deterministic + AI findings" if ai else "deterministic"
        score = 100
        if pairs:
            obs.append(f"{len(pairs)} near-identical question pair(s) detected "
                       f"(e.g. '{pairs[0][0]}' vs '{pairs[0][1]}'); duplicated "
                       f"items inflate length and confuse respondents.")
            score -= min(40, 15 * len(pairs))
        for f in ai[:3]:
            obs.append(f"AI review: {f.message}")
            score -= 8
        return self._dim("redundancy_detection", max(0, score), obs, basis)

    # -- 10. measurement validity --------------------------------------
    def _measurement_validity(self, qn, real, report) -> DimensionScore:
        obs: List[str] = []
        if not real:
            return self._dim("measurement_validity", 100, obs)
        double = [q for q in real if self._double_barreled(q)]
        leading = [q for q in real
                   if self._matches_any(self._text(q),
                                        self.v["leading_phrases"])]
        no_escape = self._sensitive_without_escape(qn, real)
        no_neutral = self._even_scale_without_neutral(qn)
        ai = [f for f in report.findings if f.category == "ai_review"
              and ("leading" in f.message.lower()
                   or "double" in f.message.lower()
                   or "bias" in f.message.lower())]
        basis = "deterministic + AI findings" if ai else "deterministic"
        score = 100
        if double:
            obs.append(f"{len(double)} question(s) look double-barreled "
                       f"(e.g. '{double[0].name or double[0].label}'); asking "
                       f"two things at once makes the answer un-analysable.")
            score -= min(30, 10 * len(double))
        if leading:
            obs.append(f"{len(leading)} question(s) use leading/loaded "
                       f"phrasing that biases the answer.")
            score -= min(25, 10 * len(leading))
        if no_escape:
            obs.append(f"{len(no_escape)} sensitive/opinion question(s) offer "
                       f"no 'don't know' or 'refused' option; forcing an "
                       f"answer manufactures data.")
            score -= min(20, 6 * len(no_escape))
        if no_neutral:
            obs.append(f"{len(no_neutral)} opinion scale(s) have an even "
                       f"point count and no neutral midpoint, forcing a "
                       f"direction.")
            score -= min(15, 8 * len(no_neutral))
        for f in ai[:3]:
            obs.append(f"AI review: {f.message}")
            score -= 6
        return self._dim("measurement_validity", max(0, score), obs, basis)

    # ------------------------------------------------------------------
    # low-level detectors
    # ------------------------------------------------------------------
    @staticmethod
    def _matches_any(text: str, terms) -> bool:
        return any(re.search(r"\b" + re.escape(t) + r"\b", text)
                   for t in terms)

    def _recall_days(self, text: str) -> Optional[int]:
        best = None
        for entry in self.v["recall_patterns"]:
            if re.search(entry["pattern"], text):
                d = int(entry["days"])
                best = d if best is None else max(best, d)
        return best

    @staticmethod
    def _humanize_days(days: int) -> str:
        if days >= 9999:
            return "lifetime"
        if days == 0:
            return "today"
        if days == 1:
            return "1 day"
        if days < 30:
            return f"{days} days"
        if days < 365:
            return f"{round(days / 30)} months"
        return f"{round(days / 365)} year(s)"

    def _scale_family(self, cl) -> Optional[str]:
        labels = " " + " ".join((c.label or "").lower() for c in cl.choices) + " "
        for fam, markers in self.v["scale_families"].items():
            hits = sum(1 for m in markers if m in labels)
            if hits >= max(2, len(markers) - 1):
                return fam
        return None

    def _scale_direction(self, cl, fam) -> Optional[str]:
        markers = self.v["scale_families"][fam]
        first_label = (cl.choices[0].label or "").lower() if cl.choices else ""
        # markers are listed positive-pole first; if the list's first option
        # matches an early marker it's "ascending", a late marker "descending".
        for idx, m in enumerate(markers):
            if m in first_label:
                return "positive_first" if idx < len(markers) / 2 \
                    else "negative_first"
        return None

    @staticmethod
    def _tokens(text: str) -> set:
        stop = {"the", "a", "an", "of", "to", "in", "is", "are", "do", "you",
                "your", "how", "what", "many", "have", "has", "did", "for"}
        return {w for w in _WORD.findall(text.lower()) if w not in stop}

    @staticmethod
    def _jaccard(a: set, b: set) -> float:
        if not a or not b:
            return 0.0
        return len(a & b) / len(a | b)

    def _double_barreled(self, q) -> bool:
        label = (q.label or q.raw_label or "").lower()
        # Only flag real question stems, not select option prompts.
        if q.base_type not in ("text", "select_one", "select_multiple",
                               "integer", "decimal", ""):
            return False
        for join in self.v["double_barrel_joins"]:
            if join in label:
                left, _, right = label.partition(join)
                # both sides must carry a noun-ish token of length >=4
                if (len(_WORD.findall(left)) >= 2
                        and any(len(w) >= 4 for w in _WORD.findall(right))
                        and any(len(w) >= 4 for w in _WORD.findall(left))):
                    return True
        return False

    def _sensitive_without_escape(self, qn, real) -> List:
        out = []
        dk = self.v["dont_know_tokens"]
        for q in real:
            if not self._matches_any(self._text(q), self.v["sensitive_terms"]):
                continue
            if q.references_choices:
                cl = qn.choice_lists.get(q.choice_list_name)
                labels = " ".join((c.label or "").lower()
                                  for c in (cl.choices if cl else []))
                if any(t in labels for t in dk):
                    continue
                out.append(q)
            # free-text sensitive questions can always be left blank unless
            # required
            elif q.required:
                out.append(q)
        return out

    def _even_scale_without_neutral(self, qn) -> List:
        out = []
        neutral = self.v["neutral_tokens"]
        for name, cl in qn.choice_lists.items():
            fam = self._scale_family(cl)
            if fam != "agreement" and fam != "satisfaction" \
                    and fam != "quality":
                continue
            if len(cl.choices) % 2 == 0:
                labels = " ".join((c.label or "").lower() for c in cl.choices)
                if not any(t in labels for t in neutral):
                    out.append(name)
        return out
