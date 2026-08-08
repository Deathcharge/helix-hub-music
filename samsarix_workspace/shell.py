"""A deliberately non-shell command surface for workspace navigation.

Commands call :class:`Workspace` methods directly. They never invoke a process,
evaluate code, expand environment variables, or interpret shell redirection.
"""

from __future__ import annotations

import shlex
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import PurePosixPath

from samsarix_workspace.workspace import Workspace, WorkspaceError


@dataclass(frozen=True, slots=True)
class ShellResult:
    """One virtual command result."""

    output: str
    cwd: str
    exit_code: int = 0
    clear: bool = False


class VirtualShell:
    """Stateful, allowlisted workspace commands with bounded output."""

    HELP = """Available commands:
  help                 Show this guide
  pwd                  Print the current workspace folder
  cd [path]            Change the virtual working folder
  ls [-a] [path]       List files and folders
  cat <file>           Print a UTF-8 text file
  head [-n N] <file>   Print the first lines of a file
  tail [-n N] <file>   Print the last lines of a file
  wc <file>            Count lines, words, and UTF-8 bytes
  find [path] [term]   Find workspace paths
  grep <term> <file>   Print matching lines
  mkdir <path>         Create one folder
  touch <path>         Create an empty file
  mv <source> <dest>   Move or rename an entry
  rm [-r] <path>       Delete an entry (-r confirms a folder tree)
  echo [text]          Print text (redirection is not supported)
  clear                Clear terminal output

This is a safe virtual terminal, not an operating-system shell."""

    def __init__(
        self,
        workspace: Workspace,
        *,
        max_command_chars: int = 2_048,
        max_output_chars: int = 65_536,
    ) -> None:
        self.workspace = workspace
        self.cwd = ""
        self.max_command_chars = max_command_chars
        self.max_output_chars = max_output_chars
        self.handlers: dict[str, Callable[[list[str]], ShellResult]] = {
            "help": self._help,
            "pwd": self._pwd,
            "cd": self._cd,
            "ls": self._ls,
            "cat": self._cat,
            "head": self._head,
            "tail": self._tail,
            "wc": self._wc,
            "find": self._find,
            "grep": self._grep,
            "mkdir": self._mkdir,
            "touch": self._touch,
            "mv": self._move,
            "rm": self._remove,
            "echo": self._echo,
            "clear": self._clear,
        }

    def _path(self, value: str | None = None) -> str:
        if value is None or value in {"", "."}:
            return self.cwd
        if value == "/":
            return ""
        if value.startswith("/"):
            combined = PurePosixPath(value.removeprefix("/"))
        else:
            combined = PurePosixPath(self.cwd) / value if self.cwd else PurePosixPath(value)
        collapsed: list[str] = []
        for part in combined.parts:
            if part in {"", "."}:
                continue
            if part == "..":
                if not collapsed:
                    raise WorkspaceError("path_escape", "Path escapes the workspace root.")
                collapsed.pop()
            else:
                collapsed.append(part)
        return self.workspace.normalize("/".join(collapsed))

    def _bounded(self, output: str) -> str:
        if len(output) <= self.max_output_chars:
            return output
        marker = "\n… output truncated by Samsarix Workspace …"
        if self.max_output_chars <= len(marker):
            return output[: self.max_output_chars]
        return output[: self.max_output_chars - len(marker)] + marker

    def execute(self, command: str) -> ShellResult:
        """Parse and execute one allowlisted command."""

        if len(command) > self.max_command_chars:
            return ShellResult(
                f"error: commands are limited to {self.max_command_chars} characters",
                self.cwd,
                2,
            )
        try:
            arguments = shlex.split(command, posix=True)
        except ValueError as exc:
            return ShellResult(f"error: {exc}", self.cwd, 2)
        if not arguments:
            return ShellResult("", self.cwd)

        name, *args = arguments
        handler = self.handlers.get(name.casefold())
        if handler is None:
            return ShellResult(
                f"error: unknown command {name!r}; run 'help' for the allowlist",
                self.cwd,
                127,
            )
        try:
            result = handler(args)
        except WorkspaceError as exc:
            return ShellResult(f"error [{exc.code}]: {exc.message}", self.cwd, 1)
        return ShellResult(self._bounded(result.output), result.cwd, result.exit_code, result.clear)

    def _require_count(self, args: list[str], count: int, usage: str) -> None:
        if len(args) != count:
            raise WorkspaceError("usage", f"Usage: {usage}")

    def _help(self, args: list[str]) -> ShellResult:
        self._require_count(args, 0, "help")
        return ShellResult(self.HELP, self.cwd)

    def _pwd(self, args: list[str]) -> ShellResult:
        self._require_count(args, 0, "pwd")
        return ShellResult("/" + self.cwd, self.cwd)

    def _cd(self, args: list[str]) -> ShellResult:
        if len(args) > 1:
            raise WorkspaceError("usage", "Usage: cd [path]")
        destination = self._path(args[0] if args else "/")
        self.workspace.assert_directory(destination)
        self.cwd = destination
        return ShellResult("", self.cwd)

    def _ls(self, args: list[str]) -> ShellResult:
        show_hidden = False
        values = list(args)
        if values and values[0] == "-a":
            show_hidden = True
            values.pop(0)
        if len(values) > 1:
            raise WorkspaceError("usage", "Usage: ls [-a] [path]")
        entries = self.workspace.list_entries(self._path(values[0] if values else None))
        lines = []
        for entry in entries:
            if not show_hidden and entry.name.startswith("."):
                continue
            suffix = "/" if entry.kind == "directory" else ""
            lines.append(entry.name + suffix)
        return ShellResult("\n".join(lines), self.cwd)

    def _cat(self, args: list[str]) -> ShellResult:
        self._require_count(args, 1, "cat <file>")
        return ShellResult(self.workspace.read_file(self._path(args[0])).content, self.cwd)

    @staticmethod
    def _line_arguments(args: list[str], usage: str) -> tuple[int, str]:
        if len(args) == 1:
            return 10, args[0]
        if len(args) == 3 and args[0] == "-n":
            try:
                count = int(args[1])
            except ValueError as exc:
                raise WorkspaceError("usage", f"Usage: {usage}") from exc
            if not 0 <= count <= 1_000:
                raise WorkspaceError("usage", "Line count must be between 0 and 1000.")
            return count, args[2]
        raise WorkspaceError("usage", f"Usage: {usage}")

    def _head(self, args: list[str]) -> ShellResult:
        count, path = self._line_arguments(args, "head [-n N] <file>")
        lines = self.workspace.read_file(self._path(path)).content.splitlines()
        return ShellResult("\n".join(lines[:count]), self.cwd)

    def _tail(self, args: list[str]) -> ShellResult:
        count, path = self._line_arguments(args, "tail [-n N] <file>")
        lines = self.workspace.read_file(self._path(path)).content.splitlines()
        return ShellResult("\n".join(lines[-count:] if count else []), self.cwd)

    def _wc(self, args: list[str]) -> ShellResult:
        self._require_count(args, 1, "wc <file>")
        document = self.workspace.read_file(self._path(args[0]))
        line_count = len(document.content.splitlines())
        word_count = len(document.content.split())
        return ShellResult(f"{line_count} {word_count} {document.size} {args[0]}", self.cwd)

    def _find(self, args: list[str]) -> ShellResult:
        if len(args) > 2:
            raise WorkspaceError("usage", "Usage: find [path] [term]")
        path = self._path(args[0]) if args else self.cwd
        term = args[1].casefold() if len(args) == 2 else ""
        entries = self.workspace.list_entries(path, recursive=True)
        matches = [entry.path for entry in entries if term in entry.path.casefold()]
        return ShellResult("\n".join(matches), self.cwd)

    def _grep(self, args: list[str]) -> ShellResult:
        self._require_count(args, 2, "grep <term> <file>")
        term, path = args
        lines = self.workspace.read_file(self._path(path)).content.splitlines()
        matches = [f"{number}:{line}" for number, line in enumerate(lines, 1) if term in line]
        return ShellResult("\n".join(matches), self.cwd, 0 if matches else 1)

    def _mkdir(self, args: list[str]) -> ShellResult:
        self._require_count(args, 1, "mkdir <path>")
        self.workspace.make_directory(self._path(args[0]))
        return ShellResult("", self.cwd)

    def _touch(self, args: list[str]) -> ShellResult:
        self._require_count(args, 1, "touch <path>")
        path = self._path(args[0])
        try:
            existing = self.workspace.read_file(path)
        except WorkspaceError as exc:
            if exc.code != "not_found":
                raise
            self.workspace.write_file(path, "")
        else:
            self.workspace.write_file(path, existing.content, expected_etag=existing.etag)
        return ShellResult("", self.cwd)

    def _move(self, args: list[str]) -> ShellResult:
        self._require_count(args, 2, "mv <source> <destination>")
        self.workspace.move(self._path(args[0]), self._path(args[1]))
        return ShellResult("", self.cwd)

    def _remove(self, args: list[str]) -> ShellResult:
        recursive = False
        values = list(args)
        if values and values[0] in {"-r", "-R"}:
            recursive = True
            values.pop(0)
        self._require_count(values, 1, "rm [-r] <path>")
        target = self._path(values[0])
        self.workspace.delete(target, recursive=recursive)
        return ShellResult("", self.cwd)

    def _echo(self, args: list[str]) -> ShellResult:
        return ShellResult(" ".join(args), self.cwd)

    def _clear(self, args: list[str]) -> ShellResult:
        self._require_count(args, 0, "clear")
        return ShellResult("", self.cwd, clear=True)
