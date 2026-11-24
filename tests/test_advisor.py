"""AI advisor: grounding checks, card selection, CLI invocation (fake runner, no network)."""

import json
import subprocess

import pytest

from hinan import advisor as A
from hinan.data import load_all
from hinan.guide import guide

NISHIKUJO = (34.68241, 135.4705)
SHIMAYA = (34.674039, 135.443735)


@pytest.fixture(scope="module")
def ds():
    return load_all()


@pytest.fixture(scope="module")
def known(ds):
    return {s.name for d in ds for s in d.shelters}


def _advice(*texts, ids=("facts",)):
    return A.Advice(headline="見出し", steps=[A.Step(text=t, source_ids=list(ids)) for t in texts], caution="確認してください。")


def test_mock_advice_passes_grounding(ds, known):
    for point, hazard in [(NISHIKUJO, "tsunami"), (SHIMAYA, "storm_surge")]:
        advice, cards = A.advise(A.MockAdvisor(), guide(ds, *point, hazard), known)
        assert advice.steps and cards


def test_invented_number_is_rejected(ds, known):
    r = guide(ds, *NISHIKUJO, "tsunami")
    problems = A.check_grounded(_advice("徒歩で約37分です。"), A.facts_for(r), A.cards_for(r), known)
    assert any("37" in p for p in problems)


def test_full_width_digits_are_checked_too(ds, known):
    r = guide(ds, *NISHIKUJO, "tsunami")
    assert A.check_grounded(_advice("約３７分"), A.facts_for(r), A.cards_for(r), known)


def test_site_not_among_candidates_is_rejected(ds, known):
    r = guide(ds, *NISHIKUJO, "tsunami")
    given = {c.name for c in r.candidates}
    other = sorted(known - given)[0]
    problems = A.check_grounded(_advice(f"「{other}」へ向かってください。"), A.facts_for(r), A.cards_for(r), known)
    assert any("候補にない避難場所" in p for p in problems)


def test_candidate_name_containing_another_site_name_is_not_flagged():
    facts = {"evacuation_sites": [{"name": "酉島小学校（運動場）"}]}
    advice = _advice("まず「酉島小学校（運動場）」へ向かってください。")
    assert A.check_grounded(advice, facts, [], {"酉島小学校（運動場）", "酉島小学校"}) == []
    assert A.check_grounded(_advice("酉島小学校へ。"), facts, [], {"酉島小学校（運動場）", "酉島小学校"})
    # half-width parentheses and dropped spaces, as the model actually writes them
    assert A.check_grounded(_advice("まず酉島小学校(運動場)へ。"), facts, [], {"酉島小学校（運動場）", "酉島小学校"}) == []


def test_unknown_source_id_is_rejected(ds, known):
    r = guide(ds, *NISHIKUJO, "tsunami")
    assert A.check_grounded(_advice("海辺から離れてください。", ids=("made-up",)), A.facts_for(r), A.cards_for(r), known)


def test_storm_surge_without_sites_gets_upper_floor_cards(ds):
    r = guide(ds, *SHIMAYA, "storm_surge")
    ids = [c.id for c in A.cards_for(r)]
    assert "jma-alert-upper" in ids and "bousai-kinds" in ids


def test_facts_sent_to_ai_contain_no_coordinates(ds):
    facts = json.dumps(A.facts_for(guide(ds, *NISHIKUJO, "tsunami")), ensure_ascii=False)
    assert "34.68" not in facts and "135.47" not in facts


def test_out_of_area_never_calls_the_ai(ds, known):
    class Boom(A.MockAdvisor):
        def advise(self, facts, cards):
            raise AssertionError("must not be called")

    with pytest.raises(A.AdviceError):
        A.advise(Boom(), guide(ds, 34.7025, 135.4959, "tsunami"), known)


class FakeRunner:
    def __init__(self, payload, returncode=0):
        self.payload, self.returncode, self.args, self.kwargs = payload, returncode, None, None

    def __call__(self, args, **kwargs):
        self.args, self.kwargs = args, kwargs
        return subprocess.CompletedProcess(args, self.returncode, stdout=json.dumps({"structured_output": self.payload}), stderr="")


def test_claude_cli_is_called_text_only_without_tools(ds):
    r = guide(ds, *NISHIKUJO, "tsunami")
    payload = {"headline": "h", "steps": [{"text": "海辺から離れる", "source_ids": ["jma-tsunami-move"]}], "caution": "c"}
    runner = FakeRunner(payload)
    A.ClaudeAdvisor(runner=runner).advise(A.facts_for(r), A.cards_for(r))
    cmd = runner.args
    assert cmd[0] == "claude" and cmd[cmd.index("--tools") + 1] == ""
    assert "--strict-mcp-config" in cmd and cmd[cmd.index("--permission-mode") + 1] == "dontAsk"
    assert A.SYSTEM_PROMPT in cmd
    assert runner.kwargs["stdin"] is subprocess.DEVNULL and runner.kwargs["cwd"]


def test_claude_failures_become_user_facing_errors(ds):
    r = guide(ds, *NISHIKUJO, "tsunami")
    with pytest.raises(A.AdviceError):
        A.ClaudeAdvisor(runner=FakeRunner({}, returncode=1)).advise(A.facts_for(r), A.cards_for(r))
    with pytest.raises(A.AdviceError):
        A.ClaudeAdvisor(runner=FakeRunner({"headline": "x"})).advise(A.facts_for(r), A.cards_for(r))


def test_claude_chat_command_is_text_only_and_carries_history(ds):
    r = guide(ds, *NISHIKUJO, "tsunami")
    payload = {"answer": "海辺から離れてください。", "source_ids": ["jma-tsunami-move"], "in_scope": True}
    runner = FakeRunner(payload)
    A.ClaudeAdvisor(runner=runner).chat(A.facts_for(r), A.cards_for(r), [{"role": "user", "text": "前の質問"}], "今の質問")
    cmd = runner.args
    assert cmd[cmd.index("--tools") + 1] == "" and "--strict-mcp-config" in cmd
    assert A.CHAT_SYSTEM_PROMPT in cmd and "今の質問" in cmd[2] and "前の質問" in cmd[2]


def test_chat_history_is_trimmed_and_roles_sanitised(ds, known):
    seen = {}

    class Spy(A.MockAdvisor):
        def chat(self, facts, cards, history, question):
            seen["history"] = history
            return super().chat(facts, cards, history, question)

    r = guide(ds, *NISHIKUJO, "tsunami")
    history = [{"role": "system", "text": "x" * 999}] + [{"role": "user", "text": str(i)} for i in range(10)]
    A.chat(Spy(), A.facts_for(r), A.cards_for(r), history, "質問", known)
    assert len(seen["history"]) == A.MAX_HISTORY
    assert all(h["role"] in ("user", "assistant") and len(h["text"]) <= A.MAX_QUESTION for h in seen["history"])
