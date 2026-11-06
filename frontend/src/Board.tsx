import { useEffect, useState } from "react";
import { api } from "./api";
export function Board({
  onTask,
  onDraft,
}: {
  onTask: (id: string) => void;
  onDraft: (id: string) => void;
}) {
  const [data, setData] = useState<any>({
      columns: [],
      items: [],
      model: { labels: {} },
    }),
    [q, setQ] = useState(""),
    [mode, setMode] = useState(""),
    [column, setColumn] = useState(""),
    [history, setHistory] = useState(false),
    [page, setPage] = useState(1),
    [error, setError] = useState("");
  useEffect(() => {
    let alive = true;
    const refresh = () =>
      api(
        `/api/dashboard/?${new URLSearchParams({ q, mode, column, page: String(page), history: history ? "1" : "0" })}`,
      )
        .then((d) => {
          if (alive) {
            setData(d);
            setError("");
          }
        })
        .catch((e) => {
          if (alive) setError(String(e));
        });
    refresh();
    const t = setInterval(refresh, 2000);
    return () => {
      alive = false;
      clearInterval(t);
    };
  }, [q, mode, column, page, history]);
  return (
    <section className="board-page">
      <div className="section-heading">
        <div>
          <p className="eyebrow">后台任务 · 按执行事实更新</p>
          <h1>任务看板</h1>
        </div>
        <span className="status">
          模型：{data.model.labels?.[data.model.state] || "检查中"}
          {data.model.model && ` · ${data.model.model}`}
        </span>
      </div>
      <div className="board-filters">
        <input
          aria-label="搜索看板"
          placeholder="搜索任务"
          value={q}
          onChange={(e) => {
            setQ(e.target.value);
            setPage(1);
          }}
        />
        <select
          aria-label="模式筛选"
          value={mode}
          onChange={(e) => {
            setMode(e.target.value);
            setPage(1);
          }}
        >
          <option value="">全部模式</option>
          <option value="real">真实模型</option>
          <option value="demo">离线演示</option>
        </select>
        <select
          aria-label="阶段筛选"
          value={column}
          onChange={(e) => {
            setColumn(e.target.value);
            setPage(1);
          }}
        >
          <option value="">全部阶段</option>
          {data.columns.map(([k, n]: string[]) => (
            <option key={k} value={k}>
              {n}
            </option>
          ))}
        </select>
        <label>
          <input
            type="checkbox"
            checked={history}
            onChange={(e) => {
              setHistory(e.target.checked);
              setPage(1);
            }}
          />
          取消历史
        </label>
      </div>
      {error && <p role="alert">{error}</p>}
      <div className="kanban">
        {data.columns
          .filter(([k]: string[]) => !column || column === k)
          .map(([key, label]: string[]) => (
            <section className="kanban-column" key={key}>
              <h2>
                {label}
                <small>{data.counts?.[key] || 0}</small>
              </h2>
              {data.items
                .filter((i: any) => i.column === key)
                .map((i: any) => (
                  <button
                    className="kanban-card"
                    data-testid={`card-${i.id}`}
                    key={i.id}
                    onClick={() =>
                      i.kind === "draft" ? onDraft(i.id) : onTask(i.id)
                    }
                  >
                    <strong>{i.title}</strong>
                    <span className="status">
                      {i.mode === "real"
                        ? "真实模型"
                        : i.mode === "demo"
                          ? "离线演示"
                          : i.kind === "draft"
                            ? "草稿"
                            : "尚未启动"}
                    </span>
                    <p>{i.activity}</p>
                    {i.reason && (
                      <small className="card-reason">{i.reason}</small>
                    )}
                    <small>
                      {i.started_at ? "开始于 " : "创建于 "}
                      {new Date(i.started_at || i.created_at).toLocaleString(
                        "zh-CN",
                      )}
                    </small>
                  </button>
                ))}
              {!data.items.some((i: any) => i.column === key) && (
                <p className="column-empty">本页无任务</p>
              )}
            </section>
          ))}
      </div>
      <div className="pagination">
        <button disabled={page <= 1} onClick={() => setPage(page - 1)}>
          上一页
        </button>
        <span>
          {data.page || 1} / {data.pages || 1} · 共 {data.total || 0} 项（每页
          30 项）
        </span>
        <button
          disabled={page >= (data.pages || 1)}
          onClick={() => setPage(page + 1)}
        >
          下一页
        </button>
      </div>
    </section>
  );
}
