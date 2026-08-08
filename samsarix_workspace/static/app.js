"use strict";

const state = {
  token: sessionStorage.getItem("samsarix-token") || "",
  files: [],
  selectedPath: null,
  selectedKind: null,
  etag: null,
  dirty: false,
  terminalSession: null,
  entryMode: "file",
  pendingConflict: null,
  toastTimer: null,
};

const elements = Object.fromEntries(
  [
    "health-dot", "workspace-name", "usage", "refresh-button", "new-file-button",
    "new-folder-button", "empty-new-button", "files-loading", "files-empty", "file-tree",
    "document-path", "document-title", "dirty-indicator", "rename-button", "delete-button",
    "save-button", "editor-empty", "editor", "editor-message", "file-stats",
    "terminal-output", "terminal-form", "terminal-prompt", "terminal-input", "entry-dialog",
    "entry-form", "entry-eyebrow", "entry-title", "entry-path", "entry-submit",
    "confirm-dialog", "confirm-form", "confirm-title", "confirm-message", "conflict-dialog",
    "conflict-message", "conflict-cancel", "conflict-reload", "conflict-overwrite", "token-dialog",
    "token-form", "token-input", "token-error", "toast",
  ].map((id) => [id, document.getElementById(id)])
);

class ApiError extends Error {
  constructor(code, message, status) {
    super(message);
    this.code = code;
    this.status = status;
  }
}

async function api(path, options = {}) {
  const headers = new Headers(options.headers || {});
  if (options.body && !headers.has("Content-Type")) headers.set("Content-Type", "application/json");
  if (state.token) headers.set("Authorization", `Bearer ${state.token}`);
  let response;
  try {
    response = await fetch(path, { ...options, headers });
  } catch (_error) {
    setConnection(false);
    throw new ApiError("connection_failed", "The local workspace server is unavailable.", 0);
  }
  setConnection(true);
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    const error = payload.error || {};
    if (response.status === 401) showTokenDialog();
    throw new ApiError(error.code || "request_failed", error.message || `Request failed (${response.status}).`, response.status);
  }
  return payload;
}

function setConnection(online) {
  elements["health-dot"].classList.toggle("online", online);
  elements["health-dot"].classList.toggle("offline", !online);
}

function formatBytes(bytes) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function toast(message, isError = false) {
  clearTimeout(state.toastTimer);
  elements.toast.textContent = message;
  elements.toast.classList.toggle("error", isError);
  elements.toast.hidden = false;
  state.toastTimer = setTimeout(() => { elements.toast.hidden = true; }, 3500);
}

function showError(error) {
  const message = error instanceof ApiError ? error.message : "Something unexpected happened.";
  toast(message, true);
  elements["editor-message"].textContent = message;
}

function updateDirty(dirty) {
  state.dirty = dirty;
  elements["dirty-indicator"].hidden = !dirty;
  elements["save-button"].disabled = !state.selectedPath || !dirty;
  elements["editor-message"].textContent = dirty ? "Unsaved changes" : "Saved";
}

function updateStats() {
  const content = elements.editor.value;
  const lines = content ? content.split("\n").length : 0;
  const bytes = new TextEncoder().encode(content).length;
  elements["file-stats"].textContent = `${lines} lines · ${formatBytes(bytes)}`;
}

function canLeaveEditor() {
  return !state.dirty || window.confirm("Discard unsaved changes?");
}

async function refreshWorkspace({ keepSelection = true } = {}) {
  elements["files-loading"].hidden = false;
  elements["files-empty"].hidden = true;
  elements["file-tree"].hidden = true;
  try {
    const [summary, listing] = await Promise.all([
      api("/api/v1/workspace"),
      api("/api/v1/files?recursive=true"),
    ]);
    state.files = listing.entries;
    elements["workspace-name"].textContent = summary.workspace.name || "Workspace";
    elements.usage.textContent = `${formatBytes(summary.workspace.usage_bytes)} / ${formatBytes(summary.workspace.limits.max_total_bytes)}`;
    if (keepSelection && state.selectedPath && !state.files.some((entry) => entry.path === state.selectedPath)) {
      closeDocument();
    }
    renderFiles();
  } catch (error) {
    showError(error);
  } finally {
    elements["files-loading"].hidden = true;
  }
}

