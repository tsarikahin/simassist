const BASE = import.meta.env.VITE_API_BASE_URL ?? import.meta.env.VITE_API_URL ?? "http://127.0.0.1:8000";

export interface FileAttachment {
  file_id: string;
  filename: string;
  format: string;
  size_bytes: number;
}

export interface UploadedFile extends FileAttachment {
  project_id: string;
  file_type: "cad_geometry";
  status: string;
  inspection: { dimension: number; coordinate_units: "mm" };
}

export function uploadProjectFile(projectId: string, file: File, onProgress: (percent: number) => void, signal: AbortSignal): Promise<UploadedFile> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    const abort = () => xhr.abort();
    const cleanup = () => signal.removeEventListener("abort", abort);
    xhr.open("POST", `${BASE}/api/projects/${projectId}/files`);
    xhr.timeout = 120_000;
    xhr.upload.onprogress = event => {
      if (event.lengthComputable) onProgress(Math.round(event.loaded / event.total * 100));
    };
    xhr.onload = () => {
      cleanup();
      let data;
      try { data = JSON.parse(xhr.responseText); } catch { reject(new Error(`Upload failed: HTTP ${xhr.status}. Check the backend console for errors.`)); return; }
      if (xhr.status >= 200 && xhr.status < 300) resolve(data as UploadedFile);
      else reject(new Error(typeof data.detail === "string" ? data.detail : `Upload failed: HTTP ${xhr.status}`));
    };
    xhr.onerror = () => { cleanup(); reject(new Error("Upload request failed. Check the backend console for errors, then retry.")); };
    xhr.ontimeout = () => { cleanup(); reject(new Error("Upload or STEP inspection timed out. Try a smaller model.")); };
    xhr.onabort = () => { cleanup(); reject(new DOMException("Upload cancelled", "AbortError")); };
    signal.addEventListener("abort", abort, { once: true });
    if (signal.aborted) { cleanup(); reject(new DOMException("Upload cancelled", "AbortError")); return; }
    const form = new FormData();
    form.append("file", file);
    xhr.send(form);
  });
}
