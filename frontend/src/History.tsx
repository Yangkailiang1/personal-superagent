import { useEffect, useState } from "react";
import { api, states, type Task } from "./api";
export function History({ task }: { task: Task }) {
  const [attempt, setAttempt] = useState(task.attempt?.id || ""),
    [events, setEvents] = useState<any[]>([]),
    [cursor, setCursor] = useState(0),
    [more, setMore] = useState(false),
    [error, setError] = useState("");
  useEffect(() => {
    let alive = true;
    setEvents([]);
    setCursor(0);
    setMore(false);
    if (attempt)
      api<any>(`/tasks/${task.id}/attempts/${attempt}/events/?after=0`)
        .then((d) => {
          if (alive) {
            setEvents(d.events);
            setCursor(d.cursor);
            setMore(d.has_more);
          }
        })
        .catch((e) => {
          if (alive) setError(String(e));
        });
    return () => {
      alive = false;
    };
  }, [task.id, attempt]);
  async function load() {
    try {
      const d = await api<any>(
        `/tasks/${task.id}/attempts/${attempt}/events/?after=${cursor}`,
      );
      setEvents([...events, ...d.events]);
      setCursor(d.cursor);
      setMore(d.has_more);
    } catch (e) {
      setError(String(e));
    }
  }
  return (
    <div className="draft-panel">
      {task.source ? (
        <p>
          来源：
          <a href={`/app/?intake=${task.source.conversation_id}`}>需求对话</a> ·
          草稿版本 {task.source.version}
        </p>
      ) : (
        <p>直接创建的任务</p>
      )}
      <label>
        执行记录
        <select
          aria-label="历史执行"
          value={attempt}
          onChange={(e) => setAttempt(e.target.value)}
        >
          {task.attempts?.map((a) => (
            <option key={a.id} value={a.id}>
              {new Date(a.created_at).toLocaleString()} · {a.mode} ·{" "}
              {states[a.state]}
            </option>
          ))}
        </select>
      </label>
      {task.attempts?.find((a) => a.id === attempt)?.error && (
        <p>{task.attempts.find((a) => a.id === attempt)?.error}</p>
      )}
      {error && <p role="alert">{error}</p>}
      <ol>
        {events.map((e) => (
          <li key={e.sequence}>
            <small>
              {e.sequence} · {e.kind} ·{" "}
              {new Date(e.created_at).toLocaleString()}
            </small>
            <details>
              <summary>事件详情</summary>
              <pre>{JSON.stringify(e.data, null, 2)}</pre>
            </details>
          </li>
        ))}
      </ol>
      {more && <button onClick={load}>加载更多事件</button>}
    </div>
  );
}
