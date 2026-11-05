"""业务任务与执行图分开保存；本课只允许创建和读取。"""
import uuid

from django.conf import settings
from django.db import models


class Task(models.Model):
    """用户创建的业务任务。

    与 agent 执行图（节点、事件、checkpoint）分开存储：本表只记录
    "用户要什么"，执行过程由另一套模型负责，两者通过外键关联。
    本课范围只允许创建和读取，不提供更新/删除接口。
    """

    class Status(models.TextChoices):
        """任务状态枚举。本课只有一个状态，后续课程再扩展。

        TextChoices 的每个成员是 (数据库值, 人类可读标签)：
        数据库存 "pending"，Admin/表单里显示 "待执行"。
        用枚举而不是裸字符串，可以让 choices 校验、表单下拉框、
        模板显示标签全部自动获得，且杜绝拼写错误的非法状态值。
        """

        PENDING = "pending", "待执行"

    # 主键使用 UUID 而不是默认的自增整数。
    # 好处：ID 由应用层生成（default=uuid.uuid4），插入前就知道主键，
    # 且不可枚举——/tasks/3 这类自增 ID 会让外人猜出任务总量并逐个试探，
    # UUID 则无法遍历。editable=False 禁止它在任何表单/Admin 里被修改。
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # 任务归属人。项目约定（AGENTS.md）：所有用户数据从建表第一天起就带 owner，
    # 后续每次查询都必须按 owner 过滤，否则就是越权漏洞。
    # 引用 settings.AUTH_USER_MODEL 而不是直接 import User 模型，
    # 是为了将来替换自定义用户模型时不用改这里的代码。
    # on_delete=CASCADE：用户被删除时，其所有任务一并删除，不留孤儿数据。
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)

    # 任务标题，限制 120 字符，数据库层和表单层都会校验。
    title = models.CharField(max_length=120)

    # 任务详细描述。TextField 在 PostgreSQL 中对应 text 类型，理论上不限长，
    # 这里的 max_length=10000 只作用于表单校验，防止误贴超大文本。
    description = models.TextField(max_length=10000)

    # 当前状态。choices=Status.choices 让 Django 在表单和 Admin 中渲染成下拉框，
    # 并在 clean() 校验时拒绝枚举之外的值；default 保证新建任务必然是"待执行"。
    # max_length=24 预留了后续扩展状态名的空间。
    status = models.CharField(max_length=24, choices=Status.choices, default=Status.PENDING)

    # 创建时间。auto_now_add=True 表示只在 INSERT 时自动写入当前时间，
    # 之后任何 update 都不会改动它；与 auto_now（每次保存都刷新）相区别。
    # 因 settings.USE_TZ=True，存储的是带时区的 UTC 时间。
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        # 默认排序：按创建时间倒序（最新在前），时间相同时按 id 正序保证稳定分页。
        # 注意 ordering 只是 ORM 查询的默认 ORDER BY，不创建索引、不影响存储。
        ordering = ["-created_at", "id"]

        # 组合索引 (owner, created_at DESC)。
        # 本系统最高频的查询是"列出某用户的任务列表"（列表页），
        # 即 WHERE owner = ? ORDER BY created_at DESC——这个索引让该查询
        # 一次索引扫描即可完成过滤 + 排序，无需全表扫描后再排序。
        # 选组合索引而不是 owner 单列索引的原因：单列索引只能加速过滤，
        # 排序仍需回表后 sort；组合索引的 B-tree 顺序本身就是有序的。
        indexes = [models.Index(fields=["owner", "-created_at"])]
