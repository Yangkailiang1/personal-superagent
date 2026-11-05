"""仅监听服务器 loopback，经加密 SSH 隧道访问；不是公网 HTTP 部署配置。"""
from .settings import *  # noqa: F403

DEBUG = False
SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False
