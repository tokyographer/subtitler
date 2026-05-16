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
  const [task, setTask] = useState("transcribe");
  const [maxLineChars, setMaxLineChars] = useState(42);
  const [maxSegmentDuration, setMaxSegmentDuration] = useState(0);
  const [mergeGapMs, setMergeGapMs] = useState(0);
  const [showAdvanced, setShowAdvanced] = useState(false);

  // Job state
  const [jobId, setJobId] = useState(null);
  const [jobStatus, setJobStatus] = useState(null);
  const [progress, setProgress] = useState(0);
  const [logs, setLogs] = useState([]);
  const [error, setError] = useState(null);
  const [uploading, setUploading] = useState(false);

  const logBoxRef = useRef(null);
  const fileInputRef = useRef(null);

  useEffect(() => {
    fetchConfig()
      .then((cfg) => {
        setConfig(cfg);
        setModel(cfg.defaults.model);
        setLanguage(cfg.defaults.language);
        setEngine(cfg.defaults.engine);
        setTask(cfg.defaults.task ?? "transcribe");
        setMaxLineChars(cfg.defaults.max_line_chars ?? 42);
        setMaxSegmentDuration(cfg.defaults.max_segment_duration ?? 0);
        setMergeGapMs(cfg.defaults.merge_gap_ms ?? 0);
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
      onDone: (status) => setJobStatus(status),
      onError: (msg) => setLogs((prev) => [...prev, { text: msg, type: "error" }]),
    });
    return () => es.close();
  }, [jobId]);

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
      const { job_id } = await uploadVideo(file, {
        language,
        model,
        engine,
        task,
        max_line_chars: maxLineChars,
        max_segment_duration: maxSegmentDuration,
        merge_gap_ms: mergeGapMs,
      });
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
                <FieldGroup label="Language">
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
                {/* Translate row */}
                <div className="form-row-2">
                  <FieldGroup
                    label="Task"
                    hint={task === "translate" ? "Output will be in English regardless of source language." : "Output matches source language."}
                  >
                    <select value={task} onChange={(e) => setTask(e.target.value)}>
                      <option value="transcribe">Transcribe (keep original language)</option>
                      <option value="translate">Translate to English</option>
                    </select>
                  </FieldGroup>
                </div>

                <div className="form-row adv-row">
                  <FieldGroup
                    label="Max line length (chars)"
                    hint="Characters per subtitle line before wrapping."
                  >
                    <input
                      type="number"
                      min={10}
                      max={84}
                      value={maxLineChars}
                      onChange={(e) => setMaxLineChars(Number(e.target.value))}
                      className="num-input"
                    />
                  </FieldGroup>

                  <FieldGroup
                    label="Max display duration (s)"
                    hint="Cap each subtitle block. 0 = no limit."
                  >
                    <input
                      type="number"
                      min={0}
                      max={30}
                      step={0.5}
                      value={maxSegmentDuration}
                      onChange={(e) => setMaxSegmentDuration(Number(e.target.value))}
                      className="num-input"
                    />
                  </FieldGroup>

                  <FieldGroup
                    label="Merge gap (ms)"
                    hint="Merge consecutive segments closer than this. 0 = off."
                  >
                    <input
                      type="number"
                      min={0}
                      max={2000}
                      step={50}
                      value={mergeGapMs}
                      onChange={(e) => setMergeGapMs(Number(e.target.value))}
                      className="num-input"
                    />
                  </FieldGroup>
                </div>
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

          {jobStatus === "completed" && (
            <div className="card" style={{ textAlign: "center" }}>
              <a className="btn-download" href={downloadSrtUrl(jobId)} download>
                ⬇ Download .srt file
              </a>
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
