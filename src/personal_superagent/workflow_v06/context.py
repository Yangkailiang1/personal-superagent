from contextvars import ContextVar

CURRENT = ContextVar("execution", default={})
