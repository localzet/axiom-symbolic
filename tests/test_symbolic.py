import tempfile
import unittest
from pathlib import Path

from axiom_symbolic import evaluate_program, verify

SPEC = """AXIOM-IR/2
module=abs
input.0.name=x
input.0.type=int
output.name=result
output.type=int
domain.x.kind=unbounded
requires.0.id=req
requires.0.expr=true
ensures.0.id=nonnegative
ensures.0.expr=result >= 0
ensures.1.id=magnitude
ensures.1.expr=result == x || result == -x
"""

BAD = """AXIOM-PROGRAM/2
module=abs
inputs=x
output=result
capabilities=
source.expr=x
code:
LOAD_INPUT r0 x
RETURN r0
end
"""

GOOD = """AXIOM-PROGRAM/2
module=abs
inputs=x
output=result
capabilities=
source.expr=if x < 0 then -x else x
code:
LOAD_INPUT r0 x
NEG r1 r0
SELECT_NEG_INPUT r2 x r1 r0
RETURN r2
end
"""


class SymbolicTests(unittest.TestCase):
    def test_bad_program_has_counterexample(self):
        valid, _, cex = verify(SPEC, BAD)
        self.assertFalse(valid)
        self.assertIsNotNone(cex)
        self.assertLess(int(cex["input.x"]), 0)

    def test_abs_is_universally_valid(self):
        valid, meta, cex = verify(SPEC, GOOD)
        self.assertTrue(valid)
        self.assertIsNone(cex)
        self.assertEqual(meta["paths"], "2")

    def test_runtime_evaluator(self):
        self.assertEqual(evaluate_program(GOOD, -13), 13)
        self.assertEqual(evaluate_program(GOOD, 7), 7)


if __name__ == "__main__":
    unittest.main()
