"""M32 — deterministic calc tool (safe AST evaluator)."""

import unittest

from assistant_core.tools.calc import CalcTool, safe_eval, maybe_answer_arithmetic


class ArithmeticInterceptTests(unittest.TestCase):
    def test_plain_expressions_answered(self):
        self.assertEqual(maybe_answer_arithmetic("4 + 6 ="), "4 + 6 = 10")
        self.assertEqual(maybe_answer_arithmetic("4 + 6"), "4 + 6 = 10")
        self.assertEqual(maybe_answer_arithmetic("what is 3 * 7?"), "3 * 7 = 21")
        self.assertEqual(maybe_answer_arithmetic("compute (2+3)*4"), "(2+3)*4 = 20")

    def test_non_arithmetic_returns_none(self):
        for m in ["hello", "what is love", "4", "the year 2024", "search for 5 + 6 notes",
                  "", "note 42"]:
            self.assertIsNone(maybe_answer_arithmetic(m), m)


class SafeEvalTests(unittest.TestCase):
    def test_basic_arithmetic(self):
        self.assertEqual(safe_eval("4 + 6"), 10)
        self.assertEqual(safe_eval("6 + 6"), 12)
        self.assertEqual(safe_eval("2 * (3 + 4)"), 14)
        self.assertEqual(safe_eval("10 / 4"), 2.5)
        self.assertEqual(safe_eval("17 // 5"), 3)
        self.assertEqual(safe_eval("2 ** 10"), 1024)
        self.assertEqual(safe_eval("-5 + 3"), -2)

    def test_functions(self):
        self.assertEqual(safe_eval("abs(-7)"), 7)
        self.assertEqual(safe_eval("max(3, 9, 2)"), 9)
        self.assertEqual(safe_eval("sqrt(144)"), 12.0)

    def test_rejects_unsafe(self):
        for bad in ["__import__('os')", "x + 1", "os.system('x')", "(1).__class__",
                    "[i for i in range(3)]", "open('f')", "2 ** 999999"]:
            with self.assertRaises(Exception):
                safe_eval(bad)


class CalcToolTests(unittest.TestCase):
    def setUp(self):
        self.tool = CalcTool()

    def test_the_four_plus_six_case(self):
        res = self.tool.run("4 + 6 =")          # trailing '=' tolerated
        self.assertTrue(res.success)
        self.assertEqual(res.output, "4 + 6 = 10")
        self.assertEqual(res.metadata["result"], "10")

    def test_float_integer_formatting(self):
        self.assertEqual(self.tool.run("8 / 2").output, "8 / 2 = 4")   # 4.0 → 4

    def test_division_by_zero(self):
        res = self.tool.run("5 / 0")
        self.assertFalse(res.success)
        self.assertIn("division by zero", res.output)

    def test_bad_expression_fails_gracefully(self):
        res = self.tool.run("hello world")
        self.assertFalse(res.success)
        self.assertIn("Could not evaluate", res.output)

    def test_empty(self):
        self.assertFalse(self.tool.run("   ").success)


if __name__ == "__main__":
    unittest.main()
