/** 一次工具调用对应不可变参数；缓存决定不能被复用到另一个命令。 */
export class PermissionBroker {
  private pending = new Map<string, (allow: boolean) => void>();
  private signatures = new Map<string, string>();
  private decisions = new Map<string, Promise<boolean>>();
  constructor(private emit: (event: Record<string, unknown>) => void) {}
  request(
    id: string,
    tool: string,
    args: Record<string, unknown>,
  ): Promise<boolean> {
    const signature = JSON.stringify({ tool, args });
    if (this.signatures.has(id) && this.signatures.get(id) !== signature)
      throw Error("Permission ID content changed");
    if (!this.decisions.has(id)) {
      this.signatures.set(id, signature);
      this.decisions.set(
        id,
        new Promise((resolve) => this.pending.set(id, resolve)),
      );
      this.emit({ kind: "permission", request_id: id, tool, args });
    }
    return this.decisions.get(id)!;
  }
  respond(id: string, decision: string) {
    const resolve = this.pending.get(id);
    if (!resolve || !["approve", "reject"].includes(decision))
      throw Error("Unknown permission");
    resolve(decision === "approve");
    this.pending.delete(id);
    this.emit({ kind: "permission_applied", request_id: id, decision });
  }
  cancel() {
    for (const resolve of this.pending.values()) resolve(false);
    this.pending.clear();
  }
}
