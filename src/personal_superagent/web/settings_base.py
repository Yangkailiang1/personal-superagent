"""Django 应用配置：生产环境基线，本地开发需通过环境变量覆盖敏感项。

本文件仅包含生产环境所需的显式配置，不包含任何本地调试或教学演示的默认值。
所有密钥、数据库凭据必须通过环境变量注入，避免硬编码泄露风险。
"""
import os

# Django 加密签名密钥，用于 session、CSRF token、密码重置链接等敏感操作。
# 生产环境必须通过 DJANGO_SECRET_KEY 环境变量提供，为空会导致 Django 拒绝启动。
SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "")

# 调试模式开关。生产环境必须为 False，关闭详细错误页面和静态文件自动服务。
DEBUG = False

# 允许访问的主机头列表，防止 HTTP Host 头攻击。
# 默认只允许 localhost 和 127.0.0.1，生产环境需通过 DJANGO_ALLOWED_HOSTS 配置实际域名。
# 逗号分隔，自动去除空白项，避免空字符串导致校验失败。
ALLOWED_HOSTS = [h.strip() for h in os.environ.get("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",") if h.strip()]

# 根 URL 路由配置模块，指向本项目的 URL 分发器。
ROOT_URLCONF = "personal_superagent.web.urls"

# WSGI 应用入口，生产服务器（如 gunicorn、uwsgi）通过此路径加载 Django 应用。
WSGI_APPLICATION = "personal_superagent.web.wsgi.application"

# 已启用的 Django 应用列表。
# 包含：用户认证、内容类型框架、会话管理，以及本项目的核心任务模块。
INSTALLED_APPS = [
    "django.contrib.auth",           # 用户认证与权限系统
    "django.contrib.contenttypes",   # 内容类型框架，支持外键关联任意模型
    "django.contrib.sessions",       # 会话管理，支持登录状态保持
    "personal_superagent.tasks",     # 本项目核心任务模块
    "personal_superagent.execution",
    "personal_superagent.devices",
    "personal_superagent.intake",
    "personal_superagent.collaboration",
    "personal_superagent.happier",
    "personal_superagent.modeling",
]

# 中间件栈，按请求处理顺序排列。
# 每个中间件在请求到达视图前/响应返回客户端前执行特定处理。
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",              # 安全头（HSTS、XSS 过滤等）
    "django.contrib.sessions.middleware.SessionMiddleware",        # 会话解析，注入 request.session
    "django.middleware.common.CommonMiddleware",                   # 通用处理（URL 规范化、APPEND_SLASH 等）
    "django.middleware.csrf.CsrfViewMiddleware",                   # CSRF 防护，校验 POST 请求的 token
    "django.contrib.auth.middleware.AuthenticationMiddleware",     # 认证解析，注入 request.user
    "django.middleware.clickjacking.XFrameOptionsMiddleware",      # 点击劫持防护，设置 X-Frame-Options
]

# 模板引擎配置。
# 使用 Django 自带模板引擎，自动在各 app 的 templates/ 目录下查找模板。
TEMPLATES = [{
    "BACKEND": "django.template.backends.django.DjangoTemplates",
    "APP_DIRS": True,  # 自动加载 INSTALLED_APPS 中每个 app 的 templates/ 目录
    "OPTIONS": {"context_processors": [
        "django.template.context_processors.request",  # 模板中可直接访问 request 对象
        "django.contrib.auth.context_processors.auth",   # 模板中可直接访问 user 和 perms
    ]},
}]

# 数据库配置：PostgreSQL。
# 所有连接参数通过环境变量注入，默认值仅用于本地开发占位。
DATABASES = {"default": {
    "ENGINE": "django.db.backends.postgresql",
    "NAME": os.environ.get("PGDATABASE", "personal_superagent"),      # 数据库名
    "USER": os.environ.get("PGUSER", "personal_superagent"),            # 数据库用户
    "PASSWORD": os.environ.get("PGPASSWORD", ""),                       # 数据库密码（必须显式设置）
    "HOST": os.environ.get("PGHOST", "127.0.0.1"),                      # 数据库主机
    "PORT": os.environ.get("PGPORT", "5432"),                           # 数据库端口
}}

# 密码强度校验器，用户注册/改密码时依次执行。
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},  # 密码不能与用户名/邮箱等属性过于相似
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},             # 最小长度限制（默认 8 位）
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},            # 禁止使用常见弱密码（如 123456、password）
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},           # 禁止纯数字密码
]

# 国际化与本地化配置。
LANGUAGE_CODE = "zh-hans"      # 默认语言：简体中文
TIME_ZONE = "Asia/Shanghai"    # 默认时区：中国标准时间
USE_TZ = True                  # 启用时区感知，存储 UTC 时间，展示时转换为本地时间

# 默认主键字段类型：自增 BigInteger（64 位），避免整数溢出。
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# 认证相关 URL 配置。
LOGIN_URL = "/accounts/login/"           # 未登录用户访问受限页面时重定向到此
LOGIN_REDIRECT_URL = "/app/"                 # 登录成功后默认跳转首页
LOGOUT_REDIRECT_URL = "/accounts/login/" # 登出后跳转回登录页

# 会话 Cookie 安全策略。
SESSION_COOKIE_SECURE = True   # 仅通过 HTTPS 传输会话 Cookie，防止中间人窃取
CSRF_COOKIE_SECURE = True      # 仅通过 HTTPS 传输 CSRF Token，防止跨站请求伪造
ALLOW_REAL_MODE = os.environ.get("ALLOW_REAL_MODE", "1") == "1"
# 供 Django 框架/LiveServer 识别；SPA 构建资源独立通过 /app/assets/ 提供。
STATIC_URL = "/static/"
MEDIA_URL = "/media/"

# 生图设备回传采用有大小上限的独立图片动作。
DATA_UPLOAD_MAX_MEMORY_SIZE = 16 * 1024 * 1024
