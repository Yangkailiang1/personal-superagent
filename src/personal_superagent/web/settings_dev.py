"""PostgreSQL 本机开发；保留独立密钥要求，只为本机 HTTP 关闭安全 Cookie。"""
from .settings import *  # noqa: F403

DEBUG = True
SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False
