import { api } from "./api";
export function HappierRun({
  run,
  onRefresh,
  onError,
}: {
  run: any;
  onRefresh: () => void;
  onError: (s: string) => void;
}) {
  const report = run.report || {};
  return (
    <section className="draft-panel external-run">
      <h3>Claude Code · 本机执行</h3>
      <p className="muted">
        基线 {run.baseline.slice(0, 12)} · worktree 提供代码隔离，不是安全沙箱
      </p>
      <p>写入范围：{run.policy.write_paths.join("、")}</p>
      {run.permissions.map((p: any) => (
        <article className="approval-card" key={p.id}>
          <h3>
            {p.tool} ·{" "}
            {p.decision === "pending"
              ? "等待确认"
              : p.applied
                ? p.decision === "approve"
                  ? "已批准本次"
                  : "已拒绝"
                : "等待本机确认决定"}
          </h3>
          <pre style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}>
            {JSON.stringify(p.arguments, null, 2)}
          </pre>
          {p.tool === "Bash" && (
            <p>命令在本机运行，可能访问工作目录以外的资源。请检查完整命令。</p>
          )}
          {p.decision === "pending" && (
            <footer>
              {(["reject", "approve"] as const).map((decision) => (
                <button
                  key={decision}
                  onClick={async () => {
                    try {
                      await api("/api/happier/decide/", {
                        id: p.id,
                        version: p.version,
                        decision,
                        request_key: crypto.randomUUID(),
                      });
                      onRefresh();
                    } catch (e) {
                      onError(String(e));
                    }
                  }}
                >
                  {decision === "approve" ? "批准本次" : "拒绝"}
                </button>
              ))}
            </footer>
          )}
        </article>
      ))}
      {report.branch && (
        <p>
          保留任务分支：<code>{report.branch}</code>
        </p>
      )}
      {report.violations?.length > 0 && (
        <p className="error-banner">
          越范围或无法回收：{report.violations.join("、")}
        </p>
      )}
      {report.diff && (
        <details>
          <summary>代码差异</summary>
          <pre style={{ whiteSpace: "pre-wrap" }}>{report.diff}</pre>
        </details>
      )}
      {report.files?.map((f: any) => (
        <details key={f.path}>
          <summary>{f.path}{f.deleted ? " · 删除" : ""}</summary>
          <pre style={{ whiteSpace: "pre-wrap" }}>{f.content}</pre>
        </details>
      ))}
      {report.checks?.map((c: any, i: number) => (
        <details key={i}>
          <summary>
            {c.command} · 退出码 {c.exit_code}
          </summary>
          <pre style={{ whiteSpace: "pre-wrap" }}>{c.output}</pre>
        </details>
      ))}
      {report.state && (
        <button
          onClick={() => {
            const url = URL.createObjectURL(
              new Blob([JSON.stringify(report, null, 2)], {
                type: "application/json",
              }),
            );
            const a = document.createElement("a");
            a.href = url;
            a.download = "claude-delivery.json";
            a.click();
            setTimeout(() => URL.revokeObjectURL(url), 1000);
          }}
        >
          下载交付报告
        </button>
      )}
      <small>
        差异与检查由执行设备回传，不代表独立验证；无检查证据时不得视为测试通过。
      </small>
    </section>
  );
}
