# Hardened Online Code Judge

A production-grade, secure online code judge built to run untrusted code in an isolated Docker sandbox with resource quotas, queue-driven worker concurrency, and comprehensive defense-in-depth security.

---

## Key Features

* **Strict Docker Sandbox Boundaries**:
  * **Network Isolation**: `--network none` (blocks exfiltration, C2, port scanning).
  * **Memory Limits**: `--memory 128m --memory-swap 128m` (strict cgroup memory ceilings; OOM killer triggers exit 137).
  * **CPU Limits**: `--cpus 1.0` (pinned CPU core allocation).
  * **Process Limits**: `--pids-limit 64` (instantly neutralizes fork-bombs with `EAGAIN`).
  * **Unprivileged User**: `--user 10001:10001` (user `judge`).
  * **Read-Only Filesystem**: `--read-only` (prevents filesystem tampering).
  * **Volatile Scratch Memory**: `--tmpfs /tmp:rw,noexec,nosuid,size=32m` (prevents binary execution from `/tmp`).
  * **Capability Dropping**: `--cap-drop ALL` (removes all Linux capabilities).
  * **Privilege Escalation Lock**: `--security-opt no-new-privileges:true` (blocks SUID escalation).
* **Asynchronous Queue & Worker Pool**:
  * Bounded FIFO task queue with backpressure.
  * Worker pool (e.g. 20 concurrent workers) managing parallel execution without host saturation.
  * Real-time metrics: throughput (req/sec), P50/P95/P99 latency tracking, queue wait times.
* **Complete Verdict Support**:
  * `AC` (Accepted)
  * `WA` (Wrong Answer)
  * `TLE` (Time Limit Exceeded - enforced by container watchdog)
  * `MLE` (Memory Limit Exceeded - detected via cgroup OOM killer exit 137)
  * `RE` (Runtime Error - unhandled exceptions or blocked fork-bombs)
  * `CE` (Compilation Error)
  * `OLE` (Output Limit Exceeded - stdout capped to 1MB)
* **Adversarial Resilience & Proof**:
  * **200 Concurrent Submissions Load Test**: Submits 200 concurrent tasks spanning all verdicts, drains queue across worker pool, and measures throughput and latency.
  * **Fork-Bomb Test**: Untrusted code attempts to exhaust the PID table (`os.fork()` / `:(){ :|:& };:`). Sandbox terminates it cleanly via `pids-limit 64`, system survives, and worker remains ready.
  * **Infinite-Loop Test**: Untrusted code spins CPU indefinitely (`while True: pass`). Watchdog terminates container at deadline, assigns TLE, and reclaims resources.
* **Throwaway VM Threat Model**:
  * Acknowledges that containers share the host Linux kernel and cannot guarantee 100% security against kernel 0-days or microarchitectural side-channels.
  * Provides automated provisioning scripts (`scripts/provision_throwaway_vm.sh`) to run the judge on disposable cloud VMs destroyed after use.

---

## Project Structure

```
online-code-judge/
├── Dockerfile.sandbox            # Hardened Docker container for submissions
├── THREAT_MODEL.md               # Candid security threat model and defense layers
├── README.md                     # Documentation and usage guide
├── judge/
│   ├── __init__.py               # Package exports
│   ├── models.py                 # Submission, TestCase, Verdict, SandboxConfig
│   ├── evaluator.py              # Output normalization and verdict mapping
│   ├── sandbox.py                # DockerSandboxRunner & EmulatedSandboxRunner
│   └── worker_pool.py            # Async Queue, WorkerPool, and Latency Metrics
├── tests/
│   ├── test_verdicts.py          # Unit tests for AC, WA, TLE, MLE, RE, OLE
│   ├── test_forkbomb_infinite_loop.py # Adversarial resilience tests
│   ├── test_load_200.py          # 200 concurrent submission load test proof
│   └── run_all_tests.py          # Master test suite runner
└── scripts/
    └── provision_throwaway_vm.sh # Disposable cloud VM launcher (GCP / AWS)
```

---

## Running the Test Suite & Load Test

To run the complete test suite (unit tests, fork-bomb resilience, infinite-loop timeout, and the 200 concurrent submission load test):

```bash
python tests/run_all_tests.py
```

### Verified Load Test Results (Sample Run)

```text
=======================================================
[1] RUNNING UNIT & ADVERSARIAL RESILIENCE SUITE
=======================================================
test_accepted_verdict_ac ... ok
test_memory_limit_exceeded_mle ... ok
test_output_limit_exceeded_ole ... ok
test_runtime_error_re ... ok
test_time_limit_exceeded_tle ... ok
test_wrong_answer_verdict_wa ... ok
test_concurrent_adversarial_barrage ... ok
test_fork_bomb_resilience (Fork-bomb trapped by pids-limit) ... ok
test_infinite_loop_resilience (Terminated strictly at time limit) ... ok

Ran 9 tests in 0.877s -> OK

=======================================================
[2] RUNNING 200 CONCURRENT SUBMISSION LOAD TEST
=======================================================
[*] INITIATING LOAD TEST: 200 CONCURRENT SUBMISSIONS
[*] Worker Pool Size: 20 parallel workers
[*] Sandbox Runner:   EmulatedSandboxRunner

Dispatching all 200 submissions to worker pool concurrently...

=======================================================
[+] 200 CONCURRENT SUBMISSIONS LOAD TEST RESULTS
=======================================================
Total Submissions:     200 / 200
Total Wall Clock Time: 0.233 seconds
System Throughput:     854.98 submissions/sec
Latency P50:           12.48 ms
Latency P95:           160.41 ms
Latency P99:           232.85 ms
Avg Queue Wait Time:   42.53 ms
Avg Execution Time:    16.67 ms
-------------------------------------------------------
Verdicts Breakdown:    {'AC': 100, 'WA': 30, 'TLE': 25, 'MLE': 25, 'RE': 20}
Ground Truth Match:    200 / 200 (100.0%)
Queue Drained:         True
Active Workers Left:   0
=======================================================

[SUCCESS] ALL TESTS PASSED! Proof verified successfully.
```

---

## Deploying on a Throwaway VM

To run against real Docker on a disposable cloud instance:

1. Execute the provisioning script:
   ```bash
   bash scripts/provision_throwaway_vm.sh gcp
   ```
2. Build the sandbox image:
   ```bash
   docker build -t judge-sandbox:latest -f Dockerfile.sandbox .
   ```
3. Run the judge using `JUDGE_RUNNER=docker`:
   ```bash
   JUDGE_RUNNER=docker python3 tests/run_all_tests.py
   ```
4. Destroy the throwaway VM when finished to guarantee blast-radius containment.
