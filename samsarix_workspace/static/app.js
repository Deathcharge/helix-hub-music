"use strict";

const state = {
  token: sessionStorage.getItem("samsarix-token") || "",
  workspaceId: null,
  maxFileBytes: 0,
  files: [],
  selectedPath: null,
  selectedKind: null,
  etag: null,
  dirty: false,
  saving: false,
  loading: false,
  openGeneration: 0,
  mutating: false,
  trashLoading: false,
  trashGeneration: 0,
  historyLoading: false,
  historyGeneration: 0,
  historyVersion: null,
  historyCurrent: null,
  restoreItem: null,
  confirmAction: null,
  terminalSession: null,
  entryMode: "file",
  searchQuery: "",
  searchGeneration: 0,
  searchTimer: null,
  preview: false,
  draftTimer: null,
  pendingDraft: null,
  pendingConflict: null,
  toastTimer: null,
};

const elements = Object.fromEntries(
  [
    "health-dot", "workspace-name", "usage", "refresh-button", "import-button", "file-input",
    "new-file-button", "new-folder-button", "empty-new-button", "files-loading", "files-empty",
    "file-tree", "search-form", "search-input", "search-clear", "search-status", "search-results",
    "document-path", "document-title", "dirty-indicator", "rename-button", "delete-button",
    "preview-button", "download-button", "save-button", "editor-empty", "editor",
    "markdown-preview", "editor-message", "file-stats",
    "terminal-output", "terminal-form", "terminal-prompt", "terminal-input", "entry-dialog",
    "entry-form", "entry-eyebrow", "entry-title", "entry-path", "entry-submit",
    "confirm-dialog", "confirm-form", "confirm-title", "confirm-message", "conflict-dialog",
    "conflict-message", "conflict-cancel", "conflict-reload", "conflict-overwrite", "draft-dialog",
    "draft-message", "draft-discard", "draft-restore", "token-dialog",
    "token-form", "token-input", "token-error", "toast",
    "trash-button", "trash-dialog", "trash-refresh", "trash-status", "trash-error", "trash-items",
    "entry-error", "confirm-error", "confirm-submit",
    "history-button", "history-dialog", "history-path", "history-refresh", "history-all",
    "history-status", "history-retention", "history-error", "history-items", "history-preview",
    "history-preview-title", "history-current-status", "history-content", "history-current",
    "history-copy-form", "history-destination", "history-copy", "history-replace",
  ].map((id) => [id, document.getElementById(id)])
);

const DRAFT_KEY = "samsarix-workspace-draft";

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
  let payload;
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 15000);
  try {
    response = await fetch(path, { ...options, headers, signal: controller.signal });
    try {
      payload = await response.json();
    } catch (error) {
      if (!(error instanceof SyntaxError)) throw error;
      payload = null;
    }
  } catch (_error) {
    setConnection(false);
    if (controller.signal.aborted) {
      throw new ApiError("request_timeout", "The workspace request timed out. Your edit is still here; retry to check the disk version.", 0);
    }
    throw new ApiError("connection_failed", "The local workspace server is unavailable.", 0);
  } finally {
    clearTimeout(timeout);
  }
  setConnection(true);
  if (!response.ok) {
    const error = payload?.error || {};
    if (response.status === 401) showTokenDialog();
    throw new ApiError(error.code || "request_failed", error.message || `Request failed (${response.status}).`, response.status);
  }
  if (!payload || typeof payload !== "object" || Array.isArray(payload)) {
    throw new ApiError("invalid_response", "The workspace returned an invalid response. Your edit is still here; retry to check the disk version.", response.status);
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
  updateEditorActions();
  elements["editor-message"].textContent = dirty ? "Unsaved changes" : "Saved";
}

function updateEditorActions() {
  const busy = state.loading || state.saving || state.mutating;
  const fileOpen = state.selectedKind === "file";
  elements.editor.readOnly = state.loading || state.mutating;
  elements.editor.setAttribute("aria-busy", String(busy));
  elements["save-button"].disabled = busy || !fileOpen || !state.dirty;
  elements["rename-button"].disabled = busy || !state.selectedPath || state.selectedKind.startsWith("blocked");
  elements["delete-button"].disabled = busy || !state.selectedPath;
  elements["preview-button"].disabled = busy || !fileOpen || !isMarkdown(state.selectedPath);
  elements["download-button"].disabled = state.loading || !fileOpen;
  for (const id of ["new-file-button", "new-folder-button", "empty-new-button", "import-button"]) {
    elements[id].disabled = busy;
  }
  elements["entry-submit"].disabled = state.mutating;
  elements["confirm-form"].querySelector("[type=submit]").disabled = state.mutating;
  elements["trash-button"].disabled = busy;
  elements["history-button"].disabled = busy;
  for (const id of ["history-refresh", "history-all", "history-path", "history-destination"]) {
    elements[id].disabled = busy || state.historyLoading;
  }
  elements["history-copy"].disabled = busy || state.historyLoading || !state.historyVersion;
  elements["history-replace"].disabled = busy || state.historyLoading || !state.historyCurrent;
  elements["history-items"].querySelectorAll("button").forEach((button) => {
    button.disabled = busy || state.historyLoading || button.dataset.unavailable === "true";
  });
  elements["trash-refresh"].disabled = busy || state.trashLoading;
  elements["trash-items"].querySelectorAll("button").forEach((button) => {
    button.disabled = busy || state.trashLoading || button.dataset.unavailable === "true";
  });
}

function updateStats() {
  const content = elements.editor.value;
  const lines = content ? content.split("\n").length : 0;
  const bytes = new TextEncoder().encode(content).length;
  elements["file-stats"].textContent = `${lines} lines · ${formatBytes(bytes)}`;
}

function readDraft() {
  try {
    const value = JSON.parse(sessionStorage.getItem(DRAFT_KEY) || "null");
    return value && typeof value === "object" ? value : null;
  } catch (_error) {
    sessionStorage.removeItem(DRAFT_KEY);
    return null;
  }
}

