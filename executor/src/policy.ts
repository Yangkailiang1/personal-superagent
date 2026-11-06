import { existsSync, lstatSync, realpathSync, statSync } from "node:fs";
import { resolve, relative, isAbsolute, sep } from "node:path";

export type Policy = { cwd: string; write_paths: string[]; checks: string[] };
const blocked = new Set([
  ".git",
  ".ssh",
  ".aws",
  ".personal-superagent",
  ".env",
  ".server",
]);
// 所有工具都经过 PreToolUse，不能只依赖「需要询问时」才触发的 canUseTool。
export function safePath(
  cwd: string,
  value: unknown,
  scopes?: string[],
): boolean {
  if (typeof value !== "string" || !value || value.includes("\0")) return false;
  if (value.split(/[\\/]/).includes("..")) return false;
  const target = resolve(cwd, value),
    rel = relative(cwd, target);
  if (isAbsolute(rel) || rel === ".." || rel.startsWith(".." + sep))
    return false;
  const parts = rel.split(sep).filter(Boolean);
  if (
    parts.some(
      (p) =>
        blocked.has(p) || p.startsWith(".env.") || p.startsWith(".server."),
    )
  )
    return false;
  let path = cwd;
  for (const part of parts) {
    path = resolve(path, part);
    try {
      if (lstatSync(path).isSymbolicLink()) return false;
    } catch {
      /* 新建文件的父组件可能尚不存在 */
    }
  }
  if (
    existsSync(target) &&
    !realpathSync(target).startsWith(realpathSync(cwd) + sep) &&
    target !== cwd
  )
    return false;
  return (
    !scopes ||
    scopes.some(
      (s) =>
        rel === s ||
        (s === "." && !!rel) ||
        rel.startsWith(s.replace(/\/$/, "") + "/"),
    )
  );
}
export function classify(
  tool: string,
  args: Record<string, unknown>,
  policy: Policy,
): "allow" | "deny" | "ask" {
  if (tool === "Read")
    return safePath(policy.cwd, args.file_path) ? "allow" : "deny";
  if (tool === "Glob") {
    const pattern = String(args.pattern || "");
    return safePath(policy.cwd, args.path || ".") &&
      !isAbsolute(pattern) &&
      !pattern.split("/").includes("..") &&
      !pattern.includes(".git") &&
      !pattern.includes(".env")
      ? "allow"
      : "deny";
  }
  // 避免递归搜索绕过敏感文件和符号链接限制：先列文件，再对单个文件检索。
  if (tool === "Grep") {
    try {
      return safePath(policy.cwd, args.path) &&
        statSync(resolve(policy.cwd, String(args.path))).isFile()
        ? "allow"
        : "deny";
    } catch {
      return "deny";
    }
  }
  if (tool === "Write" || tool === "Edit")
    return safePath(policy.cwd, args.file_path, policy.write_paths)
      ? "allow"
      : "deny";
  if (tool !== "Bash") return "deny";
  if (args.run_in_background === true || typeof args.command !== "string")
    return "deny";
  const command = args.command;
  // 白名单是完整命令，不接受 Shell 组合、重定向、变量替换或调用者附加参数。
  if (/^[a-zA-Z0-9_ ./=:-]+$/.test(command) && !command.includes("..")) {
    if (
      [
        "pwd",
        "git status --short",
        "git diff --stat",
        "git diff --no-ext-diff",
      ].includes(command)
    )
      return "allow";
    if (policy.checks.includes(command)) return "allow";
  }
  return "ask";
}
