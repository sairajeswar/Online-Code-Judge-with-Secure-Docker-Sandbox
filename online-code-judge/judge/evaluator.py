"""Evaluator logic: maps raw execution results to Verdicts (AC, WA, TLE, MLE, RE, CE, OLE)."""

from typing import List
from judge.models import (
    Verdict,
    TestCase,
    TestCaseResult,
    ExecutionRawResult,
    SubmissionResult,
    Submission,
)


class Evaluator:
    """Evaluates test cases against expected outputs and maps verdicts."""

    @staticmethod
    def normalize_output(text: str) -> str:
        """Strip trailing whitespace from each line and trailing newlines."""
        if text is None:
            return ""
        lines = [line.rstrip() for line in text.splitlines()]
        # Remove trailing empty lines
        while lines and not lines[-1]:
            lines.pop()
        return "\n".join(lines)

    @classmethod
    def evaluate_test_case(
        cls, test_case: TestCase, raw: ExecutionRawResult, output_limit_bytes: int = 1048576
    ) -> TestCaseResult:
        """Determines the verdict for a single testcase."""
        # 1. Check for output limit exceeded (OLE)
        if raw.output_exceeded or len(raw.stdout.encode("utf-8", errors="ignore")) > output_limit_bytes:
            return TestCaseResult(
                test_case_id=test_case.id,
                verdict=Verdict.OLE,
                time_taken_ms=raw.wall_time_ms,
                memory_used_mb=raw.memory_used_mb,
                stdout=raw.stdout[:500] + "... [TRUNCATED]",
                stderr=raw.stderr,
                exit_code=raw.exit_code,
                error_message="Output limit exceeded (OLE)",
            )

        # 2. Check for Time Limit Exceeded (TLE)
        if raw.timed_out:
            return TestCaseResult(
                test_case_id=test_case.id,
                verdict=Verdict.TLE,
                time_taken_ms=raw.wall_time_ms,
                memory_used_mb=raw.memory_used_mb,
                stdout=raw.stdout,
                stderr=raw.stderr,
                exit_code=raw.exit_code,
                error_message="Execution timed out (TLE)",
            )

        # 3. Check for Memory Limit Exceeded (MLE)
        # In Linux/Docker, process killed by OOM killer receives SIGKILL (signal 9 -> exit code 137)
        if raw.oom_killed or raw.exit_code == 137:
            return TestCaseResult(
                test_case_id=test_case.id,
                verdict=Verdict.MLE,
                time_taken_ms=raw.wall_time_ms,
                memory_used_mb=raw.memory_used_mb,
                stdout=raw.stdout,
                stderr=raw.stderr,
                exit_code=raw.exit_code,
                error_message="Out of memory: process killed by cgroup OOM killer (exit 137)",
            )

        # 4. Check for Runtime Error (RE)
        # Fork-bomb failure (EAGAIN / Resource temporarily unavailable) or unhandled exceptions
        if raw.pids_exhausted or raw.exit_code != 0:
            err_msg = raw.error_message or f"Process exited with non-zero status code: {raw.exit_code}"
            if "Resource temporarily unavailable" in raw.stderr or "BlockingIOError" in raw.stderr or raw.pids_exhausted:
                err_msg = "Process limit (PID limit) reached - fork bomb prevented (RE)"
            return TestCaseResult(
                test_case_id=test_case.id,
                verdict=Verdict.RE,
                time_taken_ms=raw.wall_time_ms,
                memory_used_mb=raw.memory_used_mb,
                stdout=raw.stdout,
                stderr=raw.stderr,
                exit_code=raw.exit_code,
                error_message=err_msg,
            )

        # 5. Output comparison (AC vs WA)
        norm_actual = cls.normalize_output(raw.stdout)
        norm_expected = cls.normalize_output(test_case.expected_stdout)

        if norm_actual == norm_expected:
            verdict = Verdict.AC
            err_msg = None
        else:
            verdict = Verdict.WA
            err_msg = f"Output mismatch. Expected: '{norm_expected[:100]}', got: '{norm_actual[:100]}'"

        return TestCaseResult(
            test_case_id=test_case.id,
            verdict=verdict,
            time_taken_ms=raw.wall_time_ms,
            memory_used_mb=raw.memory_used_mb,
            stdout=raw.stdout,
            stderr=raw.stderr,
            exit_code=raw.exit_code,
            error_message=err_msg,
        )

    @classmethod
    def aggregate_submission(
        cls,
        submission: Submission,
        results: List[TestCaseResult],
        compile_output: str = None,
        is_ce: bool = False,
    ) -> SubmissionResult:
        """Determines overall submission verdict by finding the first failing verdict, or AC."""
        if is_ce:
            return SubmissionResult(
                submission_id=submission.id,
                verdict=Verdict.CE,
                test_case_results=[],
                total_time_ms=0.0,
                max_memory_mb=0.0,
                compile_output=compile_output or "Compilation error",
            )

        if not results:
            return SubmissionResult(
                submission_id=submission.id,
                verdict=Verdict.SE,
                test_case_results=[],
                total_time_ms=0.0,
                max_memory_mb=0.0,
                compile_output="No test cases were executed",
            )

        # Priority of verdicts: SE > OLE > MLE > TLE > RE > WA > AC
        priority = {
            Verdict.SE: 1,
            Verdict.OLE: 2,
            Verdict.MLE: 3,
            Verdict.TLE: 4,
            Verdict.RE: 5,
            Verdict.WA: 6,
            Verdict.AC: 7,
        }

        # Overall verdict is typically the first non-AC verdict encountered
        overall_verdict = Verdict.AC
        for r in results:
            if r.verdict != Verdict.AC:
                overall_verdict = r.verdict
                break

        total_time = sum(r.time_taken_ms for r in results)
        max_mem = max(r.memory_used_mb for r in results) if results else 0.0

        return SubmissionResult(
            submission_id=submission.id,
            verdict=overall_verdict,
            test_case_results=results,
            total_time_ms=total_time,
            max_memory_mb=max_mem,
            compile_output=compile_output,
        )
