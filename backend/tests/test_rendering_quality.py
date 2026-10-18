from __future__ import annotations

"""Regression tests for the content-rendering quality defects.

Covers the exact bugs fixed in the final quality pass:
  * dotted figure citations ("Fig. 2.25)") leaving an orphaned "25)." fragment
  * decorative self-quotes surviving simplification as "...hours.”."
  * truncation mid-parenthetical or on a dangling participle
  * reference lines rendering "et al.." or with no locator at all
"""

import pytest

from app.services.content_generation.references import (
    MISSING_REFERENCE_TEXT,
    normalize_reference,
    reference_line,
    references_bullets,
)
from app.services.content_generation.wording import (
    _ends_complete,
    headline_from_claim,
    normalize_text,
    simplify_claim,
    strip_paper_artifacts,
    strip_self_quotes,
)


class TestStripPaperArtifacts:
    def test_dotted_figure_citation_leaves_no_orphan(self):
        out = strip_paper_artifacts(
            "24 participants were followed up at 24 weeks "
            "to evaluate the legacy effects (Fig. 2.25)."
        )
        assert "25)" not in out
        assert "(Fig" not in out
        assert "2.25" not in out
        assert out.count("(") == out.count(")")
        assert out.endswith("effects")
        assert out.startswith("24 participants")

    def test_glued_citation_and_header_fragment_removed(self):
        out = strip_paper_artifacts("Risk was lower without T2D.15 More")
        assert out == "Risk was lower without T2D"
        assert "15" not in out
        assert "More" not in out

    def test_dehyphenated_word_rejoined(self):
        assert strip_paper_artifacts("with- drawal of GLP-1RA") == "withdrawal of GLP-1RA"

    def test_statistical_and_subgroup_parens_preserved(self):
        out = strip_paper_artifacts(
            "The between-group difference was -6.7 mmHg (95% CI -9.8 to -3.6)."
        )
        assert "(95% CI -9.8 to -3.6)" in out
        out = strip_paper_artifacts(
            "29 participants (n = 14 lifestyle, n = 15 liraglutide) completed it."
        )
        assert "(n = 14 lifestyle, n = 15 liraglutide)" in out

    def test_dangling_figure_pointer_without_number_removed(self):
        # The up-stream sentence splitter cuts on the period in "Fig.", leaving
        # a claim that ends "...interventions (Fig." with no figure number.
        out = strip_paper_artifacts(
            "Twenty-four participants were followed up at 24 weeks "
            "to evaluate the legacy effects of interventions (Fig."
        )
        assert "(Fig" not in out
        assert out.count("(") == out.count(")")
        assert out.endswith("interventions")

    def test_ligature_expanded(self):
        assert "first" in normalize_text("first")
        assert "\ufb01" not in normalize_text("first")


class TestSimplifyClaim:
    def test_no_quote_outside_period(self):
        raw = "\u201cAmong 1,360 participants with T2DM, the mean sleep duration was 6.45 \u00b1 1.95 hours.\u201d"
        out = simplify_claim(raw)
        assert "\u201c" not in out and "\u201d" not in out
        assert "\u201d." not in out
        assert out.endswith(".")
        assert ".." not in out

    def test_numbers_always_preserved(self):
        out = simplify_claim(
            "After 12 weeks, the intervention group had a mean change of -8.2 mmHg "
            "(95% CI -11.0 to -5.4) compared with -1.5 mmHg in the control group. "
            "Adherence averaged 84% of scheduled sessions across the intervention group. "
            "The between-group difference was -6.7 mmHg with a further sentence.",
            limit=120,
        )
        for n in ("12", "-8.2", "-11.0", "-5.4", "-1.5", "84"):
            assert n in out, f"lost number {n}"

    def test_headline_is_complete_and_keeps_numbers(self):
        # All six numbers cannot fit under the limit, so the honest contract is
        # to keep them and stay a complete sentence rather than truncate.
        out = headline_from_claim(
            "After 12 weeks the intervention group had a mean change in resting systolic "
            "blood pressure of -8.2 mmHg (95% CI -11.0 to -5.4) compared with usual care. "
            "The between-group difference was -6.7 mmHg, which is clinically meaningful. "
            "Adherence averaged 84% of scheduled sessions across the intervention group."
        )
        assert out[0].isupper()
        assert out.endswith((".", "!", "?"))
        assert _ends_complete(out)
        for n in ("12", "-8.2", "-11.0", "-5.4", "-6.7", "84"):
            assert n in out, f"headline dropped number {n}"

    def test_headline_shortens_when_it_can(self):
        out = headline_from_claim(
            "In this randomized trial, adherence averaged 84% of scheduled sessions "
            "across the intervention group over the whole twelve week period.",
            limit=95,
        )
        assert len(out) <= 96
        assert "84" in out
        assert _ends_complete(out)

    def test_not_truncated_mid_parenthetical(self):
        out = simplify_claim(
            "24 participants (n = 12 in both arms) were followed up at 24 weeks "
            "to evaluate the legacy effects of interventions (Fig. 2.25). "
            "After a 12-week washout, the legacy effect was evaluated at week 24. "
            "A further sentence pads this out so the limit is exceeded for testing.",
            limit=120,
        )
        assert out.count("(") == out.count(")")


class TestEndsComplete:
    @pytest.mark.parametrize(
        "s",
        [
            "Thirty-three of 49 participants entered the study.",
            "Adherence averaged 84% of sessions.",
            "The intervention arm was higher (n = 14 lifestyle).",
        ],
    )
    def test_complete_sentences_pass(self, s):
        assert _ends_complete(s)

    @pytest.mark.parametrize(
        "s",
        [
            "Participants were followed up at 24 weeks in the",
            "GLP-1RA withdrawal may be predisposing",
            "After a washout, the effect was evaluated (n = 14 lifestyle",
        ],
    )
    def test_fragments_rejected(self, s):
        assert not _ends_complete(s)


