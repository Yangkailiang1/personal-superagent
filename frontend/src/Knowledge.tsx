import { useEffect, useState } from "react";
import { api } from "./api";
import { Markdown } from "./Chat";
export function Knowledge() {
  const [data, setData] = useState<any>({
      sources: [],
      pages: [],
      proposals: [],
      log: [],
      schedule: [],
      inspections: [],
    }),
    [error, setError] = useState(""),
    [title, setTitle] = useState(""),
    [content, setContent] = useState(""),
    [artifact, setArtifact] = useState(""),
    [selected, setSelected] = useState<string[]>([]),
    [mode, setMode] = useState("demo"),
    [query, setQuery] = useState(""),
    [results, setResults] = useState<any[]>([]);
  const refresh = () =>
    api("/api/collaboration/wiki/")
      .then(setData)
      .catch((e) => setError(String(e)));
  useEffect(() => {
    refresh();
    const timer = setInterval(refresh, 3000);
    return () => clearInterval(timer);
  }, []);
  async function action(name: string, body: any) {
    try {
      await api(`/api/collaboration/${name}/`, body);
      await refresh();
      setError("");
    } catch (e) {
      setError(String(e));
    }
  }
  const schedule = data.schedule[0] || {
    enabled: false,
    version: 1,
    timezone: "Asia/Shanghai",
    mode: "demo",
  };
  return (
    <section className="page knowledge-page">
      <div className="section-heading">
        <h1>知识与长期任务</h1>
        <select
          aria-label="知识模式"
          value={mode}
          onChange={(e) => setMode(e.target.value)}
        >
          <option value="demo">离线演示</option>
          <option value="real">真实模型</option>
        </select>
      </div>
      {error && <p role="alert">{error}</p>}
      <details>
        <summary>添加只读材料</summary>
        <input
          aria-label="材料标题"
          placeholder="标题"
          value={title}
          onChange={(e) => setTitle(e.target.value)}
        />
        <textarea
          aria-label="材料内容"
          placeholder="明确选定的材料正文"
          value={content}
          onChange={(e) => setContent(e.target.value)}
        />
        <input
          aria-label="交付物ID"
          placeholder="或输入当前用户的文档交付物 ID"
          value={artifact}
          onChange={(e) => setArtifact(e.target.value)}
        />
        <button
          onClick={() =>
            action("source", {
              title,
              content,
              artifact_id: artifact ? Number(artifact) : undefined,
            })
          }
        >
          保存原始材料
        </button>
      </details>
      <h2>材料</h2>
      {data.sources.map((s: any) => (
        <label className="source-row" key={s.id}>
          <input
            type="checkbox"
            checked={selected.includes(s.id)}
            onChange={(e) =>
              setSelected(
                e.target.checked
                  ? [...selected, s.id]
                  : selected.filter((i) => i !== s.id),
              )
            }
          />
          {s.title}
          <details>
            <summary>查看原文</summary>
            <pre>{s.content}</pre>
          </details>
        </label>
      ))}
      <button
        disabled={!selected.length}
        onClick={() =>
          action("propose", {
            source_ids: selected,
            mode,
            request_key: crypto.randomUUID(),
          })
        }
      >
        整理所选材料
      </button>
      <h2>待确认的知识整理</h2>
      {data.proposals.map((p: any) => (
        <article className="draft-panel" key={p.id}>
          <strong>{p.state}</strong>
          <Markdown text={p.report} />
          {p.changes.map((c: any) => (
            <details key={c.slug}>
              <summary>
                {c.slug} · 基于 v{c.base}
              </summary>
              <Markdown text={c.content} />
              <small>来源：{c.sources.join(", ")}</small>
            </details>
          ))}
          {p.state === "review" && (
            <button onClick={() => action("approve", { id: p.id })}>
              确认知识修订
            </button>
          )}
        </article>
      ))}
      <h2>知识索引</h2>
      <form
        onSubmit={async (e) => {
          e.preventDefault();
          try {
            setResults(
              (
                await api<any>(
                  "/api/collaboration/query/?q=" + encodeURIComponent(query),
                )
              ).items,
            );
          } catch (e) {
            setError(String(e));
          }
        }}
      >
        <input
          aria-label="知识查询"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="查询规范知识页"
        />
        <button>查询</button>
      </form>
      {results.map((p: any) => (
        <article key={p.slug}>
          <h3>
            {p.slug} · v{p.revision}
          </h3>
          <Markdown text={p.content} />
          <small>来源：{p.sources.join(", ")}</small>
        </article>
      ))}
      {data.pages.map((p: any) => (
        <details key={p.id}>
          <summary>
            {p.slug} · v{p.revision}
          </summary>
          <Markdown text={p.content} />
          <small>来源：{p.sources.join(", ")}</small>
          <details>
            <summary>历史修订</summary>
            {p.history.map((r: any) => (
              <div key={r.number}>
                <strong>v{r.number}</strong>
                <Markdown text={r.content} />
              </div>
            ))}
          </details>
        </details>
      ))}
      <h2>每日巡检</h2>
      <label>
        巡检时区
        <select
          aria-label="巡检时区"
          value={schedule.timezone}
          onChange={(e) =>
            action("schedule", { ...schedule, timezone: e.target.value })
          }
        >
          {[
            ...new Set([
              schedule.timezone,
              "Asia/Shanghai",
              "UTC",
              "America/New_York",
              "Europe/London",
            ]),
          ].map((zone) => (
            <option key={zone} value={zone}>
              {zone}
            </option>
          ))}
        </select>
      </label>
      <p>
        09:00（{schedule.timezone}
        ），每日一次、最多八次模型请求；仅提出建议，不自动执行或改知识。
      </p>
      <label>
        <input
          type="checkbox"
          checked={schedule.enabled}
          onChange={(e) =>
            action("schedule", { ...schedule, enabled: e.target.checked, mode })
          }
        />
        启用每日巡检（当前选择的模型模式）
      </label>
      {data.inspections.map((i: any) => (
        <article className="draft-panel" key={i.id}>
          <strong>
            {i.day} · {i.job__state} · {i.calls} 次请求
          </strong>
          <Markdown text={i.report} />
        </article>
      ))}
      <h2>知识变更日志</h2>
      {data.log.map((entry: any) => (
        <p key={entry.id}>
          {new Date(entry.created_at).toLocaleString()} · {entry.entry}
        </p>
      ))}
    </section>
  );
}
