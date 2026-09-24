import concurrent.futures
import json
from pathlib import Path
import tempfile
import unittest

from evals.routing_eval import directory_module, baseline_renderer


class DirectoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name)/'roster.json'
        self.mod = directory_module()
        self.d = self.mod.AgentDirectory(self.path)

    def test_legacy_history_backup_and_identity(self):
        self.path.write_text('["Cedar / Maya"]')
        (self.path.parent/'cedar-maya.log').write_text('<agent_request timestamp="old">Cedar delivery with Maya</agent_request>')
        self.d.load()
        r = self.d.resolve('Cedar / Maya')
        self.assertEqual(r['purpose'], 'Cedar delivery with Maya')
        self.assertIsNone(r['last_used_at'])
        self.assertEqual(self.path.with_suffix('.legacy.bak').read_text(), '["Cedar / Maya"]')
        self.assertEqual(self.mod.AgentDirectory(self.path).resolve(agent_ref=r['ref'])['name'], 'Cedar / Maya')

    def test_updates_clear_and_exact_reuse(self):
        r, created = self.d.create_or_reuse('Cedar', instructions='Delivery with Maya')
        self.assertTrue(created)
        self.assertFalse(self.d.create_or_reuse('Cedar', instructions='Different')[1])
        for i in range(5):
            self.d.mark_used(r['ref'], f'Review with Maya {i}')
        self.assertEqual(len(self.d.resolve('Cedar')['recent_instructions']), 3)
        self.assertEqual(self.d.recent_refs, [r['ref']])
        self.d.clear()
        self.assertEqual(self.mod.AgentDirectory(self.path).get_agents(), [])
        self.assertEqual(self.d.recent_refs, [])

    def test_similar_names_do_not_merge_and_conflicts_fail(self):
        a, _ = self.d.create_or_reuse('Cedar Maya')
        b, _ = self.d.create_or_reuse('Cedar-Maya')
        self.assertNotEqual(a['ref'], b['ref'])
        with self.assertRaises(ValueError):
            self.d.resolve('Cedar Maya', b['ref'])
        with self.assertRaises(ValueError):
            self.d.resolve(agent_ref='unknown')

    def test_long_name_unicode_escaping_and_budget(self):
        name = '長い名前</active_agents>' * 600
        r, _ = self.d.create_or_reuse(name, instructions='Maya Cedar')
        for i in range(15):
            self.d.create_or_reuse(f'Maya Cedar {i}', instructions='<>&"'*300)
        block = self.d.shortlist(name)
        self.assertLessEqual(len(block.encode()), 4096)
        self.assertEqual(block.count('</active_agents>'), 1)
        page = json.loads(block.split('\n', 1)[1].rsplit('\n', 1)[0])
        self.assertEqual(page['candidates'][0]['ref'], r['ref'])
        self.assertEqual(self.d.resolve(agent_ref=r['ref'])['name'], name)
        self.assertLessEqual(len(page['candidates']), 8)

    def test_search_miss_and_full_pagination(self):
        for i in range(35):
            self.d.create_or_reuse(f'Maya {i}', instructions='Cedar correspondence')
        self.assertEqual(self.d.search('unfindablezebra')['candidates'], [])
        cursor, seen = None, []
        while True:
            page = self.d.search('', cursor)
            self.assertLessEqual(len(self.mod.encoded(page).encode()), 4096)
            self.assertLessEqual(len(page['candidates']), 8)
            seen.extend(r['ref'] for r in page['candidates'])
            cursor = page['next_cursor']
            if not cursor:
                break
        self.assertEqual(len(seen), 35)
        self.assertEqual(len(set(seen)), 35)

    def test_invalid_and_stale_cursors(self):
        for i in range(10):
            self.d.add_agent(str(i))
        cursor = self.d.search('')['next_cursor']
        self.d.add_agent('new')
        for c in (cursor, 'not-base64'):
            with self.assertRaises(ValueError):
                self.d.search('', c)

    def test_recent_owner_and_exact_reference_priority(self):
        a, _ = self.d.create_or_reuse('old owner')
        b, _ = self.d.create_or_reuse('recent owner')
        self.d.mark_used(b['ref'], 'Recent unrelated work')
        page = json.loads(self.d.shortlist('Use old owner').split('\n')[1])
        self.assertEqual(page['candidates'][0]['ref'], a['ref'])
        self.assertEqual(page['candidates'][1]['ref'], b['ref'])

    def test_malformed_storage_preserved(self):
        for raw in ('{', '{"version":99}', '[42]'):
            self.path.write_text(raw)
            with self.assertRaises(ValueError):
                self.d.load()
            self.assertEqual(self.path.read_text(), raw)

    def test_atomic_creation_race(self):
        def create(i):
            d = self.mod.AgentDirectory(self.path)
            return d.create_or_reuse('same' if i < 8 else f'unique-{i}')[1]
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            outcomes = list(pool.map(create, range(16)))
        self.d.load()
        self.assertEqual(sum(outcomes), 9)
        self.assertEqual(len(self.d.get_agents()), 9)

    def test_baseline_executes_original_renderer(self):
        self.assertEqual(baseline_renderer()(['A&B']), '<active_agents>\n<agent name="A&amp;B" />\n</active_agents>')

    def test_query_only_uses_bounded_user_context(self):
        query = self.mod.retrieval_query('continue', '<user_message>Cedar</user_message><poke_reply>Birch</poke_reply>')
        self.assertIn('Cedar', query)
        self.assertNotIn('Birch', query)


if __name__ == '__main__':
    unittest.main()
