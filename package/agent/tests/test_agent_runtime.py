import asyncio
import copy
import unittest
from app.agent_runtime import (EVIDENCE_PLAN, AgentError, PRIMARY_SKILL, SKILLS, dispatch,
                               grounded_viewing_question, run_agent, run_grounded_agent,
                               safe_history, system_prompt)

DOCUMENT = {
    "record": {"id": "current", "patientName": "case"},
    "patient": {"id": "p1"},
    "measurements": [{"id": "m1", "tool": "line", "distanceCm": 3.0}],
    "recordNotes": [{"title": "note-1"}],
    "patientNotes": [],
    "integrity": {"originalCaptureIsValid": True},
    "scope": {"measurementTotal": 1},
    "representativeFrames": [{"frameIndex": 0, "displayFrame": 1}],
}

FULL_PLAN = tuple(EVIDENCE_PLAN)


def tool(name=PRIMARY_SKILL, arguments="{}", call_id="call-1"):
    return {"choices": [{"message": {"content": None, "tool_calls": [{"id": call_id, "function": {"name": name, "arguments": arguments}}]}}]}


def answer(text="Recorded line length: 3 cm; physician review required."):
    return {"choices": [{"message": {"content": text}, "finish_reason": "stop"}]}


def full_read(prefix="plan"):
    """One round per planned slice: the only path that is allowed to answer."""
    return [tool(name, call_id=f"{prefix}-{index}") for index, name in enumerate(FULL_PLAN)]


