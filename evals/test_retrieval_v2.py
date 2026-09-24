import json
from pathlib import Path
import tempfile
import unittest
from evals.routing_eval import directory_module


class RetrievalV2Tests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.mod = directory_module()
        self.d = self.mod.AgentDirectory(Path(self.tmp.name)/'roster.json')

    def test_plural_matches_without_changing_identity(self):
        row,_ = self.d.create_or_reuse('Policies', instructions='Manage insurance policies and warranty extensions')
        found = self.d.search('policy warranty extension')['candidates']
        self.assertEqual(found[0]['ref'],row['ref'])
        self.assertIsNone(self.d.resolve('Policy'))
        self.assertEqual(self.d.resolve(agent_ref=row['ref'])['name'],'Policies')

    def test_repeated_metadata_is_not_extra_evidence(self):
        row,_ = self.d.create_or_reuse('opaque',instructions='Manage copper warranty extensions')
        before = self.d.rank('copper warranty')[0][2]
        self.d.mark_used(row['ref'],'Manage copper warranty extensions')
        self.d.mark_used(row['ref'],'Manage copper warranty extensions')
        after = self.d.rank('copper warranty')[0][2]
        self.assertEqual(before,after)

    def test_wrong_project_name_does_not_double_count_history(self):
        owner,_ = self.d.create_or_reuse('ticket-81', instructions='Manage Pollen certificate renewals with Tariq')
        for i in range(20):
            self.d.create_or_reuse(f'Finch Tariq certificate renewals {i}',
                                  instructions='Manage Finch certificate renewals with Tariq')
        refs = [r['ref'] for r in self.d.search('Pollen certificate renewal Tariq')['candidates']]
        self.assertIn(owner['ref'],refs)

    def test_generic_aliases_and_contrast(self):
        self.assertEqual(self.mod.retrieval_tokens('vendor agreements'), self.mod.retrieval_tokens('supplier contracts'))
        self.assertEqual(self.mod.positive_query('inspection, not payments.'), 'inspection ')
        self.assertEqual(self.mod.positive_query('not yet approved'), 'not yet approved')

    def test_names_only_and_empty_directory(self):
        self.assertEqual(self.d.rank('anything'),[])
        self.d.create_or_reuse('opaque',instructions='copper warranty')
        self.assertEqual(self.d.search('copper',enriched=False)['candidates'],[])

    def test_request_outranks_stale_context_without_pin(self):
        self.d.create_or_reuse('old',instructions='Manage amber permits')
        new,_=self.d.create_or_reuse('new',instructions='Manage silver permits')
        self.assertEqual(self.d.rank('silver permits\namber permits')[0][4]['ref'],new['ref'])

    def test_adversarial_rendered_budget_and_reachability(self):
        for i in range(25):
            self.d.create_or_reuse('猫<&"'+str(i)*100,instructions='<&"'*100)
        block=self.d.shortlist('猫')
        self.assertLessEqual(len(block.encode()),4096)
        page=json.loads(block.split('\n',1)[1].rsplit('\n',1)[0])
        self.assertLessEqual(len(page['candidates']),8)
        seen=set(); cursor=None
        while True:
            page=self.d.search('',cursor)
            self.assertLessEqual(len(self.mod.encoded(page).encode()),4096)
            seen.update(r['ref'] for r in page['candidates'])
            cursor=page['next_cursor']
            if not cursor: break
        self.assertEqual(len(seen),25)

if __name__=='__main__': unittest.main()
