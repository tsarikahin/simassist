
import { useEffect, useRef, useState } from "react";
import { Bot, Send, User } from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import { streamChatMessage } from "../../../services/chat";

type Message = {
  id: number;
  role: "assistant" | "user";
  content: string;
};

interface AssistantPanelProps {
  projectId: string;
  onJobsSubmitted: (jobIds: string[]) => void;
}

export function AssistantPanel({
  projectId,
  onJobsSubmitted,
}: AssistantPanelProps) {
  const [messages, setMessages] = useState<Message[]>([
    {
      id: 0,
      role: "assistant",
      content:
        "Welcome to SimAssist! Describe the engineering simulation you want to create.",
    },
  ]);

  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [status, setStatus] = useState<string | null>(null);

  const nextMessageId = useRef(1);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const controllerRef = useRef<AbortController | null>(null);
  const sendingRef = useRef(false);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({
      behavior: "smooth",
      block: "end",
    });
  }, [messages, loading, status]);

  useEffect(() => {
    return () => controllerRef.current?.abort();
  }, []);

  async function sendMessage() {
    const content = input.trim();

    if (!content || sendingRef.current) return;

    sendingRef.current = true;
    setLoading(true);
    setStatus("Connecting to SimAssist...");
    setInput("");

    const userId = nextMessageId.current++;
    const assistantId = nextMessageId.current++;

    setMessages((current) => [
      ...current,
      {
        id: userId,
        role: "user",
        content,
      },
      {
        id: assistantId,
        role: "assistant",
        content: "",
      },
    ]);

    const controller = new AbortController();
    controllerRef.current = controller;

    const knownJobIds = new Set<string>();

    function reportJobs(jobIds: string[]) {
      const fresh = jobIds.filter(
        (id) => !knownJobIds.has(id),
      );

      for (const id of fresh) {
        knownJobIds.add(id);
      }

      if (fresh.length > 0) {
        onJobsSubmitted(fresh);
      }
    }

    try {
      await streamChatMessage(
        {
          project_id: projectId,
          message: content,
        },
        {
          onStatus(message) {
            setStatus(message);
          },

          onDelta(text) {
            setStatus(null);

            setMessages((current) =>
              current.map((message) =>
                message.id === assistantId
                  ? {
                      ...message,
                      content: message.content + text,
                    }
                  : message,
              ),
            );
          },

          onJobs(jobIds) {
            reportJobs(jobIds);
          },

          onDone(response) {
            // The final text is authoritative.
            setMessages((current) =>
              current.map((message) =>
                message.id === assistantId
                  ? {
                      ...message,
                      content:
                        response.message ||
                        message.content,
                    }
                  : message,
              ),
            );

            reportJobs(response.submitted_job_ids);
          },
        },
        controller.signal,
      );
    } catch (error) {
      if (!controller.signal.aborted) {
        const detail =
          error instanceof Error
            ? error.message
            : "Unknown streaming error";

        setMessages((current) =>
          current.map((message) =>
            message.id === assistantId
              ? {
                  ...message,
                  content:
                    message.content +
                    `\n\n**Stream error:** ${detail}`,
                }
              : message,
          ),
        );
      }
    } finally {
      controllerRef.current = null;
      sendingRef.current = false;
      setLoading(false);
      setStatus(null);
    }
  }

  return (
    <div className="assistant-content">
      <div className="chat-messages">
        {messages.map((message) => (
          <div
            key={message.id}
            className={`chat-message ${message.role}`}
          >
            {message.role === "assistant" ? (
              <Bot size={17} />
            ) : (
              <User size={17} />
            )}

            <div className="message-content">
              {message.role === "assistant" ? (
                <ReactMarkdown
                  remarkPlugins={[remarkGfm]}
                >
                  {message.content}
                </ReactMarkdown>
              ) : (
                <p>{message.content}</p>
              )}

              {loading &&
                message.id === nextMessageId.current - 1 &&
                !message.content && (
                  <span className="streaming-indicator">
                    {status || "Thinking..."}
                  </span>
                )}
            </div>
          </div>
        ))}

        <div ref={messagesEndRef} />
      </div>

      <div className="chat-input-area">
        <textarea
          placeholder={
            loading
              ? "SimAssist is responding..."
              : "Describe your simulation..."
          }
          value={input}
          disabled={loading}
          onChange={(event) => {
            setInput(event.target.value);
          }}
          onKeyDown={(event) => {
            if (
              event.key === "Enter" &&
              !event.shiftKey &&
              !event.nativeEvent.isComposing
            ) {
              event.preventDefault();
              void sendMessage();
            }
          }}
        />

        <button
          type="button"
          disabled={loading || !input.trim()}
          onClick={() => void sendMessage()}
          aria-label="Send message"
        >
          <Send size={18} />
        </button>
      </div>
    </div>
  );
}