function renderFiles() {
  elements["file-tree"].replaceChildren();
  const visible = state.files.filter((entry) => !entry.path.split("/").some((part) => part.startsWith(".samsarix-")));
  elements["files-empty"].hidden = visible.length !== 0;
  elements["file-tree"].hidden = visible.length === 0;
  for (const entry of visible) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "file-row";
    button.dataset.path = entry.path;
    button.dataset.kind = entry.kind;
    button.setAttribute("role", "treeitem");
    button.setAttribute("aria-selected", String(entry.path === state.selectedPath));
    button.style.paddingLeft = `${8 + Math.max(0, entry.path.split("/").length - 1) * 14}px`;
    if (entry.path === state.selectedPath) button.classList.add("selected");

    const icon = document.createElement("span");
    icon.className = "file-icon";
    icon.textContent = entry.kind === "directory" ? "▱" : entry.kind === "file" ? "·" : "×";
    const name = document.createElement("span");
    name.className = "file-name";
    name.textContent = entry.name;
    const size = document.createElement("span");
    size.className = "file-size";
    size.textContent = entry.kind === "file" ? formatBytes(entry.size) : "";
    button.append(icon, name, size);
    button.addEventListener("click", () => selectEntry(entry));
    elements["file-tree"].append(button);
  }
}

async function selectEntry(entry) {
  if (entry.path === state.selectedPath) return;
  if (!canLeaveEditor()) return;
  state.selectedPath = entry.path;
  state.selectedKind = entry.kind;
  renderFiles();
  elements["rename-button"].disabled = entry.kind.startsWith("blocked");
  elements["delete-button"].disabled = false;
  if (entry.kind !== "file") {
    state.etag = null;
    elements.editor.hidden = true;
    elements["editor-empty"].hidden = false;
    elements["document-path"].textContent = entry.path;
    elements["document-title"].textContent = entry.kind === "directory" ? "Folder selected" : "Blocked entry";
    elements["editor-empty"].querySelector("h2").textContent = entry.name;
    elements["editor-empty"].querySelector("p").textContent = entry.kind === "directory"
      ? "Folders can be renamed or deleted. Create a file inside it using its full path."
      : "Symbolic links and special files are visible but cannot be opened by this workspace.";
    updateDirty(false);
    return;
  }
  await openFile(entry.path);
}

async function openFile(path) {
  elements["editor-message"].textContent = "Opening…";
  try {
    const payload = await api(`/api/v1/file?path=${encodeURIComponent(path)}`);
    const file = payload.file;
    state.selectedPath = file.path;
    state.selectedKind = "file";
    state.etag = file.etag;
    elements.editor.value = file.content;
    elements.editor.hidden = false;
    elements["editor-empty"].hidden = true;
    elements["document-path"].textContent = file.path.includes("/") ? file.path.slice(0, file.path.lastIndexOf("/")) : "/";
    elements["document-title"].textContent = file.path.split("/").pop();
    elements["rename-button"].disabled = false;
    elements["delete-button"].disabled = false;
    updateDirty(false);
    updateStats();
    renderFiles();
    elements.editor.focus();
  } catch (error) {
    showError(error);
  }
}

function closeDocument() {
  state.selectedPath = null;
  state.selectedKind = null;
  state.etag = null;
  state.dirty = false;
  state.pendingConflict = null;
  elements.editor.value = "";
  elements.editor.hidden = true;
  elements["editor-empty"].hidden = false;
  elements["editor-empty"].querySelector("h2").textContent = "Your files, close at hand.";
  elements["editor-empty"].querySelector("p").textContent = "Open a UTF-8 text file from the sidebar or create a new one. Changes stay in the folder you chose when starting Samsarix Workspace.";
  elements["document-path"].textContent = "No file open";
  elements["document-title"].textContent = "Choose a file";
  elements["rename-button"].disabled = true;
  elements["delete-button"].disabled = true;
  elements["save-button"].disabled = true;
  elements["dirty-indicator"].hidden = true;
  elements["file-stats"].textContent = "";
  renderFiles();
}

async function saveFile() {
  if (!state.selectedPath || state.selectedKind !== "file" || !state.dirty) return;
  await persistFile(elements.editor.value, state.etag);
}

