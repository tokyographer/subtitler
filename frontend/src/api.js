const BASE = "/api";

export async function fetchConfig() {
  const res = await fetch(`${BASE}/config`);
  if (!res.ok) throw new Error("Failed to load config");
  return res.json();
}

export async function uploadVideo(file, options) {
  const body = new FormData();
  body.append("file", file);
  body.append("language", options.language);
  body.append("model", options.model);
  body.append("engine", options.engine);
  if (options.filter_translation_track) {
    body.append("filter_translation_track", "true");
  }

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
      else if (data.type === "done") {
        onDone?.(data.status, {
          hallucinationWarning: data.hallucination_warning,
          segmentsDropped: data.segments_dropped,
          loopInfo: data.loop_info,
        });
        es.close();
      }
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

export function downloadRawSrtUrl(jobId) {
  return `${BASE}/jobs/${jobId}/download-raw-srt`;
}

export async function generateTranscript(jobId, provider) {
  const res = await fetch(`${BASE}/jobs/${jobId}/transcript`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ provider: provider ?? null }),
  });
  const data = await res.json();
  if (!res.ok) throw new Error(data.detail || "Failed to start transcript generation");
  return data;
}

export function downloadTranscriptUrl(jobId) {
  return `${BASE}/jobs/${jobId}/download-transcript`;
}
