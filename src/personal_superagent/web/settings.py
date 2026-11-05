"""默认 PostgreSQL 配置，缺少密钥时拒绝启动。"""
from django.core.exceptions import ImproperlyConfigured

from .settings_base import *  # noqa: F403

if not SECRET_KEY:  # noqa: F405
    raise ImproperlyConfigured("请设置 DJANGO_SECRET_KEY；本地教学可选择 settings_local。")
