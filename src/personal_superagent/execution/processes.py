"""只管理带本次执行凭证的进程；PID 相同不代表同一进程。"""
import socket

import psutil
from django.db import transaction

from personal_superagent.tasks.models import Task
from .lifecycle import append_event
from .models import Attempt


def confirm_dead(attempt: Attempt) -> bool:
    """只在同主机验证。启动登记间隙则按命令中的执行 ID/token 扫描。"""
    if attempt.hostname != socket.gethostname():
        return False
    if attempt.process_id and attempt.process_birth:
        try:
            process = psutil.Process(attempt.process_id)
            return process.create_time() != attempt.process_birth or process.status() == psutil.STATUS_ZOMBIE
        except psutil.NoSuchProcess:
            return True
        except psutil.AccessDenied:
            return False
    # 父进程可能在 Popen 成功与保存 PID 之间崩溃，不能把空 PID 等同于从未启动。
    for process in psutil.process_iter():
        try:
            args = process.cmdline()
            if "personal_superagent.execution.child" in args and str(attempt.claim_token) in args:
                return False
        except psutil.NoSuchProcess:
            continue
        except psutil.AccessDenied:
            return False
    return True


def reconcile_interrupted() -> None:
    for item in Attempt.objects.filter(state="interrupted", process_stopped=False):
        if not confirm_dead(item):
            continue
        with transaction.atomic():
            Task.objects.select_for_update().get(pk=item.task_id)
            attempt = Attempt.objects.select_for_update().get(pk=item.pk)
            if attempt.state == "interrupted" and not attempt.process_stopped:
                attempt.process_stopped = True
                attempt.save(update_fields=["process_stopped"])
                append_event(attempt, "process_stopped", {"reason": "已核验同主机进程身份和退出状态"})
