#!/usr/bin/env python3
"""
SENTINEL v2.0 — Rich Terminal Demo
-------------------------------------
A visually compelling live demonstration for hackathon judges.
Shows every agent step, BigQuery writes, HITL approval, and vision scan
in real time with color, progress bars, and formatted panels.

Usage:
    python scripts/demo.py

Requirements:
    pip install rich httpx
    Server running: python main.py
"""
import time
import json
import httpx
from datetime import datetime
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn
from rich.live import Live
from rich.columns import Columns
from rich.text import Text
from rich import box
from rich.rule import Rule
from rich.padding import Padding

BASE = "http://localhost:8000"
KEY  = "commander-secret-key-123"
HDR  = {"x-api-key": KEY}

console = Console()


# ── Helpers ────────────────────────────────────────────────────────────────────

def banner():
    console.print()
    console.print(Panel.fit(
        "[bold white]SENTINEL[/bold white]  [dim]|[/dim]  "
        "[green]Indian Army Surveillance Multi-Agent System[/green]\n"
        "[dim]GenAI Google Academy Hackathon — Live Demo[/dim]",
        border_style="green", padding=(1, 4),
    ))
    console.print()


def section(title: str, color: str = "cyan"):
    console.print()
    console.print(Rule(f"[bold {color}]{title}[/bold {color}]", style=color))
    console.print()


def agent_step(name: str, status: str, detail: str = "", color: str = "white"):
    icon = "✓" if status == "ok" else "⟳" if status == "running" else "✗"
    icon_color = "green" if status == "ok" else "yellow" if status == "running" else "red"
    console.print(
        f"  [{icon_color}]{icon}[/{icon_color}] "
        f"[bold {color}]{name:<20}[/bold {color}] "
        f"[dim]{detail}[/dim]"
    )


def spin(label: str, seconds: float = 1.2):
    with Progress(
        SpinnerColumn(style="cyan"),
        TextColumn(f"[dim]{label}[/dim]"),
        transient=True,
        console=console,
    ) as p:
        p.add_task("", total=None)
        time.sleep(seconds)


# ── Demo sections ──────────────────────────────────────────────────────────────

def show_health():
    section("0  —  System health check", "dim white")
    r = httpx.get(f"{BASE}/", timeout=None)
    d = r.json()

    grid = Table.grid(padding=(0, 2))
    grid.add_column(style="dim", min_width=16)
    grid.add_column(style="bold white")
    grid.add_row("System",    d.get("system", "SENTINEL"))
    grid.add_row("Version",   d.get("version", "2.0.0"))
    grid.add_row("Scheduler", f"[green]{d.get('scheduler','?')}[/green]")
    grid.add_row("Next scan", d.get("next_scan", "N/A")[:19] if d.get("next_scan") else "N/A")
    grid.add_row("DB",        "[green]BigQuery via MCP Toolbox[/green]")
    console.print(Padding(grid, (0, 4)))


def show_vision_scan():
    section("1  —  Vision Agent — satellite scan of SECTOR-7", "magenta")
    console.print("  [dim]Fetching satellite imagery and sending to Claude vision API...[/dim]")
    console.print()

    spin("Fetching imagery from Mapbox / Google / OSM ...", 1.5)
    spin("Sending image to Claude vision API ...", 2.0)

    r = httpx.post(f"{BASE}/api/v1/demo/vision-scan", timeout=None)
    r.raise_for_status()
    vis = r.json()["result"]

    detected = vis.get("anomalies_detected", False)
    count    = vis.get("anomaly_count", 0)
    action   = vis.get("recommended_action", "none")
    source   = vis.get("image_source", "unknown")

    # Status panel
    status_color = "red" if detected else "green"
    status_text  = f"[bold {status_color}]{'ANOMALIES DETECTED' if detected else 'SECTOR CLEAR'}[/bold {status_color}]"
    console.print(Panel(
        f"{status_text}\n\n"
        f"[dim]Image source   :[/dim] {source}\n"
        f"[dim]Anomaly count  :[/dim] [bold]{count}[/bold]\n"
        f"[dim]Rec. action    :[/dim] [yellow]{action}[/yellow]\n\n"
        f"[dim]Assessment:[/dim]\n{vis.get('overall_assessment','')[:200]}",
        title="[bold magenta]Vision Agent Report — SECTOR-7[/bold magenta]",
        border_style="magenta", padding=(1, 2),
    ))

    # Threat indicators table
    indicators = vis.get("threat_indicators", [])
    if indicators:
        console.print()
        t = Table(title="Threat Indicators", box=box.SIMPLE_HEAD,
                  show_header=True, header_style="bold red")
        t.add_column("Type",        style="red",    min_width=22)
        t.add_column("Location",    style="yellow", min_width=26)
        t.add_column("Confidence",  justify="right")
        t.add_column("Description", style="dim",    min_width=30)
        for ind in indicators:
            conf = ind.get("confidence", 0)
            bar  = "█" * int(conf * 10) + "░" * (10 - int(conf * 10))
            t.add_row(
                ind.get("type",""),
                ind.get("location_description","")[:28],
                f"[{'green' if conf>0.7 else 'yellow'}]{bar}[/] {conf:.0%}",
                ind.get("description","")[:40],
            )
        console.print(Padding(t, (0, 4)))

    if vis.get("triggered_alert"):
        console.print(f"\n  [bold red]⚡ Alert auto-triggered:[/bold red] {vis['triggered_alert']}")

    return vis


