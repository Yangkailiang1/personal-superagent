import { createInterface } from "node:readline";
import { HappierExecutor } from "./upstream/backend.js";
import { classify, type Policy } from "./policy.js";
const emit = (v: Record<string, unknown>) =>
  process.stdout.write(JSON.stringify({ protocol: 1, ...v }) + "\n");
const pending = new Map<
  string,
  { resolve: (v: boolean) => void; tool: string; args: string }
>();
const decisions = new Map<string, Promise<boolean>>();
let policy: Policy;
const executor = new HappierExecutor(emit, async (id, tool, args) => {
  const verdict = classify(tool, args, policy);
  if (verdict !== "ask") return verdict === "allow";
  if (!decisions.has(id)) {
    decisions.set(
      id,
      new Promise((resolve) =>
        pending.set(id, { resolve, tool, args: JSON.stringify(args) }),
      ),
    );
    emit({ kind: "permission", request_id: id, tool, args });
  }
  return decisions.get(id)!;
});
let running = false;
const lines = createInterface({ input: process.stdin });
lines.on("line", (line) => {
  try {
    const msg = JSON.parse(line);
    if (msg.protocol !== 1) throw Error("Protocol mismatch");
    if (msg.action === "start" && !running) {
      running = true;
      policy = {
        cwd: msg.cwd,
        write_paths: msg.write_paths,
        checks: msg.checks,
      };
      void executor
        .start(msg)
        .then(() => emit({ kind: "result", ...executor.collect() }))
        .catch(() =>
          emit({
            kind: "result",
            state: "failed",
            error: "Claude 执行失败；请检查本机认证、模型和运行版本",
          }),
        )
        .finally(() => {
          lines.close();
          process.stdin.pause();
        });
    } else if (msg.action === "respond") {
      const p = pending.get(msg.request_id);
      if (!p || !["approve", "reject"].includes(msg.decision))
        throw Error("Unknown permission");
      p.resolve(msg.decision === "approve");
      pending.delete(msg.request_id);
      emit({
        kind: "permission_applied",
        request_id: msg.request_id,
        decision: msg.decision,
      });
    } else if (msg.action === "cancel") {
      for (const p of pending.values()) p.resolve(false);
      void executor.cancel();
    } else if (msg.action === "inspect")
      emit({ kind: "inspection", ...executor.inspect() });
    else throw Error("Unsupported action");
  } catch {
    emit({ kind: "protocol_error", error: "Invalid executor request" });
  }
});
lines.on("close", () => {
  if (running) void executor.cancel();
});
