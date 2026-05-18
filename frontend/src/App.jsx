import { useCallback, useEffect, useRef, useState } from "react";
import {
  downloadSrtUrl,
  downloadTranscriptUrl,
  fetchConfig,
  fetchJob,
  generateTranscript,
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
  const cls = status === "completed" ? "done" : status === "failed" ? "failed" : "";
  return (
    <div>
      <div className="progress-track">
        <div className={`progress-fill ${cls}`} style={{ width: `${progress}%` }} />
      </div>
      <div className="progress-label">{progress}%</div>
    </div>
  );
}

function FieldGroup({ label, children, hint }) {
  return (
    <div className="field">
      <label>{label}</label>
      {children}
      {hint && <div className="field-hint">{hint}</div>}
    </div>
  );
}

export default function App() {
  const [config, setConfig] = useState(null);
  const [ffmpegWarning, setFfmpegWarning] = useState(null);

  // Form state
  const [file, setFile] = useState(null);
  const [isDragging, setIsDragging] = useState(false);
  const [language, setLanguage] = useState("auto");
  const [model, setModel] = useState("large-v3-turbo");
  const [engine, setEngine] = useState("mlx");
  const [autoTranscript, setAutoTranscript] = useState(false);
  const [showAdvanced, setShowAdvanced] = useState(false);

  // Job state
  const [jobId, setJobId] = useState(null);
  const [jobStatus, setJobStatus] = useState(null);
  const [progress, setProgress] = useState(0);
  const [logs, setLogs] = useState([]);
  const [error, setError] = useState(null);
  const [uploading, setUploading] = useState(false);

  // Transcript state
  const [transcriptStatus, setTranscriptStatus] = useState(null);
  const [transcriptError, setTranscriptError] = useState(null);

  // Hallucination warning
  const [hallucinationWarning, setHallucinationWarning] = useState(null);

  const logBoxRef = useRef(null);
  const fileInputRef = useRef(null);

  useEffect(() => {
    fetchConfig()
      .then((cfg) => {
        setConfig(cfg);
        setModel(cfg.defaults.model);
        setLanguage(cfg.defaults.language);
        setEngine(cfg.defaults.engine);
        if (cfg.system?.ffmpeg_warning) setFfmpegWarning(cfg.system.ffmpeg_warning);

      })
      .catch(() =>
        setError("Could not reach the backend. Is the server running on port 8001?")
      );
  }, []);

  useEffect(() => {
    if (logBoxRef.current)
      logBoxRef.current.scrollTop = logBoxRef.current.scrollHeight;
  }, [logs]);

  useEffect(() => {
    if (!jobId) return;
    const es = subscribeLogs(jobId, {
      onLog: (msg) => setLogs((prev) => [...prev, { text: msg, type: "log" }]),
      onStatus: (status, pct) => { setJobStatus(status); setProgress(pct); },
      onDone: (status, meta) => {
        setJobStatus(status);
        if (meta?.hallucinationWarning) setHallucinationWarning(meta);
      },
      onError: (msg) => setLogs((prev) => [...prev, { text: msg, type: "error" }]),
    });
    return () => es.close();
  }, [jobId]);

  useEffect(() => {
    if (transcriptStatus !== "generating" || !jobId) return;
    const interval = setInterval(async () => {
      try {
        const job = await fetchJob(jobId);
        if (job.transcript_status === "ready") {
          setTranscriptStatus("ready");
        } else if (job.transcript_status === "failed") {
          setTranscriptStatus("failed");
          setTranscriptError("Transcript generation failed. Check that SUBTITLER_ANTHROPIC_API_KEY is set.");
        }
      } catch {
        // keep polling
      }
    }, 2000);
    return () => clearInterval(interval);
  }, [transcriptStatus, jobId]);

  useEffect(() => {
    if (jobStatus === "completed" && autoTranscript && transcriptStatus === null) {
      handleGenerateTranscript();
    }
  }, [jobStatus]);

  const handleGenerateTranscript = async () => {
    setTranscriptStatus("generating");
    setTranscriptError(null);
    try {
      await generateTranscript(jobId);
    } catch (err) {
      setTranscriptStatus("failed");
      setTranscriptError(err.message);
    }
  };

  const onDrop = useCallback((e) => {
    e.preventDefault();
    setIsDragging(false);
    const dropped = e.dataTransfer.files[0];
    if (dropped) setFile(dropped);
  }, []);

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
    setTranscriptStatus(null);
    setTranscriptError(null);
    setHallucinationWarning(null);
    setAutoTranscript(false);

    if (fileInputRef.current) fileInputRef.current.value = "";
  };

  const isProcessing = jobStatus && !["completed", "failed"].includes(jobStatus);
  const canSubmit = !!file && !uploading && !isProcessing;

  return (
    <div className="app">
      <header>
        <h1>🎬 Subtitler</h1>
        <p>Local video / audio transcription → YouTube-compatible .srt</p>
      </header>

      {ffmpegWarning && (
        <div className="card">
          <div className="warn-box">⚠️ {ffmpegWarning}</div>
        </div>
      )}

      {error && !jobId && (
        <div className="card">
          <div className="error-box">{error}</div>
        </div>
      )}

      {/* ── Upload form ── */}
      {!jobId && (
        <div className="card">
          <form onSubmit={handleSubmit}>
            {/* Drop zone */}
            <div
              className={`drop-zone${isDragging ? " over" : ""}${file ? " has-file" : ""}`}
              onDrop={onDrop}
              onDragOver={(e) => { e.preventDefault(); setIsDragging(true); }}
              onDragLeave={() => setIsDragging(false)}
              onClick={() => fileInputRef.current?.click()}
            >
              {file ? (
                <>
                  <div className="icon">{file.type.startsWith("audio/") ? "🎵" : "🎥"}</div>
                  <div className="file-name">{file.name}</div>
                  <div className="hint">{(file.size / 1024 / 1024).toFixed(1)} MB — click to change</div>
                </>
              ) : (
                <>
                  <div className="icon">📂</div>
                  <div>Drop a video or audio file here</div>
                  <div className="hint">or click to browse — MP4, MOV, MKV, MP3, WAV, M4A, and more</div>
                </>
              )}
            </div>
            <input
              ref={fileInputRef}
              type="file"
              accept="video/*,audio/*,.mkv,.avi,.wmv,.flv,.flac,.opus,.wma,.aiff"
              style={{ display: "none" }}
              onChange={(e) => { const f = e.target.files?.[0]; if (f) setFile(f); }}
            />

            {/* Basic options */}
            {config && (
              <div className="form-row" style={{ marginTop: 20 }}>
                <FieldGroup
                  label="Focus language"
                  hint="Auto-detect for multilingual audio. Pick a language to speed up transcription and filter the interpreter track."
                >
                  <select value={language} onChange={(e) => setLanguage(e.target.value)}>
                    {Object.entries(config.languages).map(([code, label]) => (
                      <option key={code} value={code}>{label}</option>
                    ))}
                  </select>
                </FieldGroup>

                <FieldGroup label="Model">
                  <select value={model} onChange={(e) => setModel(e.target.value)}>
                    {config.models.map((m) => (
                      <option key={m} value={m}>{m}</option>
                    ))}
                  </select>
                </FieldGroup>

                <FieldGroup label="Engine">
                  <select value={engine} onChange={(e) => setEngine(e.target.value)}>
                    {Object.entries(config.engines).map(([eng, info]) => (
                      <option key={eng} value={eng}>
                        {eng}{info.available ? "" : " (not installed)"}
                      </option>
                    ))}
                  </select>
                  {config.engines[engine]?.available === false && (
                    <div className="field-hint engine-warn">
                      ⚠ {config.engines[engine].reason.split("\n")[0]}
                    </div>
                  )}
                </FieldGroup>
              </div>
            )}

            {/* Advanced options toggle */}
            <button
              type="button"
              className="btn-advanced-toggle"
              onClick={() => setShowAdvanced((v) => !v)}
            >
              {showAdvanced ? "▲" : "▼"} Advanced options
            </button>

            {showAdvanced && (
              <div className="advanced-panel">

                {/* Generate transcript */}
                <label className="field-checkbox">
                  <input
                    type="checkbox"
                    checked={autoTranscript}
                    onChange={(e) => setAutoTranscript(e.target.checked)}
                  />
                  <span>
                    <strong>Generate transcript after SRT</strong>
                    <span className="field-hint" style={{ display: "block", marginTop: 2 }}>
                      Uses Claude to reconstruct a clean, readable transcript from the subtitles.
                      Requires <code>SUBTITLER_ANTHROPIC_API_KEY</code> in .env.
                    </span>
                  </span>
                </label>

              </div>
            )}

            <button type="submit" className="btn-submit" disabled={!canSubmit}>
              {uploading ? "Uploading…" : "Start Transcription"}
            </button>
          </form>
        </div>
      )}

      {/* ── Job status ── */}
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
              <div className="error-box" style={{ marginTop: 14 }}>{error}</div>
            )}
          </div>

          <div className="card">
            <div className="log-header">Processing Log</div>
            <div className="log-box" ref={logBoxRef}>
              {logs.length === 0 ? (
                <span className="log-line" style={{ opacity: 0.5 }}>Waiting for logs…</span>
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

          {hallucinationWarning && (
            <div className="card">
              <div className="warn-box">
                <strong>⚠ Repetition loop detected — {hallucinationWarning.segmentsDropped} segments removed.</strong>
                {" "}The SRT contains only the content before the loop started. To fix this,
                re-transcribe with the <strong>Focus language</strong> set to a specific language
                (e.g. English or Spanish) instead of Auto-detect. If the loop persists, try a
                smaller model such as <em>medium</em> or <em>small</em>.
              </div>
            </div>
          )}

          {jobStatus === "completed" && (
            <div className="card" style={{ textAlign: "center" }}>
              <a className="btn-download" href={downloadSrtUrl(jobId)} download>
                ⬇ Download .srt file
              </a>
              <div className="transcript-section">
                {transcriptStatus === null && (
                  <button className="btn-transcript" onClick={handleGenerateTranscript}>
                    Generate Transcript
                  </button>
                )}
                {transcriptStatus === "generating" && (
                  <button className="btn-transcript btn-transcript--loading" disabled>
                    <span className="spinner" /> Generating transcript…
                  </button>
                )}
                {transcriptStatus === "ready" && (
                  <a className="btn-transcript btn-transcript--ready" href={downloadTranscriptUrl(jobId)} download>
                    ⬇ Download Transcript (.md)
                  </a>
                )}
                {transcriptStatus === "failed" && (
                  <>
                    <div className="error-box">{transcriptError || "Transcript generation failed."}</div>
                    <button className="btn-transcript" onClick={handleGenerateTranscript} style={{ marginTop: 8 }}>
                      Retry
                    </button>
                  </>
                )}
              </div>
              <button className="btn-new" onClick={reset}>Transcribe another file</button>
            </div>
          )}

          {jobStatus === "failed" && (
            <div className="card">
              <button className="btn-new" onClick={reset}>Try again</button>
            </div>
          )}
        </>
      )}
    </div>
  );
}
