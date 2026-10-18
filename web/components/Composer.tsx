"use client";

import { DragEvent, KeyboardEvent, useCallback, useEffect, useRef, useState } from "react";

import { api, ModelOption, UploadedFile } from "@/lib/api";
import { clock, extractFrames } from "@/lib/video";

interface Attachment {
  key: string;
  label: string;
  status: "uploading" | "ready" | "error";
  files: UploadedFile[];
  message?: string;
}

const ACCEPT = "image/*,video/*,.pdf,.docx,.xlsx,.csv,.tsv,.txt,.md,.json";

const ClipIcon = () => (
  <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="2"
       strokeLinecap="round" strokeLinejoin="round">
    <path d="M21 11.5l-8.6 8.6a5.5 5.5 0 01-7.8-7.8l8.6-8.6a3.7 3.7 0 015.2 5.2l-8.6 8.6a1.8 1.8 0 01-2.6-2.6l7.9-7.9" />
  </svg>
);
const MicIcon = () => (
  <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="2"
       strokeLinecap="round" strokeLinejoin="round">
    <rect x="9" y="3" width="6" height="11" rx="3" /><path d="M5 11a7 7 0 0014 0M12 18v3" />
  </svg>
);
const StopIcon = () => (
  <svg viewBox="0 0 24 24" width="14" height="14" aria-hidden="true"><rect x="5" y="5" width="14" height="14" rx="2" fill="currentColor" /></svg>
);


// Web Speech API: Chrome, Edge and Safari; not Firefox.
type Recognition = {
  lang: string; continuous: boolean; interimResults: boolean;
  start: () => void; stop: () => void;
  onresult: ((e: { resultIndex: number; results: ArrayLike<{ isFinal: boolean; 0: { transcript: string } }> }) => void) | null;
  onend: (() => void) | null; onerror: ((e: { error: string }) => void) | null;
};
function speechRecognition(): (new () => Recognition) | null {
  if (typeof window === "undefined") return null;
  const w = window as unknown as { SpeechRecognition?: new () => Recognition; webkitSpeechRecognition?: new () => Recognition };
  return w.SpeechRecognition ?? w.webkitSpeechRecognition ?? null;
}