async function persistFile(content, expectedEtag) {
  elements["save-button"].disabled = true;
  elements["editor-message"].textContent = "Saving…";
  try {
    const payload = await api("/api/v1/file", {
      method: "PUT",
      body: JSON.stringify({ path: state.selectedPath, content, expected_etag: expectedEtag }),
    });
    state.etag = payload.file.etag;
    state.pendingConflict = null;
    updateDirty(false);
    toast(`Saved ${state.selectedPath}`);
    await refreshWorkspace();
  } catch (error) {
    updateDirty(true);
    if (error instanceof ApiError && error.code === "edit_conflict") {
      await prepareConflict(content);
    } else {
      showError(error);
    }
  }
}

async function prepareConflict(localContent) {
  let serverFile = null;
  try {
    const payload = await api(`/api/v1/file?path=${encodeURIComponent(state.selectedPath)}`);
    serverFile = payload.file;
  } catch (error) {
    if (!(error instanceof ApiError) || error.code !== "not_found") {
      showError(error);
      return;
    }
  }
  state.pendingConflict = { path: state.selectedPath, localContent, serverFile };
  state.etag = serverFile ? serverFile.etag : null;
  elements["conflict-message"].textContent = serverFile
    ? `${state.selectedPath} changed on disk after you opened it. Your unsaved text is still in the editor.`
    : `${state.selectedPath} was deleted on disk after you opened it. Your unsaved text is still in the editor.`;
  elements["conflict-reload"].textContent = serverFile ? "Reload disk version" : "Accept deletion";
  elements["conflict-dialog"].showModal();
  elements["conflict-overwrite"].focus();
}

async function reloadConflict() {
  const conflict = state.pendingConflict;
  if (!conflict) return;
  elements["conflict-dialog"].close();
  state.pendingConflict = null;
  if (!conflict.serverFile) {
    closeDocument();
    await refreshWorkspace({ keepSelection: false });
    toast(`Accepted deletion of ${conflict.path}`);
    return;
  }
  elements.editor.value = conflict.serverFile.content;
  state.etag = conflict.serverFile.etag;
  updateDirty(false);
  updateStats();
  toast(`Reloaded ${conflict.path}`);
  elements.editor.focus();
}

async function overwriteConflict() {
  const conflict = state.pendingConflict;
  if (!conflict) return;
  elements["conflict-dialog"].close();
  state.pendingConflict = null;
  await persistFile(conflict.localContent, conflict.serverFile ? conflict.serverFile.etag : null);
}

function openEntryDialog(mode, initialPath = "") {
  state.entryMode = mode;
  const isMove = mode === "move";
  const isFolder = mode === "folder";
  elements["entry-eyebrow"].textContent = isMove ? "Move or rename" : "Create";
  elements["entry-title"].textContent = isMove ? "Choose a new path" : isFolder ? "New folder" : "New file";
  elements["entry-submit"].textContent = isMove ? "Move" : "Create";
  elements["entry-path"].value = initialPath;
  elements["entry-dialog"].showModal();
  elements["entry-path"].focus();
  elements["entry-path"].select();
}

async function submitEntry(event) {
  event.preventDefault();
  const path = elements["entry-path"].value.trim();
  if (!path) return;
  const mode = state.entryMode;
  const movedKind = state.selectedKind;
  try {
    if (mode === "file") {
      await api("/api/v1/file", { method: "PUT", body: JSON.stringify({ path, content: "" }) });
    } else if (mode === "folder") {
      await api("/api/v1/folders", { method: "POST", body: JSON.stringify({ path }) });
    } else {
      await api("/api/v1/move", { method: "POST", body: JSON.stringify({ source: state.selectedPath, destination: path }) });
      state.selectedPath = null;
    }
    elements["entry-dialog"].close();
    await refreshWorkspace();
    if (mode === "file" || (mode === "move" && movedKind === "file")) {
      await openFile(path);
    } else if (mode === "move") {
      const movedEntry = state.files.find((entry) => entry.path === path);
      if (movedEntry) await selectEntry(movedEntry);
    }
    toast(mode === "move" ? `Moved to ${path}` : `Created ${path}`);
  } catch (error) {
    showError(error);
  }
}

function requestDelete() {
  if (!state.selectedPath) return;
  elements["confirm-title"].textContent = `Delete ${state.selectedKind === "directory" ? "folder" : "file"}?`;
  elements["confirm-message"].textContent = state.selectedKind === "directory"
    ? `${state.selectedPath} and everything inside it will be permanently removed.`
    : `${state.selectedPath} will be permanently removed.`;
  elements["confirm-dialog"].showModal();
}

