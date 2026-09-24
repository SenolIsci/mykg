"""Guards against regressing on OTel context propagation: every
ThreadPoolExecutor.submit() call in the pipeline's parallel-dispatch code
must go through mykg.tracing.submit_with_context(), not be called bare,
or spans created inside worker threads will be parentless."""

from pathlib import Path

_SRC = Path(__file__).resolve().parent.parent / "src" / "mykg"

_SITES = [
    _SRC / "pass1.py",
    _SRC / "pass2.py",
    _SRC / "orphan_connector.py",
    _SRC / "steps" / "step_ingest.py",
    _SRC / "steps" / "step_preprocess.py",
]


def test_no_bare_executor_submit_in_parallel_dispatch_files():
    offenders = []
    for path in _SITES:
        text = path.read_text(encoding="utf-8")
        for lineno, line in enumerate(text.splitlines(), start=1):
            if ".submit(" in line and "submit_with_context" not in line:
                offenders.append(f"{path.name}:{lineno}: {line.strip()}")
    assert not offenders, (
        "Found bare .submit( calls that bypass submit_with_context "
        "(breaks OTel span parenting across threads):\n" + "\n".join(offenders)
    )
