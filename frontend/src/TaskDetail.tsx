import { useState } from "react";
import {
  Play,
  Square,
  RotateCcw,
  Check,
  X,
  FileText,
  ChevronDown,
  LoaderCircle,
  Folder,
  Workflow,
  Laptop,
} from "lucide-react";
import { api, states, toolNames, type Task } from "./api";
import { History } from "./History";
import { Conversation, Markdown } from "./Chat";

export function TaskDetail({
  task,
  realEnabled,
  onRefresh,
  onError,
}: {
  task: Task;
  realEnabled: boolean;
  onRefresh: () => void;
  onError: (s: string) => void;
}) {
  const [mode, setMode] = useState("demo");
  const [busy, setBusy] = useState(false);
  const [tab, setTab] = useState("conversation");
  const attempt = task.attempt;
  const prefix = `/tasks/${task.id}/attempts/${attempt?.id}`;
  async function action(path: string, data: Record<string, string> = {}) {
    setBusy(true);
    try {
      await api(path, data, true);
      onRefresh();
    } catch (e) {
      onError(String(e));
    } finally {
      setBusy(false);
    }
  }
  const canStart = task.state === "pending",
    canRetry =
      ["failed", "cancelled", "interrupted"].includes(task.state) &&
      attempt?.stopped;
  const active = [
    "queued",
    "running",
    "waiting_approval",
    "waiting_device",
  ].includes(task.state);
  return (
    <section className="task-detail">
      <header className="task-header">
        <div>
          <span className="eyebrow">任务 / {task.id.slice(0, 8)}</span>
          <h1>{task.title}</h1>
        </div>
        <span className={`status status-${task.state}`}>
          <i className="dot" />
          {states[task.state]}
        </span>
      </header>
      {tab === "history" && <History task={task} />}
      <div className="task-toolbar">
        <div className="tabs">
          {[
            ["conversation", "对话"],
            ["process", "执行过程"],
            ["artifacts", "交付物"],
            ["history", "来源与历史"],
          ].map(([key, label]) => (
            <button
              className={tab === key ? "selected" : ""}
              key={key}
              onClick={() => setTab(key)}
            >
              {label}
            </button>
          ))}
        </div>
        <div className="actions">
          {(canStart || canRetry) && (
            <>
              <select
                value={mode}
                onChange={(e) => setMode(e.target.value)}
                aria-label="执行模式"
              >
                <option value="demo">离线演示</option>
                {realEnabled && <option value="real">真实模型</option>}
              </select>
              <button
                className="primary"
                disabled={busy}
                onClick={() =>
                  action(`/tasks/${task.id}/start/`, {
                    mode,
                    request_key: crypto.randomUUID(),
                    action: canRetry ? "retry" : "start",
                  })
                }
              >
                <Play size={14} />
                {canRetry ? "重试" : "启动"}
              </button>
            </>
          )}
          {task.state === "interrupted" &&
            attempt?.stopped &&
            attempt.workflow_version && (
              <button
                disabled={busy}
                onClick={() => action(prefix + "/resume/")}
              >
                <RotateCcw size={14} />
                恢复
              </button>
            )}
          {active && attempt && (
            <button disabled={busy} onClick={() => action(prefix + "/cancel/")}>
              <Square size={13} />
              取消
            </button>
          )}
        </div>
      </div>
      <div className="task-content">
        {tab === "conversation" && (
          <>
            <Conversation text={task.description} result="" />
            {attempt && (
              <div className="execution-summary">
                <span className="summary-icon">
                  {task.state === "running" ? (
                    <LoaderCircle size={15} className="spin" />
                  ) : (
                    <Workflow size={15} />
                  )}
                </span>
                <span>{attempt.activity}</span>
                <small>
                  {attempt.mode === "demo" ? "离线演示" : "真实模型"}
                </small>
              </div>
            )}
            {attempt && attempt.plan.length > 0 && (
              <details className="compact-plan">
                <summary>
                  任务计划 <ChevronDown size={14} />
                </summary>
                <ul>
                  {attempt.plan.map((p, i) => (
                    <li key={i}>
                      <span
                        className={
                          p.status === "completed" ? "check done" : "check"
                        }
                      >
                        {p.status === "completed" && <Check size={11} />}
                      </span>
                      {p.content}
                    </li>
                  ))}
                </ul>
              </details>
            )}
            {attempt?.approvals
              .filter((a) => a.decision === "pending")
              .map((a) => (
                <div className="approval-card" key={a.id}>
                  <div className="approval-title">
                    <span className="approval-icon">
                      <FileText size={19} />
                    </span>
                    <div>
                      <h3>需要你的确认</h3>
                      <p>
                        {toolNames[a.action.name] || a.action.name} ·{" "}
                        {a.action.args.name || a.action.args.path}
                      </p>
                      {a.action.name === "local_write_text" &&
                        attempt.scope && (
                          <p>
                            目标：
                            {attempt.scope.device_name ||
                              attempt.scope.device_id.slice(0, 8)}{" "}
                            / {attempt.scope.label}
                          </p>
                        )}
                    </div>
                  </div>
                  <div className="approval-body">
                    <Markdown
                      text={
                        a.action.args.content ||
                        JSON.stringify(a.action.args, null, 2)
                      }
                    />
                  </div>
                  <footer>
                    <span>批准后才会执行</span>
                    <div>
                      <button
                        disabled={busy}
                        onClick={() =>
                          action(prefix + `/approvals/${a.id}/`, {
                            version: String(a.version),
                            request_key: crypto.randomUUID(),
                            decision: "reject",
                          })
                        }
                      >
                        <X size={14} />
                        拒绝
                      </button>
                      <button
                        className="primary"
                        disabled={busy}
                        onClick={() =>
                          action(prefix + `/approvals/${a.id}/`, {
                            version: String(a.version),
                            request_key: crypto.randomUUID(),
                            decision: "approve",
                          })
                        }
                      >
                        <Check size={14} />
                        批准
                      </button>
                    </div>
                  </footer>
                </div>
              ))}
            {task.state === "waiting_device" && (
              <div className="waiting">
                <Laptop size={18} />
                <div>
                  <strong>等待本地设备或操作确认</strong>
                  <p>保持客户端运行。未知结果不会自动重放；请查看执行过程。</p>
                </div>
              </div>
            )}
            {attempt?.error && (
              <div className="error-banner">{attempt.error}</div>
            )}
            {attempt?.result && (
              <Conversation text="" result={attempt.result} />
            )}
          </>
        )}
        {tab === "process" && (
          <div className="process-view">
            <h2>协作与本地操作</h2>
            {attempt?.subtasks.map((s) => (
              <details className="process-card" key={s.call_id}>
                <summary>
                  <Workflow size={16} />
                  {s.role === "writer" ? "内容整理" : "质量检查"}
                  <span className="right muted">
                    {(
                      {
                        running: "执行中",
                        completed: "已完成",
                        failed: "失败",
                        interrupted: "中断",
                      } as Record<string, string>
                    )[s.state] || s.state}
                  </span>
                </summary>
                <Markdown text={s.result || s.description} />
              </details>
            ))}
            {attempt?.operations.map((o) => (
              <details className="process-card" key={o.id}>
                <summary>
                  <Folder size={16} />
                  {toolNames[o.tool]} · {o.arguments.path}
                  <span className="right muted">
                    {(
                      {
                        pending: "待设备领取",
                        leased: "本地执行中",
                        succeeded: "已完成",
                        failed: "未完成",
                        uncertain: "结果待核实",
                      } as Record<string, string>
                    )[o.state] || o.state}
                  </span>
                </summary>
                <p>{o.reason || "操作 ID：" + o.id}</p>
                {o.state === "uncertain" && (
                  <p>操作可能已经生效，请先检查本机文件；不要盲目重试。</p>
                )}
              </details>
            ))}
            <details className="events">
              <summary>技术事件 · {attempt?.events.length || 0}</summary>
              {attempt?.events.map((e) => (
                <div key={e.sequence}>
                  <code>{String(e.sequence).padStart(2, "0")}</code>
                  <strong>{e.kind}</strong>
                  <pre>{JSON.stringify(e.data, null, 2)}</pre>
                </div>
              ))}
            </details>
          </div>
        )}
        {tab === "artifacts" && (
          <div className="artifacts-view">
            <h2>交付物</h2>
            {!attempt?.artifacts.length && (
              <p className="muted">尚无正式交付物。文档审批前不会发布。</p>
            )}
            {attempt?.artifacts.map((a) => (
              <a
                className="artifact-card"
                key={a.id}
                href={prefix + `/artifacts/${a.id}/`}
                target="_blank"
                rel="noreferrer"
              >
                <FileText size={26} />
                <div>
                  <strong>{a.name}</strong>
                  <p>Markdown 文档 · 预览与下载</p>
                </div>
                <span className="right">↗</span>
              </a>
            ))}
          </div>
        )}
      </div>
    </section>
  );
}
