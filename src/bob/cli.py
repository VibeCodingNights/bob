"""CLI for Bob — hackathon discovery, analysis, team composition, and registration."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from rich.console import Console
from rich.table import Table

from bob.aggregator import fetch_all
from bob.models import Format, Hackathon
from bob.sources import ALL_SOURCES
from bob.validate import apply_corrections, validate_batch


console = Console()

_TIER_ICONS = {
    "triage": "[bold blue]triage[/]",
    "investigation": "[bold yellow]investigation[/]",
    "tokens": "[bold magenta]tokens[/]",
}


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


def _normalize_utc(dt: datetime) -> datetime:
    """Make a datetime UTC-aware; assume naive datetimes are already UTC."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _filter_by_date(
    hackathons: list[Hackathon],
    after: datetime | None,
    before: datetime | None,
) -> list[Hackathon]:
    """Exclude events whose start_date falls outside [after, before]. Events with no start_date are kept."""
    result = []
    for h in hackathons:
        if h.start_date is None:
            result.append(h)
            continue
        start = _normalize_utc(h.start_date)
        if after and start < after:
            continue
        if before and start > before:
            continue
        result.append(h)
    return result


def _to_json_obj(h: Hackathon) -> dict:
    return {
        "event_id": h.event_id,
        "name": h.name,
        "url": h.url,
        "source": h.source,
        "format": h.format.value,
        "location": h.location,
        "start_date": h.start_date.isoformat() if h.start_date else None,
        "end_date": h.end_date.isoformat() if h.end_date else None,
        "organizer": h.organizer or None,
        "registration_status": h.registration_status.value,
        "themes": h.themes,
        "prize_amount": h.prize_amount or None,
        "participants": h.participants,
    }


def display_json(hackathons: list[Hackathon]) -> None:
    print(json.dumps([_to_json_obj(h) for h in hackathons], indent=2))


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


def _progress_callback(tier: str, message: str) -> None:
    """Rich console output for validation progress."""
    icon = _TIER_ICONS.get(tier, f"[dim]{tier}[/]")
    console.print(f"  {icon}  {message}")


async def _run(args: argparse.Namespace) -> None:
    sources = [S() for S in ALL_SOURCES]

    # Filter to specific sources if requested
    if args.source:
        names = {s.strip().lower() for s in args.source.split(",")}
        sources = [s for s in sources if s.name in names]

    sf = not args.no_sf
    virtual = not args.no_virtual

    use_json = getattr(args, "json", False)
    do_validate = not args.no_validate

    if use_json:
        hackathons = await fetch_all(sources, sf=sf, virtual=virtual)
    else:
        with console.status("[bold]Fetching hackathons..."):
            hackathons = await fetch_all(sources, sf=sf, virtual=virtual)

    # Apply text filter
    if args.filter:
        q = args.filter.lower()
        hackathons = [h for h in hackathons if q in h.name.lower() or q in h.description.lower()]

    # Apply date range filters
    after_dt = _normalize_utc(datetime.strptime(args.after, "%Y-%m-%d")) if args.after else None
    before_dt = _normalize_utc(datetime.strptime(args.before, "%Y-%m-%d")) if args.before else None
    if after_dt or before_dt:
        hackathons = _filter_by_date(hackathons, after_dt, before_dt)

    # Validation layer (on by default)
    if do_validate:
        if not use_json:
            console.print(f"\n[bold]Validating {len(hackathons)} events...[/bold]")

        vresults = await validate_batch(
            hackathons,
            skip_curated=not args.no_skip_curated,
            model=args.model,
            on_progress=_progress_callback if not use_json else None,
        )
        before_count = len(hackathons)
        hackathons = apply_corrections(hackathons, vresults)
        rejected = before_count - len(hackathons)

        if not use_json:
            if rejected > 0:
                console.print(f"  [bold red]filtered[/]  {rejected} non-hackathon events removed")
            console.print(f"  [bold green]done[/]  {len(hackathons)} validated hackathons")

    # Apply limit (after all filters and sorting)
    if args.limit is not None:
        hackathons = hackathons[: args.limit]

    if use_json:
        display_json(hackathons)
        return

    display(hackathons)

    # Print URLs if verbose
    if args.verbose:
        console.print()
        for h in hackathons:
            console.print(f"  [dim]{h.source:10}[/dim] {h.url}")


