"""Optional desk prose. No key = empty. Invented numbers are rejected."""
from app.omni.desk import build_web_desk
from app.omni.llm import configured, invented_numbers, narrate_desk
from tests.test_desk import _web


def test_desk_works_without_an_llm_key():
    assert configured() is False
    desk = build_web_desk(_web(tagline="We help teams ship"))
    assert desk.narrative == ""
    assert desk.llm_used is False
    assert desk.job
    assert desk.needs
    assert "optional language model" in desk.methodology.lower()


def test_narrate_returns_empty_without_key():
    assert narrate_desk({"one_liner": "Acme ships tools.", "job": "Name an offer."}) == ""


def test_invented_numbers_are_rejected():
    desk = {"one_liner": "Acme score 40/100", "job": "Name one offer",
            "needs": [{"evidence": "Score 40"}]}
    assert invented_numbers("Traffic is 2,400,000 sessions", desk)
    assert not invented_numbers("The score is 40 and the job is one offer", desk)
