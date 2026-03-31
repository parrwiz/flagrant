"""Terminal output formatting."""

from __future__ import annotations

from rich.console import Console
from rich.panel import Panel
from rich.text import Text

from flagrant.reviewer import Issue

console = Console()

SEVERITY_STYLES = {
    "high": ("bold red", "●", "HIGH  "),
    "medium": ("bold yellow", "●", "MEDIUM"),
    "low": ("bold blue", "●", "LOW   "),
}


def display_issues(issues: list[Issue], explain: bool = False) -> None:
    """Print review issues to the terminal."""
    if not issues:
        console.print()
        console.print("[bold green]no issues found[/bold green]")
        console.print()
        return

    # Sort: high first, then medium, then low
    severity_order = {"high": 0, "medium": 1, "low": 2}
    issues.sort(key=lambda i: severity_order.get(i.severity, 3))

    # Count by severity
    counts = {}
    for issue in issues:
        counts[issue.severity] = counts.get(issue.severity, 0) + 1

    # Header
    total = len(issues)
    header_parts = []
    if counts.get("high"):
        header_parts.append(f"[bold red]{counts['high']} high[/bold red]")
    if counts.get("medium"):
        header_parts.append(f"[bold yellow]{counts['medium']} medium[/bold yellow]")
    if counts.get("low"):
        header_parts.append(f"[bold blue]{counts['low']} low[/bold blue]")

    summary = " | ".join(header_parts)

    console.print()
    console.rule(style="dim")
    console.print(
        f" [bold]flagrant[/bold] | {total} issue{'s' if total != 1 else ''} flagged  ({summary})",
    )
    console.rule(style="dim")

    # Issues
    for issue in issues:
        style, bullet, label = SEVERITY_STYLES.get(
            issue.severity, ("dim", "○", "???   ")
        )

        line_str = f" line {issue.line}" if issue.line else ""
        location = f"{issue.file}{line_str}"

        console.print()
        console.print(f"  [{style}]{bullet} {label}[/{style}]  [bold]{location}[/bold]")
        console.print(f"           {issue.issue}")
        if issue.fix:
            console.print(f"           [dim]Fix: {issue.fix}[/dim]")

        if explain and issue.explanation:
            console.print(f"           [italic cyan]{issue.explanation}[/italic cyan]")

    console.print()
    console.rule(style="dim")
    console.print()


def display_error(message: str) -> None:
    """Print an error."""
    console.print(f"\n[bold red]error: {message}[/bold red]\n")


def display_info(message: str) -> None:
    """Print an info message."""
    console.print(f"\n[dim]{message}[/dim]\n")


def display_success(message: str) -> None:
    """Print a success message."""
    console.print(f"\n[green]{message}[/green]\n")
