import { useEffect, useRef, useState } from "react";
import { Bot, Send, User, Plus, Pencil, Trash2, Paperclip, X } from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { uploadProjectFile, type FileAttachment, type UploadedFile } from "../../../services/files";
import { getChatModels, streamChatMessage } from "../../../services/chat";
import {
  createChat, deleteChat, getMessages, listChats, renameChat,
  type WorkspaceChat, type StoredMessage,
} from "../../../services/workspace";

interface AssistantPanelProps {
  projectId: string;
  onJobsSubmitted: (jobIds: string[]) => void;
}

type Message = StoredMessage;
type PendingAttachment = { id: string; original: File; progress: number; uploaded?: UploadedFile; error?: string };

function AttachmentChip({attachment}: {attachment: FileAttachment}) {
  return <span className="attachment-chip"><Paperclip size={13}/><span className="attachment-name">{attachment.filename}</span><span>{attachment.format.toUpperCase()} / {Math.ceil(attachment.size_bytes / 1024)} KB</span></span>;
}

export function AssistantPanel({ projectId, onJobsSubmitted }: AssistantPanelProps) {
  const [chats, setChats] = useState<WorkspaceChat[]>([]);
  const [chatId, setChatId] = useState("");
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [status, setStatus] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [attachments, setAttachments] = useState<PendingAttachment[]>([]);
  const [models, setModels] = useState<string[]>([]);
  const [model, setModel] = useState("");
  const [modelError, setModelError] = useState<string | null>(null);
  const [modelsReload, setModelsReload] = useState(0);
  const uploadControllers = useRef(new Map<string, AbortController>());
  const filePicker = useRef<HTMLInputElement>(null);
  const uploading = attachments.some(item => !item.uploaded && !item.error);
  const attachmentErrors = attachments.some(item => item.error);
  const nextId = useRef(1);
  const sending = useRef(false);
  const controller = useRef<AbortController | null>(null);
  const bottom = useRef<HTMLDivElement>(null);
  const textarea = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    let live = true;
    void getChatModels().then(result => {
      if (!live) return;
      let saved: string | null = null;
      try { saved = localStorage.getItem("simassist.chat.model"); } catch { /* Storage may be unavailable. */ }
      setModels(result.models);
      setModel(saved && result.models.includes(saved) ? saved : result.default_model);
    }).catch(err => {
      if (live) setModelError(err instanceof Error ? err.message : String(err));
    });
    return () => { live = false; };
  }, [modelsReload]);

  function selectModel(value: string) {
    setModel(value);
    try { localStorage.setItem("simassist.chat.model", value); } catch { /* Keep the selection in memory. */ }
  }

  useEffect(() => {
    const controllers = uploadControllers.current;
    controllers.forEach(item => item.abort());
    controllers.clear();
    setAttachments([]);
    return () => { controllers.forEach(item => item.abort()); controllers.clear(); };
  }, [projectId, chatId]);

  async function startUpload(item: PendingAttachment) {
    const abort = new AbortController();
    uploadControllers.current.set(item.id, abort);
    setAttachments(previous => previous.map(entry => entry.id === item.id ? {...entry, progress: 0, error: undefined} : entry));
    try {
      const uploaded = await uploadProjectFile(projectId, item.original, progress => {
        if (!abort.signal.aborted) setAttachments(previous => previous.map(entry => entry.id === item.id ? {...entry, progress} : entry));
      }, abort.signal);
      if (!abort.signal.aborted) setAttachments(previous => previous.map(entry => entry.id === item.id ? {...entry, uploaded} : entry));
    } catch (error) {
      if (!abort.signal.aborted) setAttachments(previous => previous.map(entry => entry.id === item.id ? {...entry, error: error instanceof Error ? error.message : String(error)} : entry));
    } finally {
      uploadControllers.current.delete(item.id);
    }
  }

  function attachFiles(files: FileList | null) {
    if (!files || loading || !chatId) return;
    const selected = Array.from(files).map(original => ({ id: crypto.randomUUID(), original, progress: 0 }));
    setAttachments(previous => [...previous, ...selected]);
    selected.forEach(item => { void startUpload(item); });
  }

  function removeAttachment(id: string) {
    uploadControllers.current.get(id)?.abort();
    uploadControllers.current.delete(id);
    setAttachments(previous => previous.filter(item => item.id !== id));
  }

  // A project has its own chats. Do not automatically recreate deleted chats.
  useEffect(() => {
    let live = true;
    controller.current?.abort();
    setChatId(""); setMessages([]); setChats([]); setError(null);
    void listChats(projectId).then(items => {
      if (!live) return;
      setChats(items);
      if (items.length) setChatId(items[0].id);
      else return createChat(projectId).then(created => {
        if (live) {setChats([created]);setChatId(created.id);}
      });
    }).catch(err => {if(live)setError(String(err));});
    return () => {live = false;controller.current?.abort();};
  }, [projectId]);

  useEffect(() => {
    let live = true;
    if (!chatId) {setMessages([]);return;}
    void getMessages(projectId, chatId).then((records: StoredMessage[]) => {
      if (!live) return;
      setMessages(records);
      nextId.current = Math.max(1, ...records.map(item => item.id + 1));
    }).catch(err => {if(live)setError(String(err));});
    return () => {live=false;};
  }, [projectId, chatId]);

  useEffect(() => {bottom.current?.scrollIntoView({block:"end"});}, [messages, status]);
  useEffect(() => {
    if (!textarea.current) return;
    textarea.current.style.height = "auto";
    textarea.current.style.height = `${Math.min(180, Math.max(40, textarea.current.scrollHeight))}px`;
  }, [input]);

  async function newChat() {
    if (sending.current) return;
    try {
      const item = await createChat(projectId);
      setChats(prev => [item, ...prev]);
      setChatId(item.id);setInput("");setMessages([]);setError(null);
    } catch(err){setError(String(err));}
  }

  async function removeChat(item: WorkspaceChat) {
    if (sending.current) return;
    if (!window.confirm(`Delete chat "${item.title}" and its message history?`)) return;
    try {
      await deleteChat(projectId, item.id);
      const remaining = chats.filter(chat => chat.id !== item.id);
      setChats(remaining);
      if (chatId === item.id) {
        setChatId(remaining[0]?.id ?? "");setMessages([]);
        if (!remaining.length) await newChat();
      }
    } catch(err){setError(String(err));}
  }

  async function editChat(item: WorkspaceChat) {
    const title = window.prompt("Chat name", item.title)?.trim();
    if (!title) return;
    try {
      await renameChat(projectId, item.id, title);
      setChats(prev => prev.map(chat => chat.id===item.id ? {...chat,title} : chat));
    } catch(err){setError(String(err));}
  }

  async function sendMessage() {
    const content = input.trim();
    if (!content || !chatId || !model || sending.current || uploading || attachmentErrors) return;
    const sentAttachments = attachments.flatMap(item => item.uploaded ? [item.uploaded] : []);
    setAttachments([]);
    sending.current = true;
    setLoading(true);setStatus("Connecting to SimAssist...");setError(null);
    setInput("");
    const activeChat = chatId;
    const userId = nextId.current++;
    const assistantId = nextId.current++;
    setMessages(prev => [...prev,{id:userId,role:"user",content,attachments:sentAttachments},{id:assistantId,role:"assistant",content:""}]);
    const abort = new AbortController();controller.current=abort;
    const reported = new Set<string>();
    const report = (jobIds: string[]) => {
      const fresh = jobIds.filter(id => !reported.has(id));
      fresh.forEach(id => reported.add(id));
      if (fresh.length) onJobsSubmitted(fresh);
    };
    try {
      await streamChatMessage({project_id:projectId,chat_id:activeChat,message:content,model,attachments:sentAttachments.map(item => ({file_id:item.file_id}))},{
        onStatus: setStatus,
        onDelta(text) {
          setStatus(null);
          setMessages(prev => prev.map(m => m.id===assistantId?{...m,content:m.content+text}:m));
        },
        onJobs: report,
        onDone(response) {
          setMessages(prev => prev.map(m => m.id===assistantId?{...m,content:response.message || m.content}:m));
          report(response.submitted_job_ids);
          void listChats(projectId).then(setChats).catch(() => {});
        },
      },abort.signal);
    } catch(err) {
      if (!abort.signal.aborted) {
        const text=err instanceof Error ? err.message : String(err);
        setMessages(prev => prev.map(m => m.id===assistantId?{...m,content:`**Stream error:** ${text}`}:m));
      }
    } finally {
      controller.current=null;sending.current=false;setLoading(false);setStatus(null);
    }
  }

  return <div className="assistant-content">
    <div className="chat-session-toolbar">
      <span>Conversations</span>
      <button type="button" disabled={loading || uploading} onClick={() => void newChat()} title="New chat"><Plus size={15}/> New</button>
    </div>
    <div className="chat-session-list">
      {chats.map(item => <div key={item.id} className={`chat-session ${item.id===chatId?"selected":""}`}>
        <button className="chat-session-select" disabled={loading || uploading} onClick={() => setChatId(item.id)} title={item.title}>{item.title}</button>
        <button type="button" disabled={loading || uploading} onClick={() => void editChat(item)} title="Rename chat"><Pencil size={12}/></button>
        <button type="button" disabled={loading || uploading} onClick={() => void removeChat(item)} title="Delete chat"><Trash2 size={12}/></button>
      </div>)}
    </div>
    {error && <div className="chat-error" role="alert">{error}</div>}
    <div className="chat-messages">
      {!messages.length && <div className="chat-welcome">Welcome to SimAssist! Describe the engineering simulation you want to create.</div>}
      {messages.map(message => <div key={message.id} className={`chat-message ${message.role}`}>
        {message.role==="assistant"?<Bot size={17}/>:<User size={17}/>}
        <div className="message-content">
          {message.attachments?.map(attachment => <AttachmentChip key={attachment.file_id} attachment={attachment}/>)}
          {message.role==="assistant"?<ReactMarkdown remarkPlugins={[remarkGfm]}>{message.content}</ReactMarkdown>:<p>{message.content}</p>}
          {loading && message.id === nextId.current-1 && !message.content && <span className="streaming-indicator">{status || "Thinking..."}</span>}
        </div>
      </div>)}
      <div ref={bottom}/>
    </div>
    <div className="chat-composer" onDragOver={event => {
      if (event.dataTransfer.types.includes("Files")) event.preventDefault();
    }} onDrop={event => {event.preventDefault(); attachFiles(event.dataTransfer.files);}}>
      <div className="chat-model-toolbar">
        <label className="chat-model-picker">
          <span>Model</span>
          <select className="workspace-select" aria-label="Chat model" value={model} disabled={loading || !models.length} onChange={event => selectModel(event.target.value)}>
            {!models.length && <option value="">{modelError ? "Models unavailable" : "Loading models..."}</option>}
            {models.map(item => <option key={item} value={item}>{item}</option>)}
          </select>
        </label>
        {modelError && <span className="chat-model-error" role="alert">{modelError}. <button type="button" onClick={() => { setModelError(null); setModelsReload(value => value + 1); }}>Retry</button></span>}
      </div>
      <input ref={filePicker} type="file" accept=".step,.stp" multiple hidden onChange={event => {
        attachFiles(event.target.files); event.target.value = "";
      }}/>
      <div className="pending-attachments">
        {attachments.map(item => <div key={item.id} className="pending-attachment">
          {item.uploaded ? <AttachmentChip attachment={item.uploaded}/> : <span className="attachment-name">{item.original.name}</span>}
          {!item.uploaded && !item.error && <span role="status">{item.progress < 100 ? `Uploading ${item.progress}%` : "Inspecting CAD..."}</span>}
          {item.error && <><span role="alert" className="attachment-error">{item.error}</span><button type="button" onClick={() => void startUpload(item)}>Retry</button></>}
          <button type="button" onClick={() => removeAttachment(item.id)} aria-label={`Remove ${item.original.name}`}><X size={14}/></button>
        </div>)}
      </div>
    <div className="chat-input-area">
      <div className="chat-input-field">
      <textarea ref={textarea} rows={1} disabled={loading || !chatId} value={input}
        placeholder={loading?"SimAssist is responding...":"Describe your simulation..."}
        onChange={event => setInput(event.target.value)}
        onKeyDown={event => {if(event.key==="Enter"&&!event.shiftKey&&!event.nativeEvent.isComposing){event.preventDefault();void sendMessage();}}}/>
      <button className="chat-attach-button" type="button" title="Attach file" aria-label="Attach file" disabled={loading || !chatId} onClick={() => filePicker.current?.click()}><Paperclip size={17}/></button>
      </div>
      <button type="button" disabled={loading||uploading||attachmentErrors||!chatId||!model||!input.trim()} onClick={()=>void sendMessage()} aria-label="Send message"><Send size={18}/></button>
    </div>
    </div>
  </div>;
}