function clearDraft(path = state.selectedPath) {
  const draft = readDraft();
  if (!draft || (draft.workspaceId === state.workspaceId && draft.path === path)) {
    sessionStorage.removeItem(DRAFT_KEY);
  }
}

function scheduleDraft() {
  clearTimeout(state.draftTimer);
  if (!state.selectedPath || !state.workspaceId || !state.dirty) return;
  state.draftTimer = setTimeout(writeDraft, 250);
}

function writeDraft() {
  if (!state.selectedPath || !state.workspaceId || !state.dirty) return;
  try {
    sessionStorage.setItem(DRAFT_KEY, JSON.stringify({
      workspaceId: state.workspaceId,
      path: state.selectedPath,
      content: elements.editor.value,
      etag: state.etag,
      savedAt: new Date().toISOString(),
    }));
  } catch (_error) {
    elements["editor-message"].textContent = "Unsaved changes · browser draft storage unavailable";
  }
}

function offerDraft(file) {
  const draft = readDraft();
  if (!draft || draft.workspaceId !== state.workspaceId || draft.path !== file.path) return false;
  if (draft.content === file.content) {
    clearDraft(file.path);
    return false;
  }
  state.pendingDraft = { ...draft, serverFile: file };
  const diskChanged = draft.etag && draft.etag !== file.etag;
  elements["draft-message"].textContent = diskChanged
    ? "This tab retained an unsaved draft, and the file also changed on disk. Restore it to continue editing; saving will still require resolving the disk conflict."
    : "This tab retained unsaved text from a page reload. Restore it to continue editing, or discard it to keep the disk version.";
  elements["draft-dialog"].showModal();
  elements["draft-restore"].focus();
  return true;
}

function restoreDraft() {
  const draft = state.pendingDraft;
  if (!draft) return;
  elements["draft-dialog"].close();
  state.pendingDraft = null;
  state.etag = draft.etag;
  elements.editor.value = draft.content;
  updateDirty(true);
  updateStats();
  scheduleDraft();
  elements.editor.focus();
  toast(`Restored unsaved draft for ${draft.path}`);
}

function discardDraft() {
  const draft = state.pendingDraft;
  elements["draft-dialog"].close();
  state.pendingDraft = null;
  clearDraft(draft ? draft.path : state.selectedPath);
  elements.editor.focus();
  toast("Discarded the browser draft");
}

function canLeaveEditor() {
  if (state.saving || state.mutating) {
    toast("Wait for the current file operation to finish.");
    return false;
  }
  if (!state.dirty) return true;
  return window.confirm("Discard unsaved changes?");
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
    state.workspaceId = summary.workspace.id;
    state.maxFileBytes = summary.workspace.limits.max_file_bytes;
    elements["workspace-name"].textContent = summary.workspace.name || "Workspace";
    elements.usage.textContent = `${formatBytes(summary.workspace.usage_bytes)} / ${formatBytes(summary.workspace.limits.max_total_bytes)}`;
    if (keepSelection && state.selectedPath && !state.files.some((entry) => entry.path === state.selectedPath)) {
      if (state.dirty || state.saving || state.loading || state.mutating) {
        toast(`${state.selectedPath} no longer appears on disk; your unsaved draft is still open.`, true);
      } else {
        closeDocument();
      }
    }
    renderFiles();
  } catch (error) {
    showError(error);
  } finally {
    elements["files-loading"].hidden = true;
  }
}

function renderFiles() {
  if (state.searchQuery) {
    elements["file-tree"].hidden = true;
    elements["files-empty"].hidden = true;
    return;
  }
  elements["search-results"].hidden = true;
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

function scheduleSearch() {
  clearTimeout(state.searchTimer);
  state.searchTimer = setTimeout(performSearch, 250);
}

function clearSearch({ focus = false } = {}) {
  clearTimeout(state.searchTimer);
  state.searchGeneration += 1;
  state.searchQuery = "";
  elements["search-input"].value = "";
  elements["search-clear"].hidden = true;
  elements["search-status"].textContent = "";
  elements["search-results"].replaceChildren();
  elements["search-results"].hidden = true;
  renderFiles();
  if (focus) elements["search-input"].focus();
}

async function performSearch() {
  const query = elements["search-input"].value.trim();
  if (!query) {
    clearSearch();
    return;
  }
  state.searchQuery = query;
  const generation = ++state.searchGeneration;
  elements["search-clear"].hidden = false;
  elements["file-tree"].hidden = true;
  elements["files-empty"].hidden = true;
  elements["search-results"].hidden = false;
  elements["search-results"].replaceChildren();
  elements["search-status"].textContent = "Searching…";
  try {
    const payload = await api(`/api/v1/search?q=${encodeURIComponent(query)}&limit=100`);
    if (generation !== state.searchGeneration) return;
    renderSearchResults(payload.search);
  } catch (error) {
    if (generation !== state.searchGeneration) return;
    elements["search-status"].textContent = "Search failed";
    showError(error);
  }
}

function renderSearchResults(report) {
  elements["search-results"].replaceChildren();
  const count = report.matches.length;
  const suffix = report.truncated ? " · limited" : "";
  elements["search-status"].textContent = `${count} ${count === 1 ? "match" : "matches"} in ${report.scanned_files} files${suffix}`;
  for (const match of report.matches) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "search-result";
    const path = document.createElement("span");
    path.className = "search-result-path";
    path.textContent = `${match.path}:${match.line}:${match.column}`;
    const preview = document.createElement("span");
    preview.className = "search-result-preview";
    preview.textContent = match.preview || "(blank matching line)";
    button.append(path, preview);
    button.addEventListener("click", () => openSearchMatch(match));
    elements["search-results"].append(button);
  }
}

async function openSearchMatch(match) {
  if (!state.loading && state.selectedPath === match.path && state.selectedKind === "file") {
    focusSearchMatch(match);
    return;
  }
  await openFile(match.path, match);
}

