"""Unit tests for judge verdict classification (AC, WA, TLE, MLE, RE, OLE)."""

import asyncio
import sys
import unittest
from judge.models import (
    Submission,
    TestCase,
    Verdict,
    Language,
    SandboxConfig,
)
from judge.worker_pool import JudgeWorkerPool
from judge.sandbox import EmulatedSandboxRunner


class TestVerdicts(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.runner = EmulatedSandboxRunner()
        self.pool = JudgeWorkerPool(num_workers=4, runner=self.runner)
        await self.pool.start()

    async def asyncTearDown(self):
        await self.pool.stop()

    async def test_accepted_verdict_ac(self):
        code = "a, b = map(int, input().split())\nprint(a + b)"
        submission = Submission(
            id="sub-ac",
            code=code,
            language=Language.PYTHON,
            test_cases=[
                TestCase(id=1, stdin="2 3\n", expected_stdout="5\n"),
                TestCase(id=2, stdin="10 20\n", expected_stdout="30\n"),
            ],
            config=SandboxConfig(time_limit_ms=1000, memory_limit_mb=64),
        )
        result = await self.pool.submit(submission)
        self.assertEqual(result.verdict, Verdict.AC)
        self.assertEqual(len(result.test_case_results), 2)
        self.assertEqual(result.test_case_results[0].verdict, Verdict.AC)
        self.assertEqual(result.test_case_results[1].verdict, Verdict.AC)

    async def test_wrong_answer_verdict_wa(self):
        code = "a, b = map(int, input().split())\nprint(a * b)"  # multiplies instead of adding
        submission = Submission(
            id="sub-wa",
            code=code,
            language=Language.PYTHON,
            test_cases=[
                TestCase(id=1, stdin="2 3\n", expected_stdout="5\n"),
            ],
            config=SandboxConfig(time_limit_ms=1000, memory_limit_mb=64),
        )
        result = await self.pool.submit(submission)
        self.assertEqual(result.verdict, Verdict.WA)
        self.assertEqual(result.test_case_results[0].verdict, Verdict.WA)

    async def test_time_limit_exceeded_tle(self):
        code = "import time\ntime.sleep(2.0)\nprint('done')"
        submission = Submission(
            id="sub-tle",
            code=code,
            language=Language.PYTHON,
            test_cases=[
                TestCase(id=1, stdin="", expected_stdout="done\n"),
            ],
            config=SandboxConfig(time_limit_ms=300),  # 300ms limit
        )
        result = await self.pool.submit(submission)
        self.assertEqual(result.verdict, Verdict.TLE)
        self.assertEqual(result.test_case_results[0].verdict, Verdict.TLE)

    async def test_memory_limit_exceeded_mle(self):
        code = "x = bytearray(1024 * 1024 * 1024)\nprint(len(x))"  # Allocates 1GB
        submission = Submission(
            id="sub-mle",
            code=code,
            language=Language.PYTHON,
            test_cases=[
                TestCase(id=1, stdin="", expected_stdout="1073741824\n"),
            ],
            config=SandboxConfig(memory_limit_mb=64),
        )
        result = await self.pool.submit(submission)
        self.assertEqual(result.verdict, Verdict.MLE)
        self.assertEqual(result.test_case_results[0].verdict, Verdict.MLE)

    async def test_runtime_error_re(self):
        code = "x = 1 / 0\nprint(x)"  # ZeroDivisionError
        submission = Submission(
            id="sub-re",
            code=code,
            language=Language.PYTHON,
            test_cases=[
                TestCase(id=1, stdin="", expected_stdout="0\n"),
            ],
            config=SandboxConfig(time_limit_ms=1000),
        )
        result = await self.pool.submit(submission)
        self.assertEqual(result.verdict, Verdict.RE)
        self.assertEqual(result.test_case_results[0].verdict, Verdict.RE)

    async def test_output_limit_exceeded_ole(self):
        code = "print('A' * 2000000)"  # 2MB of output
        submission = Submission(
            id="sub-ole",
            code=code,
            language=Language.PYTHON,
            test_cases=[
                TestCase(id=1, stdin="", expected_stdout=""),
            ],
            config=SandboxConfig(output_limit_bytes=100000),  # 100KB limit
        )
        result = await self.pool.submit(submission)
        self.assertEqual(result.verdict, Verdict.OLE)
        self.assertEqual(result.test_case_results[0].verdict, Verdict.OLE)


if __name__ == "__main__":
    unittest.main()
