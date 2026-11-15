"""Thin web composition boundary delegating exclusively to the BIS runtime."""


def build_runtime():
    """Return a WebRuntime assembled by BIS without exposing BRNS or BRC."""
    from BIS.runtime import build_web_runtime

    return build_web_runtime()