export default function Composer({ busy, disabled, disabledReason, models, model, onModel, onSend, onStop, placeholder }: {
  busy: boolean;
  disabled: boolean;
  disabledReason?: string | null;
  models: ModelOption[];
  model: string;
  onModel: (id: string) => void;
  onSend: (text: string, fileIds: string[]) => void;
  onStop?: () => void;
  placeholder: string;
}) {
  const [text, setText] = useState("");
  const [atts, setAtts] = useState<Attachment[]>([]);
  const [dragging, setDragging] = useState(false);
  const [listening, setListening] = useState(false);
  const [voiceError, setVoiceError] = useState<string | null>(null);
  const [canListen, setCanListen] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null);
  const area = useRef<HTMLTextAreaElement>(null);
  const rec = useRef<Recognition | null>(null);

  useEffect(() => { setCanListen(speechRecognition() !== null); }, []);

  // Grow the textarea with its content, up to a limit.
  useEffect(() => {
    const el = area.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 240)}px`;
  }, [text]);

  const patch = (key: string, p: Partial<Attachment>) =>
    setAtts((a) => a.map((x) => (x.key === key ? { ...x, ...p } : x)));

  const addFiles = useCallback(async (list: FileList | File[]) => {
    for (const file of Array.from(list)) {
      const key = `${file.name}-${file.size}-${Math.random()}`;
      const isVideo = file.type.startsWith("video/");
      setAtts((a) => [...a, { key, label: file.name, status: "uploading", files: [] }]);
      try {
        if (isVideo) {
          const frames = await extractFrames(file);
          const uploaded = [];
          for (const [i, f] of frames.entries()) {
            uploaded.push(await api.upload(f.blob, `${file.name} · frame ${i + 1} at ${clock(f.at)}.jpg`));
          }
          patch(key, { status: "ready", files: uploaded, label: `${file.name} (${uploaded.length} frames)` });
        } else {
          const up = await api.upload(file, file.name);
          patch(key, { status: "ready", files: [up], message: up.note ?? undefined });
        }
      } catch (e) {
        patch(key, { status: "error", message: (e as Error).message });
      }
    }
  }, []);

  const toggleVoice = () => {
    if (listening) { rec.current?.stop(); return; }
    const Ctor = speechRecognition();
    if (!Ctor) return;
    const r = new Ctor();
    r.lang = navigator.language || "en-GB";
    r.continuous = true;
    r.interimResults = false;
    r.onresult = (e) => {
      let said = "";
      for (let i = e.resultIndex; i < e.results.length; i++) if (e.results[i].isFinal) said += e.results[i][0].transcript;
      if (said) setText((t) => (t ? `${t.trimEnd()} ${said.trim()}` : said.trim()));
    };
    r.onerror = (e) => setVoiceError(e.error === "not-allowed"
      ? "Microphone access is blocked. Allow it in your browser's site settings." : `Voice input stopped (${e.error}).`);
    r.onend = () => setListening(false);
    setVoiceError(null);
    rec.current = r;
    r.start();
    setListening(true);
  };

  const ready = atts.filter((a) => a.status === "ready");
  const uploading = atts.some((a) => a.status === "uploading");
  const canSend = !disabled && !busy && !uploading && (text.trim().length > 0);

  const send = () => {
    if (!canSend) return;
    rec.current?.stop();
    onSend(text.trim(), ready.flatMap((a) => a.files.map((f) => f.file_id)));
    setText("");
    setAtts([]);
  };

  const onKey = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) { e.preventDefault(); send(); }
  };

  const onDrop = (e: DragEvent) => {
    e.preventDefault();
    setDragging(false);
    if (e.dataTransfer.files.length) addFiles(e.dataTransfer.files);
  };

  const claude = models.filter((m) => m.provider === "anthropic");
  const local = models.filter((m) => m.provider === "ollama");
  const current = models.find((m) => m.id === model);

  return (
    <div className={`composer-box${dragging ? " is-dragging" : ""}`}
         onDragOver={(e) => { e.preventDefault(); setDragging(true); }} onDragLeave={() => setDragging(false)} onDrop={onDrop}>
      {atts.length > 0 && (
        <ul className="att-list" aria-label="Attachments">
          {atts.map((a) => (
            <li key={a.key} className={`att att-${a.status}`} title={a.message}>
              <span className="att-name">{a.label}</span>
              <span className="att-state">{a.status === "uploading" ? "Uploading…" : a.status === "error" ? a.message : a.message ?? ""}</span>
              <button aria-label={`Remove ${a.label}`} onClick={() => setAtts((x) => x.filter((y) => y.key !== a.key))}>✕</button>
            </li>
          ))}
        </ul>
      )}
      <label htmlFor="composer-text" className="sr-only">Message the Scout Assistant</label>
      <textarea id="composer-text" ref={area} rows={1} value={text} placeholder={dragging ? "Drop files to attach them" : placeholder}
                onChange={(e) => setText(e.target.value)} onKeyDown={onKey} disabled={disabled}
                onPaste={(e) => { if (e.clipboardData.files.length) { e.preventDefault(); addFiles(e.clipboardData.files); } }} />
      <div className="composer-bar">
        <div className="composer-tools">
          <input ref={fileInput} type="file" multiple accept={ACCEPT} hidden
                 onChange={(e) => { if (e.target.files) addFiles(e.target.files); e.target.value = ""; }} />
          <button className="tool-btn" onClick={() => fileInput.current?.click()} disabled={disabled}
                  title="Attach images, video, PDF, Word, Excel or text files" aria-label="Attach files"><ClipIcon /></button>
          <button className={`tool-btn${listening ? " is-live" : ""}`} onClick={toggleVoice} disabled={disabled || !canListen}
                  aria-pressed={listening}
                  title={canListen ? (listening ? "Stop dictation" : "Dictate your message") : "Voice input isn't supported in this browser"}
                  aria-label={listening ? "Stop dictation" : "Dictate"}>
            {listening ? <StopIcon /> : <MicIcon />}
          </button>
          <label className="sr-only" htmlFor="model-select">Model</label>
          <select id="model-select" className="model-select" value={model} onChange={(e) => onModel(e.target.value)}
                  title={current?.note ?? ""}>
            {claude.length > 0 && (
              <optgroup label="Claude">
                {claude.map((m) => (
                  <option key={m.id} value={m.id} disabled={!m.available}>
                    {m.label}{m.available ? "" : " (unavailable)"}
                  </option>
                ))}
              </optgroup>
            )}
            {local.length > 0 && (
              <optgroup label="Local (Ollama)">
                {local.map((m) => (
                  <option key={m.id} value={m.id} disabled={!m.available}>
                    {m.available ? m.label : `${m.label}: not running`}
                  </option>
                ))}
              </optgroup>
            )}
          </select>
        </div>
        {busy && onStop ? (
          <button className="send-btn" onClick={onStop} aria-label="Stop">Stop</button>
        ) : (
          <button className="send-btn" onClick={send} disabled={!canSend} aria-label="Send">Send</button>
        )}
      </div>
      {(listening || voiceError || disabledReason) && (
        <p className="composer-hint" role="status">
          {listening ? "Listening… speak your brief, then press Send." : voiceError ?? disabledReason}
        </p>
      )}
    </div>
  );
}
