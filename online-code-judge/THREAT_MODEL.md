# Threat Model & Security Architecture for Online Code Judge

> **Fundamental Principle**: Running arbitrary untrusted code is an inherently adversarial workload. Containers alone are **NOT** a hard security boundary. Any online judge claiming its container sandbox is "secure" is either misunderstanding the Linux kernel or being dishonest. 
> 
> True defense-in-depth requires acknowledging container escape vectors and isolating the entire execution fleet inside **ephemeral, throwaway Virtual Machines (VMs)**.

---

## 1. Attacker Profile & Goals

In an open online judge, the submission input is untrusted code compiled and executed on backend infrastructure. An attacker may attempt:

1. **Host Compromise & Persistence**: Escaping the container to gain root on the host machine, installing rootkits or backdoors.
2. **Denial of Service (DoS)**: Exhausting CPU, memory, process IDs, or disk space to disrupt other students or crash the judge.
3. **Data Exfiltration / Network Abuse**: Probing internal infrastructure, hitting cloud metadata APIs (`169.254.169.254`), sending spam, or using the judge for cryptomining.
4. **Grading Manipulation**: Tampering with test cases, overwriting judge binaries, or inspecting other submissions' memory.

---

## 2. Why Docker Alone Is Not A Security Boundary

Standard Docker containers share the host's Linux kernel (`/boot/vmlinuz`). This exposes fundamental architectural vulnerabilities:

* **Kernel 0-Days & Vulnerabilities**: Exploits targeting Linux kernel syscalls (e.g., `io_uring`, `eBPF`, `cgroups`, `namespaces`, `netfilter`, or vulnerabilities like Dirty Cred / Dirty COW) allow an unprivileged container process to escalate to host root.
* **Microarchitectural Side-Channels**: Multi-tenant execution on shared physical cores exposes the system to cache-timing attacks (Spectre, Meltdown, Foreshadow), allowing an adversary to read memory across container boundaries.
* **Kernel Panics / Bug-Checks**: A malicious payload invoking malformed syscalls can crash the kernel, taking down the entire machine.

---

## 3. Defense-in-Depth Layers

To mitigate real-world risks, this judge employs four concentric defense rings:

```
[ Ring 0: Disposable Cloud VM (KVM / Hypervisor Hardware Boundary) ]
    │
    ├── [ Ring 1: Host Network Isolation (Blocked Metadata 169.254.169.254) ]
    │       │
    │       ├── [ Ring 2: Hardened Docker Container ]
    │       │       ├── --network none (Zero Network Access)
    │       │       ├── --memory / --memory-swap 128m (Cgroup OOM Hard Limits)
    │       │       ├── --cpus 1.0 (CPU Quota)
    │       │       ├── --pids-limit 64 (Blocks Fork-Bombs)
    │       │       ├── --user 10001:10001 (Non-Root User)
    │       │       ├── --read-only (Read-Only Root Filesystem)
    │       │       ├── --tmpfs /tmp:noexec,nosuid,size=32m (Volatile Scratch Memory)
    │       │       ├── --cap-drop ALL (Drops All Linux Capabilities)
    │       │       └── --security-opt no-new-privileges:true (SUID Escalation Lock)
    │       │
    │       └── [ Ring 3: Host Watchdog Reaper & Queue Throttling ]
    │               ├── Wall-Clock Watchdog (Terminates Infinite Loops)
    │               └── Bounded Worker Pool (Prevents Host Saturation)
```

### Layer 1: The Throwaway Virtual Machine (Blast Radius Containment)
* The judge daemon runs inside a dedicated, disposable VM (e.g. GCP Compute Engine or AWS EC2 instance).
* **Zero Cloud Credentials**: The VM has no IAM roles, no attached service accounts, and no access to internal corporate networks.
* **Metadata Blocking**: Outbound packets to link-local metadata endpoints (`169.254.169.254`) are dropped at the host `iptables` level.
* **Ephemeral Lifecycle**: VMs are automatically recycled/destroyed after test sessions or periodic batches (`scripts/provision_throwaway_vm.sh`). Even if an advanced 0-day escapes Docker to the VM kernel, persistence is eliminated upon VM destruction.

