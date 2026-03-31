"""CLI entry points."""

from __future__ import annotations

import os
import stat
import sys
from pathlib import Path
from typing import Optional

import click
import typer
from rich.console import Console
from rich.spinner import Spinner
from rich.live import Live

from flagrant.config import (
    get_app_config,
    load_project_config,
    setup_api_key_interactive,
    AppConfig,
    PROVIDERS,
)
from flagrant.git_utils import (
    get_git_root,
    get_staged_diff,
    get_staged_files,
    get_repo_files,
    read_single_file,
)
from flagrant.reviewer import review_code, review_diff, Issue
from flagrant.formatter import (
    display_issues,
    display_error,
    display_info,
    display_success,
)

console = Console()

_SUBCOMMANDS = {"config", "install-hook", "remove-hook"}


def _run_review(
    files: list[dict],
    app_config: AppConfig,
    strict: bool,
    explain: bool,
    diff_mode: bool,
    language: str,
    diff_text: Optional[str] = None,
) -> list[Issue]:
    """Run the review, show a spinner while waiting."""
    provider_name = PROVIDERS[app_config.provider]["name"]
    model = app_config.effective_model

    with Live(
        Spinner("dots", text=f"  [dim]Reviewing with {provider_name} ({model})...[/dim]"),
        console=console,
        transient=True,
    ):
        if diff_mode and diff_text:
            issues = review_diff(
                diff_text=diff_text,
                app_config=app_config,
                strict=strict,
                explain=explain,
                language=language,
            )
        else:
            issues = review_code(
                files=files,
                app_config=app_config,
                strict=strict,
                explain=explain,
                diff_mode=diff_mode,
                language=language,
            )

    return issues


def do_review(
    path: Optional[str] = None,
    staged: bool = False,
    file: Optional[str] = None,
    strict: bool = False,
    explain: bool = False,
) -> None:
    """Run a review based on CLI args."""
    # Default to current dir
    if path is None and not staged and file is None:
        path = "."

    # Load configs
    try:
        app_config = get_app_config()
    except SystemExit:
        raise typer.Exit(1)

    repo_root = get_git_root(path or ".")
    project_config = load_project_config(repo_root) if repo_root else None

    # Merge project config with CLI flags
    if project_config:
        strict = strict or project_config.strict
        explain = explain or project_config.explain
        language = project_config.language
        ignore_patterns = project_config.ignore
    else:
        language = "auto"
        ignore_patterns = []

    # Determine what to review
    files: list[dict] = []
    diff_text: Optional[str] = None
    diff_mode = False

    if file:
        # Single file mode
        result = read_single_file(file)
        if not result:
            display_error(f"Cannot read file: {file}")
            raise typer.Exit(1)
        files = [result]
    elif staged:
        # staged changes -- review the diff
        diff_text = get_staged_diff(path or ".")
        if not diff_text:
            display_info("nothing staged")
            raise typer.Exit(0)
        diff_mode = True
    else:
        # Full repo/directory scan
        target = path or "."
        target_path = Path(target)

        if target_path.is_file():
            result = read_single_file(str(target_path))
            if not result:
                display_error(f"Cannot read file: {target}")
                raise typer.Exit(1)
            files = [result]
        else:
            files = get_repo_files(target, ignore_patterns=ignore_patterns)
            if not files:
                display_info("no reviewable files found")
                raise typer.Exit(0)

            # limit how much we send to the api
            if len(files) > 50:
                console.print(
                    f"[yellow]{len(files)} files found, reviewing first 50. "
                    f"use --file or --staged to narrow scope.[/yellow]"
                )
                files = files[:50]

    # Run review
    try:
        issues = _run_review(
            files=files,
            app_config=app_config,
            strict=strict,
            explain=explain,
            diff_mode=diff_mode,
            language=language,
            diff_text=diff_text,
        )
    except RuntimeError:
        display_error("review failed. check your API key and account balance.")
        raise typer.Exit(1)

    # Display results
    display_issues(issues, explain=explain)

    # Exit code 1 if high severity issues found
    if any(i.severity == "high" for i in issues):
        raise typer.Exit(1)




class FlagrantCLI(click.Group):
    """Routes bare args to the review subcommand."""

    def parse_args(self, ctx: click.Context, args: list[str]) -> list[str]:
        if args:

            first_non_opt = None
            for a in args:
                if not a.startswith("-"):
                    first_non_opt = a
                    break

            if first_non_opt is None or first_non_opt not in self.commands:
                args = ["review"] + args

        if not args:
            args = ["review"]

        return super().parse_args(ctx, args)


@click.group(cls=FlagrantCLI)
def app():
    """flagrant - local AI code reviewer."""
    pass


@app.command("review")
@click.argument("path", required=False, default=None)
@click.option("--staged", "-s", is_flag=True, help="Only review staged git changes.")
@click.option("--file", "-f", "file_path", default=None, help="Review a single file.")
@click.option("--strict", is_flag=True, help="Security-focused review pass.")
@click.option("--explain", "-e", is_flag=True, help="Include teaching explanations.")
def review_cmd(path, staged, file_path, strict, explain):
    """Review code for issues like a senior developer would."""
    do_review(path=path, staged=staged, file=file_path, strict=strict, explain=explain)


@app.command("config")
def configure():
    """Reconfigure API key and provider settings."""
    setup_api_key_interactive()


PRE_COMMIT_HOOK = """#!/bin/sh
# flagrant pre-commit hook
# Installed by: flagrant install-hook

flagrant --staged
exit_code=$?

if [ $exit_code -ne 0 ]; then
    echo ""
    echo "flagrant: commit blocked (high severity issues found)"
    echo "   Fix the issues above, or commit with --no-verify to skip."
    echo ""
fi

exit $exit_code
"""


@app.command("install-hook")
def install_hook():
    """Install a pre-commit git hook that runs flagrant --staged."""
    repo_root = get_git_root(".")
    if not repo_root:
        display_error("Not inside a git repository.")
        raise SystemExit(1)

    hooks_dir = repo_root / ".git" / "hooks"
    hook_path = hooks_dir / "pre-commit"

    if hook_path.exists():
        content = hook_path.read_text()
        if "flagrant" in content.lower():
            display_info("Flagrant pre-commit hook is already installed.")
            return
        else:
            display_error(
                f"A pre-commit hook already exists at {hook_path}.\n"
                "  Back it up or remove it, then try again."
            )
            raise SystemExit(1)

    hooks_dir.mkdir(parents=True, exist_ok=True)
    hook_path.write_text(PRE_COMMIT_HOOK)
    hook_path.chmod(hook_path.stat().st_mode | stat.S_IEXEC)

    display_success(f"Pre-commit hook installed at {hook_path}")
    console.print(
        "[dim]  It will run [bold]flagrant --staged[/bold] before every commit.\n"
        "  Use [bold]git commit --no-verify[/bold] to skip.[/dim]\n"
    )


@app.command("remove-hook")
def remove_hook():
    """Remove the flagrant pre-commit hook."""
    repo_root = get_git_root(".")
    if not repo_root:
        display_error("Not inside a git repository.")
        raise SystemExit(1)

    hook_path = repo_root / ".git" / "hooks" / "pre-commit"

    if not hook_path.exists():
        display_info("no pre-commit hook found.")
        return

    content = hook_path.read_text()
    if "flagrant" not in content.lower():
        display_error(
            "The existing pre-commit hook was not installed by Flagrant.\n"
            "  Remove it manually if needed."
        )
        raise SystemExit(1)

    hook_path.unlink()
    display_success("Pre-commit hook removed.")


if __name__ == "__main__":
    app()