async def _run_analyze(args: argparse.Namespace) -> None:
    from bob.situation import analyze

    hackathon = Hackathon(name="", url=args.url, source="manual")

    result = await analyze(
        hackathon,
        model=args.model,
        max_tool_calls=args.budget,
        map_root=args.map_root,
    )

    if args.json:
        print(json.dumps({
            "event_id": result.event_id,
            "map_root": result.map_root,
            "sections_written": result.sections_written,
            "summary": result.summary,
            "tracks_found": result.tracks_found,
            "confidence": result.confidence,
            "input_tokens": result.input_tokens,
            "output_tokens": result.output_tokens,
            "total_turns": result.total_turns,
        }, indent=2))
    else:
        print(f"\n{'='*60}")
        print(f"Situation Room Analysis Complete")
        print(f"{'='*60}")
        print(f"Event ID: {result.event_id}")
        print(f"Map root: {result.map_root}")
        print(f"Tracks found: {result.tracks_found}")
        print(f"Sections written: {len(result.sections_written)}")
        print(f"Confidence: {result.confidence:.0%}")
        print(f"Tokens: {result.input_tokens:,} input + {result.output_tokens:,} output")
        print(f"Total turns: {result.total_turns}")
        print(f"\nSummary:\n{result.summary}")
        print(f"\nSections:")
        for s in result.sections_written:
            print(f"  - {s}")
        print(f"\nFull analysis at: {result.map_root}")


def _resolve_map_root(url: str) -> str:
    """Compute the map_root for a hackathon URL (mirrors analyze default)."""
    h = Hackathon(name="", url=url, source="manual")
    return os.path.join(".", "events", h.event_id)


async def _run_team(args: argparse.Namespace) -> None:
    import dataclasses

    import yaml

    from bob.composer import compose_teams, portfolio_to_dict
    from bob.roster.store import RosterStore

    map_root = _resolve_map_root(args.url)
    strategy_path = os.path.join(map_root, "strategy.md")

    if not os.path.exists(strategy_path):
        console.print(
            f"[bold red]Error:[/] No Situation Room analysis found at {map_root}\n"
            f"Run `bob analyze {args.url}` first."
        )
        sys.exit(1)

    roster = RosterStore()
    plan = await compose_teams(
        event_url=args.url,
        map_root=map_root,
        roster=roster,
        model=args.model,
        max_turns=args.budget,
    )

    # Save portfolio for downstream use by register
    plan_path = os.path.join(map_root, "portfolio.yaml")
    with open(plan_path, "w") as f:
        yaml.safe_dump(portfolio_to_dict(plan), f, sort_keys=False, allow_unicode=True)

    if args.json:
        print(json.dumps(dataclasses.asdict(plan), indent=2))
        return

    if not plan.assignments:
        console.print("[dim]No track assignments produced.[/dim]")
        return

    table = Table(show_header=True, header_style="bold", show_lines=False, pad_edge=False)
    table.add_column("Track", style="bold white", max_width=30)
    table.add_column("Play Type", width=15)
    table.add_column("Presenter", max_width=20)
    table.add_column("Builder(s)", max_width=30)

    for a in plan.assignments:
        presenters = [m.member_id for m in a.team if m.role == "presenter"]
        builders = [m.member_id for m in a.team if m.role == "builder"]
        table.add_row(
            a.track_name,
            a.play_type,
            ", ".join(presenters) if presenters else "-",
            ", ".join(builders) if builders else "-",
        )

    console.print()
    console.print(table)
    console.print(f"\n[dim]{len(plan.assignments)} assignments, "
                  f"{len(plan.unassigned_tracks)} unassigned[/dim]")
    if plan.budget_notes:
        console.print(f"[dim]Notes: {plan.budget_notes}[/dim]")
    console.print(f"\n[dim]Portfolio saved to {plan_path}[/dim]")


