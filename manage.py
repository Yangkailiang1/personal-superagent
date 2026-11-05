"""Django 管理入口；默认使用 PostgreSQL，教学可显式指定 settings_local。"""
import os
import sys

from django.core.management import execute_from_command_line

if __name__ == "__main__":
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "personal_superagent.web.settings")
    execute_from_command_line(sys.argv)