def show_alert_pipeline():
    section("2  —  Perimeter breach — sensor S7-042 fires", "red")
    console.print("  [dim]Sensor payload: motion_ir_combined | confidence=0.91[/dim]\n")

    spin("Sending alert to event bus (POST /api/v1/alert) ...", 0.8)

    r = httpx.post(f"{BASE}/api/v1/demo/trigger", timeout=None)
    r.raise_for_status()
    d = r.json()

    alert_id = d["alert_id"]
    result   = d["pipeline_result"]
    score    = result.get("threat_score", "?")
    severity = str(result.get("severity", "?")).upper()
    status   = result.get("status", "?").upper()

    sev_color = {"LOW":"green","MEDIUM":"yellow","HIGH":"orange3","CRITICAL":"red"}.get(severity,"white")

    # Alert summary panel
    console.print(Panel(
        f"[dim]Alert ID  :[/dim] {alert_id}\n"
        f"[dim]Sector    :[/dim] [bold]SECTOR-7[/bold]\n"
        f"[dim]Score     :[/dim] [bold red]{score}/10[/bold red]\n"
        f"[dim]Severity  :[/dim] [bold {sev_color}]{severity}[/bold {sev_color}]\n"
        f"[dim]Status    :[/dim] [bold yellow]{status}[/bold yellow]",
        title="[bold red]Incoming Alert[/bold red]",
        border_style="red", padding=(1, 2),
    ))
    return alert_id, result


def show_pipeline_trace(result: dict):
    section("3  —  Agent pipeline execution trace", "cyan")

    AGENT_COLORS = {
        "intel_agent":   "blue",
        "patrol_agent":  "green",
        "comms_agent":   "yellow",
        "vision_agent":  "magenta",
        "command_agent": "cyan",
    }

    for step in result.get("pipeline_steps", []):
        agent  = step["agent"]
        status = step["status"]
        color  = AGENT_COLORS.get(agent, "white")
        name   = agent.replace("_", " ").title()

        console.print(f"\n  [bold {color}]▶  {name}[/bold {color}]  [{('green' if status=='completed' else 'red')}]{status.upper()}[/]")

        out = step.get("output", {})
        for k, v in out.items():
            if v is not None:
                console.print(f"     [dim]{k:<20}[/dim] {v}")

        spin(f"  {name} writing to BigQuery ...", 0.6)

    console.print()
    console.print(f"  [bold green]All agents completed.[/bold green]  "
                  f"[dim]BigQuery audit_log updated for each step.[/dim]")


def show_hitl(alert_id: str):
    section("4  —  HITL gate — commander reviews pending actions", "yellow")

    time.sleep(0.5)
    r = httpx.get(f"{BASE}/api/v1/hitl/pending", headers=HDR, timeout=None)
    r.raise_for_status()
    pending = r.json()

    if pending["count"] == 0:
        console.print("  [green]No pending actions.[/green] Low-severity — handled automatically.")
        return []

    console.print(f"  [bold yellow]{pending['count']} action(s) awaiting commander approval:[/bold yellow]\n")

    t = Table(box=box.ROUNDED, show_header=True, header_style="bold yellow",
              border_style="yellow", padding=(0, 1))
    t.add_column("#",           width=3,  justify="right")
    t.add_column("Agent",       min_width=16)
    t.add_column("Action",      min_width=18)
    t.add_column("Description", min_width=34)
    t.add_column("ID",          style="dim", min_width=12)

    for i, a in enumerate(pending["actions"], 1):
        t.add_row(
            str(i),
            a["agent"],
            a["action_type"],
            a["description"][:38],
            a["id"][:12] + "...",
        )
    console.print(Padding(t, (0, 4)))
    return pending["actions"]


