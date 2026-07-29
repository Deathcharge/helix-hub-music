from __future__ import annotations

from samsarix_workspace.shell import VirtualShell
from samsarix_workspace.workspace import Workspace


def test_virtual_terminal_primary_journey(workspace: Workspace) -> None:
    shell = VirtualShell(workspace)
    assert "not an operating-system shell" in shell.execute("help").output
    assert shell.execute("pwd").output == "/"
    assert shell.execute("mkdir notes").exit_code == 0
    assert shell.execute("cd notes").cwd == "notes"
    assert shell.execute("touch idea.md").exit_code == 0
    workspace.write_file("notes/idea.md", "alpha\nbeta\nalpha two")

    assert shell.execute("ls").output == "idea.md"
    assert shell.execute("cat idea.md").output.startswith("alpha")
    assert shell.execute("head -n 1 idea.md").output == "alpha"
    assert shell.execute("tail -n 1 idea.md").output == "alpha two"
    assert shell.execute("wc idea.md").output == "3 4 20 idea.md"
    assert shell.execute("grep alpha idea.md").output == "1:alpha\n3:alpha two"
    assert shell.execute("grep absent idea.md").exit_code == 1
    assert shell.execute("find / idea").output == "notes/idea.md"
    assert shell.execute("mv idea.md renamed.md").exit_code == 0
    assert shell.execute("rm renamed.md").exit_code == 0
    assert shell.execute("cd /").cwd == ""
    assert shell.execute("rm -r notes").exit_code == 0


def test_terminal_is_an_allowlist_not_a_shell(workspace: Workspace) -> None:
    shell = VirtualShell(workspace)
    result = shell.execute("python -c 'print(1)'")
    assert result.exit_code == 127
    assert "unknown command" in result.output
    assert shell.execute("echo hello > owned.txt").output == "hello > owned.txt"
    assert not (workspace.root / "owned.txt").exists()
    assert shell.execute("echo $HOME && whoami").output == "$HOME && whoami"


def test_terminal_parsing_usage_and_path_errors(workspace: Workspace) -> None:
    shell = VirtualShell(workspace, max_command_chars=8)
    assert shell.execute("unterminated'").exit_code == 2
    assert shell.execute("123456789").exit_code == 2
    shell = VirtualShell(workspace)
    assert shell.execute("").output == ""
    assert shell.execute("pwd extra").exit_code == 1
    assert shell.execute("cd a b").exit_code == 1
    assert shell.execute("cd ..").exit_code == 1
    assert shell.execute("cat").exit_code == 1
    assert shell.execute("head -n nope file").exit_code == 1
    assert shell.execute("tail -n 1001 file").exit_code == 1
    assert shell.execute("find a b c").exit_code == 1
    assert shell.execute("grep only-one").exit_code == 1
    assert shell.execute("mkdir").exit_code == 1
    assert shell.execute("mv one").exit_code == 1
    assert shell.execute("rm").exit_code == 1


def test_hidden_files_clear_and_output_bound(workspace: Workspace) -> None:
    workspace.write_file(".hidden", "secret")
    workspace.write_file("visible", "abcdefghij")
    shell = VirtualShell(workspace, max_output_chars=30)
    assert shell.execute("ls").output == "visible"
    assert ".hidden" in shell.execute("ls -a").output
    assert shell.execute("ls a b").exit_code == 1
    assert shell.execute("help").output.endswith("… output truncated by Samsarix Workspace …")
    assert shell.execute("clear").clear is True


def test_touch_preserves_existing_content_and_reports_file_errors(workspace: Workspace) -> None:
    workspace.write_file("kept.txt", "keep")
    shell = VirtualShell(workspace)
    assert shell.execute("touch kept.txt").exit_code == 0
    assert workspace.read_file("kept.txt").content == "keep"
    workspace.make_directory("folder")
    result = shell.execute("touch folder")
    assert result.exit_code == 1
    assert "not_a_file" in result.output
