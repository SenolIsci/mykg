from importlib.metadata import version as _version

__version__ = _version("mykg")


def __getattr__(name: str):
    if name in ("load_adapter", "PipelineContext", "run", "STEPS"):
        import mykg.llm.config as _llm_cfg
        import mykg.orchestrator as _orch
        import mykg.pipeline as _pipe
        globals()["load_adapter"] = _llm_cfg.load_adapter
        globals()["PipelineContext"] = _orch.PipelineContext
        globals()["run"] = _orch.run
        globals()["STEPS"] = _pipe.STEPS
        return globals()[name]
    raise AttributeError(f"module 'mykg' has no attribute {name!r}")


__all__ = ["__version__", "PipelineContext", "STEPS", "run", "load_adapter"]