async def _run_register(args: argparse.Namespace) -> None:
    import yaml

    from bob.accounts.registry import AccountRegistry
    from bob.composer import portfolio_from_dict
    from bob.platform_fields import PlatformFieldRegistry
    from bob.registration import register_teams
    from bob.roster.store import RosterStore

    map_root = _resolve_map_root(args.url)
    plan_path = os.path.join(map_root, "portfolio.yaml")

    if not os.path.exists(plan_path):
        console.print(
            f"[bold red]Error:[/] No portfolio plan found at {plan_path}\n"
            f"Run `bob team {args.url}` first."
        )
        sys.exit(1)

    with open(plan_path) as f:
        plan = portfolio_from_dict(yaml.safe_load(f))

    registry = AccountRegistry()
    roster = RosterStore()
    field_registry = PlatformFieldRegistry()

    # --- Pre-flight: profile gaps ---
    from bob.preflight import (
        check_registration_readiness,
        resolve_gaps_interactive,
    )

    gaps = check_registration_readiness(plan, roster, registry, field_registry)
    if gaps:
        console.print(f"\n[bold yellow]Pre-flight:[/] {len(gaps)} missing profile field(s)")
        resolved = resolve_gaps_interactive(gaps, roster)
        remaining = len(gaps) - resolved
        if remaining:
            console.print(
                f"[bold yellow]Warning:[/] {remaining} gap(s) still unresolved. "
                f"Registration may prompt for these during the run."
            )
        else:
            console.print("[green]All gaps resolved.[/green]")

    # --- Pre-flight: ensure accounts (signup + login) ---
    from bob.account_lifecycle import ensure_all_accounts
    from bob.auth_strategy import AuthStrategyRegistry

    auth_registry = AuthStrategyRegistry()

    console.print("\n[bold]Pre-flight:[/] Ensuring all accounts are ready...")
    headless = getattr(args, "headless", True)
    account_results = await ensure_all_accounts(
        portfolio=plan,
        roster=roster,
        registry=registry,
        field_registry=field_registry,
        headless=headless,
        model=args.model,
        auth_registry=auth_registry,
    )
    if account_results:
        console.print(f"[green]All {len(account_results)} account(s) ready.[/green]")
    else:
        console.print("[bold yellow]Warning:[/] No accounts were ensured.")

    report = await register_teams(
        portfolio=plan,
        hackathon_url=args.url,
        registry=registry,
        model=args.model,
        max_turns_per_registration=args.budget,
        max_concurrent=args.concurrency,
        roster=roster,
        field_registry=field_registry,
    )

    if args.json:
        print(json.dumps({
            "event_url": report.event_url,
            "results": [
                {
                    "track": r.task.track_assignment.track_name,
                    "success": r.success,
                    "confirmation_url": r.confirmation_url,
                    "screenshot_path": r.screenshot_path,
                    "error": r.error,
                }
                for r in report.results
            ],
            "total_turns": report.total_turns,
            "input_tokens": report.input_tokens,
            "output_tokens": report.output_tokens,
        }, indent=2))
        return

    if not report.results:
        console.print("[dim]No registration results.[/dim]")
        return

    table = Table(show_header=True, header_style="bold", show_lines=False, pad_edge=False)
    table.add_column("Track", style="bold white", max_width=30)
    table.add_column("Status", width=10)
    table.add_column("Confirmation", max_width=50)

    for r in report.results:
        if r.success:
            status = "[green]OK[/green]"
            detail = r.confirmation_url or "[dim]registered[/dim]"
        else:
            status = "[red]FAIL[/red]"
            detail = r.error or "unknown error"
        table.add_row(r.task.track_assignment.track_name, status, detail)

    console.print()
    console.print(table)

    succeeded = sum(1 for r in report.results if r.success)
    console.print(f"\n[dim]{succeeded}/{len(report.results)} registrations succeeded[/dim]")
    console.print(
        f"[dim]Tokens: {report.input_tokens:,} input + "
        f"{report.output_tokens:,} output[/dim]"
    )


async def _run_login(args: argparse.Namespace) -> None:
    from bob.accounts.registry import AccountRegistry
    from bob.login import login_account

    registry = AccountRegistry()
    account = registry.get_account(args.account_id)
    if account is None:
        console.print(f"[bold red]Error:[/] Account not found: {args.account_id}")
        accounts = registry.list_accounts()
        if accounts:
            console.print("\nAvailable accounts:")
            for a in accounts:
                console.print(f"  {a.account_id}  ({a.platform.value}, {a.username})")
        sys.exit(1)

    success = await login_account(
        account_id=args.account_id,
        registry=registry,
        headless=args.headless,
    )
    if not success:
        sys.exit(1)


