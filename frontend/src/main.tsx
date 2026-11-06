import { useCallback, useEffect, useState, useRef } from "react";
import { createRoot } from "react-dom/client";
import {
  Plus,
  LayoutGrid,
  Layers,
  Laptop,
  ArrowUpRight,
  LogOut,
  Sparkle,
  Search,
  PanelLeftClose,
  PanelLeftOpen,
} from "lucide-react";
import { api, csrf, states, type Bootstrap, type Task } from "./api";
import { TaskComposer } from "./Chat";
import { Board } from "./Board";
import { Intake } from "./Intake";
import { Devices } from "./Devices";
import { TaskDetail } from "./TaskDetail";
import "./style.css";

function App() {
  const [data, setData] = useState<Bootstrap>({
    user: "",
    tasks: [],
    devices: [],
    real_enabled: false,
  });
  const [intakeId, setIntakeId] = useState(
    new URLSearchParams(location.search).get("intake") || "",
  );
  const [view, setView] = useState(
      new URLSearchParams(location.search).has("intake")
        ? "intake"
        : new URLSearchParams(location.search).get("view") || "board",
    ),
    [selected, setSelected] = useState(
      new URLSearchParams(location.search).get("task") || "",
    ),
    [task, setTask] = useState<Task | null>(null);
  const [error, setError] = useState(""),
    [busy, setBusy] = useState(false),
    [query, setQuery] = useState(""),
    [grant, setGrant] = useState(""),
    [source, setSource] = useState("input.md"),
    [side, setSide] = useState(() => window.innerWidth > 650);
  const [connected, setConnected] = useState(false);
  const current = useRef(selected);
  current.current = selected;
  const refresh = useCallback(async () => {
    try {
      setData(await api<Bootstrap>("/api/bootstrap/"));
      setConnected(true);
      if (selected) {
        const next = await api<Task>(`/api/task/?id=${selected}`);
        if (current.current === selected) setTask(next);
      }
    } catch (e) {
      setConnected(false);
      setError(String(e));
    }
  }, [selected]);
  useEffect(() => {
    refresh();
    const timer = setInterval(refresh, 2000);
    return () => clearInterval(timer);
  }, [refresh]);
  function choose(id: string) {
    setSelected(id);
    setTask(null);
    setView("task");
    if (window.innerWidth <= 650) setSide(false);
    history.replaceState(null, "", `?task=${id}`);
  }
  useEffect(() => {
    if (selected) setView("task");
  }, []);
  async function create(text: string) {
    setBusy(true);
    setError("");
    try {
      const next = await api<Task>("/api/create/", {
        text,
        grant_id: grant || null,
        source_path: source,
      });
      choose(next.id);
      setTask(next);
      await refresh();
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }
  const grants = data.devices
    .filter((d) => !d.revoked)
    .flatMap((d) =>
      d.grants
        .filter((g) => g.local_enabled && !g.revoked_at)
        .map((g) => ({ ...g, device: d.name })),
    );
  return (
    <div className={`shell ${side ? "" : "side-hidden"}`}>
      <aside className="sidebar">
        <button
          className="icon-button side-close"
          aria-label="收起侧栏"
          onClick={() => setSide(false)}
        >
          <PanelLeftClose size={17} />
        </button>
        <a className="brand" href="/app/">
          <span className="brand-icon">
            <Sparkle size={19} />
          </span>
          superagent<span className="version">0.5</span>
        </a>
        <button
          className="new-task"
          onClick={() => {
            setSelected("");
            setTask(null);
            setView("home");
            history.replaceState(null, "", "/app/");
          }}
        >
          <Plus size={17} />
          新建任务<span className="key-hint">↗</span>
        </button>
        <nav>
          {[
            ["board", "任务看板", LayoutGrid],
            ["intake", "需求对话", Layers],
            ["home", "快速创建", Plus],
            ["queue", "任务队列", Layers],
            ["devices", "设备与授权", Laptop],
          ].map(([key, label, Icon]) => {
            const I = Icon as typeof Laptop;
            return (
              <button
                key={key as string}
                className={view === key ? "nav-active" : ""}
                onClick={() => {
                  setView(key as string);
                  setSelected("");
                  setTask(null);
                  history.replaceState(null, "", `/app/?view=${key}`);
                  if (window.innerWidth <= 650) setSide(false);
                }}
              >
                <I size={17} />
                {label as string}
                {key === "queue" && (
                  <span className="count">
                    {
                      data.tasks.filter((t) =>
                        ["running", "queued"].includes(t.state),
                      ).length
                    }
                  </span>
                )}
              </button>
            );
          })}
        </nav>
        <div className="sidebar-section">最近任务</div>
        <div className="recent">
          {data.tasks.slice(0, 12).map((t) => (
            <button
              className={
                selected === t.id && view === "task" ? "recent-active" : ""
              }
              key={t.id}
              onClick={() => choose(t.id)}
            >
              <i className={`dot ${t.state === "running" ? "online" : ""}`} />
              <span>{t.title}</span>
            </button>
          ))}
        </div>
        <footer className="user-panel">
          <div className="avatar">{data.user.slice(0, 1).toUpperCase()}</div>
          <div>
            <strong>{data.user || "加载中"}</strong>
            <small>个人工作空间</small>
          </div>
          <form method="post" action="/accounts/logout/">
            <input type="hidden" name="csrfmiddlewaretoken" value={csrf()} />
            <button className="icon-button" aria-label="退出">
              <LogOut size={16} />
            </button>
          </form>
        </footer>
      </aside>
      <main className="main">
        <header className="topbar">
          <button
            className="icon-button"
            aria-label="切换侧栏"
            onClick={() => setSide(!side)}
          >
            {side ? <PanelLeftClose size={17} /> : <PanelLeftOpen size={17} />}
          </button>
          <span>
            {view === "board"
              ? "任务看板"
              : view === "intake"
                ? "需求对话"
                : view === "devices"
                  ? "设备与授权"
                  : view === "queue"
                    ? "任务队列"
                    : "个人工作台"}
          </span>
          <div className="topbar-right">
            <span className="environment">
              <i className={connected ? "dot online" : "dot"} />
              {connected ? "云端已连接" : "等待同步"}
            </span>
            <a href="/" title="返回首页">
              <ArrowUpRight size={16} />
            </a>
          </div>
        </header>
        {error && (
          <div className="toast" role="alert">
            {error}
            <button onClick={() => setError("")}>×</button>
          </div>
        )}
        {view === "board" && (
          <Board
            onTask={choose}
            onDraft={(id) => {
              setIntakeId(id);
              setView("intake");
              history.replaceState(null, "", `/app/?intake=${id}`);
            }}
          />
        )}
        {view === "intake" && (
          <Intake initialId={intakeId} onTask={choose} devices={data.devices} />
        )}
        {view === "home" && (
          <section className="home">
            <div className="home-heading">
              <div className="welcome-symbol">
                <Sparkle size={28} />
              </div>
              <h1>把想法交给工作台</h1>
              <p>云端编排，本地执行，由你掌控。</p>
            </div>
            <div className="compose-wrap">
              <TaskComposer busy={busy} onCreate={create} />
              <div className="scope-select">
                <label>
                  执行环境
                  <select
                    aria-label="授权目录"
                    value={grant}
                    onChange={(e) => setGrant(e.target.value)}
                  >
                    <option value="">仅云端 · 不访问本机</option>
                    {grants.map((g) => (
                      <option value={g.id} key={g.id}>
                        {g.device} / {g.label}
                      </option>
                    ))}
                  </select>
                </label>
                {grant && (
                  <label>
                    材料文件
                    <input
                      aria-label="材料文件"
                      value={source}
                      onChange={(e) => setSource(e.target.value)}
                      placeholder="input.md"
                    />
                  </label>
                )}
              </div>
              {grant && (
                <p className="data-notice">
                  仅访问所选授权目录，读取内容将发送云端模型；写入仍需单次审批。
                </p>
              )}
            </div>
            <div className="home-bottom">
              <span>01 / 提交目标</span>
              <span>02 / Agent 协作</span>
              <span>03 / 审核交付</span>
            </div>
          </section>
        )}
        {view === "queue" && (
          <section className="page queue">
            <div className="section-heading">
              <div>
                <p className="eyebrow">后台工作</p>
                <h1>任务队列</h1>
              </div>
              <label className="search">
                <Search size={16} />
                <input
                  aria-label="搜索任务"
                  placeholder="搜索任务"
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                />
              </label>
            </div>
            <div className="queue-list">
              {data.tasks
                .filter((t) => t.title.includes(query))
                .map((t) => (
                  <button
                    className="queue-row"
                    key={t.id}
                    onClick={() => choose(t.id)}
                  >
                    <span className={`task-glyph ${t.state}`}>
                      <Layers size={18} />
                    </span>
                    <span className="task-name">
                      <strong>{t.title}</strong>
                      <small>
                        {new Date(t.created_at).toLocaleString("zh-CN", {
                          month: "short",
                          day: "numeric",
                          hour: "2-digit",
                          minute: "2-digit",
                        })}
                      </small>
                    </span>
                    <span className={`status status-${t.state}`}>
                      {states[t.state]}
                    </span>
                    <ArrowUpRight size={16} />
                  </button>
                ))}
              {!data.tasks.length && (
                <div className="empty">还没有任务，先提交一个目标。</div>
              )}
            </div>
          </section>
        )}
        {view === "devices" && (
          <Devices
            devices={data.devices}
            onRefresh={refresh}
            onError={setError}
          />
        )}
        {view === "task" && task && (
          <TaskDetail
            task={task}
            realEnabled={data.real_enabled}
            onRefresh={refresh}
            onError={setError}
          />
        )}
      </main>
    </div>
  );
}
createRoot(document.getElementById("root")!).render(<App />);
