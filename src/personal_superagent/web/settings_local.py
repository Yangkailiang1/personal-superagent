"""显式本地教学配置：SQLite 只用于本课，不用于后续并发领取验收。"""
from pathlib import Path

from .settings_base import *  # noqa: F403

SECRET_KEY = "local-lesson-only-never-deploy"
DEBUG = True
ALLOWED_HOSTS = ["localhost", "127.0.0.1", "testserver"]
DATABASES = {"default": {
    "ENGINE": "django.db.backends.sqlite3",
    "NAME": Path(__file__).resolve().parents[3] / "lesson.sqlite3",
}}
SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False
