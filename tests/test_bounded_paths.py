"""Independent tiny-graph oracle and CLI regressions; synthetic files only."""

import json
import random
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tracecascade.engine import simulate
from tracecascade.model import load_graph, load_scenario
from tracecascade.report import markdown


def case(root, pairs, changed=('a',), extra_nodes=()):
    names = sorted(set(changed) | set(extra_nodes) | {n for p in pairs for n in p[1:3]})
    value = {'version': 1,
             'nodes': [{'id': n, 'kind': 'item', 'title': n, 'description': 'Synthetic'} for n in names],
             'edges': [{'id': p[0], 'from': p[1], 'to': p[2], 'confidence': p[3],
                        'status': p[4] if len(p) > 4 else 'confirmed', 'relation': 'feeds',
                        'evidence': {'source': 'evidence.md', 'quote': 'Synthetic relation',
                                     'line_start': 1, 'line_end': 1}} for p in pairs]}
    graph_path, scenario_path = root / 'graph.json', root / 'scenario.json'
    graph_path.write_text(json.dumps(value), encoding='utf-8')
    scenario_path.write_text(json.dumps({'version': 1, 'title': 'Synthetic bounded change',
        'changes': [{'node': n, 'operation': 'modify', 'description': 'Synthetic change'} for n in changed]}), encoding='utf-8')
    (root / 'evidence.md').write_text('Synthetic relation\n', encoding='utf-8')
    graph = load_graph(graph_path)
    return graph, load_scenario(scenario_path, graph)


def oracle(graph, scenario, depth):
    """Enumerate simple paths, not the implementation's heap/frontier algorithm.

    Powers-of-two scores in the randomized corpus are exactly representable;
    this is a graph correctness oracle, not an extreme-float precision claim.
    Changed nodes are independent roots, never transit/report targets.
    """
    changed = {c.node for c in scenario.changes}
    limit = min(depth, len(graph.nodes)-1)
    best = {}
    def visit(node, origin, seen, path, score):
        if path:
            key = (-score, len(path), tuple(e.id for e in path), origin)
            if node not in best or key < best[node][0]:
                best[node] = (key, path)
        if len(path) >= limit:
            return
        for edge in graph.edges:
            if edge.source == node and edge.target not in seen and edge.target not in changed:
                visit(edge.target, origin, seen | {edge.target}, path + (edge,), score*edge.confidence)
    for origin in sorted(changed):
        visit(origin, origin, {origin}, (), 1.0)
    return best