### Layer 2: Container Hardening Primitives
Every container execution applies the following flags:

| Flag | Security Rationale | Attacked Vector |
| :--- | :--- | :--- |
| `--network none` | Disables network stack entirely (only loopback). | Data exfiltration, port scanning, cryptomining, C2. |
| `--pids-limit 64` | Restricts maximum process/thread count to 64. | Fork bombs (`:(){ :|:& };:`, `os.fork()`). |
| `--memory 128m --memory-swap 128m` | Strict cgroup memory ceiling; disables swapping to disk. | Memory exhaustion (OOM), host memory starvation. |
| `--cpus 1.0` | Caps CPU time to 1 virtual core. | Multi-core CPU starvation / spinlocks. |
| `--user 10001:10001` | Runs as unprivileged user `judge`. | File permission bypass, root access. |
| `--read-only` | Root filesystem mounted strictly read-only. | Modifying system libraries, installing rootkits. |
| `--tmpfs /tmp:rw,noexec,nosuid,size=32m` | In-memory temporary directory; binary execution prohibited (`noexec`). | Downloading/compiling and executing malicious payloads in `/tmp`. |
| `--cap-drop ALL` | Drops all POSIX capabilities (e.g. `CAP_SYS_ADMIN`, `CAP_NET_RAW`, `CAP_DAC_OVERRIDE`). | Kernel capability abuse, raw socket tampering. |
| `--security-opt no-new-privileges:true` | Prevents gaining higher privileges via SUID binaries. | Privilege escalation. |

### Layer 3: Watchdog Timeout & Queue Throttling
* **Wall-Clock Watchdog**: Subprocess / Docker kill timeout terminates processes exceeding `time_limit_ms`.
* **Worker Pool & Backpressure**: Incoming submissions enter an asynchronous bounded FIFO queue. Only `N` workers execute concurrently (e.g., 20 parallel sandboxes), preventing fork or container storms from exhausting the host.
* **Output Limit Enforcement (`OLE`)**: Caps stdout/stderr buffers to 1 MB to prevent memory or terminal flooding.

---

## 4. Verdict Classification Matrix

| Verdict | Name | Detection Mechanism | Trigger Condition |
| :--- | :--- | :--- | :--- |
| **AC** | Accepted | Evaluator stdout match | Output matches expected output exactly (after whitespace normalization). |
| **WA** | Wrong Answer | Evaluator stdout mismatch | Output completes within limits but output differs from expected. |
| **TLE** | Time Limit Exceeded | Host Watchdog / Container Timeout | Process wall-clock/CPU time exceeds configured threshold. |
| **MLE** | Memory Limit Exceeded | Cgroup OOM Killer / Exit Code 137 | Container memory breaches limit; kernel delivers SIGKILL. |
| **RE** | Runtime Error | Non-zero Exit Code / Signal / EAGAIN | Unhandled exception, crash, or fork-bomb blocked by `pids-limit`. |
| **CE** | Compilation Error | Compiler Exit Code != 0 | Syntax errors during compiler step (C++ / GCC). |
| **OLE** | Output Limit Exceeded | Stream byte counter > limit | Output exceeds `output_limit_bytes` (1 MB default). |

---

## 5. Residual Risks & Next-Level Enhancements

For organizations running multi-tenant judges at massive scale, the following additional layers should be considered:

1. **gVisor (`runsc`)**: Run containers using Google's gVisor runtime. gVisor replaces the Linux kernel interface with a user-space kernel written in Go, eliminating direct syscall access to the host kernel.
2. **AWS Firecracker MicroVMs**: Rather than Docker containers, spin up dedicated Firecracker MicroVMs per submission with sub-5ms boot times and hardware-assisted hypervisor boundaries.
3. **Hyperthreading Isolation**: Disable hyperthreading (SMT) on the host machine to eliminate cross-thread cache-timing attacks (Spectre).
