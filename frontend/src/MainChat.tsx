import { useEffect, useState } from "react";
import { api, states } from "./api";
import { Markdown } from "./Chat";
export function MainChat({
  initialId = "",
  onTask,
  onBoard,
}: {
  initialId?: string;
  onTask: (id: string) => void;
  onBoard: () => void;
}) {
  const [id, setId] = useState(initialId),
    [list, setList] = useState<any[]>([]),
    [c, setC] = useState<any>(null),
    [text, setText] = useState(""),
    [mode, setMode] = useState("demo"),
    [agents, setAgents] = useState<any[]>([]),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false),
    [custom, setCustom] = useState(""),
    [choice, setChoice] = useState<number | null>(null),
    [advanced, setAdvanced] = useState(false),
    [edit, setEdit] = useState(""),
    [editVersion, setEditVersion] = useState(0),
    [accept, setAccept] = useState(false),
    [calls, setCalls] = useState(24),
    [images, setImages] = useState(0);
  useEffect(() => {
    setId(initialId);
  }, [initialId]);
  useEffect(() => {
    history.replaceState(null, "", id ? `/app/?intake=${id}` : "/app/");
  }, [id]);
  useEffect(() => {
    let alive = true;
    const refresh = async () => {
      try {
        const items = await api<any>("/api/intake/conversations/");
        if (alive) setList(items.items);
        const profiles = await api<any>("/api/collaboration/agents/");
        if (alive) setAgents(profiles.items);
        if (id) {
          const data = await api(`/api/intake/conversation/?id=${id}`);
          if (alive) setC(data);
        }
      } catch (e) {
        if (alive) setError(String(e));
      }
    };
    setC(null);
    refresh();
    const timer = setInterval(refresh, 2000);
    return () => {
      alive = false;
      clearInterval(timer);
    };
  }, [id]);
  const pending = c?.questions?.find((q: any) => !q.answered_at),
    running = c?.turns.some(
      (t: any) => ["queued", "running"].includes(t.state) || !t.stopped,
    );
  async function action(kind: string, extra: any = {}) {
    setBusy(true);
    setError("");
    try {
      let current = id;
      let version = c?.version;
      if (!current) {
        const created = await api<any>("/api/intake/conversations/", {
          style: "plan",
        });
        current = created.id;
        version = created.version;
        setId(current);
      }
      const data = await api<any>(`/api/intake/${kind}/`, {
        id: current,
        version,
        upgrade_plan: true,
        ...extra,
      });
      if (kind === "publish") {
        onBoard();
      } else {
        setC(data);
        if (kind === "send") setText("");
        if (kind === "answer") {
          setChoice(null);
          setCustom("");
        }
        if (kind === "edit") setAdvanced(false);
      }
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }
  function advancedEdit() {
    setEdit(JSON.stringify(c.draft, null, 2));
    setEditVersion(c.version);
    setAdvanced(!advanced);
  }
  return (
    <section className="main-chat-page">
      <header className="chat-heading">
        <h1>主对话</h1>
        <select
          aria-label="主对话会话"
          value={id}
          onChange={(e) => {
            setId(e.target.value);
            setAdvanced(false);
          }}
        >
          <option value="">新对话</option>
          {list.map((x) => (
            <option key={x.id} value={x.id}>
              {x.title}
            </option>
          ))}
        </select>
      </header>
      {error && (
        <p role="alert" className="inline-error">
          {error}
        </p>
      )}
      <div className="main-chat-scroll">
        {!c?.turns.length && (
          <div className="chat-welcome">
            <h2>有什么想交给 Agent？</h2>
            <p>先聊清目标，确认计划后由工作 Agent 执行。</p>
          </div>
        )}
        {c?.turns.map((t: any) => (
          <div className="chat-round" key={t.id}>
            <div className="intake-user">{t.text}</div>
            <small>
              {t.mode === "real" ? "真实模型" : "离线演示"} ·{" "}
              {states[t.state] || t.state}
            </small>
            {t.reply && <Markdown text={t.reply} />}{" "}
            {t.error && <p className="inline-error">{t.error}</p>}
            {["queued", "running"].includes(t.state) && (
              <button onClick={() => action("cancel", { turn_id: t.id })}>
                停止本轮
              </button>
            )}
          </div>
        ))}
        {pending && (
          <div className="question-card">
            <h3>{pending.prompt}</h3>
            {pending.options.map((option: string, i: number) => (
              <label key={i}>
                <input
                  type="radio"
                  name="question"
                  checked={choice === i}
                  onChange={() => setChoice(i)}
                />
                <span>{option}</span>
              </label>
            ))}
            <label>
              <input
                type="radio"
                name="question"
                checked={choice === 3}
                onChange={() => setChoice(3)}
              />
              <span>自行输入</span>
            </label>
            {choice === 3 && (
              <textarea
                aria-label="自行输入回答"
                value={custom}
                onChange={(e) => setCustom(e.target.value)}
              />
            )}
            <button
              className="primary"
              disabled={
                busy ||
                running ||
                choice === null ||
                (choice === 3 && !custom.trim())
              }
              onClick={() =>
                action("answer", {
                  question_id: pending.id,
                  choice,
                  custom,
                  mode,
                  request_key: crypto.randomUUID(),
                })
              }
            >
              提交选择
            </button>
          </div>
        )}
        {c?.draft?.steps?.length > 0 && (
          <div className="plan-card">
            <div className="section-heading">
              <h2>Plan · {c.draft.title}</h2>
              <small>v{c.version}</small>
            </div>
            <Markdown text={c.draft.goal} />
            {c.draft.steps.map((step: any) => (
              <article key={step.key}>
                <h3>{step.title}</h3>
                <p>{step.goal}</p>
                <small>
                  {step.role} · 依赖：{step.depends_on.join(", ") || "无"} ·
                  工具：{step.tools.join(", ") || "纯文本"}
                </small>
                <p>交付：{step.deliverables.join("；")}</p>
                <p>验收：{step.acceptance.join("；")}</p>
                <small>
                  执行目标：
                  {agents.find((a) => a.id === step.agent_id)?.name ||
                    "自动路由（资源与历史职责优先）"}
                </small>
              </article>
            ))}
            <p>设备与权限：{c.draft.device_needs}</p>
            <p>未决问题：{c.draft.questions?.join("；") || "无"}</p>
            {c.draft.assumptions?.length > 0 && (
              <label>
                <input
                  type="checkbox"
                  checked={accept}
                  onChange={(e) => setAccept(e.target.checked)}
                />
                接受假设：{c.draft.assumptions.join("；")}
              </label>
            )}
            <button onClick={advancedEdit}>高级编辑</button>
            {advanced && (
              <>
                <textarea
                  aria-label="高级 Plan JSON"
                  className="plan-json"
                  value={edit}
                  onChange={(e) => setEdit(e.target.value)}
                />
                <button
                  disabled={busy || running}
                  onClick={() => {
                    try {
                      action("edit", {
                        draft: JSON.parse(edit),
                        version: editVersion,
                      });
                    } catch {
                      setError("Plan JSON 格式错误");
                    }
                  }}
                >
                  保存 Plan 修订
                </button>
              </>
            )}
            <div className="board-filters">
              <label>
                每任务模型请求上限
                <input
                  aria-label="模型请求限额"
                  type="number"
                  min={1}
                  max={48}
                  value={calls}
                  onChange={(e) => setCalls(Number(e.target.value))}
                />
              </label>
              <label>
                每任务生图上限
                <input
                  aria-label="生图限额"
                  type="number"
                  min={0}
                  max={2}
                  value={images}
                  onChange={(e) => setImages(Number(e.target.value))}
                />
              </label>
            </div>
            <button
              className="primary"
              disabled={
                c.releases?.some((r: any) => r.version === c.version) ||
                busy ||
                running ||
                pending ||
                advanced ||
                c.draft.questions?.length > 0 ||
                (c.draft.assumptions?.length > 0 && !accept)
              }
              onClick={() =>
                action("publish", {
                  request_key: crypto.randomUUID(),
                  accept_assumptions: accept,
                  policy: {
                    mode,
                    max_model_calls: calls,
                    max_images: images,
                    timeout: 1800,
                  },
                })
              }
            >
              发布并执行
            </button>
            <p className="data-notice">
              授权本计划的任务、工具与执行限额；写入仍逐次审批。依赖满足后自动派工，失败不自动重试。
            </p>
          </div>
        )}
        {c?.releases?.map((release: any) => (
          <div className="release-card" key={release.id}>
            计划 v{release.version} 已发布{" "}
            <button onClick={onBoard}>查看任务看板</button>
          </div>
        ))}
      </div>
      <form
        className="main-composer"
        onSubmit={(e) => {
          e.preventDefault();
          action("send", { text, mode, request_key: crypto.randomUUID() });
        }}
      >
        <textarea
          aria-label="主对话消息"
          placeholder={
            pending ? "请先回答上方问题" : "描述目标，或让我修改计划…"
          }
          value={text}
          onChange={(e) => setText(e.target.value)}
          disabled={!!pending}
        />
        <div>
          <select
            aria-label="主对话模型模式"
            value={mode}
            onChange={(e) => setMode(e.target.value)}
          >
            <option value="demo">离线演示</option>
            <option value="real">真实模型</option>
          </select>
          <button
            className="primary"
            disabled={!text.trim() || busy || running || pending}
          >
            发送
          </button>
        </div>
      </form>
    </section>
  );
}
