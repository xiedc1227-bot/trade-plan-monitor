"""Process-local negative controls; never rewrite repository source."""

import ast
import functools
import inspect
import sys
import textwrap


def replace_function(module, name, transformer):
    function = getattr(module, name)
    tree = ast.parse(textwrap.dedent(inspect.getsource(function)))
    tree = transformer.visit(tree)
    ast.fix_missing_locations(tree)
    namespace = dict(function.__globals__)
    exec(compile(tree, 'bounded-transport-negative-control', 'exec'), namespace)
    setattr(module, name, namespace[name])


class SkipStreamEnd(ast.NodeTransformer):
    def visit_If(self, node):
        if any(isinstance(n, ast.Constant) and n.value == 'incomplete stream'
               for n in ast.walk(node) if n is not node.test) and len(node.body) == 1:
            if isinstance(node.body[0], ast.Raise):
                node.test = ast.Constant(False)
        return self.generic_visit(node)


class SkipCanonical(ast.NodeTransformer):
    def visit_Compare(self, node):
        if isinstance(node.left, ast.Name) and node.left.id == 'canonical_json':
            return ast.Constant(True)
        return self.generic_visit(node)


class EarlyRelease(ast.NodeTransformer):
    def visit_If(self, node):
        node = self.generic_visit(node)
        if (isinstance(node.test, ast.Compare) and isinstance(node.test.left, ast.Name)
                and node.test.left.id == 'admitted'):
            return [ast.Expr(ast.Call(ast.Attribute(ast.Name('self', ast.Load()),
                                                   '_release', ast.Load()), [], [])), node]
        return node


class SkipBudget(ast.NodeTransformer):
    def visit_If(self, node):
        if (isinstance(node.test, ast.Compare) and isinstance(node.test.left, ast.Name)
                and node.test.left.id == 'reserved'):
            node.test = ast.Constant(False)
        return self.generic_visit(node)


def child_mutation(connection, generation, mode):
    from scripts.experiments import bounded_transport
    if mode == 'stream-end':
        replace_function(bounded_transport, '_job', SkipStreamEnd())
    else:
        from trade_plan_monitor.state import projections
        replace_function(projections, '_market_index_from_row', SkipCanonical())
    bounded_transport._worker(connection, generation)


def main(mode):
    import pytest
    from scripts.experiments import bounded_codec, bounded_transport
    target = 'tests/integration/test_bounded_validation_transport.py'
    if mode in ('stream-end', 'canonical'):
        bounded_transport._worker = functools.partial(child_mutation, mode=mode)
        selection = ('incomplete_or_crossed and (count or digest)' if mode == 'stream-end'
                     else 'old_unselected and canonical')
    elif mode == 'early-release':
        replace_function(bounded_transport.ChunkWorker, 'validate', EarlyRelease())
        selection = 'repeated_observer'
    else:
        if mode == 'budget-check':
            replace_function(bounded_codec, 'plan', SkipBudget())
        else:
            bounded_codec.LIMIT += 1
        target = 'tests/unit/test_bounded_validation_codec.py'
        selection = 'aggregate_budget'
    code = pytest.main([target, '-k', selection, '-q', '--tb=short',
                        '--basetemp=.pytest_cache/bvt-mutant-'+mode])
    if code != 1:
        raise RuntimeError(f'mutation survived or test failed to collect: {mode}: {code}')
    print('MUTATION_KILLED: '+mode)


if __name__ == '__main__':
    main(sys.argv[1])
