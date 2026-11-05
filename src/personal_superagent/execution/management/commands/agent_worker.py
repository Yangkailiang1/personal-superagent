from django.core.management.base import BaseCommand, CommandError
from personal_superagent.execution.worker import run_worker


class Command(BaseCommand):
    help = "运行独立 Agent Worker（PostgreSQL；全局最多两个活动执行）"

    def add_arguments(self, parser):
        parser.add_argument("--concurrency", type=int, choices=[1, 2], default=1)
        parser.add_argument("--timeout", type=int, default=1800)
        parser.add_argument("--once", action="store_true", help="排空当前队列后退出")
        parser.add_argument("--max-jobs", type=int)

    def handle(self, *args, **options):
        if options["timeout"] < 1 or (options["max_jobs"] is not None and options["max_jobs"] < 1):
            raise CommandError("timeout 和 max-jobs 必须大于 0")
        self.stdout.write("Worker 已启动；默认 1 并发；没有自动重试。")
        run_worker(concurrency=options["concurrency"], timeout=options["timeout"], once=options["once"], max_jobs=options["max_jobs"])