class BoundedPathTests(unittest.TestCase):
    def assert_oracle(self, graph, scenario, depth):
        expected = oracle(graph, scenario, depth)
        report = simulate(graph, scenario, max_depth=depth)
        actual = {i['node']['id']: i for i in report['impacts']}
        self.assertEqual(set(actual), set(expected), f'reachability at depth {depth}')
        for node, (key, edges) in expected.items():
            item = actual[node]
            self.assertEqual(item['score'], round(-key[0], 6))
            self.assertEqual(item['origin'], key[3])
            self.assertEqual([s['edge'] for s in item['path']], list(key[2]))
            self.assertEqual(item['depth'], key[1])
            confirmed = all(e.status == 'confirmed' for e in edges)
            expected_class = 'confirmed-impact' if confirmed and -key[0] >= .8 else 'likely-impact' if -key[0] >= .5 else 'review-required'
            self.assertEqual(item['classification'], expected_class)
            self.assertEqual(item['all_relations_confirmed'], confirmed)
            path_nodes = [item['origin']] + [s['to'] for s in item['path']]
            self.assertEqual(len(path_nodes), len(set(path_nodes)), 'simple report path')
            self.assertEqual([s['evidence']['quote'] for s in item['path']], ['Synthetic relation']*len(edges))
        self.assertEqual(report['summary']['affected_nodes'], len(expected))
        return report

    def test_shallow_weaker_path_still_reaches_descendant(self):
        with tempfile.TemporaryDirectory() as tmp:
            graph, scenario = case(Path(tmp), [('ax','a','x',1), ('xb','x','b',1),
                                              ('ab','a','b',.5), ('bc','b','c',1)])
            result = self.assert_oracle(graph, scenario, 2)
            items = {i['node']['id']: i for i in result['impacts']}
            self.assertEqual(items['b']['score'],1)
            self.assertEqual(items['c']['score'],.5)
            self.assertEqual([e['edge'] for e in items['c']['path']], ['ab','bc'])

    def test_weaker_shallow_prefix_can_improve_existing_descendant(self):
        with tempfile.TemporaryDirectory() as tmp:
            graph, scenario = case(Path(tmp), [('ax','a','x',1), ('xb','x','b',1),
                ('ab','a','b',.5), ('bc','b','c',1), ('ac','a','c',.25), ('cd','c','d',1)])
            self.assert_oracle(graph, scenario, 3)

    def test_equal_score_prefers_shorter_path_before_edge_ids(self):
        with tempfile.TemporaryDirectory() as tmp:
            graph, scenario = case(Path(tmp), [('aa','a','x',1),('bb','x','b',1),
                                               ('zz','a','b',1),('bc','b','c',1)])
            result = self.assert_oracle(graph, scenario, 2)
            self.assertEqual(next(i for i in result['impacts'] if i['node']['id']=='b')['depth'],1)

    def test_legacy_unbounded_tie_rule_is_not_silently_changed(self):
        with tempfile.TemporaryDirectory() as tmp:
            graph, scenario = case(Path(tmp), [('aa','a','x',1),('bb','x','b',1),('zz','a','b',1)])
            unbounded=simulate(graph,scenario)
            self.assertEqual(next(i for i in unbounded['impacts'] if i['node']['id']=='b')['depth'],2)
            bounded=self.assert_oracle(graph,scenario,99)
            self.assertEqual(next(i for i in bounded['impacts'] if i['node']['id']=='b')['depth'],1)

    def test_zero_single_node_and_invalid_depth_values(self):
        with tempfile.TemporaryDirectory() as tmp:
            graph,scenario=case(Path(tmp),[])
            for depth in [0,1,1000000]:
                result=self.assert_oracle(graph,scenario,depth)
                self.assertEqual(result['summary']['max_depth'],0)
            for depth in [-1,True,False,1.5,'2',float('nan')]:
                with self.subTest(depth=depth), self.assertRaisesRegex(ValueError,'nonnegative'):
                    simulate(graph,scenario,max_depth=depth)

    def test_all_changed_nodes_remain_independent_roots(self):
        with tempfile.TemporaryDirectory() as tmp:
            graph,scenario=case(Path(tmp),[('ab','a','b',1),('bc','b','c',1),('ca','c','a',1)],('a','b','c'))
            for depth in [0,1,2,10]:
                self.assertEqual(self.assert_oracle(graph,scenario,depth)['impacts'],[])

    def test_parallel_edges_cycles_multisource_and_disconnected_node(self):
        with tempfile.TemporaryDirectory() as tmp:
            pairs = [('ax','a','x',1),('zx','z','x',1),('xx','a','x',1),('xb','x','b',.5,'inferred'),
                     ('bx','b','x',1),('ba','b','a',1),('bc','b','c',.5),('cz','c','z',1)]
            graph, scenario = case(Path(tmp), pairs, ('a','z'), ('isolated',))
            for depth in [0,1,2,3,99]:
                self.assert_oracle(graph, scenario, depth)

    def test_independent_exhaustive_oracle_for_240_small_graphs(self):
        rng = random.Random(20261006)
        with tempfile.TemporaryDirectory() as tmp:
            for number in range(240):
                names = ['a','b','c','d','e','f']
                pairs = []
                for source in names:
                    for target in names:
                        if source != target and rng.random() < .28:
                            pairs.append((f'e{len(pairs):02}',source,target,rng.choice([1,.5,.25]),rng.choice(['confirmed','inferred'])))
                graph, scenario = case(Path(tmp), pairs, ('a','f') if number%3==0 else ('a',), names)
                for depth in range(6):
                    with self.subTest(graph=number,depth=depth):
                        self.assert_oracle(graph, scenario, depth)

    def test_input_permutations_do_not_change_selected_paths(self):
        rng = random.Random(4)
        with tempfile.TemporaryDirectory() as tmp:
            pairs = [('aa','a','x',1),('xb','x','b',1),('zz','a','b',.5),('bc','b','c',1),('cz','c','z',.5)]
            graph, scenario = case(Path(tmp), pairs, ('a','z'))
            before = self.assert_oracle(graph, scenario, 2)
            for _ in range(12):
                rng.shuffle(pairs)
                graph, scenario = case(Path(tmp),pairs,('z','a'))
                after = self.assert_oracle(graph,scenario,2)
                self.assertEqual(after['impacts'],before['impacts'])
                self.assertEqual(after['summary'],before['summary'])

    def test_cli_reports_reachable_node_with_evidence_and_preserves_inputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            graph, scenario = case(root,[('ax','a','x',1),('xb','x','b',1),('ab','a','b',.5),('bc','b','c',1)])
            output, md = root/'out.json', root/'out.md'
            before = (graph.path.read_bytes(),scenario.path.read_bytes())
            result = subprocess.run([sys.executable,*(['-I'] if sys.flags.isolated else []),'-m','tracecascade','simulate',str(graph.path),str(scenario.path),
                '--max-depth','2','--json-out',str(output),'--markdown-out',str(md)],capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            report=json.loads(output.read_text(encoding='utf-8'))
            self.assertEqual({i['node']['id'] for i in report['impacts']},{'x','b','c'})
            self.assertEqual(md.read_text(encoding='utf-8'),markdown(report))
            self.assertEqual(before,(graph.path.read_bytes(),scenario.path.read_bytes()))


if __name__ == '__main__':
    unittest.main()
