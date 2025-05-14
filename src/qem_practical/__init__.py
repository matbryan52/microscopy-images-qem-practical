import warnings

with warnings.catch_warnings():
    warnings.simplefilter("ignore", category=UserWarning)
    try:
        import cupy as cp
    except (ImportError, ModuleNotFoundError):
        pass
