"""Readable, color-aware unittest output for BiteFinder scenario tests."""

import os
import time
import unittest
from textwrap import dedent


class FriendlyTestResult(unittest.TextTestResult):
    """Show each scenario, its expected behavior, observed result, and calls."""

    def __init__(self, stream, descriptions, verbosity):
        super().__init__(stream, descriptions, verbosity)
        setting = os.getenv("BITEFINDER_TEST_COLOR", "auto").lower()
        actual_stream = getattr(stream, "stream", stream)
        self.use_color = (setting == "always" or
                          (setting != "never" and
                           "NO_COLOR" not in os.environ and
                           actual_stream.isatty()))

    def style(self, value, code):
        return f"\033[{code}m{value}\033[0m" if self.use_color else value

    def getDescription(self, test):
        title = dedent(test._testMethodDoc or test._testMethodName).strip().splitlines()[0]
        return f"{getattr(test, 'report_group', 'BiteFinder')}: {title}"

    def startTest(self, test):
        unittest.result.TestResult.startTest(self, test)
        test._friendly_report = True
        test._report_started = time.monotonic()
        test._report_counts = (len(self.failures), len(self.errors),
                               len(self.skipped), len(self.unexpectedSuccesses))
        lines = dedent(test._testMethodDoc or "").strip().splitlines()
        title = lines[0] if lines else test._testMethodName
        self.stream.writeln("\n" + self.style(f"{self.testsRun}. {title}", "1;36"))
        for line in lines[1:]:
            if line.strip():
                self.stream.writeln("   " + self.style(line.strip(), "36"))

    def stopTest(self, test):
        details = test.report_details()
        self.stream.writeln("   " + self.style(details["target_label"] + ":", "35")
                            + f" {details['target']}")
        self.stream.writeln("   " + self.style(details["observed_label"] + ":", "32"))
        observed = details["observed"]
        for line in observed[:4]:
            self.stream.writeln(f"     {line}")
        if len(observed) > 4:
            self.stream.writeln(f"     ...and {len(observed) - 4} more checked lines")
        if not observed:
            self.stream.writeln("     No result recorded; see failure details.")
        calls = details["calls"]
        if calls:
            self.stream.writeln("   " + self.style(details["calls_label"] + ":", "33"))
            for number, call in enumerate(calls, 1):
                self.stream.writeln(f"     {number}. {call}")
        else:
            self.stream.writeln("   " + self.style(details["calls_label"] + ":", "33")
                                + " " + details["no_calls"])
        before = test._report_counts
        if len(self.failures) > before[0] or len(self.errors) > before[1]:
            status, color = "FAIL", "1;31"
        elif len(self.unexpectedSuccesses) > before[3]:
            status, color = "UNEXPECTED PASS", "1;33"
        elif len(self.skipped) > before[2]:
            status, color = "SKIP", "1;33"
        else:
            status, color = "PASS", "1;32"
        elapsed = time.monotonic() - test._report_started
        self.stream.writeln("   " + self.style(status, color)
                            + f" ({elapsed:.2f}s)")
        unittest.result.TestResult.stopTest(self, test)

    def addSuccess(self, test):
        unittest.result.TestResult.addSuccess(self, test)

    def addFailure(self, test, err):
        unittest.result.TestResult.addFailure(self, test, err)

    def addError(self, test, err):
        unittest.result.TestResult.addError(self, test, err)

    def addSkip(self, test, reason):
        unittest.result.TestResult.addSkip(self, test, reason)

    def addSubTest(self, test, subtest, err):
        unittest.result.TestResult.addSubTest(self, test, subtest, err)


class FriendlyTestRunner(unittest.TextTestRunner):
    resultclass = FriendlyTestResult


def run_friendly_suite(suite, heading):
    """Run one unittest suite with the readable report and proper exit code."""
    runner = FriendlyTestRunner(verbosity=0)
    runner.stream.writeln(runner._makeResult().style(heading, "1;35"))
    result = runner.run(suite)
    raise SystemExit(0 if result.wasSuccessful() else 1)
