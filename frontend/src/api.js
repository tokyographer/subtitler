const BASE = "/api";

export async function fetchConfig() {
  const res = await fetch(`${BASE}/config`);
  if (!res.ok) throw new Error("Failed to load config");
  return res.json();
}

/**
 * @param {File} file
 * @param {{
 *   language: string,
 *   model: string,
 *   engine: string,
 *   task: string,
 *   max_line_chars: number,
 *   max_segment_duration: number,
 *   merge_gap_ms: number,
 * }} options
 */
export async function uploadVideo(file, options) {
  const body = new FormData();
  body.append("file", file);
  body.append("language", options.language);
  body.append("model", options.model);
  body.append("engine", options.engine);
  body.append("task", options.task ?? "transcribe");
  body.append("max_line_chars", String(options.max_line_chars ?? 42));
  body.append("max_segment_duration", String(options.max_segment_duration ?? 0));
  body.append("merge_gap_ms", String(options.merge_gap_ms ?? 0));

  const res = await fetch(`${BASE}/jobs/upload`, { method: "POST", body });
  const data = await res.json();
  if (!res.ok) throw new Error(data.detail || "Upload failed");
  return data;
}

export async function fetchJob(jobId) {
  const res = await fetch(`${BASE}/jobs/${jobId}`);
  if (!res.ok) throw new Error("Failed to fetch job");
  return res.json();
}

/**
 * Open an SSE connection for live log + status updates.
 * @returns {EventSource}
 */
export function subscribeLogs(jobId, { onLog, onStatus, onDone, onError }) {
  const es = new EventSource(`${BASE}/jobs/${jobId}/logs`);

  es.onmessage = (event) => {
    try {
      const data = JSON.parse(event.data);
      if (data.type === "log") onLog?.(data.message);
      else if (data.type === "status") onStatus?.(data.status, data.progress);
      else if (data.type === "done") { onDone?.(data.status); es.close(); }
      else if (data.type === "error") { onError?.(data.message); es.close(); }
    } catch {
      // ignore parse errors
    }
  };

  es.onerror = () => { onError?.("Connection to server lost."); es.close(); };
  return es;
}

export function downloadSrtUrl(jobId) {
  return `${BASE}/jobs/${jobId}/download-srt`;
}
