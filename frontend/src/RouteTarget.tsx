import { useEffect, useState } from "react";
import { api, type Task } from "./api";
export function RouteTarget({
  task,
  onRefresh,
  onError,
}: {
  task: Task;
  onRefresh: () => void;
  onError: (s: string) => void;
}) {
  const [agents, setAgents] = useState<any[]>([]),
    [chosen, setChosen] = useState(task.dispatch?.agent_id || "");
  useEffect(() => {
    api<any>("/api/collaboration/agents/")
      .then((d) => setAgents(d.items))
      .catch((e) => onError(String(e)));
  }, [task.id]);
  return (
    <div className="board-filters">
      <label>
        执行目标
        <select
          aria-label="调整执行 Agent"
          value={chosen}
          onChange={(e) => setChosen(e.target.value)}
        >
          <option value="">自动路由</option>
          {agents
            .filter((a) => a.role === task.dispatch?.role && a.enabled)
            .map((a) => (
              <option key={a.id} value={a.id}>
                {a.name}
              </option>
            ))}
        </select>
      </label>
      <button
        onClick={async () => {
          try {
            await api("/api/collaboration/route/", {
              id: task.id,
              agent_id: chosen,
              expected: task.dispatch,
            });
            onRefresh();
          } catch (e) {
            onError(String(e));
          }
        }}
      >
        更新执行目标
      </button>
    </div>
  );
}