async function confirmDelete(event) {
  event.preventDefault();
  const path = state.selectedPath;
  if (!path) return;
  try {
    await api(`/api/v1/entry?path=${encodeURIComponent(path)}&recursive=${state.selectedKind === "directory"}`, { method: "DELETE" });
    elements["confirm-dialog"].close();
    closeDocument();
    await refreshWorkspace({ keepSelection: false });
    toast(`Deleted ${path}`);
  } catch (error) {
    showError(error);
  }
}

function appendTerminal(text, className = "") {
  if (!text) return;
  const line = document.createElement("div");
  if (className) line.className = className;
  line.textContent = text;
  elements["terminal-output"].append(line);
  elements["terminal-output"].scrollTop = elements["terminal-output"].scrollHeight;
}

async function runTerminal(event) {
  event.preventDefault();
  const command = elements["terminal-input"].value.trim();
  if (!command) return;
  elements["terminal-input"].value = "";
  appendTerminal(`${elements["terminal-prompt"].textContent} ${command}`, "terminal-command");
  try {
    let payload;
    try {
      payload = await api("/api/v1/terminal/execute", {
        method: "POST",
        body: JSON.stringify({ command, session_id: state.terminalSession }),
      });
    } catch (error) {
      if (!(error instanceof ApiError) || error.code !== "session_expired") throw error;
      state.terminalSession = null;
      payload = await api("/api/v1/terminal/execute", {
        method: "POST",
        body: JSON.stringify({ command, session_id: null }),
      });
    }
    state.terminalSession = payload.session_id;
    elements["terminal-prompt"].textContent = `${payload.cwd}$`;
    if (payload.clear) elements["terminal-output"].replaceChildren();
    appendTerminal(payload.output, payload.exit_code ? "terminal-error" : "");
    if (["mkdir", "touch", "mv", "rm"].includes(command.split(/\s+/, 1)[0])) await refreshWorkspace();
  } catch (error) {
    appendTerminal(error.message || "Terminal request failed.", "terminal-error");
  }
}

function showTokenDialog() {
  if (!elements["token-dialog"].open) elements["token-dialog"].showModal();
  elements["token-input"].focus();
}

async function submitToken(event) {
  event.preventDefault();
  state.token = elements["token-input"].value;
  sessionStorage.setItem("samsarix-token", state.token);
  elements["token-error"].textContent = "";
  try {
    await api("/api/v1/workspace");
    elements["token-dialog"].close();
    elements["token-input"].value = "";
    await refreshWorkspace();
  } catch (error) {
    state.token = "";
    sessionStorage.removeItem("samsarix-token");
    elements["token-error"].textContent = error.message;
  }
}

elements["refresh-button"].addEventListener("click", () => refreshWorkspace());
elements["new-file-button"].addEventListener("click", () => openEntryDialog("file"));
elements["new-folder-button"].addEventListener("click", () => openEntryDialog("folder"));
elements["empty-new-button"].addEventListener("click", () => openEntryDialog("file"));
elements["save-button"].addEventListener("click", saveFile);
elements["rename-button"].addEventListener("click", () => {
  if (state.selectedPath && canLeaveEditor()) openEntryDialog("move", state.selectedPath);
});
elements["delete-button"].addEventListener("click", requestDelete);
elements.editor.addEventListener("input", () => { updateDirty(true); updateStats(); });
elements["entry-form"].addEventListener("submit", submitEntry);
elements["confirm-form"].addEventListener("submit", confirmDelete);
elements["conflict-cancel"].addEventListener("click", () => elements["conflict-dialog"].close());
elements["conflict-reload"].addEventListener("click", reloadConflict);
elements["conflict-overwrite"].addEventListener("click", overwriteConflict);
elements["terminal-form"].addEventListener("submit", runTerminal);
elements["token-form"].addEventListener("submit", submitToken);
document.querySelectorAll("[data-close-dialog]").forEach((button) => {
  button.addEventListener("click", () => button.closest("dialog").close());
});
elements["token-dialog"].addEventListener("cancel", (event) => event.preventDefault());
window.addEventListener("beforeunload", (event) => {
  if (state.dirty) event.preventDefault();
});
document.addEventListener("keydown", (event) => {
  if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "s") {
    event.preventDefault();
    saveFile();
  }
});

refreshWorkspace();
