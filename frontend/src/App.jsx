import { useCallback, useEffect, useRef, useState } from "react";
import {
  downloadRawSrtUrl,
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

function fmtTime(secs) {
  if (secs == null) return "?";
  const h = Math.floor(secs / 3600);
  const m = Math.floor((secs % 3600) / 60);
  const s = Math.floor(secs % 60);
  return h > 0
    ? `${h}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`
    : `${m}:${String(s).padStart(2, "0")}`;
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
  const [transcriptProvider, setTranscriptProvider] = useState(null);
  const [ollamaModel, setOllamaModel] = useState(null);
  const [filterTranslation, setFilterTranslation] = useState(false);
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
        if (cfg.transcript?.provider) setTranscriptProvider(cfg.transcript.provider);
        if (cfg.transcript?.ollama_model) setOllamaModel(cfg.transcript.ollama_model);
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
          setTranscriptError(job.error || "Transcript generation failed.");
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
      await generateTranscript(jobId, transcriptProvider, ollamaModel);
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
      const { job_id } = await uploadVideo(file, {
        language, model, engine,
        filter_translation_track: filterTranslation,
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
    setTranscriptStatus(null);
    setTranscriptError(null);
    setHallucinationWarning(null);
    setAutoTranscript(false);
    setTranscriptProvider(config?.transcript?.provider ?? "claude");
    setOllamaModel(config?.transcript?.ollama_model ?? null);
    setFilterTranslation(false);
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
                  </span>
                </label>
                {autoTranscript && config?.transcript && (
                  <div style={{ marginLeft: 28, marginTop: 6, display: "flex", flexDirection: "column", gap: 6 }}>
                    <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                      <label style={{ fontSize: "0.85rem", color: "var(--text-muted, #888)", minWidth: 52 }}>Provider</label>
                      <select
                        value={transcriptProvider ?? config.transcript.provider}
                        onChange={(e) => setTranscriptProvider(e.target.value)}
                        style={{ fontSize: "0.85rem" }}
                      >
                        <option value="claude">Claude ({config.transcript.claude_model})</option>
                        <option value="ollama">Ollama — local, free</option>
                      </select>
                      {transcriptProvider === "claude" && (
                        <span className="field-hint" style={{ marginTop: 0 }}>
                          Requires <code>SUBTITLER_ANTHROPIC_API_KEY</code>
                        </span>
                      )}
                    </div>
                    {transcriptProvider === "ollama" && config.transcript.ollama_models?.length > 0 && (
                      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                        <label style={{ fontSize: "0.85rem", color: "var(--text-muted, #888)", minWidth: 52 }}>Model</label>
                        <select
                          value={ollamaModel ?? config.transcript.ollama_model}
                          onChange={(e) => setOllamaModel(e.target.value)}
                          style={{ fontSize: "0.85rem" }}
                        >
                          {config.transcript.ollama_models.map((m) => (
                            <option key={m} value={m}>{m}</option>
                          ))}
                        </select>
                      </div>
                    )}
                  </div>
                )}

                {/* Translation filter */}
                <label className="field-checkbox">
                  <input
                    type="checkbox"
                    checked={filterTranslation}
                    onChange={(e) => setFilterTranslation(e.target.checked)}
                  />
                  <span>
                    <strong>Filter interpreter / translation track</strong>
                    <span className="field-hint" style={{ display: "block", marginTop: 2 }}>
                      Removes live interpreter segments when audio has a main speaker
                      followed by a translator repeating the content in another language.
                      Off by default — multilingual content is always preserved.
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
              <div className="warn-box loop-warn">
                <div className="loop-warn-title">⚠ Probable Whisper hallucination loop detected</div>
                <table className="loop-warn-table">
                  <tbody>
                    <tr>
                      <td>Focus language</td>
                      <td>{hallucinationWarning.loopInfo?.focus_language
                        ? (config?.languages?.[hallucinationWarning.loopInfo.focus_language] ?? hallucinationWarning.loopInfo.focus_language)
                        : "Auto-detect"}</td>
                    </tr>
                    <tr>
                      <td>Loop starts at</td>
                      <td>
                        segment #{(hallucinationWarning.loopInfo?.loop_start_index ?? 0) + 1}
                        {" "}({fmtTime(hallucinationWarning.loopInfo?.loop_start_time)})
                      </td>
                    </tr>
                    <tr>
                      <td>Repeated text</td>
                      <td><em>"{hallucinationWarning.loopInfo?.repeated_text}"</em></td>
                    </tr>
                    <tr>
                      <td>Segments removed</td>
                      <td>{hallucinationWarning.segmentsDropped} — moved to raw_transcript.srt</td>
                    </tr>
                  </tbody>
                </table>
                <div className="loop-warn-hint">
                  {hallucinationWarning.loopInfo?.focus_language
                    ? "Try a smaller model (medium or small) or check audio quality."
                    : "Try setting a specific Focus language (e.g. English or Spanish) or use a smaller model."}
                  {" "}The safe .srt contains only the content before the loop.
                  Raw transcript (with loop intact) is preserved and available below.
                </div>
              </div>
            </div>
          )}

          {jobStatus === "completed" && (
            <div className="card" style={{ textAlign: "center" }}>
              <a className="btn-download" href={downloadSrtUrl(jobId)} download>
                {hallucinationWarning ? "⬇ Download safe .srt" : "⬇ Download .srt file"}
              </a>
              {hallucinationWarning && (
                <a className="btn-download-raw" href={downloadRawSrtUrl(jobId)} download>
                  ⬇ Download raw .srt (includes loop)
                </a>
              )}
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
