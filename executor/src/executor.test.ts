import test from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, mkdirSync, symlinkSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { classify, safePath } from "./policy.js";
import { HappierExecutor } from "./upstream/backend.js";
const cwd = mkdtempSync(join(tmpdir(), "executor-policy-"));
mkdirSync(join(cwd, "src"));
const policy = { cwd, write_paths: ["src"], checks: ["python -m pytest"] };
test("paths and symlinks fail closed", () => {
  assert.equal(safePath(cwd, "../outside"), false);
  assert.equal(safePath(cwd, ".git/config"), false);
  symlinkSync(tmpdir(), join(cwd, "link"));
  assert.equal(safePath(cwd, "link/private"), false);
  assert.equal(
    classify("Write", { file_path: join(cwd, "src/a.py") }, policy),
    "allow",
  );
  assert.equal(classify("Write", { file_path: "outside.py" }, policy), "deny");
});
test("commands use exact allowlist; unrecognized commands require approval", () => {
  for (const c of ["pwd", "git status --short", "python -m pytest"])
    assert.equal(classify("Bash", { command: c }, policy), "allow");
  for (const c of [
    "rm -rf src",
    "curl example.com",
    "python -m pytest; curl example.com",
    "git status --short && echo hi",
    "echo $(cat ~/.ssh/id_rsa)",
  ])
    assert.equal(classify("Bash", { command: c }, policy), "ask");
  assert.equal(
    classify("Bash", { command: "pwd", run_in_background: true }, policy),
    "deny",
  );
  assert.equal(classify("Agent", {}, policy), "deny");
});
test("recorded SDK event lifecycle preserves IDs, permissions and explicit result", async () => {
  const events: any[] = [];
  let approved = "";
  let config: any;
  const factory = ((options: any) => {
    config = options.options;
    return (async function* () {
      yield { type: "system", subtype: "init", session_id: "recorded-session" };
      const verdict = await config.canUseTool(
        "Bash",
        { command: "custom" },
        { toolUseID: "call-one" },
      );
      assert.equal(verdict.behavior, "allow");
      yield {
        type: "assistant",
        message: {
          content: [
            {
              type: "tool_use",
              id: "call-one",
              name: "Bash",
              input: { command: "custom" },
            },
          ],
        },
      };
      yield {
        type: "user",
        message: {
          content: [
            { type: "tool_result", tool_use_id: "call-one", content: "done" },
          ],
        },
      };
      yield {
        type: "result",
        subtype: "success",
        is_error: false,
        result: "delivered",
        usage: {},
        total_cost_usd: 0,
      };
    })();
  }) as any;
  const executor = new HappierExecutor(
    (e) => events.push(e),
    async (id) => {
      approved = id;
      return true;
    },
    factory,
  );
  await executor.start({ cwd, prompt: "recorded", max_turns: 3 });
  assert.equal(approved, "call-one");
  assert.equal(executor.inspect().session_id, "recorded-session");
  assert.equal(executor.collect().state, "succeeded");
  assert.equal(events[1].call_id, "call-one");
  assert.deepEqual(config.settingSources, []);
  assert.equal(config.strictMcpConfig, true);
  assert.deepEqual(config.plugins, []);
  assert.equal(config.permissionMode, "default");
});
test("idle or EOF without result is not success", async () => {
  const factory = (() =>
    (async function* () {
      yield { type: "system", subtype: "init", session_id: "no-result" };
    })()) as any;
  const executor = new HappierExecutor(
    () => {},
    async () => false,
    factory,
  );
  await assert.rejects(executor.start({ cwd, prompt: "x", max_turns: 1 }));
  assert.throws(() => executor.collect());
});

test("approval cache binds canonical request to immutable arguments", async () => {
  const { PermissionBroker } = await import("./permissions.js");
  const events: any[] = [];
  const broker = new PermissionBroker((e) => events.push(e));
  const first = broker.request("one", "Bash", { command: "custom" });
  assert.equal(first, broker.request("one", "Bash", { command: "custom" }));
  assert.equal(events.length, 1);
  assert.throws(() => broker.request("one", "Bash", { command: "changed" }));
  broker.respond("one", "reject");
  assert.equal(await first, false);
  const second = broker.request("two", "Bash", { command: "custom" });
  broker.cancel();
  assert.equal(await second, false);
});
