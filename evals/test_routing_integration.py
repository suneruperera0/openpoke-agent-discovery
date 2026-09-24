import asyncio
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from server.agents.interaction_agent import tools
from server.agents.interaction_agent import agent as interaction_agent
from server.agents.interaction_agent.agent import prepare_message_with_history
from server.agents.interaction_agent.runtime import InteractionAgentRuntime, _ToolCall
from server.services.execution.directory import AgentDirectory, BUDGET, LIMIT


class FakeLogs:
    def __init__(self): self.requests = []
    def record_request(self, name, instructions): self.requests.append((name, instructions))


class FakeBatch:
    def __init__(self): self.calls = []
    async def execute_agent(self, name, instructions):
        self.calls.append((name, instructions))
        return type('Result', (), {'success': True})()


class RoutingToolTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addAsyncCleanup(self._cleanup)
        self.directory = AgentDirectory(Path(self.tmp.name)/'roster.json')
        self.logs, self.batch = FakeLogs(), FakeBatch()
        self.patches = [patch.object(tools, 'get_agent_roster', return_value=self.directory),
                        patch.object(tools, 'get_execution_agent_logs', return_value=self.logs),
                        patch.object(tools, '_EXECUTION_BATCH_MANAGER', self.batch)]
        for p in self.patches: p.start()

    async def _cleanup(self):
        await asyncio.sleep(0)
        for p in reversed(self.patches): p.stop()
        self.tmp.cleanup()

    async def test_shortlist_dispatch_and_search_recovery(self):
        owner, _ = self.directory.create_or_reuse('Cedar owner', instructions='Manage Cedar delivery with Maya')
        self.assertEqual(tools.search_agents('Maya Cedar').payload['candidates'][0]['ref'], owner['ref'])
        result = tools.send_message_to_agent(agent_ref=owner['ref'], instructions='Continue Cedar')
        self.assertTrue(result.success)
        self.assertFalse(result.payload['new_agent_created'])
        await asyncio.sleep(0)
        self.assertEqual(self.logs.requests, [('Cedar owner', 'Continue Cedar')])

    async def test_unknown_requires_deliberate_creation(self):
        self.directory.create_or_reuse('Cedar owner', instructions='Maya delivery')
        before = self.directory.get_agents()
        result = tools.send_message_to_agent(agent_name='Cedar duplicate', instructions='Maya delivery')
        self.assertFalse(result.success)
        self.assertEqual(result.payload['status'], 'creation_review_required')
        self.assertEqual(self.directory.get_agents(), before)
        created = tools.create_agent('Kestrel calibration', 'Telescope calibration', 'Track Kestrel telescope calibration', 'New responsibility')
        self.assertTrue(created.payload['new_agent_created'])
        reused = tools.create_agent('Kestrel calibration', 'different', 'Continue calibration', 'Existing exact owner')
        self.assertFalse(reused.payload['new_agent_created'])
        self.assertEqual(self.directory.get_agents().count('Kestrel calibration'), 1)

    async def test_conflicting_identity_is_rejected(self):
        a, _ = self.directory.create_or_reuse('A')
        self.directory.create_or_reuse('B')
        result = tools.handle_tool_call('send_message_to_agent', {'agent_name':'B', 'agent_ref':a['ref'], 'instructions':'x'})
        self.assertFalse(result.success)
        self.assertIn('Conflicting', result.payload['error'])


class IterationBudgetTests(unittest.IsolatedAsyncioTestCase):
    async def test_repeated_discovery_exhausts_eight_iterations(self):
        runtime = object.__new__(InteractionAgentRuntime)
        count = 0
        async def response(system, messages):
            nonlocal count
            count += 1
            return {'choices':[{'message':{'content':'', 'tool_calls':[{'id':str(count), 'function':{'name':'search_agents', 'arguments':'{"query":"miss"}'}}]}}]}
        runtime._make_llm_call = response
        runtime._execute_tool = lambda call: tools.ToolResult(success=True, payload={'candidates':[]})
        with self.assertRaisesRegex(RuntimeError, 'iteration limit'):
            await runtime._run_interaction_loop('system', [{'role':'user','content':'test'}])
        self.assertEqual(count, 8)

    async def test_one_search_then_dispatch_fits_budget(self):
        runtime = object.__new__(InteractionAgentRuntime)
        calls = [
            {'choices':[{'message':{'content':'', 'tool_calls':[{'id':'1','function':{'name':'search_agents','arguments':'{"query":"Cedar"}'}}]}}]},
            {'choices':[{'message':{'content':'', 'tool_calls':[{'id':'2','function':{'name':'send_message_to_agent','arguments':'{"agent_ref":"ag_x","instructions":"continue"}'}}]}}]},
            {'choices':[{'message':{'content':'done'}}]},
        ]
        async def response(system, messages): return calls.pop(0)
        runtime._make_llm_call = response
        runtime._execute_tool = lambda call: (tools.ToolResult(success=True, payload={'candidates':[]})
            if call.name == 'search_agents' else tools.ToolResult(success=True, payload={'agent_ref':'ag_x'}))
        summary = await runtime._run_interaction_loop('system', [{'role':'user','content':'test'}])
        self.assertEqual(summary.last_assistant_text, 'done')
        self.assertEqual(summary.tool_names, ['search_agents', 'send_message_to_agent'])


class PromptPathTests(unittest.TestCase):
    """The whole point of the change: the Interaction Agent prompt must receive the
    bounded shortlist, not the full roster. These guard the prompt-construction path."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.directory = AgentDirectory(Path(self.tmp.name) / 'roster.json')
        patcher = patch.object(interaction_agent, 'get_agent_roster', return_value=self.directory)
        patcher.start()
        self.addCleanup(patcher.stop)

    @staticmethod
    def _active_block(content):
        start = content.index('<active_agents>')
        end = content.index('</active_agents>') + len('</active_agents>')
        return content[start:end]

    def test_prompt_receives_bounded_shortlist_not_full_roster(self):
        for i in range(50):
            self.directory.create_or_reuse(f'Project {i} owner', instructions=f'Handle project {i} logistics')
        content = prepare_message_with_history('Handle project 7 logistics', '', 'user')[0]['content']
        block = self._active_block(content)
        self.assertLessEqual(len(block.encode('utf-8')), BUDGET)
        page = json.loads(block.split('\n', 1)[1].rsplit('\n', 1)[0])
        self.assertLessEqual(len(page['candidates']), LIMIT)
        # 50 agents exist; the prompt must not contain them all (no full-roster leak).
        self.assertLess(len(page['candidates']), 50)

    def test_empty_roster_renders_safe_block(self):
        content = prepare_message_with_history('hello', '', 'user')[0]['content']
        page = json.loads(self._active_block(content).split('\n', 1)[1].rsplit('\n', 1)[0])
        self.assertEqual(page['candidates'], [])

    def test_malformed_roster_degrades_to_empty_block(self):
        broken = Mock()
        broken.shortlist.side_effect = ValueError('malformed directory')
        with patch.object(interaction_agent, 'get_agent_roster', return_value=broken):
            block = interaction_agent._render_active_agents('hi', '')
        self.assertIn('<active_agents>', block)
        self.assertIn('</active_agents>', block)


if __name__ == '__main__': unittest.main()
