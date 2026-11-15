
const API_URL =
  import.meta.env.VITE_API_URL ?? "http://localhost:8000";

export interface ChatRequest {
  project_id: string;
  message: string;
}

export interface ChatResponse {
  message: string;
  submitted_job_ids: string[];
}

export interface ChatStreamHandlers {
  onStatus?: (message: string) => void;
  onDelta?: (text: string) => void;
  onJobs?: (jobIds: string[]) => void;
  onDone?: (response: ChatResponse) => void;
}

export async function sendChatMessage(
  request: ChatRequest,
): Promise<ChatResponse> {
  const response = await fetch(`${API_URL}/api/chat`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(request),
  });

  if (!response.ok) {
    throw new Error(`Chat failed: HTTP ${response.status}`);
  }

  return (await response.json()) as ChatResponse;
}

export async function streamChatMessage(
  request: ChatRequest,
  handlers: ChatStreamHandlers,
  signal?: AbortSignal,
): Promise<void> {
  const response = await fetch(
    `${API_URL}/api/chat/stream`,
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Accept: "text/event-stream",
      },
      body: JSON.stringify(request),
      signal,
    },
  );

  if (!response.ok) {
    throw new Error(
      `Chat stream failed: HTTP ${response.status}`,
    );
  }

  if (!response.body) {
    throw new Error("Streaming response has no body");
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();

  let buffer = "";
  let completed = false;

  function processEvent(block: string) {
    let eventName = "message";
    const dataLines: string[] = [];

    for (const line of block.split("\n")) {
      if (line.startsWith("event:")) {
        eventName = line.slice(6).trim();
      } else if (line.startsWith("data:")) {
        dataLines.push(line.slice(5).trimStart());
      }
    }

    if (dataLines.length === 0) return;

    const payload: unknown = JSON.parse(
      dataLines.join("\n"),
    );

    if (!payload || typeof payload !== "object") {
      throw new Error("Invalid SSE payload");
    }

    const data = payload as Record<string, unknown>;

    switch (eventName) {
      case "status":
        if (typeof data.message === "string") {
          handlers.onStatus?.(data.message);
        }
        break;

      case "delta":
        if (typeof data.text === "string") {
          handlers.onDelta?.(data.text);
        }
        break;

      case "jobs":
        if (
          Array.isArray(data.job_ids) &&
          data.job_ids.every(
            (id) => typeof id === "string",
          )
        ) {
          handlers.onJobs?.(data.job_ids);
        }
        break;

      case "done": {
        if (
          typeof data.message !== "string" ||
          !Array.isArray(data.submitted_job_ids) ||
          !data.submitted_job_ids.every(
            (id) => typeof id === "string",
          )
        ) {
          throw new Error("Invalid completion payload");
        }

        completed = true;

        handlers.onDone?.({
          message: data.message,
          submitted_job_ids: data.submitted_job_ids,
        });
        break;
      }

      case "error":
        throw new Error(
          typeof data.message === "string"
            ? data.message
            : "Agent stream failed",
        );
    }
  }

  function processBuffer() {
    // Normalize line endings before parsing SSE blocks.
    buffer = buffer.replace(/\r\n/g, "\n");

    let separator = buffer.indexOf("\n\n");

    while (separator !== -1) {
      const block = buffer.slice(0, separator);
      buffer = buffer.slice(separator + 2);

      processEvent(block);

      separator = buffer.indexOf("\n\n");
    }
  }

  try {
    while (true) {
      const { done, value } = await reader.read();

      if (done) break;

      buffer += decoder.decode(value, {
        stream: true,
      });

      processBuffer();
    }

    buffer += decoder.decode();
    processBuffer();

    if (buffer.trim()) {
      processEvent(buffer);
    }

    if (!completed) {
      throw new Error(
        "Chat stream ended without completion",
      );
    }
  } finally {
    await reader.cancel().catch(() => {});
    reader.releaseLock();
  }
}
