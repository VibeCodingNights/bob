"""CLI for hackathon-finder."""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys

from rich.console import Console
from rich.table import Table

from hackathon_finder.aggregator import fetch_all
from hackathon_finder.models import Format, Hackathon
from hackathon_finder.sources import ALL_SOURCES


console = Console()


def _format_date(h: Hackathon) -> str:
    if h.start_date:
        s = h.start_date.strftime("%b %d")
        if h.end_date and h.end_date.date() != h.start_date.date():
            s += f" - {h.end_date.strftime('%b %d')}"
        return s
    return "TBD"


def _format_badge(h: Hackathon) -> str:
    parts = []
    if h.format == Format.IN_PERSON:
        parts.append("[bold green]IRL[/]")
    elif h.format == Format.HYBRID:
        parts.append("[bold yellow]HYBRID[/]")
    else:
        parts.append("[bold cyan]VIRTUAL[/]")

    if h.registration_status.value == "open":
        parts.append("[green]OPEN[/]")
    elif h.registration_status.value == "waitlist":
        parts.append("[yellow]WAITLIST[/]")
    elif h.registration_status.value == "upcoming":
        parts.append("[blue]UPCOMING[/]")

    return " ".join(parts)


def display(hackathons: list[Hackathon], show_source: bool = True) -> None:
    if not hackathons:
        console.print("[dim]No hackathons found.[/dim]")
        return

    table = Table(show_header=True, header_style="bold", show_lines=False, pad_edge=False)
    table.add_column("Date", style="cyan", width=14)
    table.add_column("Name", style="bold white", max_width=50)
    table.add_column("Location", max_width=28)
    table.add_column("Status", width=18)
    if show_source:
        table.add_column("Source", style="dim", width=10)

    for h in hackathons:
        row = [
            _format_date(h),
            h.name,
            h.location if h.format != Format.VIRTUAL else "[dim]Online[/dim]",
            _format_badge(h),
        ]
        if show_source:
            row.append(h.source)
        table.add_row(*row)

    console.print()
    console.print(table)
    console.print(f"\n[dim]{len(hackathons)} hackathons found[/dim]")


async def _run(args: argparse.Namespace) -> None:
    sources = [S() for S in ALL_SOURCES]

    # Filter to specific sources if requested
    if args.source:
        names = {s.strip().lower() for s in args.source.split(",")}
        sources = [s for s in sources if s.name in names]

    sf = not args.no_sf
    virtual = not args.no_virtual

    with console.status("[bold]Fetching hackathons..."):
        hackathons = await fetch_all(sources, sf=sf, virtual=virtual)

    # Apply text filter
    if args.filter:
        q = args.filter.lower()
        hackathons = [h for h in hackathons if q in h.name.lower() or q in h.description.lower()]

    display(hackathons)

    # Print URLs if verbose
    if args.verbose:
        console.print()
        for h in hackathons:
            console.print(f"  [dim]{h.source:10}[/dim] {h.url}")


def main():
    parser = argparse.ArgumentParser(description="Find hackathons — SF in-person and virtual")
    parser.add_argument("--no-sf", action="store_true", help="Exclude SF in-person events")
    parser.add_argument("--no-virtual", action="store_true", help="Exclude virtual events")
    parser.add_argument("--source", type=str, help="Comma-separated sources (devpost,mlh,luma,eventbrite)")
    parser.add_argument("--filter", type=str, help="Filter by keyword in name/description")
    parser.add_argument("-v", "--verbose", action="store_true", help="Show event URLs")
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")
    args = parser.parse_args()

    if args.debug:
        logging.basicConfig(level=logging.DEBUG)
    else:
        logging.basicConfig(level=logging.WARNING)

    try:
        asyncio.run(_run(args))
    except KeyboardInterrupt:
        sys.exit(0)


if __name__ == "__main__":
    main()