class TestReferences:
    def test_et_al_not_doubled(self):
        ref = normalize_reference(
            {
                "title": "Randomised trial comparing weight loss",
                "authors": '["Ahmad Moolla", "Toryn Poolman", "Nantia Othonos", "Jiawen Dong"]',
                "journal": "JHEP Reports",
                "year": 2025,
                "doi": "10.1016/j.jhepr.2025.101363",
            }
        )
        line = reference_line(ref)
        assert "et al.." not in line
        assert "et al." in line
        assert ".." not in line

    def test_untitled_source_uses_doi_as_locator(self):
        ref = normalize_reference(
            {
                "title": "untitled",
                "authors": '["Mariko Watanabe", "Masako Yokotsuka"]',
                "journal": "Public Health Nutrition",
                "year": 2017,
                "doi": "10.1017/S1368980016001920",
            }
        )
        line = reference_line(ref)
        assert "10.1017/S1368980016001920" in line
        assert "untitled" not in line.lower()
        assert line.count("10.1017") == 1

    def test_no_invention_for_empty_source(self):
        assert normalize_reference({"title": "", "authors": None}) is None

    def test_bullets_never_empty(self):
        assert references_bullets(None) == [MISSING_REFERENCE_TEXT]
        assert references_bullets([{}]) == [MISSING_REFERENCE_TEXT]

    def test_real_fields_kept(self):
        line = reference_line(
            normalize_reference(
                {
                    "title": "Combination of exercise and GLP-1 receptor agonist treatment",
                    "authors": '["Rasmus M. Sandsdal", "Christian R. Juhl", "Simon B. K. Jensen", "Julie R. Lundgren"]',
                    "journal": "Cardiovascular Diabetology",
                    "year": 2023,
                    "doi": "10.1186/s12933-023-01765-z",
                }
            )
        )
        assert line.startswith("Rasmus M. Sandsdal, Christian R. Juhl, Simon B. K. Jensen et al.")
        assert "10.1186/s12933-023-01765-z" in line


class TestBullets:
    def test_single_char_bullets_dropped(self):
        from app.services.rendering.pptx_builder import _bullets

        out = _bullets(["O", "Bas", "Background section", "x", "The quick brown fox jumps."])
        assert "O" not in out
        assert "Bas" not in out
        assert len(out) == 2


class TestValidatorGuards:
    def test_overclaim_ignores_hyphenated_proven(self):
        from app.core.text import has_overclaim

        assert not has_overclaim(
            "The study enrolled people with biopsy-proven disease and without T2D."
        )
        assert has_overclaim("This treatment is proven to cure the disease.")
        assert has_overclaim("A guaranteed result every time.")

    def test_deck_fallback_question_and_table(self):
        from app.services.content_generation import fallback

        claims = [{
            "id": "CLM-0001",
            "claim_text": "Resting systolic blood pressure fell by 8.2 mmHg.",
            "status": "supported",
            "risk_level": "medium",
            "population": None, "study_design": None, "effect_size": None, "limitations": None,
            "evidence": [{
                "source_id": "src1",
                "excerpt": "Resting systolic blood pressure fell by 8.2 mmHg.",
                "page": 2, "doi": None, "url": None,
                "source": {"title": "Trial", "journal": "J", "year": 2023},
            }],
        }]
        summary = {
            "research_question": [],
            "numbers": [{"label": "Mean change", "value": "-8.2 mmHg"}],
            "limitations": [{"text": "People with biopsy-proven disease formed a small subgroup."}],
        }
        sources = [{"id": "src1", "title": "Trial", "journal": "J", "year": 2023,
                    "authors": '["A. Author", "B. Author", "C. Author", "D. Author"]'}]
        payload = fallback.build_deck("Demo", summary, claims, sources)
        # a project-name fallback question must not be wrapped in quotes
        rq = payload["slides"][1]["bullets"][0]
        assert "\u201c" not in rq and "\u201d" not in rq
        # the quantitative slide must carry a real table with the measurement
        quant = next(s for s in payload["slides"] if s.get("table"))
        assert quant["table"]["rows"] == [["Mean change", "-8.2 mmHg"]]

    def test_reference_bullets_not_shortened(self):
        from app.services.content_generation import fallback

        claims = [{
            "id": "CLM-0001",
            "claim_text": "Resting systolic blood pressure fell by 8.2 mmHg.",
            "status": "supported", "risk_level": "medium",
            "population": None, "study_design": None, "effect_size": None, "limitations": None,
            "evidence": [{
                "source_id": "src1",
                "excerpt": "Resting systolic blood pressure fell by 8.2 mmHg.",
                "page": 1, "doi": None, "url": None, "source": {"title": "T"},
            }],
        }]
        long_title = ("Combination of exercise and GLP-1 receptor agonist treatment reduces "
                      "severity of metabolic syndrome, abdominal obesity, and inflammation: "
                      "a randomized controlled trial")
        sources = [{
            "id": "src1", "title": long_title, "journal": "Cardiovascular Diabetology",
            "year": 2023, "doi": "10.1186/s12933-023-01765-z",
            "authors": '["Rasmus M. Sandsdal", "Christian R. Juhl", "Simon B. K. Jensen", "Julie R. Lundgren"]',
        }]
        payload = fallback.build_deck("Demo", {"numbers": [{"label": "x", "value": "-8.2 mmHg"}]},
                                      claims, sources)
        ref_slide = payload["slides"][-1]
        joined = " ".join(ref_slide["bullets"])
        assert "10.1186/s12933-023-01765-z" in joined, "reference DOI must not be truncated"
        assert not joined.rstrip().endswith("\u2014")