function focusSearchMatch(match) {
  if (state.preview) togglePreview();
  const lines = elements.editor.value.split("\n");
  const preceding = lines.slice(0, Math.max(0, match.line - 1));
  const offset = preceding.reduce((total, line) => total + line.length + 1, 0);
  const target = lines[match.line - 1] || "";
  const points = Array.from(target);
  const pointStart = Math.min(points.length, Math.max(0, match.column - 1));
  const pointEnd = Math.min(points.length, pointStart + Math.max(0, match.length));
  const prefix = points.slice(0, pointStart).join("");
  const matched = points.slice(pointStart, pointEnd).join("");
  const start = Math.min(elements.editor.value.length, offset + prefix.length);
  const end = Math.min(elements.editor.value.length, start + matched.length);
  elements.editor.focus();
  elements.editor.setSelectionRange(start, end);
}

async function selectEntry(entry) {
  if (!state.loading && entry.path === state.selectedPath) return;
  if (entry.kind === "file") {
    await openFile(entry.path);
    return;
  }
  if (!canLeaveEditor()) return;
  state.openGeneration += 1;
  state.loading = false;
  clearTimeout(state.draftTimer);
  clearDraft();
  state.selectedPath = entry.path;
  state.selectedKind = entry.kind;
  renderFiles();
  elements["rename-button"].disabled = entry.kind.startsWith("blocked");
  elements["delete-button"].disabled = false;
  if (entry.kind !== "file") {
    state.etag = null;
    elements.editor.hidden = true;
    elements["markdown-preview"].hidden = true;
    state.preview = false;
    elements["preview-button"].textContent = "Preview";
    elements["preview-button"].disabled = true;
    elements["download-button"].disabled = true;
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
}

async function openFile(path, match = null) {
  if (!canLeaveEditor()) return;
  const generation = ++state.openGeneration;
  state.loading = true;
  clearTimeout(state.draftTimer);
  writeDraft();
  updateEditorActions();
  elements["editor-message"].textContent = "Opening…";
  try {
    const payload = await api(`/api/v1/file?path=${encodeURIComponent(path)}`);
    if (generation !== state.openGeneration) return;
    const file = payload.file;
    if (state.selectedPath !== path) clearDraft();
    state.selectedPath = file.path;
    state.selectedKind = "file";
    state.etag = file.etag;
    state.preview = false;
    elements.editor.value = file.content;
    elements.editor.hidden = false;
    elements["markdown-preview"].hidden = true;
    elements["editor-empty"].hidden = true;
    elements["document-path"].textContent = file.path.includes("/") ? file.path.slice(0, file.path.lastIndexOf("/")) : "/";
    elements["document-title"].textContent = file.path.split("/").pop();
    elements["rename-button"].disabled = false;
    elements["delete-button"].disabled = false;
    elements["preview-button"].disabled = !isMarkdown(file.path);
    elements["preview-button"].textContent = "Preview";
    elements["download-button"].disabled = false;
    updateDirty(false);
    updateStats();
    renderFiles();
    const draftOffered = offerDraft(file);
    if (!draftOffered) {
      elements.editor.focus();
      if (match) focusSearchMatch(match);
    }
  } catch (error) {
    if (generation !== state.openGeneration) return;
    showError(error);
  } finally {
    if (generation === state.openGeneration) {
      state.loading = false;
      updateEditorActions();
    }
  }
}

function closeDocument() {
  state.openGeneration += 1;
  state.loading = false;
  clearTimeout(state.draftTimer);
  clearDraft();
  state.selectedPath = null;
  state.selectedKind = null;
  state.etag = null;
  state.dirty = false;
  state.pendingConflict = null;
  state.pendingDraft = null;
  state.preview = false;
  elements.editor.value = "";
  elements.editor.hidden = true;
  elements["markdown-preview"].hidden = true;
  elements["editor-empty"].hidden = false;
  elements["editor-empty"].querySelector("h2").textContent = "Your files, close at hand.";
  elements["editor-empty"].querySelector("p").textContent = "Open a UTF-8 text file from the sidebar or create a new one. Changes stay in the folder you chose when starting Samsarix Workspace.";
  elements["document-path"].textContent = "No file open";
  elements["document-title"].textContent = "Choose a file";
  elements["rename-button"].disabled = true;
  elements["delete-button"].disabled = true;
  elements["preview-button"].disabled = true;
  elements["preview-button"].textContent = "Preview";
  elements["download-button"].disabled = true;
  elements["save-button"].disabled = true;
  elements["dirty-indicator"].hidden = true;
  elements["file-stats"].textContent = "";
  updateEditorActions();
  renderFiles();
}

async function saveFile() {
  if (!state.selectedPath || state.selectedKind !== "file" || !state.dirty || state.saving || state.loading || state.mutating || document.querySelector("dialog[open]")) return;
  await persistFile(elements.editor.value, state.etag);
}

async function persistFile(content, expectedEtag, createOnly = false) {
  if (state.saving || state.loading || state.mutating) return;
  const path = state.selectedPath;
  state.saving = true;
  updateEditorActions();
  elements["editor-message"].textContent = "Saving…";
  try {
    const payload = await api("/api/v1/file", {
      method: "PUT",
      body: JSON.stringify({ path, content, expected_etag: expectedEtag, create_only: createOnly }),
    });
    state.etag = payload.file.etag;
    state.pendingConflict = null;
    updateDirty(elements.editor.value !== content);
    if (state.dirty) writeDraft();
    else clearDraft(path);
    toast(state.dirty ? `Saved ${path}; newer edits are still unsaved.` : `Saved ${path}`);
    await refreshWorkspace();
  } catch (error) {
    updateDirty(true);
    writeDraft();
    if (error instanceof ApiError && ["edit_conflict", "already_exists"].includes(error.code)) {
      await prepareConflict();
    } else {
      showError(error);
    }
  } finally {
    state.saving = false;
    updateEditorActions();
  }
}

async function prepareConflict() {
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
  state.pendingConflict = { path: state.selectedPath, serverFile };
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
  clearDraft();
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
  await persistFile(elements.editor.value, conflict.serverFile ? conflict.serverFile.etag : null, !conflict.serverFile);
}

async function importFiles(event) {
  const files = Array.from(event.target.files || []);
  event.target.value = "";
  if (!files.length || state.loading || state.saving || state.mutating) return;
  const targetFolder = state.selectedKind === "directory" ? state.selectedPath : "";
  state.mutating = true;
  updateEditorActions();
  let imported;
  try {
    imported = await importDocuments(files, targetFolder);
  } finally {
    state.mutating = false;
    updateEditorActions();
  }
  if (imported.length === 1 && !state.dirty) await openFile(imported[0]);
}

async function importDocuments(files, targetFolder) {
  const imported = [];
  const failures = [];
  for (const file of files) {
    const path = targetFolder ? `${targetFolder}/${file.name}` : file.name;
    if (!file.name || file.name.includes("/") || file.name.includes("\\")) {
      failures.push(`${file.name || "unnamed file"}: invalid filename`);
      continue;
    }
    if (state.maxFileBytes && file.size > state.maxFileBytes) {
      failures.push(`${file.name}: larger than ${formatBytes(state.maxFileBytes)}`);
      continue;
    }
    let content;
    try {
      content = new TextDecoder("utf-8", { fatal: true }).decode(await file.arrayBuffer());
    } catch (_error) {
      failures.push(`${file.name}: not valid UTF-8 text`);
      continue;
    }
    try {
      await api("/api/v1/file", {
        method: "PUT",
        body: JSON.stringify({ path, content, create_only: true }),
      });
      imported.push(path);
    } catch (error) {
      if (!(error instanceof ApiError) || error.code !== "already_exists") {
        failures.push(`${file.name}: ${error.message || "import failed"}`);
        continue;
      }
      const replace = window.confirm(`${path} already exists. Replace its disk contents?`);
      if (!replace) {
        failures.push(`${file.name}: skipped`);
        continue;
      }
      try {
        const existing = await api(`/api/v1/file?path=${encodeURIComponent(path)}`);
        await api("/api/v1/file", {
          method: "PUT",
          body: JSON.stringify({ path, content, expected_etag: existing.file.etag }),
        });
        imported.push(path);
      } catch (replaceError) {
        failures.push(`${file.name}: ${replaceError.message || "replace failed"}`);
      }
    }
  }
  await refreshWorkspace();
  if (failures.length) {
    toast(`Imported ${imported.length}; ${failures.length} skipped. ${failures[0]}`, true);
  } else {
    toast(`Imported ${imported.length} ${imported.length === 1 ? "file" : "files"}`);
  }
  return imported;
}

function downloadFile() {
  if (!state.selectedPath || state.selectedKind !== "file") return;
  const blob = new Blob([elements.editor.value], { type: "text/plain;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = state.selectedPath.split("/").pop() || "document.txt";
  document.body.append(link);
  link.click();
  const name = link.download;
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 0);
  toast(`Downloaded ${name}${state.dirty ? " with unsaved edits" : ""}`);
}

function isMarkdown(path) {
  return /\.(md|markdown)$/i.test(path || "");
}

function safeLinkTarget(value) {
  if (value.startsWith("#")) return value;
  try {
    const url = new URL(value);
    return ["http:", "https:", "mailto:"].includes(url.protocol) ? url.href : null;
  } catch (_error) {
    return null;
  }
}

function appendInline(parent, text) {
  const tokens = /(`[^`\n]+`|\*\*[^*\n]+\*\*|\*[^*\n]+\*|\[[^\]\n]+\]\([^\s)]+\))/g;
  let cursor = 0;
  for (const match of text.matchAll(tokens)) {
    parent.append(document.createTextNode(text.slice(cursor, match.index)));
    const token = match[0];
    let node;
    if (token.startsWith("`")) {
      node = document.createElement("code");
      node.textContent = token.slice(1, -1);
    } else if (token.startsWith("**")) {
      node = document.createElement("strong");
      node.textContent = token.slice(2, -2);
    } else if (token.startsWith("*")) {
      node = document.createElement("em");
      node.textContent = token.slice(1, -1);
    } else {
      const separator = token.lastIndexOf("](");
      const label = token.slice(1, separator);
      const target = safeLinkTarget(token.slice(separator + 2, -1));
      if (target) {
        node = document.createElement("a");
        node.href = target;
        node.textContent = label;
        if (!target.startsWith("#")) {
          node.target = "_blank";
          node.rel = "noopener noreferrer";
        }
      } else {
        node = document.createTextNode(label);
      }
    }
    parent.append(node);
    cursor = match.index + token.length;
  }
  parent.append(document.createTextNode(text.slice(cursor)));
}

