import { useEffect, useState } from "react";
import { api, states } from "./api";
import { Markdown } from "./Chat";
import { MainComposer } from "./MainComposer";
import { PlanControls } from "./PlanControls";
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
    [repositories, setRepositories] = useState<any[]>([]),
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
    const lastMode = c?.turns.at(-1)?.mode;
    if (lastMode) setMode(lastMode);
  }, [c?.id]);
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
        const repos = await api<any>("/api/happier/repositories/");
        if (alive) setRepositories(repos.items);
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
  useEffect(() => {
    if (pending) document.querySelector(".question-card")?.scrollIntoView({ block: "nearest" });
  }, [pending?.id]);
  // 确认只对当前修订有效，避免旧版勾选被沿用到新的假设。
  useEffect(() => { setAccept(false); }, [c?.id, c?.version]);
  const publishReason = c?.releases?.some((r: any) => r.version === c.version)
    ? "这个版本已发布，可在任务看板查看进展。"
    : running ? "本轮对话仍在处理，请等待完成。"
    : pending ? "请先回答上方问题。"
    : advanced ? "请先保存或收起计划编辑。"
    : c?.draft?.questions?.length ? `还有 ${c.draft.questions.length} 项未决问题，请先补充回答。`
    : c?.draft?.assumptions?.length && !accept ? "请先确认以上假设，再发布计划。"
    : !Number.isInteger(calls) || calls < 1 || calls > 48 || !Number.isInteger(images) || images < 0 || images > 2
      ? "请在执行设置中填写有效限额。" : "";
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
              {t.state === "succeeded" ? "本轮回复完成" : states[t.state] || t.state}
            </small>
            {t.reply && <Markdown text={t.reply} />}{" "}
            {t.error && <p className="inline-error">{t.error}</p>}

          </div>
        ))}
        {pending && (
          <div className="question-card">
            <small className="muted">等待你的选择</small>
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
        {c?.turns.length > 0 && !running && !pending && !c.draft?.steps?.length && (
          <div className="conversation-next">
            <p>尚未形成计划，任务还没有发布。</p>
            <button
              disabled={busy}
              onClick={() => action("send", {
                text: c.turns.at(-1).text,
                mode,
                request_key: crypto.randomUUID(),
              })}
            >继续制定计划</button>
          </div>
        )}
        {c?.draft?.steps?.length > 0 && (
          <div className="plan-card">
            <div className="section-heading">
              <h2>Plan · {c.draft.title}</h2>
              <small>v{c.version}</small>
            </div>
            <Markdown text={c.draft.goal} />
            {c.draft.steps.map((step: any, index: number) => (
              <article key={step.key}>
                <h3 className="plan-step-title"><span>{index + 1}</span>{step.title}</h3>
                <p>{step.goal}</p>
                <small>
                  {step.role} · 依赖：{step.depends_on.join(", ") || "无"} ·
                  工具：{step.tools.join(", ") || "纯文本"}
                </small>
                {repositories.length > 0 && <label>本机代码执行目标
                  <select aria-label={`代码仓库 ${step.key}`} value={step.repository_id || ""} disabled={busy || running || c.releases?.some((r:any)=>r.version===c.version)} onChange={e=>{
                    const repo=repositories.find(r=>r.id===e.target.value); if(!repo)return;
                    action("edit",{draft:{...c.draft,steps:c.draft.steps.map((s:any)=>s.key===step.key?{...s,role:"coder",agent_id:repo.agent_id,repository_id:repo.id,repository_version:repo.version,base_commit:repo.baseline,write_paths:repo.policy.write_paths,checks:repo.policy.checks,grant_id:"",tools:["repository_read","repository_write","repository_command"]}:s)}});
                  }}><option value="">保留当前角色</option>{repositories.filter(r=>r.agent__enabled).map(r=><option key={r.id} value={r.id}>{r.label} · {r.baseline.slice(0,8)}</option>)}</select>
                </label>}
                {step.repository_id && <p className="data-notice">Claude · 基线 {step.base_commit.slice(0,12)} · 最多 {repositories.find(r=>r.id===step.repository_id)?.policy.max_turns ?? "待核查"} 轮 · 写入 {step.write_paths.join("、")} · 检查 {step.checks.join("；") || "未配置，不能视为测试通过"}。低风险及预授权命令自动执行，其余逐项审批；本机非安全沙箱。</p>}
                {step.role==="modeler" && <p className="data-notice">Blender 任务按能力派给在线设备，文件只留本机，云端不接收模型或预览。</p>}
                <details className="plan-step-evidence">
                  <summary>交付与验收</summary>
                  <h4>交付物</h4><ul>{step.deliverables.map((item: string, i: number) => <li key={i}>{item}</li>)}</ul>
                  <h4>验收标准</h4><ul>{step.acceptance.map((item: string, i: number) => <li key={i}>{item}</li>)}</ul>
                </details>
                <small>
                  执行目标：
                  {agents.find((a) => a.id === step.agent_id)?.name ||
                    "自动路由（资源与历史职责优先）"}
                </small>
              </article>
            ))}
            <p>设备与权限：{c.draft.device_needs}</p>
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
            <PlanControls
              questions={c.draft.questions || []} clarifying={!!running} waitingChoice={!!pending}
              onClarify={() => {
                if (pending) {
                  document.querySelector<HTMLElement>(".question-card input")?.focus();
                  return;
                }
                action("send", {
                  text: "请把当前计划的待澄清问题通过 ask_user 提供三个具体可选项，另保留自行输入。不要替我回答，也不要发布任务。",
                  mode, request_key: crypto.randomUUID(),
                });
              }}
              assumptions={c.draft.assumptions || []} accepted={accept} onAccept={setAccept}
              calls={calls} images={images} onCalls={setCalls} onImages={setImages}
              reason={publishReason} busy={busy} advanced={advanced} onEdit={advancedEdit}
              localExecution={c.draft.steps.some((s: any) => ["coder", "modeler"].includes(s.role))}
              onPublish={() => action("publish", {
                request_key: crypto.randomUUID(), accept_assumptions: accept,
                policy: {
                  mode: c.draft.steps.every((s: any) => ["coder", "modeler"].includes(s.role)) ? "real" : mode,
                  max_model_calls: calls, max_images: images, timeout: 1800,
                },
              })}
            />
          </div>
        )}
        {c?.releases?.map((release: any) => (
          <div className="release-card" key={release.id}>
            计划 v{release.version} 已发布{" "}
            <button onClick={onBoard}>查看任务看板</button>
          </div>
        ))}
      </div>
      <MainComposer text={text} onText={setText} mode={mode} onMode={setMode}
        pending={!!pending} running={!!running} busy={busy}
        onSend={() => action("send", { text, mode, request_key: crypto.randomUUID() })}
        onCancel={() => {
          const turn = c?.turns.findLast((t: any) => ["queued", "running"].includes(t.state));
          if (turn) action("cancel", { turn_id: turn.id });
        }}
      />
    </section>
  );
}
