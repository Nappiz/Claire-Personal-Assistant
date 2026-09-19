export type WebSearchActivity =
  | {
      phase: "searching";
      query: string;
      queries?: string[];
      engines: string[];
    }
  | {
      phase: "reading";
      pages: Array<{
        title: string;
        url: string;
      }>;
    }
  | {
      phase: "complete";
      status: "ok" | "no_results" | "unavailable" | "disabled";
      query: string;
      results: Array<{
        title: string;
        url: string;
        engine: string;
      }>;
      pages: Array<{
        title: string;
        url: string;
      }>;
    };

export type InternalErrorDetails = {
  code: "INTERNAL_FEATURE_ERROR" | string;
  operation: string;
  message: string;
  analysis: string;
  log: string;
};

export type ChatStreamEvent =
  | { type: "session"; session_id: string; turn_id?: string }
  | ({ type: "web_search" } & WebSearchActivity)
  | { type: "delta"; delta: string }
  | {
      type: "done";
      response_status?: "complete" | "incomplete";
      finish_reason?: string | null;
      session_id: string;
      turn_id?: string;
      usage: {
        prompt_tokens?: number;
        completion_tokens?: number;
        total_tokens?: number;
      };
    }
  | {
      type: "error";
      session_id: string;
      turn_id?: string;
      error: { code: string; message: string };
    }
  | {
      type: "internal_error";
      session_id: string;
      error: InternalErrorDetails;
    };

function eventData(frame: string): string | null {
  const data: string[] = [];

  for (const line of frame.split(/\r\n|\r|\n/)) {
    if (!line || line.startsWith(":")) continue;

    const colonIndex = line.indexOf(":");
    const field = colonIndex === -1 ? line : line.slice(0, colonIndex);
    let value = colonIndex === -1 ? "" : line.slice(colonIndex + 1);
    if (value.startsWith(" ")) value = value.slice(1);

    if (field === "data") data.push(value);
  }

  return data.length > 0 ? data.join("\n") : null;
}

export async function* parseSSEStream(
  response: Response,
): AsyncGenerator<ChatStreamEvent> {
  if (!response.ok) {
    throw new Error(`Chat request failed with HTTP ${response.status}`);
  }
  if (!response.body) {
    throw new Error("This browser did not expose a response stream");
  }

  const contentType = response.headers.get("content-type") ?? "";
  if (!contentType.toLowerCase().includes("text/event-stream")) {
    throw new Error(`Expected text/event-stream, received ${contentType || "no content type"}`);
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let finished = false;

  const parseFrame = (frame: string): ChatStreamEvent | null => {
    const data = eventData(frame);
    if (data === null || data === "[DONE]") return null;
    return JSON.parse(data) as ChatStreamEvent;
  };

  try {
    while (true) {
      const { value, done } = await reader.read();
      if (done) {
        finished = true;
        buffer += decoder.decode();
        break;
      }

      buffer += decoder.decode(value, { stream: true });
      while (true) {
        const separator = buffer.match(/\r\n\r\n|\n\n|\r\r/);
        if (!separator || separator.index === undefined) break;

        const frame = buffer.slice(0, separator.index);
        buffer = buffer.slice(separator.index + separator[0].length);
        const parsed = parseFrame(frame);
        if (parsed) yield parsed;
      }
    }

    // Dispatch a final valid event even if an intermediary stripped its last
    // blank line. The backend still always emits the standard delimiter.
    if (buffer.trim()) {
      const parsed = parseFrame(buffer);
      if (parsed) yield parsed;
    }
  } finally {
    if (!finished) await reader.cancel();
    reader.releaseLock();
  }
}
