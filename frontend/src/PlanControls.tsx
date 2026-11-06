import { ArrowUpRight, ChevronDown, Settings2 } from "lucide-react";

/** 发布门槛仍由主对话和后端检查；这里只把确认与高级设置分开呈现。 */
export function PlanControls({
  assumptions,
  accepted,
  onAccept,
  calls,
  images,
  onCalls,
  onImages,
  reason,
  busy,
  localExecution,
  onPublish,
  onEdit,
  advanced,
  questions,
  onClarify,
  clarifying,
  waitingChoice,
}: {
  assumptions: string[];
  accepted: boolean;
  onAccept: (value: boolean) => void;
  calls: number;
  images: number;
  onCalls: (value: number) => void;
  onImages: (value: number) => void;
  reason: string;
  busy: boolean;
  localExecution: boolean;
  onPublish: () => void;
  onEdit: () => void;
  advanced: boolean;
  questions: string[];
  onClarify: () => void;
  clarifying: boolean;
  waitingChoice: boolean;
}) {
  return (
    <div className="plan-controls">
      {questions.length > 0 && (
        <section className="plan-open-questions" aria-label="阻止发布的问题">
          <h3>发布前还需回答 {questions.length} 个问题</h3>
          <ul>
            {questions.map((question, i) => (
              <li key={i}>{question}</li>
            ))}
          </ul>
          <button onClick={onClarify} disabled={busy || clarifying}>
            {waitingChoice ? "回答上方选择题" : "补充回答"}
          </button>
        </section>
      )}
      {assumptions.length > 0 && (
        <section className="plan-assumptions" aria-label="计划假设">
          <h3>需要你确认的假设</h3>
          <ul>
            {assumptions.map((item, i) => (
              <li key={i}>{item}</li>
            ))}
          </ul>
          <label className="assumption-check">
            <input
              type="checkbox"
              checked={accepted}
              onChange={(e) => onAccept(e.target.checked)}
            />
            <span>我已阅读并接受以上假设</span>
          </label>
        </section>
      )}
      <details className="execution-settings">
        <summary>
          <span>
            <Settings2 size={15} />
            执行设置
          </span>
          <span className="settings-summary">
            每任务 {calls} 次模型请求 · {images} 次生图
            <ChevronDown size={14} />
          </span>
        </summary>
        <div className="execution-fields">
          <label htmlFor="plan-call-limit">
            模型请求上限
            <input
              id="plan-call-limit"
              aria-label="模型请求限额"
              type="number"
              min={1}
              max={48}
              value={calls}
              onChange={(e) => onCalls(Number(e.target.value))}
            />
          </label>
          <label htmlFor="plan-image-limit">
            生图调用上限
            <input
              id="plan-image-limit"
              aria-label="生图限额"
              type="number"
              min={0}
              max={2}
              value={images}
              onChange={(e) => onImages(Number(e.target.value))}
            />
          </label>
        </div>
        <p>
          限额按任务计算。本机 Claude 另受本机授权的轮次限制；Blender
          预览渲染不计入生图调用。
        </p>
      </details>
      {localExecution && (
        <p className="plan-execution-note">
          包含本机执行：使用已授权的设备与工具，可能产生真实模型费用。
        </p>
      )}
      <div className="plan-actions">
        <button className="plan-edit-button" onClick={onEdit} disabled={busy}>
          {advanced ? "收起编辑" : "编辑计划"}
        </button>
        <button
          className="primary publish-button"
          disabled={!!reason || busy}
          onClick={onPublish}
          aria-describedby={reason ? "plan-publish-reason" : undefined}
        >
          {busy ? "处理中…" : "发布并执行"}
          <ArrowUpRight size={15} />
        </button>
      </div>
      <p
        className={`plan-publish-hint ${reason ? "needs-action" : ""}`}
        id="plan-publish-reason"
      >
        {reason || "发布即授权以上任务与执行限额，依赖满足后自动派发。"}
      </p>
    </div>
  );
}
