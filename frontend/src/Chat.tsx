import {
  AssistantRuntimeProvider,
  ThreadPrimitive,
  MessagePrimitive,
  ComposerPrimitive,
  useExternalStoreRuntime,
  type AppendMessage,
  type ThreadMessageLike,
} from "@assistant-ui/react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { ArrowUp, Sparkle } from "lucide-react";

export function Markdown({ text }: { text: string }) {
  return (
    <div className="markdown">
      <ReactMarkdown remarkPlugins={[remarkGfm]}>{text}</ReactMarkdown>
    </div>
  );
}
function Text({ text }: { text: string }) {
  return <Markdown text={text} />;
}
function UserMessage() {
  return (
    <MessagePrimitive.Root className="message user-message">
      <MessagePrimitive.Parts components={{ Text }} />
    </MessagePrimitive.Root>
  );
}
function AssistantMessage() {
  return (
    <MessagePrimitive.Root className="message assistant-message">
      <span className="assistant-mark">
        <Sparkle size={16} />
      </span>
      <MessagePrimitive.Parts components={{ Text }} />
    </MessagePrimitive.Root>
  );
}

export function Conversation({
  text,
  result,
}: {
  text: string;
  result: string;
}) {
  const messages: ThreadMessageLike[] = [];
  if (text)
    messages.push({
      id: "input",
      role: "user",
      content: [{ type: "text", text }],
    });
  if (result)
    messages.push({
      id: "result",
      role: "assistant",
      content: [{ type: "text", text: result }],
    });
  const runtime = useExternalStoreRuntime({
    messages,
    convertMessage: (message: ThreadMessageLike) => message,
    onNew: async () => {},
  });
  return (
    <AssistantRuntimeProvider runtime={runtime}>
      <ThreadPrimitive.Root>
        <ThreadPrimitive.Viewport>
          <ThreadPrimitive.Messages
            components={{ UserMessage, AssistantMessage }}
          />
        </ThreadPrimitive.Viewport>
      </ThreadPrimitive.Root>
    </AssistantRuntimeProvider>
  );
}

export function TaskComposer({
  onCreate,
  busy,
}: {
  onCreate: (text: string) => Promise<void>;
  busy: boolean;
}) {
  const runtime = useExternalStoreRuntime({
    messages: [] as ThreadMessageLike[],
    isRunning: busy,
    convertMessage: (m: ThreadMessageLike) => m,
    onNew: async (message: AppendMessage) => {
      const text = message.content
        .filter((p) => p.type === "text")
        .map((p) => (p.type === "text" ? p.text : ""))
        .join("\n");
      if (text.trim()) await onCreate(text);
    },
  });
  return (
    <AssistantRuntimeProvider runtime={runtime}>
      <ComposerPrimitive.Root className="composer">
        <ComposerPrimitive.Input
          placeholder="描述你想完成的任务…"
          className="composer-input"
          autoFocus
          aria-label="任务需求"
        />
        <div className="composer-bottom">
          <span>先创建任务，再确认执行范围</span>
          <ComposerPrimitive.Send
            className="send-button"
            aria-label="创建任务"
            disabled={busy}
          >
            <ArrowUp size={19} />
          </ComposerPrimitive.Send>
        </div>
      </ComposerPrimitive.Root>
    </AssistantRuntimeProvider>
  );
}
