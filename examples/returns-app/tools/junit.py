"""Run unittest discovery and write a JUnit XML report.

Each test's docstring starts with its AC tag (e.g. 'T-042-01/AC-1'); the tag goes into
the JUnit test name so `sdlc gate` can prove every acceptance criterion has a passing test.
"""
import argparse
import sys
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

ap = argparse.ArgumentParser()
ap.add_argument("--out", required=True)
ap.add_argument("--start", default="app")
ap.add_argument("--pattern", default="test_*.py")
args = ap.parse_args()

root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(root))
start = root / args.start
suite = (unittest.defaultTestLoader.discover(str(start), pattern=args.pattern, top_level_dir=str(root))
         if start.is_dir() else unittest.TestSuite())


class Recorder(unittest.TextTestResult):
    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.cases = []

    def _record(self, test, status, msg=""):
        doc = (test._testMethodDoc or "").strip().splitlines()
        name = f"{test._testMethodName} {doc[0]}" if doc else test._testMethodName
        self.cases.append((type(test).__name__, name, status, msg))

    def addSuccess(self, test):
        super().addSuccess(test)
        self._record(test, "passed")

    def addFailure(self, test, err):
        super().addFailure(test, err)
        self._record(test, "failed", self._exc_info_to_string(err, test))

    def addError(self, test, err):
        super().addError(test, err)
        self._record(test, "failed", self._exc_info_to_string(err, test))

    def addSkip(self, test, reason):
        super().addSkip(test, reason)
        self._record(test, "skipped", reason)


result = unittest.TextTestRunner(resultclass=Recorder, verbosity=1).run(suite)
ts = ET.Element("testsuite", name=args.start, tests=str(len(result.cases)))
for classname, name, status, msg in result.cases:
    tc = ET.SubElement(ts, "testcase", classname=classname, name=name)
    if status == "failed":
        ET.SubElement(tc, "failure", message=msg[:200]).text = msg
    elif status == "skipped":
        ET.SubElement(tc, "skipped", message=msg)
Path(args.out).parent.mkdir(parents=True, exist_ok=True)
ET.ElementTree(ts).write(args.out, encoding="utf-8", xml_declaration=True)
sys.exit(0 if result.wasSuccessful() else 1)
