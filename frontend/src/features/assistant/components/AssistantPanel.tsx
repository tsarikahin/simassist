
import { useState } from "react";
import { Bot, Send, User } from "lucide-react";

type Message = {
  role: "assistant" | "user";
  content: string;
};

export function AssistantPanel() {
  const [messages, setMessages] = useState<Message[]>([
    {
      role: "assistant",
      content:
        "Welcome to SimAssist! Describe the simulation you want to create.",
    },
  ]);

  const [input, setInput] = useState("");

  function sendMessage() {
    const content = input.trim();

    if (!content) return;

    setMessages((current) => [
      ...current,
      { role: "user", content },
    ]);

    setInput("");
  }

  return (
    <div className="assistant-content">
      <div className="chat-messages">
        {messages.map((message, index) => (
          <div key={index} className={`chat-message ${message.role}`}>
            {message.role === "assistant" ? (
              <Bot size={17} />
            ) : (
              <User size={17} />
            )}

            <p>{message.content}</p>
          </div>
        ))}
      </div>

      <div className="chat-input-area">
        <textarea
          placeholder="Ask SimAssist..."
          value={input}
          onChange={(event) => setInput(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter" && !event.shiftKey) {
              event.preventDefault();
              sendMessage();
            }
          }}
        />

        <button onClick={sendMessage} aria-label="Send message">
          <Send size={18} />
        </button>
      </div>
    </div>
  );
}
