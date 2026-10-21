"""Prior-art research agent and code question modes (hermetic: no network, no key)."""

from agents.idea_agent import DecomposedIdea
from agents.prior_art_agent import (
    PriorArtAgent,
    build_queries,
    clean_citations,
    novelty_from_similarities,
    support_ratio,
)
from agents.orchestrator import classify_code_question
from core.llm import llm_client
from tools.paper_search import (
    Paper,
    PaperSearchResult,
    arxiv_query_variants,
    bibtex_entry,
    ieee_reference,
    merge_papers,
)


def _idea():
    return DecomposedIdea(
        raw_idea="A smart ultrasonic water meter using LoRaWAN to detect pipe leaks in real time.",
        project_title="LoRaWAN Ultrasonic Water Leak Meter",
        problem_statement="Households find pipe leaks only after a large water bill arrives.",
        target_personas=[],
        core_value_prop="Real-time leak alerts from a low-power ultrasonic meter.",
        key_assumptions=[],
        mvp_features=["Ultrasonic flow sensing", "LoRaWAN uplink", "Leak alert rules"],
        trace=[],
    )


def _papers():
    return [
        Paper(title="Battery-less Water Leak Detection with LoRa", authors=["Roshan Nepal", "Brandon Brown"],
              year=2025, abstract="We detect water leaks in pipes with LoRa radios and energy harvesting.",
              url="https://arxiv.org/abs/2507.03649", source="arxiv", arxiv_id="2507.03649"),
        Paper(title="Ultrasonic Flow Metering for Smart Water Networks", authors=["A. Kumar"], year=2022,
              abstract="Ultrasonic transit-time flow meters measure household water consumption accurately.",
              url="https://example.org/flow", source="openalex", doi="10.1000/flow", citation_count=12),
        Paper(title="Deep Learning for Image Classification", authors=["B. Lee"], year=2020,
              abstract="Convolutional networks classify natural images.", url="https://example.org/cnn",
              source="semantic_scholar"),
    ]


def _searcher(papers):
    return lambda queries: PaperSearchResult(papers=papers, queries=queries,
                                             sources_ok=["arxiv", "openalex"], sources_failed={})


def test_queries_are_built_from_the_idea():
    queries = build_queries(_idea())
    assert queries and all(q.strip() for q in queries)
    assert any("lorawan" in q.lower() for q in queries)


def test_arxiv_query_relaxes_from_strict_to_pairs():
    variants = arxiv_query_variants("Residential LoRaWAN Ultrasonic Water Metering System")
    assert variants[0].count("AND") == 2
    assert " OR " in variants[1]


def test_merge_dedupes_by_title_and_keeps_metadata():
    a = Paper(title="Same Paper", authors=[], year=2020, abstract="", url="u1", source="arxiv")
    b = Paper(title="same paper!", authors=[], year=2020, abstract="text", url="u2", source="openalex",
              citation_count=5, doi="10.1/x")
    merged = merge_papers([[a], [b]])
    assert len(merged) == 1
    assert merged[0].abstract == "text" and merged[0].citation_count == 5 and merged[0].doi == "10.1/x"
    assert merged[0].also_found_in == ["openalex"]


def test_novelty_index_is_computed_from_similarities():
    index, band = novelty_from_similarities([0.8, 0.5, 0.4], "MiniLM")
    # 100 * (1 - (0.6*0.8 + 0.4*mean(0.8,0.5,0.4)))
    assert index == round(100 * (1 - (0.48 + 0.4 * (1.7 / 3))))
    assert band.startswith("Very close")
    assert novelty_from_similarities([], "MiniLM")[0] is None


def test_out_of_range_citations_are_removed():
    text, removed, cited = clean_citations("A [1] and B [7] and C [2, 9].", max_ref=3)
    assert removed == 2
    assert cited == [1, 2]
    assert "[7]" not in text and "[9]" not in text


def test_support_ratio_measures_claim_against_abstract():
    abstract = "We detect water leaks in pipes with LoRa radios."
    assert support_ratio("Detects pipe leaks using LoRa radios", abstract) > 0.6
    assert support_ratio("Quantum cryptography for satellites", abstract) == 0.0


def test_reference_formatting():
    paper = _papers()[0]
    ref = ieee_reference(paper, 1)
    assert ref.startswith("[1] R. Nepal and B. Brown") or ref.startswith("[1] R. Nepal, and B. Brown")
    assert "arXiv:2507.03649" in ref
    bib = bibtex_entry(paper)
    assert bib.startswith("@misc{nepal2025") and "eprint = {2507.03649}" in bib


def test_agent_drops_comparisons_for_papers_it_did_not_retrieve(monkeypatch):
    def fake_json(**kwargs):
        return {
            "comparisons": [
                {"ref": "P1", "what_it_does": "Detects water leaks in pipes with LoRa radios.",
                 "overlap": "Leak detection over LoRa", "paper_is_stronger_at": "Battery-less design",
                 "idea_adds": "Ultrasonic flow sensing", "overlap_level": "high"},
                {"ref": "P9", "what_it_does": "Invented paper", "overlap": "", "overlap_level": "low"},
            ],
            "research_gap": "Gap", "positioning": "Position",
            "related_work": "Leak detection was studied in [1] and [12].",
        }

    monkeypatch.setattr(llm_client, "generate_json", lambda **kw: fake_json(**kw))
    report = PriorArtAgent(searcher=_searcher(_papers())).research(_idea())
    assert report.generation_source == "llm"
    assert [c.ref for c in report.comparisons] == ["P1"]
    assert report.verification["invalid_refs_dropped"] == 1
    assert report.verification["citations_removed"] == 1
    assert "[12]" not in report.related_work
    # Unrelated CNN paper ranks last.
    assert report.papers[-1].title.startswith("Deep Learning")
    assert report.novelty_index is not None and 0 <= report.novelty_index <= 100
    assert len(report.ieee_references) == len(report.papers)
    assert report.similarity_map and report.similarity_map[0]["is_idea"]


def test_agent_falls_back_without_llm_and_without_inventing():
    with llm_client.force_offline():
        report = PriorArtAgent(searcher=_searcher(_papers())).research(_idea())
    assert report.generation_source == "fallback"
    assert all("LLM unavailable" in c.paper_is_stronger_at for c in report.comparisons)
    assert report.related_work == ""


def test_no_papers_means_no_novelty_and_no_fake_papers():
    report = PriorArtAgent(searcher=_searcher([])).research(_idea())
    assert report.papers == [] and report.novelty_index is None
    assert report.generation_source == "fallback"
    assert "No research papers" in report.to_markdown()


def test_code_question_modes():
    assert classify_code_question("What is the blast radius if I modify verify_token?") == "impact"
    assert classify_code_question("ValueError: token expired in checkout") == "bug"
    assert classify_code_question("Where is customer authentication verified?") == "explain"
