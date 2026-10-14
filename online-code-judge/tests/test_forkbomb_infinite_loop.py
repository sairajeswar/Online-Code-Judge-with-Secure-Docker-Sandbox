"""Adversarial security resilience tests: proving that the sandbox survives
fork-bombs and infinite loops without starving the host or crashing worker pools."""

import asyncio
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


class TestAdversarialResilience(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.runner = EmulatedSandboxRunner()
        self.pool = JudgeWorkerPool(num_workers=4, runner=self.runner)
        await self.pool.start()

    async def asyncTearDown(self):
        await self.pool.stop()

    async def test_fork_bomb_resilience(self):
        """Proof: An aggressive fork-bomb submission is trapped by pids-limit.
        The sandbox terminates it, yields RE, and the judge system remains healthy."""
        fork_bomb_code = """
import os
import sys

# Attempt to exhaust PID table
while True:
    try:
        os.fork()
    except Exception as e:
        sys.stderr.write(f"Fork failed: {e}\\n")
        sys.exit(1)
"""
        submission = Submission(
            id="sub-forkbomb-01",
            code=fork_bomb_code,
            language=Language.PYTHON,
            test_cases=[
                TestCase(id=1, stdin="", expected_stdout="survived\n"),
            ],
            config=SandboxConfig(pids_limit=64, time_limit_ms=2000),
        )

        result = await self.pool.submit(submission)

        # Verdict must be RE (due to blocked fork / pids limit exhaustion)
        self.assertEqual(result.verdict, Verdict.RE)
        self.assertTrue(
            result.test_case_results[0].verdict in (Verdict.RE, Verdict.TLE),
            "Fork bomb must not execute to completion or cause system error",
        )

        # Verification: System and worker pool remain alive and can handle normal AC submissions
        followup_sub = Submission(
            id="sub-followup-ac",
            code="print('Judge is alive and healthy')",
            language=Language.PYTHON,
            test_cases=[
                TestCase(id=1, stdin="", expected_stdout="Judge is alive and healthy\n"),
            ],
            config=SandboxConfig(time_limit_ms=1000),
        )
        followup_res = await self.pool.submit(followup_sub)
        self.assertEqual(followup_res.verdict, Verdict.AC)
        self.assertEqual(followup_res.test_case_results[0].stdout.strip(), "Judge is alive and healthy")

    async def test_infinite_loop_resilience(self):
        """Proof: An infinite loop spinning CPU at 100% is killed strictly at time_limit_ms.
        Yields TLE, frees worker immediately, and worker pool continues cleanly."""
        infinite_loop_code = """
# Infinite CPU burn
i = 0
while True:
    i = (i + 1) % 1000000
"""
        time_limit_ms = 400  # Strict 400ms limit
        submission = Submission(
            id="sub-infloop-01",
            code=infinite_loop_code,
            language=Language.PYTHON,
            test_cases=[
                TestCase(id=1, stdin="", expected_stdout="never\n"),
            ],
            config=SandboxConfig(time_limit_ms=time_limit_ms, cpu_limit=1.0),
        )

        start_time = asyncio.get_event_loop().time()
        result = await self.pool.submit(submission)
        duration_sec = asyncio.get_event_loop().time() - start_time

        # Verdict must be TLE
        self.assertEqual(result.verdict, Verdict.TLE)
        self.assertEqual(result.test_case_results[0].verdict, Verdict.TLE)

        # Cutoff timing should be bounded close to the time limit (allow generous buffer for async scheduling)
        self.assertLess(duration_sec, 2.5, "Infinite loop was not terminated in a timely manner")

        # Worker pool is immediately ready for next job
        followup_sub = Submission(
            id="sub-followup-ac-2",
            code="print(42)",
            language=Language.PYTHON,
            test_cases=[
                TestCase(id=1, stdin="", expected_stdout="42\n"),
            ],
            config=SandboxConfig(time_limit_ms=1000),
        )
        followup_res = await self.pool.submit(followup_sub)
        self.assertEqual(followup_res.verdict, Verdict.AC)

    async def test_concurrent_adversarial_barrage(self):
        """Submits multiple fork-bombs and infinite-loops simultaneously to verify worker pool stability."""
        tasks = []
        for i in range(5):
            tasks.append(self.pool.submit(Submission(
                id=f"fork-{i}",
                code="import os\nwhile True:\n    os.fork()",
                language=Language.PYTHON,
                test_cases=[TestCase(id=1, stdin="", expected_stdout="out\n")],
                config=SandboxConfig(time_limit_ms=500, pids_limit=64),
            )))
            tasks.append(self.pool.submit(Submission(
                id=f"loop-{i}",
                code="while True: pass",
                language=Language.PYTHON,
                test_cases=[TestCase(id=1, stdin="", expected_stdout="out\n")],
                config=SandboxConfig(time_limit_ms=300),
            )))
            tasks.append(self.pool.submit(Submission(
                id=f"ac-{i}",
                code="print('ok')",
                language=Language.PYTHON,
                test_cases=[TestCase(id=1, stdin="", expected_stdout="ok\n")],
                config=SandboxConfig(time_limit_ms=1000),
            )))

        results = await asyncio.gather(*tasks)
        self.assertEqual(len(results), 15)

        # Confirm expected verdicts
        fork_verdicts = [r.verdict for r in results if r.submission_id.startswith("fork-")]
        loop_verdicts = [r.verdict for r in results if r.submission_id.startswith("loop-")]
        ac_verdicts = [r.verdict for r in results if r.submission_id.startswith("ac-")]

        for v in fork_verdicts:
            self.assertIn(v, (Verdict.RE, Verdict.TLE))
        for v in loop_verdicts:
            self.assertEqual(v, Verdict.TLE)
        for v in ac_verdicts:
            self.assertEqual(v, Verdict.AC)


if __name__ == "__main__":
    unittest.main()
