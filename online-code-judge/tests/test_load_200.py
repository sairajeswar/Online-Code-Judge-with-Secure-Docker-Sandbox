"""Proof: High-concurrency load test of 200 simultaneous submissions across worker pool.
Validates queue handling, worker pool throughput, latency percentiles, and ground-truth verdicts."""

import asyncio
import time
from typing import List, Tuple
from judge.models import (
    Submission,
    TestCase,
    Verdict,
    Language,
    SandboxConfig,
)
from judge.worker_pool import JudgeWorkerPool
from judge.sandbox import get_default_runner


async def run_200_concurrent_load_test(num_workers: int = 20) -> dict:
    runner = get_default_runner()
    pool = JudgeWorkerPool(num_workers=num_workers, runner=runner)
    await pool.start()

    print(f"\n=======================================================")
    print(f"[*] INITIATING LOAD TEST: 200 CONCURRENT SUBMISSIONS")
    print(f"[*] Worker Pool Size: {num_workers} parallel workers")
    print(f"[*] Sandbox Runner:   {runner.__class__.__name__}")
    print(f"=======================================================\n")

    # Construct 200 diverse submissions with known expected verdicts
    submissions_plan: List[Tuple[Submission, Verdict]] = []

    # 1. 100 Accepted (AC) submissions
    for i in range(100):
        sub = Submission(
            id=f"load-ac-{i:03d}",
            code=f"a, b = map(int, input().split())\nprint(a + b + {i})",
            language=Language.PYTHON,
            test_cases=[
                TestCase(id=1, stdin=f"10 20\n", expected_stdout=f"{30 + i}\n"),
            ],
            config=SandboxConfig(time_limit_ms=500, memory_limit_mb=64),
        )
        submissions_plan.append((sub, Verdict.AC))

    # 2. 30 Wrong Answer (WA) submissions
    for i in range(30):
        sub = Submission(
            id=f"load-wa-{i:03d}",
            code="a, b = map(int, input().split())\nprint(a * b)",
            language=Language.PYTHON,
            test_cases=[
                TestCase(id=1, stdin="10 20\n", expected_stdout="30\n"),
            ],
            config=SandboxConfig(time_limit_ms=500, memory_limit_mb=64),
        )
        submissions_plan.append((sub, Verdict.WA))

    # 3. 25 Time Limit Exceeded (TLE) submissions (infinite loops / sleeps)
    for i in range(25):
        sub = Submission(
            id=f"load-tle-{i:03d}",
            code="while True: pass",
            language=Language.PYTHON,
            test_cases=[
                TestCase(id=1, stdin="", expected_stdout="done\n"),
            ],
            config=SandboxConfig(time_limit_ms=100),  # short 100ms timeout for load speed
        )
        submissions_plan.append((sub, Verdict.TLE))

    # 4. 25 Memory Limit Exceeded (MLE) submissions
    for i in range(25):
        sub = Submission(
            id=f"load-mle-{i:03d}",
            code="b = bytearray(1024 * 1024 * 1024)\nprint(len(b))",
            language=Language.PYTHON,
            test_cases=[
                TestCase(id=1, stdin="", expected_stdout="1073741824\n"),
            ],
            config=SandboxConfig(memory_limit_mb=64),
        )
        submissions_plan.append((sub, Verdict.MLE))

    # 5. 10 Fork-bomb submissions (RE - PIDs limit)
    for i in range(10):
        sub = Submission(
            id=f"load-fork-{i:03d}",
            code="import os\nwhile True:\n    os.fork()",
            language=Language.PYTHON,
            test_cases=[
                TestCase(id=1, stdin="", expected_stdout="out\n"),
            ],
            config=SandboxConfig(pids_limit=64, time_limit_ms=300),
        )
        submissions_plan.append((sub, Verdict.RE))

    # 6. 10 Runtime Error (RE) submissions (ZeroDivisionError)
    for i in range(10):
        sub = Submission(
            id=f"load-re-{i:03d}",
            code="x = 1 / 0",
            language=Language.PYTHON,
            test_cases=[
                TestCase(id=1, stdin="", expected_stdout="0\n"),
            ],
            config=SandboxConfig(time_limit_ms=500),
        )
        submissions_plan.append((sub, Verdict.RE))

    assert len(submissions_plan) == 200, f"Expected 200 submissions, got {len(submissions_plan)}"

    # Launch all 200 concurrently
    print(f"Dispatching all 200 submissions to worker pool concurrently...")
    start_time = time.perf_counter()

    tasks = [pool.submit(sub) for sub, _ in submissions_plan]
    results = await asyncio.gather(*tasks)

    elapsed_time = time.perf_counter() - start_time

    # Verify verdicts
    mismatches = []
    verdicts_summary = {}
    for (sub, expected_verdict), result in zip(submissions_plan, results):
        verdicts_summary[result.verdict.value] = verdicts_summary.get(result.verdict.value, 0) + 1
        if result.verdict != expected_verdict:
            mismatches.append({
                "submission_id": sub.id,
                "expected": expected_verdict.value,
                "actual": result.verdict.value,
            })

    metrics = pool.metrics.get_summary()
    await pool.stop()

    print(f"\n=======================================================")
    print(f"[+] 200 CONCURRENT SUBMISSIONS LOAD TEST RESULTS")
    print(f"=======================================================")
    print(f"Total Submissions:     {len(results)} / 200")
    print(f"Total Wall Clock Time: {elapsed_time:.3f} seconds")
    print(f"System Throughput:     {metrics['throughput_req_per_sec']} submissions/sec")
    print(f"Latency P50:           {metrics['latency_p50_ms']} ms")
    print(f"Latency P95:           {metrics['latency_p95_ms']} ms")
    print(f"Latency P99:           {metrics['latency_p99_ms']} ms")
    print(f"Avg Queue Wait Time:   {metrics['avg_queue_wait_ms']} ms")
    print(f"Avg Execution Time:    {metrics['avg_execution_ms']} ms")
    print(f"-------------------------------------------------------")
    print(f"Verdicts Breakdown:    {verdicts_summary}")
    print(f"Ground Truth Match:    {200 - len(mismatches)} / 200 ({100.0 * (200 - len(mismatches)) / 200:.1f}%)")
    print(f"Queue Drained:         {pool.queue.empty()}")
    print(f"Active Workers Left:   {pool.active_workers_count}")
    print(f"=======================================================\n")

    if mismatches:
        print(f"[!] Warning: {len(mismatches)} mismatches detected:")
        for m in mismatches[:5]:
            print(f"  {m}")

    return {
        "total": len(results),
        "wall_clock_sec": elapsed_time,
        "metrics": metrics,
        "verdicts": verdicts_summary,
        "mismatches": len(mismatches),
    }


if __name__ == "__main__":
    asyncio.run(run_200_concurrent_load_test())
