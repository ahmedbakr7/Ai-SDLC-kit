"""The full build -> test -> review -> merge conveyor for the example's first ticket."""
import contextlib
import io
import unittest

import regen_example


class FirstTicketConveyor(unittest.TestCase):
    def test_build_test_review_merge(self) -> None:
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = regen_example.main(write=False)
        self.assertEqual(code, 0, out.getvalue()[-3000:])
        self.assertIn("T-042-01: in_review -> done", out.getvalue())


if __name__ == "__main__":
    unittest.main()