async def _run_account(args: argparse.Namespace) -> None:
    from bob.accounts.registry import AccountRegistry

    registry = AccountRegistry()

    if args.account_action == "list":
        accounts = registry.list_accounts()
        if not accounts:
            console.print("[dim]No accounts found.[/dim]")
            return
        if getattr(args, "json", False):
            print(json.dumps([
                {
                    "account_id": a.account_id,
                    "platform": a.platform.value,
                    "username": a.username,
                    "member_id": a.member_id,
                    "status": a.status,
                    "last_login": a.last_login,
                }
                for a in accounts
            ], indent=2))
            return
        table = Table(show_header=True, header_style="bold", show_lines=False, pad_edge=False)
        table.add_column("Account ID", style="bold white", max_width=30)
        table.add_column("Platform", width=12)
        table.add_column("Username", max_width=20)
        table.add_column("Member", max_width=15)
        table.add_column("Status", width=12)
        for a in accounts:
            status = "[green]active[/]" if a.status == "active" else f"[yellow]{a.status}[/]"
            table.add_row(a.account_id, a.platform.value, a.username, a.member_id, status)
        console.print()
        console.print(table)
        console.print(f"\n[dim]{len(accounts)} accounts[/dim]")
        return

    if args.account_action == "setup-totp":
        import pyotp

        account = registry.get_account(args.account_id)
        if account is None:
            console.print(f"[bold red]Error:[/] Account not found: {args.account_id}")
            sys.exit(1)

        secret = input("Enter the TOTP secret (the text code shown alongside the QR code): ").strip()
        if not secret:
            console.print("[bold red]Error:[/] No secret provided.")
            sys.exit(1)

        totp_ref = f"{account.member_id}-{account.platform.value}-totp"
        registry._vault.store_credential(totp_ref, secret)

        code = pyotp.TOTP(secret).now()
        console.print(f"[green]TOTP configured for {args.account_id}. Current code: {code}[/green]")
        return

    if args.account_action == "ensure":
        from bob.account_lifecycle import ensure_account
        from bob.auth_strategy import AuthStrategyRegistry
        from bob.platform_fields import PlatformFieldRegistry
        from bob.roster.store import RosterStore

        roster = RosterStore()
        field_registry = PlatformFieldRegistry()
        auth_registry = AuthStrategyRegistry()

        console.print(f"Ensuring {args.platform} account for {args.member_id}...")
        account = await ensure_account(
            member_id=args.member_id,
            platform=args.platform,
            roster=roster,
            registry=registry,
            field_registry=field_registry,
            headless=getattr(args, "headless", False),
            cdp_endpoint=getattr(args, "cdp_endpoint", None),
            auth_registry=auth_registry,
        )
        if account:
            console.print(
                f"[green]Account ready:[/] {account.account_id} "
                f"({account.username}, status={account.status})"
            )
        else:
            console.print("[bold red]Failed to ensure account.[/bold red]")
            sys.exit(1)

    if args.account_action == "warm":
        from bob.profile_warming import warm_github_profile
        from bob.roster.store import RosterStore

        roster = RosterStore()

        account = registry.get_account(args.account_id)
        if account is None:
            console.print(f"[bold red]Error:[/] Account not found: {args.account_id}")
            accounts = registry.list_accounts()
            if accounts:
                console.print("\nAvailable accounts:")
                for a in accounts:
                    console.print(f"  {a.account_id}  ({a.platform.value}, {a.username})")
            sys.exit(1)

        if account.platform.value != "github":
            console.print(
                f"[bold red]Error:[/] Account {args.account_id} is not a GitHub account "
                f"(platform={account.platform.value}). Profile warming is GitHub-only."
            )
            sys.exit(1)

        console.print(f"Warming GitHub profile for {args.account_id}...")
        success = await warm_github_profile(
            account_id=args.account_id,
            roster=roster,
            registry=registry,
            model=getattr(args, "model", "claude-sonnet-4-6"),
        )
        if success:
            console.print("[green]Profile warming complete.[/green]")
        else:
            console.print("[bold red]Profile warming failed.[/bold red]")
            sys.exit(1)


