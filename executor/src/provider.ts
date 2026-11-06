/** 只读取 CC Switch 写入的连接字段，不启用用户 hooks、插件或通用 MCP。 */
import { readFileSync, existsSync } from "node:fs";
import { join } from "node:path";
import { homedir } from "node:os";
import { createHash } from "node:crypto";
const allowed = [
  "ANTHROPIC_AUTH_TOKEN",
  "ANTHROPIC_API_KEY",
  "ANTHROPIC_BASE_URL",
  "ANTHROPIC_MODEL",
  "ANTHROPIC_DEFAULT_HAIKU_MODEL",
  "ANTHROPIC_DEFAULT_SONNET_MODEL",
  "ANTHROPIC_DEFAULT_OPUS_MODEL",
];
export function loadProvider(
  path = join(homedir(), ".claude", "settings.json"),
) {
  const settings = existsSync(path)
    ? JSON.parse(readFileSync(path, "utf8"))
    : {};
  const env: Record<string, string> = {};
  for (const key of allowed) {
    const value = settings.env?.[key] ?? process.env[key];
    if (typeof value === "string" && value) env[key] = value;
  }
  const fingerprint = createHash("sha256")
    .update(JSON.stringify(env))
    .digest("hex");
  return {
    env,
    model: env.ANTHROPIC_MODEL || "",
    fingerprint,
    configured: Boolean(env.ANTHROPIC_AUTH_TOKEN || env.ANTHROPIC_API_KEY),
  };
}
