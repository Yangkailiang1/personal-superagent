from django import template
from django.utils.safestring import mark_safe
from markdown_it import MarkdownIt

register = template.Library()
RENDERER = MarkdownIt("commonmark", {"html": False})


@register.filter(name="markdown")
def markdown(text):
    """不允许原始 HTML，MarkdownIt 默认拒绝 javascript: 等危险链接。"""
    return mark_safe(RENDERER.render(str(text or "")))
