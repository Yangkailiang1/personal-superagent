export const csrf = () =>
  decodeURIComponent(
    document.cookie
      .split("; ")
      .find((x) => x.startsWith("csrftoken="))
      ?.split("=")[1] || "",
  );
export async function api<T = any>(
  path: string,
  data?: unknown,
  form = false,
): Promise<T> {
  const response = await fetch(path, {
    method: data === undefined ? "GET" : "POST",
    headers:
      data === undefined
        ? {}
        : {
            "X-CSRFToken": csrf(),
            "Content-Type": form
              ? "application/x-www-form-urlencoded"
              : "application/json",
          },
    body:
      data === undefined
        ? undefined
        : form
          ? new URLSearchParams(data as Record<string, string>).toString()
          : JSON.stringify(data),
    cache: "no-store",
  });
  if (response.redirected && response.url.includes("/accounts/login")) {
    location.assign(response.url);
    throw Error("请重新登录");
  }
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw Error(body.error || `请求失败 (${response.status})`);
  }
  if (form) return {} as T;
  return response.json();
}
export const states: Record<string, string> = {
  pending: "待启动",
  queued: "排队中",
  running: "执行中",
  waiting_approval: "待审批",
  waiting_device: "等待设备",
  succeeded: "执行完成",
  failed: "执行失败",
  cancelled: "已取消",
  interrupted: "已中断",
};
export const toolNames: Record<string, string> = {
  list_files: "列出文件",
  read_text: "读取文本",
  write_text: "新建文本",
  local_write_text: "新建本地文件",
  save_document: "保存交付文档",
};
export type Device = {
  id: string;
  name: string;
  online: boolean;
  revoked: boolean;
  last_seen: string | null;
  grants: {
    id: string;
    label: string;
    tools: string[];
    revision: number;
    local_enabled: boolean;
    revoked_at: string | null;
  }[];
};
export type TaskSummary = {
  id: string;
  title: string;
  state: string;
  created_at: string;
};
export type Task = TaskSummary & {
  source?: { conversation_id: string; version: number; draft: unknown } | null;
  attempts?: {
    id: string;
    state: string;
    mode: string;
    error: string;
    created_at: string;
  }[];
  description: string;
  grant_id: string | null;
  attempt?: {
    id: string;
    state: string;
    mode: string;
    activity: string;
    result: string;
    error: string;
    stopped: boolean;
    workflow_version: string;
    scope?: { device_id: string; device_name?: string; label: string } | null;
    started_at: string | null;
    finished_at: string | null;
    plan: { content: string; status: string }[];
    subtasks: any[];
    approvals: any[];
    artifacts: { id: number; name: string }[];
    operations: any[];
    events: any[];
  };
};
export type Bootstrap = {
  user: string;
  real_enabled: boolean;
  tasks: TaskSummary[];
  devices: Device[];
};
