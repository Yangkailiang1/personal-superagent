import { useEffect, useRef } from "react";
import { ArrowUp, ChevronDown, Square } from "lucide-react";

/** Enter 发送、Shift+Enter 换行；中文输入法选词时不发送。 */
export function MainComposer({
  text,
  onText,
  mode,
  onMode,
  pending,
  running,
  busy,
  onSend,
  onCancel,
}: {
  text: string;
  onText: (text: string) => void;
  mode: string;
  onMode: (mode: string) => void;
  pending: boolean;
  running: boolean;
  busy: boolean;
  onSend: () => void;
  onCancel: () => void;
}) {
  const input = useRef<HTMLTextAreaElement>(null);
  useEffect(() => {
    if (!input.current) return;
    input.current.style.height = "0px";
    input.current.style.height = `${Math.min(160, Math.max(40, input.current.scrollHeight))}px`;
  }, [text]);
  return (
    <form
      className="main-composer"
      onSubmit={(e) => {
        e.preventDefault();
        if (text.trim() && !pending && !running && !busy) onSend();
      }}
    >
      <textarea
        id="main-chat-message"
        ref={input}
        aria-label="主对话消息"
        rows={1}
        placeholder={
          pending ? "先选择上方选项，或自行输入回答" : "描述任务，或补充计划…"
        }
        value={text}
        onChange={(e) => onText(e.target.value)}
        disabled={pending}
        onKeyDown={(e) => {
          if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
            e.preventDefault();
            e.currentTarget.form?.requestSubmit();
          }
        }}
      />
      <div className="composer-toolbar">
        <div className="composer-mode">
          <select
            aria-label="主对话模型模式"
            value={mode}
            onChange={(e) => onMode(e.target.value)}
            disabled={busy || running}
          >
            <option value="demo">离线演示</option>
            <option value="real">真实模型</option>
          </select>
          <ChevronDown size={12} aria-hidden="true" />
        </div>
        {running ? (
          <button
            type="button"
            className="composer-send"
            aria-label="停止本轮"
            title="停止本轮"
            disabled={busy}
            onClick={onCancel}
          >
            <Square size={13} fill="currentColor" />
          </button>
        ) : (
          <button
            type="submit"
            className="composer-send"
            aria-label="发送"
            title="发送 · Enter"
            disabled={!text.trim() || busy || pending}
          >
            <ArrowUp size={18} />
          </button>
        )}
      </div>
    </form>
  );
}
