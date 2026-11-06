import { createInterface } from "node:readline";
import { HappierExecutor } from "./upstream/backend.js";
import { classify, type Policy } from "./policy.js";
import { PermissionBroker } from "./permissions.js";
const emit = (v: Record<string, unknown>) =>
  process.stdout.write(JSON.stringify({ protocol: 1, ...v }) + "\n");
const broker = new PermissionBroker(emit);
let policy: Policy;
const executor = new HappierExecutor(emit, async (id, tool, args) => {
  const verdict = classify(tool, args, policy);
  if (verdict !== "ask") return verdict === "allow";
  return broker.request(id, tool, args);
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
      broker.respond(msg.request_id, msg.decision);
    } else if (msg.action === "cancel") {
      broker.cancel();
      void executor.cancel();
    } else if (msg.action === "inspect")
      emit({ kind: "inspection", ...executor.inspect() });
    else throw Error("Unsupported action");
  } catch {
    emit({ kind: "protocol_error", error: "Invalid executor request" });
  }
});
lines.on("close", () => {
  broker.cancel();
  if (running) void executor.cancel();
});
