"""Asynchronous submission queue and worker pool for the Online Code Judge."""

import asyncio
import time
from typing import Dict, List, Optional, Tuple
import statistics

from judge.models import (
    Submission,
    SubmissionResult,
    Verdict,
    TestCaseResult,
)
from judge.evaluator import Evaluator
from judge.sandbox import BaseSandboxRunner, get_default_runner


class WorkerMetrics:
    """Tracks latency percentiles and throughput for the judge."""

    def __init__(self):
        self.submissions_received: int = 0
        self.submissions_completed: int = 0
        self.verdicts_count: Dict[Verdict, int] = {v: 0 for v in Verdict}
        self.latencies_ms: List[float] = []
        self.queue_wait_ms: List[float] = []
        self.execution_times_ms: List[float] = []
        self.start_time: float = time.time()

    def record_completed(
        self,
        verdict: Verdict,
        total_time_ms: float,
        queue_time_ms: float,
        execution_time_ms: float,
    ):
        self.submissions_completed += 1
        self.verdicts_count[verdict] = self.verdicts_count.get(verdict, 0) + 1
        self.latencies_ms.append(total_time_ms)
        self.queue_wait_ms.append(queue_time_ms)
        self.execution_times_ms.append(execution_time_ms)

    def get_summary(self) -> Dict[str, any]:
        elapsed_sec = max(time.time() - self.start_time, 0.001)
        throughput = self.submissions_completed / elapsed_sec

        def calc_percentile(data: List[float], p: float) -> float:
            if not data:
                return 0.0
            sorted_data = sorted(data)
            k = (len(sorted_data) - 1) * (p / 100.0)
            f = int(k)
            c = min(f + 1, len(sorted_data) - 1)
            d = k - f
            return sorted_data[f] + (sorted_data[c] - sorted_data[f]) * d

        return {
            "received": self.submissions_received,
            "completed": self.submissions_completed,
            "throughput_req_per_sec": round(throughput, 2),
            "verdicts": {v.value: count for v, count in self.verdicts_count.items() if count > 0},
            "latency_p50_ms": round(calc_percentile(self.latencies_ms, 50), 2),
            "latency_p95_ms": round(calc_percentile(self.latencies_ms, 95), 2),
            "latency_p99_ms": round(calc_percentile(self.latencies_ms, 99), 2),
            "avg_queue_wait_ms": round(statistics.mean(self.queue_wait_ms) if self.queue_wait_ms else 0.0, 2),
            "avg_execution_ms": round(statistics.mean(self.execution_times_ms) if self.execution_times_ms else 0.0, 2),
        }


class JudgeWorkerPool:
    """Manages worker coroutines processing judge submissions from an asyncio Queue."""

    def __init__(
        self,
        num_workers: int = 10,
        runner: Optional[BaseSandboxRunner] = None,
        max_queue_size: int = 1000,
    ):
        self.num_workers = num_workers
        self.runner = runner or get_default_runner()
        self.queue: asyncio.Queue[Tuple[Submission, asyncio.Future[SubmissionResult]]] = asyncio.Queue(maxsize=max_queue_size)
        self.workers: List[asyncio.Task] = []
        self.is_running: bool = False
        self.metrics = WorkerMetrics()
        self.active_workers_count: int = 0
        self._lock = asyncio.Lock()

    async def start(self):
        """Spawns the pool of background judge workers."""
        if self.is_running:
            return
        self.is_running = True
        self.metrics = WorkerMetrics()
        self.workers = [
            asyncio.create_task(self._worker_loop(f"worker-{i+1}"))
            for i in range(self.num_workers)
        ]

    async def stop(self):
        """Gracefully stops all workers in the pool."""
        self.is_running = False
        for _ in self.workers:
            await self.queue.put((None, None))  # Sentinel to terminate worker
        await asyncio.gather(*self.workers, return_exceptions=True)
        self.workers.clear()

    async def submit(self, submission: Submission) -> SubmissionResult:
        """Pushes a submission to the queue and awaits its final evaluated result."""
        if not self.is_running:
            raise RuntimeError("Judge worker pool is not running. Call await start() first.")

        self.metrics.submissions_received += 1
        loop = asyncio.get_running_loop()
        future: asyncio.Future[SubmissionResult] = loop.create_future()

        await self.queue.put((submission, future))
        return await future

    async def _worker_loop(self, worker_id: str):
        """Worker loop continuously fetching and grading submissions."""
        while self.is_running:
            try:
                submission, future = await self.queue.get()
                if submission is None:  # Shutdown sentinel
                    self.queue.task_done()
                    break

                queue_wait_ms = (time.time() - submission.created_at) * 1000.0

                async with self._lock:
                    self.active_workers_count += 1

                exec_start = time.perf_counter()
                tc_results: List[TestCaseResult] = []

                # Grade each test case sequentially (stops early on first failure if desired)
                for tc in submission.test_cases:
                    raw_res = await self.runner.run(
                        code=submission.code,
                        language=submission.language,
                        stdin_data=tc.stdin,
                        config=submission.config,
                    )
                    tc_res = Evaluator.evaluate_test_case(
                        test_case=tc,
                        raw=raw_res,
                        output_limit_bytes=submission.config.output_limit_bytes,
                    )
                    tc_results.append(tc_res)

                    # Short-circuit on fatal runtime / limit breach
                    if tc_res.verdict in (Verdict.TLE, Verdict.MLE, Verdict.RE, Verdict.OLE):
                        break

                exec_elapsed_ms = (time.perf_counter() - exec_start) * 1000.0
                submission_result = Evaluator.aggregate_submission(submission, tc_results)
                submission_result.worker_id = worker_id
                submission_result.queued_duration_ms = queue_wait_ms
                submission_result.execution_duration_ms = exec_elapsed_ms

                total_latency_ms = queue_wait_ms + exec_elapsed_ms

                self.metrics.record_completed(
                    verdict=submission_result.verdict,
                    total_time_ms=total_latency_ms,
                    queue_time_ms=queue_wait_ms,
                    execution_time_ms=exec_elapsed_ms,
                )

                async with self._lock:
                    self.active_workers_count -= 1

                if not future.done():
                    future.set_result(submission_result)

                self.queue.task_done()

            except asyncio.CancelledError:
                break
            except Exception as e:
                async with self._lock:
                    if self.active_workers_count > 0:
                        self.active_workers_count -= 1
                if 'future' in locals() and not future.done():
                    future.set_exception(e)
                self.queue.task_done()
