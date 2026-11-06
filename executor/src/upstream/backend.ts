/**
 * Adapted from Happier ClaudeSdkAgentBackend.ts at manifest.json commit (MIT).
 * 保留上游 start/load、可推送输入、权限 ID、session init、显式 result 与 abort 的生命周期。
 * 将其内部 query 换为固定版本 Anthropic SDK，移除 relay、语音及后台任务依赖。
 */
import { query, type SDKUserMessage } from "@anthropic-ai/claude-agent-sdk";
import { PushableAsyncIterable } from "./PushableAsyncIterable.js";
export type Emit = (event: Record<string, unknown>) => void;
export class HappierExecutor {
  private abortController = new AbortController();
  private prompts = new PushableAsyncIterable<SDKUserMessage>();
  private active: ReturnType<typeof query> | null = null;
  private state = "new";
  private sessionId = "";
  private result: Record<string, unknown> | null = null;
  constructor(
    private emit: Emit,
    private permission: (
      id: string,
      tool: string,
      args: Record<string, unknown>,
    ) => Promise<boolean>,
    private queryFactory: typeof query = query,
  ) {}
  inspect() {
    return { state: this.state, session_id: this.sessionId };
  }
  async cancel() {
    this.state = "cancelled";
    this.prompts.end();
    this.abortController.abort();
    try {
      await this.active?.interrupt();
    } catch {
      /* abort 后 transport 可能已关闭 */
    }
  }
  collect() {
    if (!this.result) throw Error("No terminal result");
    return this.result;
  }
  async start(input: any) {
    if (this.state !== "new") throw Error("Already started");
    this.state = "running";
    const authorize = async (
      id: string,
      tool: string,
      args: Record<string, unknown>,
    ) => {
      if (!id)
        throw Error("Cannot apply permission without canonical tool-use ID");
      return this.permission(id, tool, args);
    };
    this.active = this.queryFactory({
      prompt: this.prompts,
      options: {
        cwd: input.cwd,
        model: input.model || undefined,
        resume: input.resume || undefined,
        abortController: this.abortController,
        permissionMode: "default",
        settingSources: [],
        mcpServers: {},
        tools: ["Read", "Glob", "Grep", "Write", "Edit", "Bash"],
        maxTurns: input.max_turns,
        persistSession: true,
        env: {
          ...process.env,
          CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC: "1",
          CLAUDE_CODE_DISABLE_AUTO_MEMORY: "1",
          GIT_CONFIG_COUNT: "3",
          GIT_CONFIG_KEY_0: "core.hooksPath",
          GIT_CONFIG_VALUE_0: "/dev/null",
          GIT_CONFIG_KEY_1: "core.fsmonitor",
          GIT_CONFIG_VALUE_1: "false",
          GIT_CONFIG_KEY_2: "diff.external",
          GIT_CONFIG_VALUE_2: "",
        },
        hooks: {
          PreToolUse: [
            {
              hooks: [
                async (hook: any) => ({
                  hookSpecificOutput: {
                    hookEventName: "PreToolUse",
                    permissionDecision: (await authorize(
                      hook.tool_use_id,
                      hook.tool_name,
                      hook.tool_input,
                    ))
                      ? "allow"
                      : "deny",
                    permissionDecisionReason:
                      "Workbench frozen policy / explicit user decision",
                    updatedInput:
                      hook.tool_name === "Bash"
                        ? {
                            ...hook.tool_input,
                            command: [
                              "git diff --stat",
                              "git diff --no-ext-diff",
                            ].includes(hook.tool_input.command)
                              ? hook.tool_input.command +
                                " --no-textconv --no-ext-diff"
                              : hook.tool_input.command,
                            timeout: Math.min(
                              Number(hook.tool_input.timeout) || 120000,
                              120000,
                            ),
                            run_in_background: false,
                          }
                        : hook.tool_input,
                  },
                }),
              ],
            },
          ],
        },
        canUseTool: async (tool, args, options) =>
          (await authorize(options.toolUseID, tool, args))
            ? { behavior: "allow", updatedInput: args }
            : {
                behavior: "deny",
                message: "Denied by Workbench policy",
                interrupt: true,
              },
        stderr: () => {},
      },
    });
    this.prompts.push({
      type: "user",
      message: { role: "user", content: input.prompt },
      parent_tool_use_id: null,
      session_id: input.resume || "",
    });
    let terminal = false;
    try {
      for await (const msg of this.active) {
        if (msg.type === "system" && msg.subtype === "init") {
          this.sessionId = msg.session_id;
          this.emit({ kind: "session", session_id: this.sessionId });
        }
        if (msg.type === "assistant") {
          for (const block of msg.message.content) {
            if (block.type === "text")
              this.emit({ kind: "text", text: block.text });
            if (block.type === "tool_use")
              this.emit({
                kind: "tool_start",
                call_id: block.id,
                tool: block.name,
                args: block.input,
              });
          }
        }
        if (msg.type === "user" && Array.isArray(msg.message.content)) {
          for (const block of msg.message.content)
            if (block.type === "tool_result")
              this.emit({
                kind: "tool_end",
                call_id: block.tool_use_id,
                failed: block.is_error || false,
              });
        }
        if (msg.type === "result") {
          terminal = true;
          this.state =
            msg.subtype === "success" && !msg.is_error ? "succeeded" : "failed";
          this.result = {
            state: this.state,
            session_id: this.sessionId,
            text: msg.subtype === "success" ? msg.result : "",
            usage: msg.usage,
            cost_usd: msg.total_cost_usd,
          };
          this.prompts.end();
          break;
        }
      }
      if (!terminal) throw Error("Provider exited without terminal result");
    } finally {
      this.prompts.end();
      this.abortController.abort();
    }
  }
}
