import { useEffect, useRef, useState } from "react";
import { X } from "lucide-react";
import type { LLMSettings } from "../../services/chat";

interface Props {
  settings: LLMSettings | null;
  onApply: (settings: LLMSettings | null) => void;
  onClose: () => void;
}

export function LLMSettingsDialog({ settings, onApply, onClose }: Props) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [provider, setProvider] = useState<LLMSettings["provider"] | "default">(settings?.provider ?? "default");
  const [endpoint, setEndpoint] = useState(settings?.endpoint ?? "");
  const [apiKey, setApiKey] = useState(settings?.api_key ?? "");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const element = dialog.current;
    element?.showModal();
    return () => element?.close();
  }, []);

  function changeProvider(value: typeof provider) {
    setProvider(value);
    setApiKey("");
    setError(null);
    setEndpoint(value === "openai" ? "https://api.openai.com/v1" : value === "lm_studio" ? "http://127.0.0.1:1235/v1" : "");
  }

  return (
    <dialog ref={dialog} className="llm-settings-dialog" aria-labelledby="llm-settings-title" aria-describedby="llm-settings-description" onCancel={onClose}>
      <form onSubmit={event => {
        event.preventDefault();
        if (provider !== "default" && (!endpoint.trim() || (provider !== "lm_studio" && !apiKey.trim()))) {
          setError("Enter an endpoint and API key for the selected provider.");
          return;
        }
        onApply(provider === "default" ? null : {
          provider, endpoint: endpoint.trim(), api_key: apiKey.trim() || undefined,
        });
        onClose();
      }}>
        <div className="llm-settings-heading">
          <h2 id="llm-settings-title">LLM settings</h2>
          <button className="llm-settings-button" type="button" aria-label="Close settings" onClick={onClose}><X size={19} /></button>
        </div>
        <p id="llm-settings-description">Choose the provider for new chat messages. Settings and API keys are kept in memory until this page is refreshed.</p>
        <label htmlFor="llm-provider">Provider</label>
        <select id="llm-provider" className="workspace-select" value={provider} onChange={event => changeProvider(event.target.value as typeof provider)}>
          <option value="default">Backend default</option>
          <option value="lm_studio">LM Studio</option>
          <option value="openai">OpenAI</option>
          <option value="openai_compatible">OpenAI-compatible endpoint</option>
        </select>
        {provider !== "default" && <>
          <label htmlFor="llm-endpoint">API endpoint</label>
          <input id="llm-endpoint" type="url" pattern="https?://.+" required value={endpoint} onChange={event => setEndpoint(event.target.value)} placeholder="https://api.example.com/v1" />
          <label htmlFor="llm-api-key">API key {provider === "lm_studio" && "(optional)"}</label>
          <input id="llm-api-key" type="password" autoComplete="off" spellCheck={false} required={provider !== "lm_studio"} value={apiKey} onChange={event => setApiKey(event.target.value)} />
        </>}
        {error && <p className="chat-error" role="alert">{error}</p>}
        <div className="llm-settings-actions">
          <button type="button" onClick={onClose}>Cancel</button>
          <button type="submit">Apply settings</button>
        </div>
      </form>
    </dialog>
  );
}