async def _run_profile(args: argparse.Namespace) -> None:
    from rich.panel import Panel

    from bob.roster.store import RosterStore

    roster = RosterStore()

    # --list: show all members
    if args.list:
        members = roster.list_members()
        if not members:
            console.print("[dim]No members in roster.[/dim]")
            return
        if args.json:
            import dataclasses
            print(json.dumps([dataclasses.asdict(m) for m in members], indent=2))
            return
        table = Table(show_header=True, header_style="bold", show_lines=False, pad_edge=False)
        table.add_column("Member ID", style="bold white", max_width=20)
        table.add_column("Display Name", max_width=25)
        table.add_column("Skills", width=8, justify="right")
        table.add_column("Attributes", width=12, justify="right")
        for m in members:
            table.add_row(m.member_id, m.display_name, str(len(m.skills)), str(len(m.attributes)))
        console.print()
        console.print(table)
        console.print(f"\n[dim]{len(members)} members[/dim]")
        return

    # Require member_id for all other operations
    if not args.member_id:
        console.print("[bold red]Error:[/] Provide a member_id or use --list")
        return

    member = roster.load_member(args.member_id)

    # --set key=value
    if args.set:
        if member is None:
            console.print(f"[bold red]Error:[/] Member '{args.member_id}' not found")
            return
        for pair in args.set:
            if "=" not in pair:
                console.print(f"[bold red]Error:[/] Invalid format '{pair}' — use key=value")
                return
            key, value = pair.split("=", 1)
            member.attributes[key] = value
        roster.save_member(member)
        console.print(f"[green]Updated attributes for {args.member_id}[/green]")
        return

    # --delete key
    if args.delete:
        if member is None:
            console.print(f"[bold red]Error:[/] Member '{args.member_id}' not found")
            return
        for key in args.delete:
            if key in member.attributes:
                del member.attributes[key]
            else:
                console.print(f"[yellow]Warning:[/] Key '{key}' not found in attributes")
        roster.save_member(member)
        console.print(f"[green]Updated attributes for {args.member_id}[/green]")
        return

    # Show full profile
    if member is None:
        console.print(f"[bold red]Error:[/] Member '{args.member_id}' not found")
        return

    if args.json:
        import dataclasses
        print(json.dumps(dataclasses.asdict(member), indent=2))
        return

    lines = [
        f"[bold]Member ID:[/] {member.member_id}",
        f"[bold]Display Name:[/] {member.display_name}",
        f"[bold]Presentation Style:[/] {member.presentation_style.value}",
        f"[bold]Timezone:[/] {member.availability.timezone}",
        f"[bold]Commitment:[/] {member.availability.commitment}",
    ]

    if member.platform_account_ids:
        lines.append(f"[bold]Accounts:[/] {', '.join(member.platform_account_ids)}")

    if member.skills:
        skill_strs = [f"{s.name} ({s.domain}, depth {s.depth})" for s in member.skills]
        lines.append(f"[bold]Skills:[/] {', '.join(skill_strs)}")

    if member.interests:
        lines.append(f"[bold]Interests:[/] {', '.join(member.interests)}")

    if member.history:
        for h in member.history:
            lines.append(f"[bold]History:[/] {h.event_name} — {h.placement} ({h.role})")

    if member.attributes:
        lines.append("[bold]Attributes:[/]")
        for k, v in member.attributes.items():
            lines.append(f"  {k}: {v}")

    if member.availability.blackout_dates:
        lines.append(f"[bold]Blackout Dates:[/] {', '.join(member.availability.blackout_dates)}")

    if member.notes:
        lines.append(f"[bold]Notes:[/] {member.notes}")

    console.print()
    console.print(Panel("\n".join(lines), title=member.display_name, border_style="cyan"))


async def _run_logs(args: argparse.Namespace) -> None:
    from platformdirs import user_data_dir

    log_dir = Path(user_data_dir("bob")) / "logs"

    # --- Replay a specific file ---
    if args.session_file:
        path = Path(args.session_file)
        if not path.exists():
            # Try relative to log_dir
            path = log_dir / args.session_file
        if not path.exists():
            console.print(f"[bold red]Error:[/] File not found: {args.session_file}")
            sys.exit(1)
        _replay_session(path)
        return

    # --- Replay the most recent session ---
    if args.last:
        sessions = _list_session_files(log_dir)
        if not sessions:
            console.print("[dim]No log sessions found.[/dim]")
            return
        _replay_session(sessions[0])
        return

    # --- List sessions ---
    sessions = _list_session_files(log_dir)
    if not sessions:
        console.print("[dim]No log sessions found.[/dim]")
        return

    # Apply filters
    if args.agent:
        prefix = args.agent.lower()
        sessions = [s for s in sessions if _session_agent_name(s).lower().startswith(prefix)]

    if args.failed:
        sessions = [s for s in sessions if _session_has_errors(s)]

    if not args.all:
        sessions = sessions[:20]

    if not sessions:
        console.print("[dim]No matching sessions found.[/dim]")
        return

    table = Table(show_header=True, header_style="bold", show_lines=False, pad_edge=False)
    table.add_column("File", style="dim", max_width=45)
    table.add_column("Agent", style="cyan", max_width=30)
    table.add_column("Timestamp", style="dim", width=20)
    table.add_column("Turns", width=6, justify="right")
    table.add_column("Duration", width=10, justify="right")
    table.add_column("Status", width=8)

    for path in sessions:
        info = _session_summary(path)
        status = "[red]error[/]" if info["has_error"] else "[green]ok[/]"
        table.add_row(
            path.name,
            info["agent"],
            info["timestamp"],
            str(info["turns"]),
            info["duration"],
            status,
        )

    console.print()
    console.print(table)
    console.print(f"\n[dim]{len(sessions)} sessions[/dim]")