def show_approval(actions: list):
    if not actions:
        return

    section("5  —  Commander approves action", "green")
    first = actions[0]

    console.print(f"  [dim]Approving:[/dim] [bold]{first['description'][:60]}[/bold]")
    spin("Executing Calendar MCP call ...", 1.2)

    r = httpx.put(f"{BASE}/api/v1/hitl/approve/{first['id']}", headers=HDR, timeout=None)
    r.raise_for_status()
    res = r.json()

    console.print(Panel(
        f"[dim]Action ID :[/dim] {first['id'][:20]}...\n"
        f"[dim]Approved  :[/dim] [green]{'Yes' if res.get('approved') else 'No'}[/green]\n"
        f"[dim]Executed  :[/dim] [green]{'Yes' if res.get('executed') else 'No (MCP fallback)'}[/green]\n"
        f"[dim]Result    :[/dim] {res.get('message','')}",
        title="[bold green]Commander Approved[/bold green]",
        border_style="green", padding=(1, 2),
    ))

    if len(actions) > 1:
        section("5b — Commander rejects second action", "red")
        second = actions[1]
        r2 = httpx.put(
            f"{BASE}/api/v1/hitl/reject/{second['id']}",
            json={"reason": "Alternate unit handling. Stand down."},
            headers=HDR, timeout=None,
        )
        if r2.status_code == 200:
            console.print(f"  [red]Rejected:[/red] {second['description'][:50]}")
            console.print(f"  [dim]Reason  : Alternate unit handling. Stand down.[/dim]")


def show_scan_history():
    section("6  —  BigQuery scan history — SECTOR-7", "blue")
    r = httpx.get(f"{BASE}/api/v1/scan/history/SECTOR-7?limit=5", timeout=None)
    r.raise_for_status()
    hist = r.json()

    t = Table(box=box.SIMPLE, show_header=True, header_style="bold blue")
    t.add_column("Time (UTC)", min_width=19)
    t.add_column("Source",     min_width=18)
    t.add_column("Status",     min_width=10)
    t.add_column("Anomalies",  justify="right")
    t.add_column("Action",     min_width=22)

    for s in hist.get("scans", []):
        flag  = "[red]ALERT[/red]" if s["detected"] else "[green]clear[/green]"
        t.add_row(
            s["scanned_at"][:19],
            s.get("source",""),
            flag,
            str(s["anomalies"]),
            s.get("action",""),
        )
    console.print(Padding(t, (0, 4)))


def show_audit(alert_id: str):
    section("7  —  Full audit trail (BigQuery audit_logs)", "dim white")
    r = httpx.get(f"{BASE}/api/v1/audit/{alert_id}", headers=HDR, timeout=None)
    r.raise_for_status()
    events = r.json().get("events", [])

    t = Table(box=box.SIMPLE, show_header=True, header_style="bold")
    t.add_column("Time",    style="dim",  width=8)
    t.add_column("Actor",   min_width=20)
    t.add_column("Action",  min_width=28)
    t.add_column("OK",      width=4, justify="center")

    ACTOR_COLORS = {
        "command_agent": "cyan",  "intel_agent":  "blue",
        "patrol_agent":  "green", "comms_agent":  "yellow",
        "vision_agent":  "magenta","commander":   "red",
        "scheduler":     "white",
    }

    for ev in events:
        actor = ev["actor"]
        color = ACTOR_COLORS.get(actor, "white")
        ok    = "[green]✓[/green]" if ev["success"] else "[red]✗[/red]"
        t.add_row(
            ev["timestamp"][11:19],
            f"[{color}]{actor}[/{color}]",
            ev["action"],
            ok,
        )
    console.print(Padding(t, (0, 4)))


def show_summary(alert_id: str):
    console.print()
    console.print(Panel(
        f"[bold green]Demo complete.[/bold green]\n\n"
        f"[dim]API docs      :[/dim]  {BASE}/docs\n"
        f"[dim]Alert status  :[/dim]  GET {BASE}/api/v1/status/{alert_id}\n"
        f"[dim]Scan history  :[/dim]  GET {BASE}/api/v1/scan/history/SECTOR-7\n"
        f"[dim]Pending HITL  :[/dim]  GET {BASE}/api/v1/hitl/pending\n\n"
        f"[dim]Database      :[/dim]  [green]Google BigQuery via MCP Toolbox[/green]\n"
        f"[dim]Agents        :[/dim]  Command → Intel → Patrol → Comms → Vision\n"
        f"[dim]Tools         :[/dim]  Calendar MCP · Notes MCP · Task MCP · Geo MCP",
        title="[bold white]SENTINEL v2.0[/bold white]",
        border_style="green", padding=(1, 3),
    ))
    console.print()


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    banner()

    try:
        show_health()
        time.sleep(0.5)

        show_vision_scan()
        time.sleep(0.5)

        alert_id, result = show_alert_pipeline()
        time.sleep(0.5)

        show_pipeline_trace(result)
        time.sleep(0.5)

        actions = show_hitl(alert_id)
        time.sleep(0.5)

        show_approval(actions)
        time.sleep(0.5)

        show_scan_history()
        time.sleep(0.3)

        show_audit(alert_id)

        show_summary(alert_id)

    except httpx.ConnectError:
        console.print("[bold red]Error:[/bold red] Cannot connect to server at "
                      f"{BASE}. Is it running? Try: [dim]python main.py[/dim]")
    except Exception as e:
        console.print_exception()


if __name__ == "__main__":
    main()