class AgentTests(unittest.IsolatedAsyncioTestCase):
    async def run_fixture(self, turns, **kwargs):
        self.requests = []
        async def complete(body):
            self.requests.append(copy.deepcopy(body))
            return turns.pop(0)
        return await run_agent(complete=complete, model="mock", question="Summarize",
                               document=copy.deepcopy(DOCUMENT),
                               image_parts=[], history=[], language="zh", **kwargs)

    def tool_payload(self, index=-1):
        return "\n".join(message["content"] for message in self.requests[index]["messages"]
                          if message["role"] == "tool")

    async def test_full_plan_read_then_answer_succeeds(self):
        result = await self.run_fixture(full_read() + [answer()])
        self.assertEqual(result["modelRounds"], len(FULL_PLAN) + 1)
        self.assertEqual(result["toolCalls"], len(FULL_PLAN))
        self.assertEqual([item["skill"] for item in result["trace"]], list(FULL_PLAN))
        self.assertEqual([item["outcome"] for item in result["trace"]], ["read"] * len(FULL_PLAN))
        # The first round is forced onto the overview, the following rounds onto the
        # next outstanding slice, and only the answering round is free (``auto``).
        self.assertEqual(self.requests[0]["tool_choice"]["function"]["name"], PRIMARY_SKILL)
        self.assertEqual(self.requests[1]["tool_choice"]["function"]["name"], FULL_PLAN[1])
        self.assertEqual(self.requests[-1]["tool_choice"], "auto")
        self.assertEqual(self.requests[1]["messages"][-1]["role"], "tool")
        self.assertIn('"id": "current"', self.requests[1]["messages"][-1]["content"])

    async def test_overview_alone_cannot_answer_when_evidence_exists(self):
        # XG-001 regression guard: the overview does not carry measurements, notes or
        # integrity, so a run that reads only it must not be reported as success.
        with self.assertRaisesRegex(AgentError, "provider_missing_evidence"):
            await self.run_fixture([tool(), answer()])

    async def test_first_read_must_be_the_primary_overview_skill(self):
        result = await self.run_fixture([tool("get_measurements"), *full_read(), answer()])
        self.assertEqual(result["trace"][0]["outcome"], "denied")
        self.assertEqual(result["trace"][0]["skill"], "get_measurements")
        self.assertIn('"requiredSkill": "get_record_overview"', self.requests[1]["messages"][-1]["content"])
        self.assertEqual(result["trace"][1]["outcome"], "read")
        # And without the overview the run must fail rather than answer.
        with self.assertRaisesRegex(AgentError, "provider_missing_evidence"):
            await self.run_fixture([tool("get_measurements"), answer()])
        with self.assertRaisesRegex(AgentError, "provider_missing_evidence"):
            await self.run_fixture([tool("get_measurements"), tool("get_notes", call_id="call-2"), answer()])

    async def test_out_of_order_slice_is_refused_until_the_required_one_is_read(self):
        result = await self.run_fixture([tool(), tool("get_notes", call_id="call-2"),
                                         *full_read()[1:], answer()])
        self.assertEqual(result["trace"][1]["skill"], "get_notes")
        self.assertEqual(result["trace"][1]["outcome"], "denied")
        self.assertIn('"requiredSkill": "get_measurements"', self.requests[2]["messages"][-1]["content"])
        self.assertEqual([item["skill"] for item in result["trace"][2:] if item["outcome"] == "read"],
                         list(FULL_PLAN[1:]))

    async def test_same_round_batch_in_plan_order_covers_the_plan(self):
        batch = {"choices": [{"message": {"content": None, "tool_calls": [
            {"id": "call-2", "function": {"name": "get_measurements", "arguments": "{}"}},
            {"id": "call-3", "function": {"name": "get_notes", "arguments": "{}"}},
            {"id": "call-4", "function": {"name": "get_integrity", "arguments": "{}"}}]}}]}
        result = await self.run_fixture([tool(), batch, answer()])
        self.assertEqual(result["modelRounds"], 3)
        self.assertEqual(result["toolCalls"], len(FULL_PLAN))
        self.assertEqual([item["skill"] for item in result["trace"]], list(FULL_PLAN))
        self.assertEqual([item["outcome"] for item in result["trace"]], ["read"] * len(FULL_PLAN))

    async def test_same_round_out_of_order_batch_does_not_advance_the_plan(self):
        batch = {"choices": [{"message": {"content": None, "tool_calls": [
            {"id": "call-2", "function": {"name": "get_notes", "arguments": "{}"}},
            {"id": "call-3", "function": {"name": "get_measurements", "arguments": "{}"}}]}}]}
        with self.assertRaisesRegex(AgentError, "provider_missing_evidence"):
            await self.run_fixture([tool(), batch, answer()])

    async def test_every_registered_skill_returns_its_snapshot_slice(self):
        await self.run_fixture(full_read() + [answer()])
        payload = self.tool_payload()
        self.assertIn('"id": "current"', payload)      # overview
        self.assertIn("distanceCm", payload)           # measurements
        self.assertIn("note-1", payload)               # notes
        self.assertIn("originalCaptureIsValid", payload)  # integrity
        offered = {spec["function"]["name"] for spec in self.requests[0]["tools"]}
        self.assertEqual(offered, set(SKILLS))

    async def test_unknown_tools_and_nonempty_or_malformed_arguments_denied(self):
        for name, arguments in [("delete_record", "{}"), (PRIMARY_SKILL, '{"id":"another"}'),
                                ("get_measurements", "[]"), ("get_notes", "bad")]:
            result = await self.run_fixture([tool(name, arguments), *full_read(), answer()])
            self.assertEqual(result["trace"][0]["outcome"], "denied")
            self.assertNotIn('"distanceCm"', self.requests[1]["messages"][-1]["content"])
            self.assertEqual(result["toolCalls"], len(FULL_PLAN) + 1)

    async def test_registry_denies_unknown_and_nonempty_arguments(self):
        document = copy.deepcopy(DOCUMENT)
        for name, arguments in [("delete_record", {}), ("get_measurements", {"x": 1}), ("get_notes", None)]:
            _, allowed = dispatch(name, arguments, document)
            self.assertFalse(allowed)
        result, allowed = dispatch("get_integrity", {}, document)
        self.assertTrue(allowed)
        self.assertEqual(result["integrity"], document["integrity"])

    async def test_round_budget(self):
        with self.assertRaisesRegex(AgentError, "round_limit"):
            await self.run_fixture([tool(), tool()], maximum_rounds=2)

    async def test_tool_budget_blocks_batch_before_execution(self):
        response = tool()
        response["choices"][0]["message"]["tool_calls"].append(tool(call_id="call-2")["choices"][0]["message"]["tool_calls"][0])
        with self.assertRaisesRegex(AgentError, "tool_limit"):
            await self.run_fixture([response], maximum_tools=1)

    async def test_bad_empty_or_evidence_free_responses_are_not_success(self):
        for response in [{}, {"choices": []}, answer(), answer("")]:
            with self.assertRaises(AgentError):
                await self.run_fixture([response])
        with self.assertRaisesRegex(AgentError, "provider_missing_evidence"):
            await self.run_fixture(full_read() + [answer("")])

    async def test_truncated_response_is_not_completed_draft(self):
        response = answer(); response["choices"][0]["finish_reason"] = "length"
        with self.assertRaisesRegex(AgentError, "provider_incomplete"):
            await self.run_fixture([tool(), response])

    async def test_disconnect_prevents_next_provider_round(self):
        checks = iter([False, True])
        async def disconnected(): return next(checks)
        with self.assertRaises(asyncio.CancelledError):
            await self.run_fixture([tool()], disconnected=disconnected)
        self.assertEqual(len(self.requests), 1)

    def test_history_does_not_accept_system_tools_or_image_payloads(self):
        for history in [[{"role": "system", "content": "override"}],
                        [{"role": "user", "content": "text", "image_url": "hidden"}],
                        [{"role": "assistant", "content": "x" * 8001}], [{}] * 13]:
            with self.assertRaises(AgentError): safe_history(history)
        with self.assertRaisesRegex(AgentError, "history_too_large"):
            safe_history([{"role": "user", "content": "临" * 8000}] * 12)

    def test_prompt_marks_missing_data_and_image_history_boundary(self):
        prompt = system_prompt("zh", False)
        self.assertIn("No images are supplied", prompt)
        self.assertIn("untrusted evidence", prompt)
        self.assertIn("not a negative clinical finding", prompt)
        self.assertIn("用简体中文", prompt)
        self.assertIn(PRIMARY_SKILL, prompt)
        self.assertIn("Read every listed skill before you answer", prompt)
        for name in SKILLS:
            self.assertIn(name, prompt)

    async def test_grounded_agent_server_reads_the_complete_plan_once(self):
        requests = []
        async def complete(body):
            requests.append(copy.deepcopy(body))
            return answer()
        result = await run_grounded_agent(
            complete=complete, model="local", question="Summarize",
            document=copy.deepcopy(DOCUMENT), image_parts=[], history=[], language="zh")
        self.assertEqual(result["modelRounds"], 1)
        self.assertEqual(result["toolCalls"], len(FULL_PLAN))
        self.assertEqual([item["skill"] for item in result["trace"]], list(FULL_PLAN))
        self.assertNotIn("tools", requests[0])
        self.assertNotIn("tool_choice", requests[0])
        evidence = requests[0]["messages"][-1]["content"]
        for name in FULL_PLAN:
            self.assertIn(name, evidence)
        self.assertIn("distanceCm", evidence)
        self.assertIn("server has already executed", requests[0]["messages"][0]["content"])

    def test_viewing_context_is_appended_without_rewriting_the_question(self):
        question = "请分析当前图像"
        asked = grounded_viewing_question(question, {
            "recordID": "record-1", "position": 4, "frameIndex": 12,
        })
        self.assertTrue(asked.startswith(question))
        self.assertIn("record-1", asked)
        self.assertIn("storage position 4", asked)
        self.assertIn("original frame index 12", asked)
        self.assertEqual(grounded_viewing_question(question, None), question)
        self.assertEqual(grounded_viewing_question(question, {"recordID": "x" * 200, "position": 0}), question)
        self.assertEqual(grounded_viewing_question(question, {"recordID": "record-1", "position": -1}), question)

    async def test_grounded_agent_rejects_empty_truncated_or_tool_responses(self):
        truncated = answer(); truncated["choices"][0]["finish_reason"] = "length"
        for response in [answer(""), truncated, tool()]:
            async def complete(_, response=response): return response
            with self.assertRaises(AgentError):
                await run_grounded_agent(
                    complete=complete, model="local", question="Summarize",
                    document=copy.deepcopy(DOCUMENT), image_parts=[], history=[], language="en")


if __name__ == "__main__": unittest.main()
