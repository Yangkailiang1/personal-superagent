import { useState } from "react";
import { Laptop, Plus, Copy, ShieldCheck, Folder, Unplug } from "lucide-react";
import { api, toolNames, type Device } from "./api";

export function Devices({
  devices,
  onRefresh,
  onError,
}: {
  devices: Device[];
  onRefresh: () => void;
  onError: (s: string) => void;
}) {
  const [code, setCode] = useState("");
  const run = async (action: () => Promise<unknown>) => {
    try {
      await action();
      onRefresh();
    } catch (e) {
      onError(String(e));
    }
  };
  return (
    <section className="page devices-page">
      <div className="section-heading">
        <div>
          <p className="eyebrow">个人环境</p>
          <h1>设备与授权</h1>
        </div>
        <button
          className="primary"
          onClick={() =>
            run(async () => {
              const r = await api("/api/pairing/", {});
              setCode(r.code);
            })
          }
        >
          <Plus size={16} />
          绑定设备
        </button>
      </div>
      {code && (
        <div className="pairing-box">
          <div>
            <strong>一次性绑定码</strong>
            <span className="muted"> · 10 分钟有效，请在自己的电脑使用</span>
          </div>
          <code>{code}</code>
          <button onClick={() => navigator.clipboard.writeText(code)}>
            <Copy size={14} />
            复制
          </button>
          <pre>
            superagent-client pair --url {location.origin} --code {code} --name
            我的电脑
          </pre>
          <p>
            在本地授权目录后运行客户端。目录内容经授权后会发送至云端和模型。
          </p>
          <button className="link-button" onClick={() => setCode("")}>
            收起
          </button>
        </div>
      )}
      <details className="draft-panel"><summary>连接本机 Claude 代码 Agent</summary>
        <p>先绑定设备，再在本机登记真实 Git 仓库。每个任务使用独立 worktree，保留原目录修改。无需 Happier 账号或服务。</p>
        <pre>{`npm ci --prefix executor && npm run build --prefix executor
superagent-client happier-check
superagent-client happier-repo --name 我的项目 --path /绝对路径/仓库 --write-path src --check "python -m pytest" --ack-cloud-transfer
superagent-client happier-run`}</pre>
        <p>首次使用请先在本机完成 Claude 登录。只授权实际需要的路径和检查命令；撤销用 happier-revoke --name 我的项目。</p>
      </details>
      <div className="device-grid">
        {devices.length === 0 && (
          <div className="empty">
            <Laptop size={34} />
            <h3>连接你的电脑</h3>
            <p>云端编排任务；本机可运行独立 Agent，也可只提供文件工具。</p>
            <p>设备离线时，任务会等待，不会偷偷改用服务器目录。</p>
          </div>
        )}
        {devices.map((device) => (
          <article className="device-card" key={device.id}>
            <header>
              <div className="device-icon">
                <Laptop size={22} />
              </div>
              <div>
                <h3>{device.name}</h3>
                <span className="muted">
                  <i className={device.online ? "dot online" : "dot"} />
                  {device.revoked
                    ? "已解绑"
                    : device.online
                      ? "在线"
                      : "离线"}{" "}
                  · {device.id.slice(0, 8)}
                </span>
              </div>
              {!device.revoked && (
                <button
                  className="icon-button right"
                  aria-label={`解绑 ${device.name}`}
                  onClick={() =>
                    run(() => api("/api/revoke/", { device_id: device.id }))
                  }
                >
                  <Unplug size={16} />
                </button>
              )}
            </header>
            <p className="data-notice">
              {device.agents?.length
                ? `独立工作 Agent：${[...new Set(device.agents.map((a) => a.role))].join("、")} · ${device.agents.some((a) => a.modes.includes("real")) ? "真实模型已声明可用" : "仅演示模型"}`
                : "尚未连接独立工作 Agent；原文件客户端仍可使用。"}
            </p>
            <div className="grants">
              {device.grants.length === 0 && (
                <p className="muted">尚未授权目录。请在本地使用 grant 命令。</p>
              )}
              {device.grants.map((grant) => (
                <div className="grant" key={grant.id}>
                  <Folder size={17} />
                  <div>
                    <strong>{grant.label}</strong>
                    <div className="tool-tags">
                      {grant.tools.map((t) => (
                        <span key={t}>{toolNames[t]}</span>
                      ))}
                    </div>
                    {(grant.revoked_at || !grant.local_enabled) && (
                      <small>已撤销 / 未在本地启用</small>
                    )}
                  </div>
                  {!grant.revoked_at && grant.local_enabled && (
                    <button
                      className="link-button right"
                      onClick={() =>
                        run(() => api("/api/revoke/", { grant_id: grant.id }))
                      }
                    >
                      撤销
                    </button>
                  )}
                </div>
              ))}
            </div>
            <footer>
              <ShieldCheck size={14} />
              只执行已授权工具 · 云端不保存本机绝对路径
            </footer>
          </article>
        ))}
      </div>
    </section>
  );
}
