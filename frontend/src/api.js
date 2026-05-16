const BASE = "/api";

export async function fetchConfig() {
  const res = await fetch(`${BASE}/config`);
  if (!res.ok) throw new Error("Failed to load config");
  return res.json();
}

/**
 * Upload a video file and start transcription.
 * @param {File} file
 * @param {{ language: string, model: string, engine: string }} options
 * @returns {Promise<{ job_id: string, status: string }>}
 */
export async function uploadVideo(file, { language, model, engine }) {
  const body = new FormData();
  body.append("file", file);
  body.append("language", language);
  body.append("model", model);
  body.append("engine", engine);

  const res = await fetch(`${BASE}/jobs/upload`, { method: "POST", body });
  const data = await res.json();
  if (!res.ok) throw new Error(data.detail || "Upload failed");
  return data;
}

/**
 * Poll job status once.
 * @param {string} jobId
 */
export async function fetchJob(jobId) {
  const res = await fetch(`${BASE}/jobs/${jobId}`);
  if (!res.ok) throw new Error("Failed to fetch job");
  return res.json();
}

/**
 * Open an SSE connection for live log + status updates.
 * @param {string} jobId
 * @param {{ onLog: Function, onStatus: Function, onDone: Function, onError: Function }} callbacks
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
        onDone?.(data.status);
        es.close();
      } else if (data.type === "error") {
        onError?.(data.message);
        es.close();
      }
    } catch {
      // ignore parse errors
    }
  };

  es.onerror = () => {
    onError?.("Connection to server lost.");
    es.close();
  };

  return es;
}

export function downloadSrtUrl(jobId) {
  return `${BASE}/jobs/${jobId}/download-srt`;
}
