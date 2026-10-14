"""Data models and enums for the Online Code Judge."""

from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional, Dict, Any
import time


class Verdict(str, Enum):
    AC = "AC"    # Accepted
    WA = "WA"    # Wrong Answer
    TLE = "TLE"  # Time Limit Exceeded
    MLE = "MLE"  # Memory Limit Exceeded
    RE = "RE"    # Runtime Error (non-zero exit, crash, unhandled exception, fork-bomb fail)
    CE = "CE"    # Compilation Error
    OLE = "OLE"  # Output Limit Exceeded
    SE = "SE"    # System / Sandbox Error


class Language(str, Enum):
    PYTHON = "python"
    CPP = "cpp"
    BASH = "bash"


@dataclass
class TestCase:
    id: int
    stdin: str
    expected_stdout: str


@dataclass
class SandboxConfig:
    """Security and resource sandbox constraints for Docker."""
    cpu_limit: float = 1.0            # Cores (e.g. --cpus 1.0)
    memory_limit_mb: int = 128        # RAM limit in Megabytes (e.g. -m 128m)
    time_limit_ms: int = 2000         # Time limit in Milliseconds (wall-clock / CPU)
    pids_limit: int = 64              # Maximum processes (e.g. --pids-limit 64; blocks fork bombs)
    tmpfs_size_mb: int = 32           # Scratch space in RAM (e.g. --tmpfs /tmp:size=32m,noexec,nosuid)
    output_limit_bytes: int = 1048576 # 1 MB maximum output to prevent disk/pipe flooding (OLE)
    network_enabled: bool = False     # Docker --network none
    read_only_root: bool = True       # Docker --read-only
    user_uid: int = 10001             # Unprivileged user UID
    user_gid: int = 10001             # Unprivileged user GID
    cap_drop_all: bool = True         # Docker --cap-drop=ALL
    no_new_privileges: bool = True    # Docker --security-opt=no-new-privileges:true


@dataclass
class ExecutionRawResult:
    stdout: str
    stderr: str
    exit_code: int
    wall_time_ms: float
    memory_used_mb: float
    timed_out: bool = False
    oom_killed: bool = False
    pids_exhausted: bool = False
    output_exceeded: bool = False
    error_message: Optional[str] = None


@dataclass
class TestCaseResult:
    test_case_id: int
    verdict: Verdict
    time_taken_ms: float
    memory_used_mb: float
    stdout: str
    stderr: str
    exit_code: int
    error_message: Optional[str] = None


@dataclass
class Submission:
    id: str
    code: str
    language: Language
    test_cases: List[TestCase]
    config: SandboxConfig = field(default_factory=SandboxConfig)
    created_at: float = field(default_factory=time.time)


@dataclass
class SubmissionResult:
    submission_id: str
    verdict: Verdict
    test_case_results: List[TestCaseResult]
    total_time_ms: float
    max_memory_mb: float
    compile_output: Optional[str] = None
    worker_id: Optional[str] = None
    queued_duration_ms: float = 0.0
    execution_duration_ms: float = 0.0
