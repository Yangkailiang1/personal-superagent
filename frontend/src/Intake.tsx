import { useEffect, useState } from "react";
import { api, states, type Device } from "./api";
import { Markdown } from "./Chat";
const fields: Record<string, string> = {
  title: "任务名称",
  goal: "目标",
  materials: "输入材料",
  deliverables: "交付物（每行一项）",
  acceptance: "验收标准（每行一项）",
  questions: "待确认问题（解决后清空）",
  assumptions: "假设（每行一项）",
  device_needs: "设备与权限需求",
};
const arrays = ["deliverables", "acceptance", "questions", "assumptions"];
export function Intake({
  initialId,
  onTask,
  devices,
}: {
  initialId: string;
  onTask: (id: string) => void;
  devices: Device[];
}) {
  const [editVersion, setEditVersion] = useState<number | null>(null);
  const [id, setId] = useState(initialId),
    [list, setList] = useState<any[]>([]),
    [data, setData] = useState<any>(null),
    [text, setText] = useState(""),
    [mode, setMode] = useState("demo"),
    [draft, setDraft] = useState<any>(null),
    [dirty, setDirty] = useState(false),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false),
    [accept, setAccept] = useState(false),
    [grant, setGrant] = useState(""),
    [source, setSource] = useState("input.md");
  useEffect(() => {
    setId(initialId);
  }, [initialId]);
  useEffect(() => {
    history.replaceState(
      null,
      "",
      id ? `/app/?intake=${id}` : "/app/?view=intake",
    );
  }, [id]);
  useEffect(() => {
    let active = true;
    const refresh = async () => {
      try {
        const l = await api<any>("/api/intake/conversations/");
        if (active) setList(l.items);
        if (id) {
          const d = await api(`/api/intake/conversation/?id=${id}`);
          if (active) {
            setData(d);
            if (!dirty) setDraft(d.draft);
          }
        }
      } catch (e) {
        if (active) setError(String(e));
      }
    };
    setData(null);
    refresh();
    const timer = setInterval(refresh, 2000);
    return () => {
      active = false;
      clearInterval(timer);
    };
  }, [id, dirty]);
  const running = data?.turns.some(
    (t: any) => ["queued", "running"].includes(t.state) || !t.stopped,
  );
  async function action(kind: string, extra: any = {}) {
    setBusy(true);
    setError("");
    try {
      let current = id;
      if (!current) {
        const d = await api<any>("/api/intake/conversations/", {});
        current = d.id;
        setId(current);
        setData(d);
        extra.version = d.version;
      }
      const d = await api<any>(`/api/intake/${kind}/`, {
        id: current,
        version: data?.version,
        ...extra,
      });
      if (kind === "confirm") {
        onTask(d.task_id);
      } else {
        setData(d);
        setDraft(d.draft);
        setDirty(false);
        setAccept(false);
      }
      if (kind === "send") setText("");
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }
  const grants = devices
    .filter((d) => !d.revoked)
    .flatMap((d) =>
      d.grants
        .filter((g) => g.local_enabled && !g.revoked_at)
        .map((g) => ({ ...g, device: d.name })),
    );
  return (
    <section className="intake-page">
      <div className="section-heading">
        <div>
          <p className="eyebrow">先讨论，再确认入队</p>
          <h1>需求对话</h1>
        </div>
        <select
          aria-label="需求会话"
          value={id}
          onChange={(e) => {
            setId(e.target.value);
            setDirty(false);
            setDraft(null);
          }}
        >
          <option value="">新会话</option>
          {list.map((c) => (
            <option key={c.id} value={c.id}>
              {c.title}
            </option>
          ))}
        </select>
      </div>
      {error && <p role="alert">{error}</p>}
      <div className="intake-grid">
        <div className="intake-chat">
          {data?.turns.map((t: any) => (
            <div key={t.id}>
              <div className="intake-user">{t.text}</div>
              <small>
                {t.mode === "real" ? "真实模型" : "离线演示"} ·{" "}
                {states[t.state] || t.state}
              </small>
              {t.reply && <Markdown text={t.reply} />}{" "}
              {t.error && <p role="alert">{t.error}</p>}
              {["queued", "running"].includes(t.state) && (
                <button onClick={() => action("cancel", { turn_id: t.id })}>
                  取消本轮
                </button>
              )}
            </div>
          ))}
          <form
            onSubmit={(e) => {
              e.preventDefault();
              action("send", { text, mode, request_key: crypto.randomUUID() });
            }}
          >
            <textarea
              aria-label="需求消息"
              placeholder="描述目标，或补充需要澄清的信息…"
              value={text}
              onChange={(e) => setText(e.target.value)}
            />
            <div className="board-filters">
              <select
                aria-label="接待模式"
                value={mode}
                onChange={(e) => setMode(e.target.value)}
              >
                <option value="demo">离线演示</option>
                <option value="real">真实模型</option>
              </select>
              <button disabled={busy || running || dirty || !text.trim()}>
                发送
              </button>
            </div>
            {dirty && <small>先保存草稿编辑，再继续对话。</small>}
          </form>
        </div>
        <div className="draft-panel">
          <h2>
            任务草稿 <small>v{data?.version || 1}</small>
          </h2>
          {draft && Object.keys(draft).length > 0 ? (
            <>
              {Object.entries(fields).map(([key, label]) => (
                <label key={key}>
                  {label}
                  <textarea
                    aria-label={label}
                    disabled={running || busy}
                    value={
                      Array.isArray(draft[key])
                        ? draft[key].join("\n")
                        : draft[key] || ""
                    }
                    onChange={(e) => {
                      if (!dirty) setEditVersion(data.version);
                      setDirty(true);
                      setDraft({
                        ...draft,
                        [key]: arrays.includes(key)
                          ? e.target.value.split("\n").filter(Boolean)
                          : e.target.value,
                      });
                    }}
                  />
                </label>
              ))}
              <button
                disabled={!dirty || running || busy}
                onClick={() => action("edit", { draft, version: editVersion })}
              >
                保存草稿
              </button>
              <label>
                <input
                  type="checkbox"
                  checked={accept}
                  onChange={(e) => setAccept(e.target.checked)}
                />
                我明确接受上述假设
              </label>
              <label>
                执行目录
                <select
                  aria-label="确认授权目录"
                  value={grant}
                  onChange={(e) => setGrant(e.target.value)}
                >
                  <option value="">仅云端</option>
                  {grants.map((g) => (
                    <option key={g.id} value={g.id}>
                      {g.device} / {g.label}
                    </option>
                  ))}
                </select>
              </label>
              {grant && (
                <input
                  aria-label="需求材料路径"
                  value={source}
                  onChange={(e) => setSource(e.target.value)}
                />
              )}
              <button
                className="primary"
                disabled={
                  dirty ||
                  running ||
                  busy ||
                  draft.questions?.length > 0 ||
                  (draft.assumptions?.length > 0 && !accept)
                }
                onClick={() =>
                  action("confirm", {
                    request_key: crypto.randomUUID(),
                    accept_assumptions: accept,
                    grant_id: grant || null,
                    source_path: source,
                  })
                }
              >
                确认生成任务
              </button>
              <p className="data-notice">
                确认仅生成待启动任务，不自动执行。读写本地资料仍需已有授权。
              </p>
            </>
          ) : (
            <p>与接待 Agent 讨论后，结构化草稿会出现在这里。</p>
          )}
        </div>
      </div>
    </section>
  );
}
