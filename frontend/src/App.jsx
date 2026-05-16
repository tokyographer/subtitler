import { useCallback, useEffect, useRef, useState } from "react";
import {
  downloadSrtUrl,
  fetchConfig,
  subscribeLogs,
  uploadVideo,
} from "./api";

const STATUS_LABEL = {
  uploaded: "Queued",
  extracting_audio: "Extracting Audio",
  transcribing: "Transcribing",
  generating_srt: "Generating SRT",
  completed: "Completed",
  failed: "Failed",
};

function Badge({ status }) {
  return (
    <span className={`badge badge-${status}`}>
      {STATUS_LABEL[status] ?? status}
    </span>
  );
}

function ProgressBar({ progress, status }) {
  const cls =
    status === "completed"
      ? "done"
      : status === "failed"
      ? "failed"
      : "";
  return (
    <div>
      <div className="progress-track">
        <div
          className={`progress-fill ${cls}`}
          style={{ width: `${progress}%` }}
        />
      </div>
      <div className="progress-label">{progress}%</div>
    </div>
  );
}

export default function App() {
  const [config, setConfig] = useState(null);
  const [file, setFile] = useState(null);
  const [isDragging, setIsDragging] = useState(false);
  const [language, setLanguage] = useState("auto");
  const [model, setModel] = useState("large-v3-turbo");
  const [engine, setEngine] = useState("mlx");

  const [jobId, setJobId] = useState(null);
  const [jobStatus, setJobStatus] = useState(null);
  const [progress, setProgress] = useState(0);
  const [logs, setLogs] = useState([]);
  const [error, setError] = useState(null);
  const [uploading, setUploading] = useState(false);

  const logBoxRef = useRef(null);
  const fileInputRef = useRef(null);

  // Load backend config (models / languages / engines)
  useEffect(() => {
    fetchConfig()
      .then((cfg) => {
        setConfig(cfg);
        setModel(cfg.defaults.model);
        setLanguage(cfg.defaults.language);
        setEngine(cfg.defaults.engine);
      })
      .catch(() => setError("Could not reach the backend. Is the server running?"));
  }, []);

  // Auto-scroll logs
  useEffect(() => {
    if (logBoxRef.current) {
      logBoxRef.current.scrollTop = logBoxRef.current.scrollHeight;
    }
  }, [logs]);

  // SSE subscription for the active job
  useEffect(() => {
    if (!jobId) return;
    const es = subscribeLogs(jobId, {
      onLog: (msg) =>
        setLogs((prev) => [...prev, { text: msg, type: "log" }]),
      onStatus: (status, pct) => {
        setJobStatus(status);
        setProgress(pct);
      },
      onDone: (status) => setJobStatus(status),
      onError: (msg) =>
        setLogs((prev) => [...prev, { text: msg, type: "error" }]),
    });
    return () => es.close();
  }, [jobId]);

  // Drag & drop handlers
  const onDrop = useCallback((e) => {
    e.preventDefault();
    setIsDragging(false);
    const dropped = e.dataTransfer.files[0];
    if (dropped) setFile(dropped);
  }, []);

  const onDragOver = (e) => { e.preventDefault(); setIsDragging(true); };
  const onDragLeave = () => setIsDragging(false);

  const onFileChange = (e) => {
    const picked = e.target.files?.[0];
    if (picked) setFile(picked);
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!file) return;

    setError(null);
    setLogs([]);
    setJobId(null);
    setJobStatus(null);
    setProgress(0);
    setUploading(true);

    try {
      const { job_id } = await uploadVideo(file, { language, model, engine });
      setJobId(job_id);
      setJobStatus("uploaded");
    } catch (err) {
      setError(err.message);
    } finally {
      setUploading(false);
    }
  };

  const reset = () => {
    setFile(null);
    setJobId(null);
    setJobStatus(null);
    setProgress(0);
    setLogs([]);
    setError(null);
    if (fileInputRef.current) fileInputRef.current.value = "";
  };

  const isProcessing =
    jobStatus && !["completed", "failed"].includes(jobStatus);
  const canSubmit = !!file && !uploading && !isProcessing;

  return (
    <div className="app">
      <header>
        <h1>🎬 Subtitler</h1>
        <p>Local video transcription → YouTube-compatible .srt</p>
      </header>

      {error && !jobId && (
        <div className="card">
          <div className="error-box">{error}</div>
        </div>
      )}

      {/* ── Upload form ── */}
      {!jobId && (
        <div className="card">
          <form onSubmit={handleSubmit}>
            <div
              className={`drop-zone${isDragging ? " over" : ""}${file ? " has-file" : ""}`}
              onDrop={onDrop}
              onDragOver={onDragOver}
              onDragLeave={onDragLeave}
              onClick={() => fileInputRef.current?.click()}
            >
              {file ? (
                <>
                  <div className="icon">{file.type.startsWith("audio/") ? "🎵" : "🎥"}</div>
                  <div className="file-name">{file.name}</div>
                  <div className="hint">
                    {(file.size / 1024 / 1024).toFixed(1)} MB — click to change
                  </div>
                </>
              ) : (
                <>
                  <div className="icon">📂</div>
                  <div>Drop a video file here</div>
                  <div className="hint">
                    or click to browse — MP4, MOV, MKV, MP3, WAV, M4A, and more
                  </div>
                </>
              )}
            </div>

            <input
              ref={fileInputRef}
              type="file"
              accept="video/*,audio/*,.mkv,.avi,.wmv,.flv,.flac,.opus,.wma,.aiff"
              style={{ display: "none" }}
              onChange={onFileChange}
            />

            {config && (
              <div className="form-row">
                <div className="field">
                  <label>Language</label>
                  <select
                    value={language}
                    onChange={(e) => setLanguage(e.target.value)}
                  >
                    {Object.entries(config.languages).map(([code, label]) => (
                      <option key={code} value={code}>
                        {label}
                      </option>
                    ))}
                  </select>
                </div>

                <div className="field">
                  <label>Model</label>
                  <select
                    value={model}
                    onChange={(e) => setModel(e.target.value)}
                  >
                    {config.models.map((m) => (
                      <option key={m} value={m}>
                        {m}
                      </option>
                    ))}
                  </select>
                </div>

                <div className="field">
                  <label>Engine</label>
                  <select
                    value={engine}
                    onChange={(e) => setEngine(e.target.value)}
                  >
                    {config.engines.map((eng) => (
                      <option key={eng} value={eng}>
                        {eng}
                      </option>
                    ))}
                  </select>
                </div>
              </div>
            )}

            <button
              type="submit"
              className="btn-submit"
              disabled={!canSubmit}
            >
              {uploading ? "Uploading…" : "Start Transcription"}
            </button>
          </form>
        </div>
      )}

      {/* ── Job status + logs ── */}
      {jobId && jobStatus && (
        <>
          <div className="card job-status">
            <div className="status-row">
              <Badge status={jobStatus} />
              <span style={{ color: "var(--text-muted)", fontSize: "0.85rem" }}>
                {file?.name}
              </span>
            </div>

            <ProgressBar progress={progress} status={jobStatus} />

            {jobStatus === "failed" && error && (
              <div className="error-box" style={{ marginTop: 14 }}>
                {error}
              </div>
            )}
          </div>

          <div className="card">
            <div className="log-header">Processing Log</div>
            <div className="log-box" ref={logBoxRef}>
              {logs.length === 0 ? (
                <span className="log-line" style={{ opacity: 0.5 }}>
                  Waiting for logs…
                </span>
              ) : (
                logs.map((l, i) => (
                  <div
                    key={i}
                    className={`log-line${l.type === "error" ? " error" : l.type === "done" ? " done" : ""}`}
                  >
                    {l.text}
                  </div>
                ))
              )}
            </div>
          </div>

          {jobStatus === "completed" && (
            <div className="card" style={{ textAlign: "center" }}>
              <a
                className="btn-download"
                href={downloadSrtUrl(jobId)}
                download
              >
                ⬇ Download .srt file
              </a>
              <button className="btn-new" onClick={reset}>
                Transcribe another video
              </button>
            </div>
          )}

          {jobStatus === "failed" && (
            <div className="card">
              <button className="btn-new" onClick={reset}>
                Try again
              </button>
            </div>
          )}
        </>
      )}
    </div>
  );
}