def _list_session_files(log_dir: Path) -> list[Path]:
    """List JSONL session files sorted by modification time (newest first)."""
    if not log_dir.is_dir():
        return []
    files = sorted(log_dir.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
    return files


def _read_events(path: Path) -> list[dict]:
    """Read all events from a JSONL session file."""
    events = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    return events


def _session_agent_name(path: Path) -> str:
    """Extract agent name from the first event in a session file."""
    events = _read_events(path)
    if events:
        return events[0].get("agent", "unknown")
    return "unknown"


def _session_has_errors(path: Path) -> bool:
    """Check if a session contains any error events."""
    events = _read_events(path)
    return any(e.get("event_type") == "error" for e in events)


def _session_summary(path: Path) -> dict:
    """Extract summary info from a session file."""
    events = _read_events(path)
    agent = events[0].get("agent", "unknown") if events else "unknown"
    timestamp = events[0].get("timestamp", "")[:19] if events else ""
    turns = max((e.get("turn", 0) for e in events), default=0) if events else 0
    has_error = any(e.get("event_type") == "error" for e in events)

    # Compute duration from first to last event timestamps
    duration = ""
    if len(events) >= 2:
        try:
            t0 = datetime.fromisoformat(events[0]["timestamp"])
            t1 = datetime.fromisoformat(events[-1]["timestamp"])
            secs = int((t1 - t0).total_seconds())
            mins, s = divmod(secs, 60)
            duration = f"{mins}m{s:02d}s" if mins else f"{s}s"
        except (KeyError, ValueError):
            pass

    return {
        "agent": agent,
        "timestamp": timestamp,
        "turns": turns,
        "has_error": has_error,
        "duration": duration,
    }


def _replay_session(path: Path) -> None:
    """Replay a session file with Rich formatting."""
    events = _read_events(path)
    if not events:
        console.print(f"[dim]Empty session: {path}[/dim]")
        return

    console.print(f"\n[bold]Replaying:[/] {path.name}")
    console.print(f"[dim]Agent: {events[0].get('agent', 'unknown')}[/dim]\n")

    # Compute relative timestamps from the first event
    try:
        t0 = datetime.fromisoformat(events[0]["timestamp"])
    except (KeyError, ValueError):
        t0 = None

    for event in events:
        turn = event.get("turn", 0)
        etype = event.get("event_type", "")
        data = event.get("data", {})

        # Relative time
        elapsed = ""
        if t0:
            try:
                t = datetime.fromisoformat(event["timestamp"])
                secs = int((t - t0).total_seconds())
                mins, s = divmod(secs, 60)
                elapsed = f"{mins:02d}:{s:02d}"
            except (KeyError, ValueError):
                elapsed = "??:??"
        else:
            elapsed = "??:??"

        if etype == "tool_call":
            tool = data.get("tool", "?")
            args = data.get("args", {})
            args_str = ", ".join(f"{k}={v!r}" for k, v in args.items())
            console.print(
                f"[dim]{elapsed}[/] Turn {turn} | [cyan]{tool}[/]({args_str})"
            )
        elif etype == "tool_result":
            tool = data.get("tool", "?")
            summary = data.get("summary", "")
            ms = data.get("duration_ms", 0)
            # Truncate summary for display
            display_summary = summary[:100]
            if len(summary) > 100:
                display_summary += "..."
            console.print(
                f'[dim]{elapsed}[/] Turn {turn} | [green]\u2192 "{display_summary}"[/] [dim]({ms}ms)[/]'
            )
        elif etype == "error":
            error_type = data.get("error_type", "")
            error_msg = data.get("error_msg", "")
            console.print(
                f"[dim]{elapsed}[/] Turn {turn} | [red]ERROR: {error_type}: {error_msg}[/]"
            )
        elif etype == "escalation":
            field = data.get("field", "")
            desc = data.get("description", "")
            console.print(
                f"[dim]{elapsed}[/] Turn {turn} | [yellow]ESCALATION: {field} \u2014 {desc}[/]"
            )
        elif etype == "message":
            role = data.get("role", "")
            content = data.get("content", "")[:100]
            console.print(
                f"[dim]{elapsed}[/] Turn {turn} | [dim]{role}: {content}[/]"
            )
        elif etype == "status":
            msg = data.get("message", "")
            console.print(
                f"[dim]{elapsed}[/] Turn {turn} | [blue]{msg}[/]"
            )

    console.print()


async def _run_plan(args: argparse.Namespace) -> None:
    console.print("Planner not yet implemented. Coming soon.")


# ---------------------------------------------------------------------------


def _add_discover_args(parser: argparse.ArgumentParser) -> None:
    """Add discover subcommand arguments to a parser."""
    parser.add_argument("--no-sf", action="store_true", help="Exclude SF in-person events")
    parser.add_argument("--no-virtual", action="store_true", help="Exclude virtual events")
    parser.add_argument("--source", type=str, help="Comma-separated sources (devpost,mlh,luma,eventbrite)")
    parser.add_argument("--filter", type=str, help="Filter by keyword in name/description")
    parser.add_argument("-v", "--verbose", action="store_true", help="Show event URLs")
    parser.add_argument("--json", action="store_true", help="Output results as JSON array")
    parser.add_argument("--limit", type=int, default=None, metavar="N", help="Show only first N results")
    parser.add_argument("--after", type=str, metavar="YYYY-MM-DD", help="Exclude events starting before this date")
    parser.add_argument("--before", type=str, metavar="YYYY-MM-DD", help="Exclude events starting after this date")
    parser.add_argument("--no-validate", action="store_true", help="Skip validation layer")
    parser.add_argument("--no-skip-curated", action="store_true", help="Investigate all events including curated sources")
    parser.add_argument(
        "--model", type=str, default="claude-haiku-4-5-20251001",
        help="Anthropic model for investigation (default: haiku)",
    )


def main():
    parser = argparse.ArgumentParser(description="Find hackathons — SF in-person and virtual")
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")

    subparsers = parser.add_subparsers(dest="command")

    # discover subcommand (default)
    discover_parser = subparsers.add_parser("discover", help="Discover upcoming hackathons")
    _add_discover_args(discover_parser)

    # analyze subcommand
    analyze_parser = subparsers.add_parser("analyze", help="Run Situation Room analysis on a hackathon URL")
    analyze_parser.add_argument("url", help="Hackathon event URL to analyze")
    analyze_parser.add_argument(
        "--model", type=str, default="claude-sonnet-4-6",
        help="Anthropic model ID (default: claude-sonnet-4-6)",
    )
    analyze_parser.add_argument("--budget", type=int, default=200, help="Safety limit for tool calls (default: 200)")
    analyze_parser.add_argument(
        "--map-root", type=str, default=None,
        help="Directory for semantic map output (default: ./events/<event_id>/)",
    )
    analyze_parser.add_argument("--json", action="store_true", help="Output JSON instead of rich text")

    # team subcommand
    team_parser = subparsers.add_parser("team", help="Run Team Composer to allocate members across tracks")
    team_parser.add_argument("url", help="Hackathon event URL (must have been analyzed first)")
    team_parser.add_argument(
        "--model", type=str, default="claude-sonnet-4-6",
        help="Anthropic model ID (default: claude-sonnet-4-6)",
    )
    team_parser.add_argument("--budget", type=int, default=20, help="Max agent turns (default: 20)")
    team_parser.add_argument("--json", action="store_true", help="Output JSON instead of rich text")

    # register subcommand
    register_parser = subparsers.add_parser("register", help="Register teams on hackathon platforms")
    register_parser.add_argument("url", help="Hackathon event URL (must have a portfolio plan)")
    register_parser.add_argument(
        "--model", type=str, default="claude-sonnet-4-6",
        help="Anthropic model ID (default: claude-sonnet-4-6)",
    )
    register_parser.add_argument("--budget", type=int, default=25, help="Max turns per registration (default: 25)")
    register_parser.add_argument(
        "--concurrency", type=int, default=2,
        help="Max concurrent browser registrations (default: 2)",
    )
    register_parser.add_argument("--json", action="store_true", help="Output JSON instead of rich text")
    register_parser.add_argument(
        "--force", action="store_true",
        help="Proceed even if some accounts are not logged in",
    )
    register_parser.add_argument(
        "--headless", action="store_true", default=True,
        help="Run account login browsers headlessly (default: True)",
    )

    # login subcommand
    login_parser = subparsers.add_parser("login", help="Interactively log in to a platform account")
    login_parser.add_argument("account_id", help="Account ID to log in (e.g. 'noot-devpost')")
    login_parser.add_argument(
        "--headless", action="store_true",
        help="Run browser in headless mode (default: visible for 2FA)",
    )

    # profile subcommand
    profile_parser = subparsers.add_parser("profile", help="View and edit member profiles")
    profile_parser.add_argument("member_id", nargs="?", default=None, help="Member ID to view or edit")
    profile_parser.add_argument("--list", action="store_true", help="List all members")
    profile_parser.add_argument("--set", nargs="+", metavar="key=value", help="Set attribute(s)")
    profile_parser.add_argument("--delete", nargs="+", metavar="key", help="Delete attribute(s)")
    profile_parser.add_argument("--json", action="store_true", help="Output as JSON")

    # account subcommand
    account_parser = subparsers.add_parser("account", help="Manage platform accounts")
    account_sub = account_parser.add_subparsers(dest="account_action")

    account_list_parser = account_sub.add_parser("list", help="List all platform accounts")
    account_list_parser.add_argument("--json", action="store_true", help="Output as JSON")

    account_ensure_parser = account_sub.add_parser(
        "ensure",
        help="Ensure a member has a working account (run github first for OAuth)",
    )
    account_ensure_parser.add_argument(
        "platform",
        help="Platform (github, devpost, ethglobal, luma, devfolio). Ensure github first — it enables OAuth on other platforms.",
    )
    account_ensure_parser.add_argument("member_id", help="Member ID")
    account_ensure_parser.add_argument(
        "--headless", action="store_true", default=True,
        help="Run browser headlessly (default: True)",
    )
    account_ensure_parser.add_argument(
        "--cdp-endpoint",
        help="Connect to an existing Chrome via CDP (e.g. http://localhost:9222). Zero automation artifacts.",
    )

    account_totp_parser = account_sub.add_parser("setup-totp", help="Configure TOTP for an account")
    account_totp_parser.add_argument("account_id", help="Account ID (e.g. 'noot-devpost')")

    account_warm_parser = account_sub.add_parser(
        "warm", help="Fill out a GitHub profile (name, bio, company, etc.)"
    )
    account_warm_parser.add_argument("account_id", help="GitHub account ID (e.g. 'noot-github')")
    account_warm_parser.add_argument(
        "--model", type=str, default="claude-sonnet-4-6",
        help="Anthropic model ID (default: claude-sonnet-4-6)",
    )

    # logs subcommand
    logs_parser = subparsers.add_parser("logs", help="List and replay agent session logs")
    logs_parser.add_argument("session_file", nargs="?", default=None, help="Replay a specific session JSONL file")
    logs_parser.add_argument("--last", action="store_true", help="Replay the most recent session")
    logs_parser.add_argument("--agent", type=str, default=None, help="Filter by agent name prefix")
    logs_parser.add_argument("--failed", action="store_true", help="Show only sessions with errors")
    logs_parser.add_argument("--all", action="store_true", help="Show all sessions (default: last 20)")

    # plan subcommand (placeholder)
    subparsers.add_parser("plan", help="Run Planner (coming soon)")

    # For backward compatibility: if no subcommand is given, add discover args to the
    # top-level parser so that bare `bob --json` etc. still work.
    _add_discover_args(parser)

    args = parser.parse_args()

    if args.debug:
        logging.basicConfig(level=logging.DEBUG)
    else:
        logging.basicConfig(level=logging.WARNING)

    # Default to discover behavior when no subcommand given
    if args.command is None or args.command == "discover":
        runner = _run(args)
    elif args.command == "analyze":
        runner = _run_analyze(args)
    elif args.command == "team":
        runner = _run_team(args)
    elif args.command == "register":
        runner = _run_register(args)
    elif args.command == "login":
        runner = _run_login(args)
    elif args.command == "profile":
        runner = _run_profile(args)
    elif args.command == "account":
        runner = _run_account(args)
    elif args.command == "logs":
        runner = _run_logs(args)
    elif args.command == "plan":
        runner = _run_plan(args)
    else:
        parser.print_help()
        sys.exit(1)

    try:
        asyncio.run(runner)
    except KeyboardInterrupt:
        sys.exit(0)


if __name__ == "__main__":
    main()
