import { api } from "./api";
export function LocalFiles({
  files,
  onError,
}: {
  files: any[];
  onError: (s: string) => void;
}) {
  if (!files?.length) return null;
  return (
    <section className="draft-panel external-run">
      <h3>本机交付文件</h3>
      <p>云端只保存追踪关系；文件和预览留在执行设备。</p>
      {files.map((f) => (
        <div key={f.id} className="artifact-card">
          <div>
            <strong>{f.path}</strong>
            <p>
              {f.device_name} · {(f.size / 1024).toFixed(1)} KB ·{" "}
              {f.device_online
                ? (
                    {
                      available: "可访问",
                      changed: "文件已变化",
                      missing: "文件已删除",
                    } as any
                  )[f.state]
                : "设备离线"}
            </p>
            <small>SHA-256 {f.sha256.slice(0, 16)}…</small>
          </div>
          <button
            disabled={!f.device_online || f.state !== "available"}
            onClick={async () => {
              try {
                await api("/api/local-files/open/", { id: f.id });
              } catch (e) {
                onError(String(e));
              }
            }}
          >
            在执行设备打开
          </button>
        </div>
      ))}
    </section>
  );
}