function isMarkdownBlockStart(line) {
  return /^\s*(#{1,6})\s+/.test(line)
    || /^\s*(`{3,}|~{3,})/.test(line)
    || /^\s*>/.test(line)
    || /^\s*([-+*]|\d+\.)\s+/.test(line)
    || /^\s*((\*\s*){3,}|(-\s*){3,}|(_\s*){3,})$/.test(line);
}

function renderMarkdown(content) {
  const preview = elements["markdown-preview"];
  preview.replaceChildren();
  const lines = content.replace(/\r\n?/g, "\n").split("\n");
  let index = 0;
  while (index < lines.length) {
    const line = lines[index];
    if (!line.trim()) {
      index += 1;
      continue;
    }
    const fence = line.match(/^\s*(`{3,}|~{3,})/);
    if (fence) {
      const marker = fence[1][0];
      const codeLines = [];
      index += 1;
      while (index < lines.length && !new RegExp(`^\\s*${marker}{3,}`).test(lines[index])) {
        codeLines.push(lines[index]);
        index += 1;
      }
      if (index < lines.length) index += 1;
      const pre = document.createElement("pre");
      const code = document.createElement("code");
      code.textContent = codeLines.join("\n");
      pre.append(code);
      preview.append(pre);
      continue;
    }
    const heading = line.match(/^\s*(#{1,6})\s+(.+)$/);
    if (heading) {
      const element = document.createElement(`h${heading[1].length}`);
      appendInline(element, heading[2].replace(/\s+#+\s*$/, ""));
      preview.append(element);
      index += 1;
      continue;
    }
    if (/^\s*((\*\s*){3,}|(-\s*){3,}|(_\s*){3,})$/.test(line)) {
      preview.append(document.createElement("hr"));
      index += 1;
      continue;
    }
    if (/^\s*>/.test(line)) {
      const quote = document.createElement("blockquote");
      const paragraph = document.createElement("p");
      const quoteLines = [];
      while (index < lines.length && /^\s*>/.test(lines[index])) {
        quoteLines.push(lines[index].replace(/^\s*>\s?/, ""));
        index += 1;
      }
      appendInline(paragraph, quoteLines.join(" "));
      quote.append(paragraph);
      preview.append(quote);
      continue;
    }
    const listItem = line.match(/^\s*([-+*]|\d+\.)\s+(.+)$/);
    if (listItem) {
      const ordered = /\d+\./.test(listItem[1]);
      const list = document.createElement(ordered ? "ol" : "ul");
      while (index < lines.length) {
        const item = lines[index].match(/^\s*([-+*]|\d+\.)\s+(.+)$/);
        if (!item || /\d+\./.test(item[1]) !== ordered) break;
        const element = document.createElement("li");
        appendInline(element, item[2]);
        list.append(element);
        index += 1;
      }
      preview.append(list);
      continue;
    }
    const paragraphLines = [line.trim()];
    index += 1;
    while (index < lines.length && lines[index].trim() && !isMarkdownBlockStart(lines[index])) {
      paragraphLines.push(lines[index].trim());
      index += 1;
    }
    const paragraph = document.createElement("p");
    appendInline(paragraph, paragraphLines.join(" "));
    preview.append(paragraph);
  }
}

function togglePreview() {
  if (!state.selectedPath || !isMarkdown(state.selectedPath)) return;
  state.preview = !state.preview;
  if (state.preview) renderMarkdown(elements.editor.value);
  elements.editor.hidden = state.preview;
  elements["markdown-preview"].hidden = !state.preview;
  elements["preview-button"].textContent = state.preview ? "Edit" : "Preview";
  elements["editor-message"].textContent = state.preview
    ? "Safe basic Markdown preview · raw HTML is shown as text"
    : state.dirty ? "Unsaved changes" : "Saved";
  (state.preview ? elements["markdown-preview"] : elements.editor).focus();
}

function openEntryDialog(mode, initialPath = "") {
  if (state.loading || state.saving || state.mutating) return;
  state.entryMode = mode;
  const isMove = mode === "move";
  const isFolder = mode === "folder";
  const isRestore = mode === "restore";
  if (!isRestore) state.restoreItem = null;
  elements["entry-eyebrow"].textContent = isRestore ? "Recover from Trash" : isMove ? "Move or rename" : "Create";
  elements["entry-title"].textContent = isRestore ? "Restore to a path" : isMove ? "Choose a new path" : isFolder ? "New folder" : "New file";
  elements["entry-submit"].textContent = isRestore ? "Restore" : isMove ? "Move" : "Create";
  elements["entry-error"].textContent = "";
  elements["entry-path"].value = initialPath;
  elements["entry-dialog"].showModal();
  elements["entry-path"].focus();
  elements["entry-path"].select();
}

async function submitEntry(event) {
  event.preventDefault();
  if (state.loading || state.saving || state.mutating) return;
  const path = elements["entry-path"].value.trim();
  if (!path) return;
  const mode = state.entryMode;
  if (mode === "restore" && !state.restoreItem) return;
  elements["entry-error"].textContent = "";
  const movedKind = state.selectedKind;
  const opensFile = mode === "file" || (mode === "move" && movedKind === "file");
  if (opensFile && !canLeaveEditor()) return;
  state.mutating = true;
  updateEditorActions();
  let succeeded = false;
  let restoredCopyRetained = false;
  try {
    if (mode === "restore") {
      const result = await api(`/api/v1/trash/${state.restoreItem.id}/restore`, {
        method: "POST", body: JSON.stringify({ destination: path }),
      });
      restoredCopyRetained = result.trash_retained;
    } else if (mode === "file") {
      await api("/api/v1/file", {
        method: "PUT",
        body: JSON.stringify({ path, content: "", create_only: true }),
      });
    } else if (mode === "folder") {
      await api("/api/v1/folders", { method: "POST", body: JSON.stringify({ path }) });
    } else {
      await api("/api/v1/move", { method: "POST", body: JSON.stringify({ source: state.selectedPath, destination: path }) });
      closeDocument();
    }
    if (opensFile) {
      closeDocument();
    }
    elements["entry-dialog"].close();
    await refreshWorkspace();
    succeeded = true;
    if (mode === "restore") {
      toast(restoredCopyRetained ? `Restored ${path}; Trash cleanup failed. Inspect the retained item.` : `Restored ${path}`, restoredCopyRetained);
    } else toast(mode === "move" ? `Moved to ${path}` : `Created ${path}`);
  } catch (error) {
    elements["entry-error"].textContent = error.message || "The file operation failed.";
    showError(error);
  } finally {
    state.mutating = false;
    updateEditorActions();
  }
  if (succeeded && opensFile) {
    await openFile(path);
  } else if (succeeded && mode === "move") {
    const movedEntry = state.files.find((entry) => entry.path === path);
    if (movedEntry) await selectEntry(movedEntry);
  }
}

async function openTrash() {
  if (state.loading || state.saving || state.mutating) return;
  if (!elements["trash-dialog"].open) elements["trash-dialog"].showModal();
  await loadTrash();
  if (elements["trash-dialog"].open) elements["trash-refresh"].focus();
}

async function loadTrash() {
  const generation = ++state.trashGeneration;
  state.trashLoading = true;
  elements["trash-dialog"].setAttribute("aria-busy", "true");
  elements["trash-status"].textContent = "Loading recovery items…";
  elements["trash-error"].textContent = "";
  updateEditorActions();
  try {
    const { trash } = await api("/api/v1/trash");
    if (generation !== state.trashGeneration) return;
    elements["trash-items"].replaceChildren();
    const prefix = trash.unavailable_items ? "At least " : "";
    elements["trash-status"].textContent = `${trash.items.length} / ${trash.limits.max_items} items · ${prefix}${formatBytes(trash.usage_bytes)} / ${formatBytes(trash.limits.max_bytes)} · ${trash.entries} / ${trash.limits.max_entries} entries`;
    if (trash.unavailable_items) elements["trash-error"].textContent = "Unreadable items block further deletion until inspected or permanently deleted.";
    if (!trash.items.length) {
      const empty = document.createElement("p");
      empty.textContent = "Trash is empty. Deleted files and folders will appear here.";
      elements["trash-items"].append(empty);
    }
    for (const item of trash.items) {
      const card = document.createElement("section");
      card.className = "trash-item";
      card.dataset.trashId = item.id;
      const heading = document.createElement("h3");
      heading.textContent = item.path || "Unreadable recovery item";
      const details = document.createElement("p");
      details.textContent = item.state === "ready"
        ? `${item.kind} · ${formatBytes(item.bytes)} · ${new Date(item.deleted_at).toLocaleString()}`
        : item.message;
      const identity = document.createElement("code");
      identity.textContent = item.id;
      const actions = document.createElement("div");
      actions.className = "trash-actions";
      const restore = document.createElement("button");
      restore.type = "button";
      restore.className = "button primary";
      restore.textContent = "Restore";
      restore.setAttribute("aria-label", `Restore ${item.path || item.id}`);
      restore.dataset.unavailable = String(item.state !== "ready");
      restore.addEventListener("click", () => {
        if (state.mutating || state.trashLoading || item.state !== "ready") return;
        state.restoreItem = item;
        elements["trash-dialog"].close();
        openEntryDialog("restore", item.path);
      });
      const purge = document.createElement("button");
      purge.type = "button";
      purge.className = "button danger-ghost";
      purge.textContent = "Delete permanently";
      purge.setAttribute("aria-label", `Permanently delete ${item.path || item.id}`);
      purge.addEventListener("click", () => requestPurge(item));
      actions.append(restore, purge);
      card.append(heading, identity, details, actions);
      elements["trash-items"].append(card);
    }
  } catch (error) {
    if (generation !== state.trashGeneration) return;
    elements["trash-items"].replaceChildren();
    elements["trash-status"].textContent = "Trash could not be loaded.";
    elements["trash-error"].textContent = error.message || "Refresh Trash to retry.";
  } finally {
    if (generation === state.trashGeneration) {
      state.trashLoading = false;
      elements["trash-dialog"].setAttribute("aria-busy", "false");
      updateEditorActions();
    }
  }
}

async function openHistory() {
  if (state.loading || state.saving || state.mutating) return;
  elements["history-path"].value = state.selectedKind === "file" ? state.selectedPath : "";
  elements["history-dialog"].showModal();
  await loadHistory();
}

async function loadHistory() {
  const generation = ++state.historyGeneration;
  state.historyLoading = true;
  state.historyVersion = null;
  state.historyCurrent = null;
  elements["history-preview"].hidden = true;
  elements["history-dialog"].setAttribute("aria-busy", "true");
  elements["history-error"].textContent = "";
  elements["history-status"].textContent = "Loading saved versions…";
  updateEditorActions();
  try {
    const path = elements["history-path"].value.trim();
    const { history } = await api(`/api/v1/history${path ? `?path=${encodeURIComponent(path)}` : ""}`);
    if (generation !== state.historyGeneration) return;
    elements["history-items"].replaceChildren();
    elements["history-status"].textContent = `${history.items.length} shown · ${history.total_items} / ${history.limits.max_items} total · ${history.unavailable_items ? "at least " : ""}${formatBytes(history.usage_bytes)} / ${formatBytes(history.limits.max_bytes)}`;
    elements["history-retention"].textContent = `Automatic retention: up to ${history.limits.max_per_file} versions per original path. Oldest checkpoints expire when these limits require it; Trash is unaffected.`;
    if (history.unavailable_items) elements["history-error"].textContent = "Unavailable records block new checkpoints. Inspect or remove them before saving existing files.";
    if (!history.items.length) elements["history-items"].textContent = "No saved versions. Checkpoints appear before an existing text file is overwritten through the app.";
    for (const item of history.items) {
      const card = document.createElement("section");
      card.className = "trash-item";
      const title = document.createElement("h3");
      title.textContent = item.path || "Unavailable saved version";
      const detail = document.createElement("p");
      detail.textContent = item.state === "ready" ? `Version ${item.sequence} · ${formatBytes(item.size)} · ${new Date(item.saved_at).toLocaleString()}` : item.id;
      const actions = document.createElement("div");
      actions.className = "trash-actions";
      const preview = document.createElement("button");
      preview.type = "button";
      preview.className = "button primary";
      preview.textContent = "Preview";
      preview.setAttribute("aria-label", `Preview ${item.path || item.id} version ${item.sequence}`);
      preview.dataset.unavailable = String(item.state !== "ready");
      preview.addEventListener("click", () => previewVersion(item));
      const remove = document.createElement("button");
      remove.type = "button";
      remove.className = "button danger-ghost";
      remove.textContent = "Remove version";
      remove.setAttribute("aria-label", `Remove ${item.path || item.id} version ${item.sequence}`);
      remove.addEventListener("click", () => requestVersionAction("purge-version", item));
      actions.append(preview, remove);
      card.append(title, detail, actions);
      elements["history-items"].append(card);
    }
  } catch (error) {
    if (generation !== state.historyGeneration) return;
    elements["history-items"].replaceChildren();
    elements["history-status"].textContent = "History could not be loaded.";
    elements["history-error"].textContent = error.message || "Refresh history to retry.";
  } finally {
    if (generation === state.historyGeneration) {
      state.historyLoading = false;
      elements["history-dialog"].setAttribute("aria-busy", "false");
      updateEditorActions();
    }
  }
}

async function previewVersion(item) {
  if (state.mutating || state.historyLoading || item.state !== "ready") return;
  const generation = ++state.historyGeneration;
  state.historyLoading = true;
  state.historyVersion = null;
  state.historyCurrent = null;
  elements["history-dialog"].setAttribute("aria-busy", "true");
  elements["history-status"].textContent = "Loading version preview…";
  elements["history-preview"].hidden = true;
  elements["history-error"].textContent = "";
  updateEditorActions();
  try {
    const { version } = await api(`/api/v1/history/${item.id}`);
    let current = null;
    let currentMessage = "The original path is absent. Restore a new copy to recover this version.";
    try {
      current = (await api(`/api/v1/file?path=${encodeURIComponent(version.path)}`)).file;
      currentMessage = `Current disk file: ${version.path} · ETag ${current.etag}`;
    } catch (error) {
      if (error.code !== "not_found") currentMessage = `Current disk file unavailable: ${error.message}. Restore a new copy instead.`;
    }
    if (generation !== state.historyGeneration) return;
    state.historyVersion = version;
    state.historyCurrent = current;
    elements["history-preview-title"].textContent = `${version.path} · saved version ${version.sequence}`;
    elements["history-content"].value = version.content;
    elements["history-current"].value = current ? current.content : "";
    elements["history-current-status"].textContent = currentMessage;
    elements["history-status"].textContent = "Saved version ready. Restore a new copy or confirm replacement of the previewed disk file.";
    elements["history-destination"].value = `${version.path}.restored`;
    elements["history-preview"].hidden = false;
    elements["history-preview"].scrollIntoView({ block: "nearest" });
  } catch (error) {
    if (generation === state.historyGeneration) {
      elements["history-status"].textContent = "Version preview could not be loaded.";
      elements["history-error"].textContent = error.message || "This version could not be previewed.";
    }
  } finally {
    if (generation === state.historyGeneration) {
      state.historyLoading = false;
      elements["history-dialog"].setAttribute("aria-busy", "false");
      updateEditorActions();
    }
  }
}

async function restoreVersionCopy(event) {
  event.preventDefault();
  if (state.mutating || state.historyLoading || !state.historyVersion) return;
  const destination = elements["history-destination"].value.trim();
  if (!destination) return;
  const version = state.historyVersion;
  state.mutating = true;
  elements["history-error"].textContent = "";
  updateEditorActions();
  try {
    await api(`/api/v1/history/${version.id}/restore`, { method: "POST", body: JSON.stringify({ destination }) });
    await refreshWorkspace();
    toast(`Restored a new copy: ${destination}. Your editor was kept unchanged.`);
  } catch (error) {
    elements["history-error"].textContent = error.message || "The copy could not be restored.";
    showError(error);
  } finally {
    state.mutating = false;
    updateEditorActions();
  }
}

function requestVersionAction(type, item) {
  if (state.mutating || state.historyLoading || !item) return;
  if (type === "restore-version" && !state.historyCurrent) return;
  state.confirmAction = { type, id: item.id, path: item.path, etag: state.historyCurrent?.etag };
  elements["confirm-title"].textContent = type === "restore-version" ? "Replace the current disk file?" : "Permanently remove this saved version?";
  elements["confirm-message"].textContent = type === "restore-version"
    ? `${item.path} will be replaced with saved version ${item.sequence}, only if it still matches the disk preview. Current disk content is checkpointed first. Unsaved editor drafts are kept.`
    : `This checkpoint of ${item.path || item.id} will be removed permanently. The active file, other versions, and Trash are unchanged.`;
  elements["confirm-submit"].textContent = type === "restore-version" ? "Replace disk file" : "Remove version permanently";
  elements["confirm-error"].textContent = "";
  elements["confirm-dialog"].showModal();
}

function requestPurge(item) {
  if (state.mutating || state.trashLoading) return;
  state.confirmAction = { type: "purge", id: item.id };
  elements["confirm-title"].textContent = "Permanently delete recovery item?";
  elements["confirm-message"].textContent = `${item.path || item.id} will be removed from Trash. This Trash copy cannot be restored afterward. Older saved-history checkpoints, if any, are separate and remain until removed or expired.`;
  elements["confirm-submit"].textContent = "Delete permanently";
  elements["confirm-error"].textContent = "";
  elements["confirm-dialog"].showModal();
}

function requestDelete() {
  if (!state.selectedPath || state.loading || state.saving || state.mutating) return;
  const permanent = state.selectedKind.startsWith("blocked");
  state.confirmAction = {
    type: "delete", path: state.selectedPath, recursive: state.selectedKind === "directory",
    permanent, etag: state.selectedKind === "file" ? state.etag : null,
  };
  elements["confirm-title"].textContent = permanent ? "Permanently remove blocked entry?" : "Move to Trash?";
  elements["confirm-message"].textContent = permanent
    ? `${state.selectedPath} cannot be recovered by Trash. Only this link or special entry will be removed, not a link target.`
    : `${state.selectedPath}${state.selectedKind === "directory" ? " and its contents" : ""} will move to local Trash and can be restored. ${state.dirty ? "Unsaved editor changes will be discarded; only the disk version is kept." : "Nothing is permanently deleted yet."}`;
  elements["confirm-submit"].textContent = permanent ? "Delete permanently" : "Move to Trash";
  elements["confirm-error"].textContent = "";
  elements["confirm-dialog"].showModal();
}

async function confirmDelete(event) {
  event.preventDefault();
  if (state.loading || state.saving || state.mutating) return;
  const action = state.confirmAction;
  if (!action) return;
  elements["confirm-error"].textContent = "";
  state.mutating = true;
  let reloadPath = null;
  updateEditorActions();
  try {
    if (action.type === "purge-version") {
      await api(`/api/v1/history/${action.id}?confirm=true`, { method: "DELETE" });
      elements["confirm-dialog"].close();
      await loadHistory();
      toast("Permanently removed the saved version.");
    } else if (action.type === "restore-version") {
      await api(`/api/v1/history/${action.id}/restore`, { method: "POST", body: JSON.stringify({ destination: action.path, expected_etag: action.etag }) });
      elements["confirm-dialog"].close();
      elements["history-dialog"].close();
      if (state.selectedPath === action.path && !state.dirty) {
        reloadPath = action.path;
        closeDocument();
      }
      await refreshWorkspace();
      toast(`Restored ${action.path}.${state.dirty ? " Your unsaved editor draft is unchanged; resolve its disk conflict before saving." : ""}`);
    } else if (action.type === "purge") {
      await api(`/api/v1/trash/${action.id}?confirm=true`, { method: "DELETE" });
      elements["confirm-dialog"].close();
      await loadTrash();
      toast("Permanently deleted the Trash item.");
    } else {
      const query = new URLSearchParams({ path: action.path, recursive: String(action.recursive), permanent: String(action.permanent) });
      if (action.etag) query.set("expected_etag", action.etag);
      await api(`/api/v1/entry?${query}`, { method: "DELETE" });
      elements["confirm-dialog"].close();
      closeDocument();
      await refreshWorkspace({ keepSelection: false });
      toast(action.permanent ? `Permanently deleted ${action.path}` : `Moved ${action.path} to Trash`);
    }
    state.confirmAction = null;
  } catch (error) {
    elements["confirm-error"].textContent = error.message || "The operation failed.";
    showError(error);
  } finally {
    state.mutating = false;
    updateEditorActions();
    if (action.type === "purge" && !elements["confirm-dialog"].open && elements["trash-dialog"].open) {
      elements["trash-refresh"].focus();
    }
    if (action.type === "purge-version" && !elements["confirm-dialog"].open && elements["history-dialog"].open) elements["history-refresh"].focus();
  }
  if (reloadPath) await openFile(reloadPath);
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
    if (["mkdir", "touch", "mv", "rm", "restore", "purge", "restore-version", "purge-version"].includes(command.split(/\s+/, 1)[0].toLowerCase())) await refreshWorkspace();
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
elements["trash-button"].addEventListener("click", openTrash);
elements["trash-refresh"].addEventListener("click", loadTrash);
elements["history-button"].addEventListener("click", openHistory);
elements["history-refresh"].addEventListener("click", loadHistory);
elements["history-all"].addEventListener("click", () => {
  elements["history-path"].value = "";
  loadHistory();
});
elements["history-path"].addEventListener("keydown", (event) => {
  if (event.key === "Enter") { event.preventDefault(); loadHistory(); }
});
elements["history-dialog"].addEventListener("close", () => {
  state.historyGeneration += 1;
  state.historyLoading = false;
  updateEditorActions();
});
elements["history-copy-form"].addEventListener("submit", restoreVersionCopy);
elements["history-replace"].addEventListener("click", () => requestVersionAction("restore-version", state.historyVersion));
elements["import-button"].addEventListener("click", () => elements["file-input"].click());
elements["file-input"].addEventListener("change", importFiles);
elements["new-file-button"].addEventListener("click", () => openEntryDialog("file"));
elements["new-folder-button"].addEventListener("click", () => openEntryDialog("folder"));
elements["empty-new-button"].addEventListener("click", () => openEntryDialog("file"));
elements["save-button"].addEventListener("click", saveFile);
elements["preview-button"].addEventListener("click", togglePreview);
elements["download-button"].addEventListener("click", downloadFile);
elements["rename-button"].addEventListener("click", () => {
  if (state.selectedPath) openEntryDialog("move", state.selectedPath);
});
elements["delete-button"].addEventListener("click", requestDelete);
elements.editor.addEventListener("input", () => {
  updateDirty(true);
  updateStats();
  scheduleDraft();
});
elements["entry-form"].addEventListener("submit", submitEntry);
elements["confirm-form"].addEventListener("submit", confirmDelete);
elements["conflict-cancel"].addEventListener("click", () => elements["conflict-dialog"].close());
elements["conflict-reload"].addEventListener("click", reloadConflict);
elements["conflict-overwrite"].addEventListener("click", overwriteConflict);
elements["draft-discard"].addEventListener("click", discardDraft);
elements["draft-restore"].addEventListener("click", restoreDraft);
elements["terminal-form"].addEventListener("submit", runTerminal);
elements["token-form"].addEventListener("submit", submitToken);
elements["search-form"].addEventListener("submit", (event) => {
  event.preventDefault();
  clearTimeout(state.searchTimer);
  performSearch();
});
elements["search-input"].addEventListener("input", scheduleSearch);
elements["search-input"].addEventListener("keydown", (event) => {
  if (event.key === "Escape") clearSearch({ focus: true });
});
elements["search-clear"].addEventListener("click", () => clearSearch({ focus: true }));
document.querySelectorAll("[data-close-dialog]").forEach((button) => {
  button.addEventListener("click", () => button.closest("dialog").close());
});
elements["token-dialog"].addEventListener("cancel", (event) => event.preventDefault());
elements["draft-dialog"].addEventListener("cancel", (event) => event.preventDefault());
window.addEventListener("beforeunload", (event) => {
  if (state.dirty) {
    clearTimeout(state.draftTimer);
    writeDraft();
    event.preventDefault();
  }
});
document.addEventListener("keydown", (event) => {
  if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "s") {
    event.preventDefault();
    saveFile();
  }
  if ((event.ctrlKey || event.metaKey) && event.shiftKey && event.key.toLowerCase() === "f") {
    event.preventDefault();
    elements["search-input"].focus();
    elements["search-input"].select();
  }
});

refreshWorkspace();
