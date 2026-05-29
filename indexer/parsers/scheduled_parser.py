"""Scheduled task parser — extracts cron jobs, celery beat, Yii console commands."""

from __future__ import annotations

import re
from pathlib import Path
from tree_sitter import Language, Node

from parsers.base import BaseParser

# Crontab line: minute hour day month weekday command
CRON_PATTERN = re.compile(
    r"^(\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s+(.+)$"
)

# Laravel scheduler: $schedule->command('foo')->dailyAt('14:00')
LARAVEL_SCHEDULE = re.compile(
    r"""\$schedule\s*->\s*command\s*\(\s*['"]([^'"]+)['"]"""
    r"""(?:.*?->(\w+)\s*\(\s*['"]?([^'")\s]+)['"]?\s*\))?""",
    re.DOTALL,
)

# Celery beat: schedule=crontab(minute='*/5', hour='*')
CELERY_CRONTAB = re.compile(
    r"(\w+)\s*=\s*crontab\s*\(([^)]+)\)"
)

# Yii console command mapping: 'command/action' => ['class' => 'ClassName']
YII_CONSOLE_MAP = re.compile(
    r"""['"](\w+)/(\w+)['"]\s*=>\s*\[\s*['"]class['"]\s*=>\s*['"]([^'"]+)['"]"""
)


def _describe_schedule(minute, hour, day, month, weekday):
    parts = []
    if minute != "*":
        parts.append(f"min={minute}")
    if hour != "*":
        parts.append(f"hour={hour}")
    if day != "*":
        parts.append(f"day={day}")
    if weekday != "*":
        parts.append(f"dow={weekday}")
    return " ".join(parts) if parts else "every minute"


class ScheduledParser(BaseParser):
    """Parser for crontab files and scheduled task definitions."""

    language = None
    extensions = [".cron", ".crontab"]
    # Also match filenames
    filenames = {"crontab", "Cronfile", ".crontab"}

    def __init__(self):
        pass

    def parse(self, source_code: bytes, file_path: str) -> dict:
        text = source_code.decode("utf-8", errors="replace")
        filename = Path(file_path).name
        results = []

        # Crontab format
        if filename in ("crontab", "Cronfile", ".crontab") or file_path.endswith(".cron"):
            for line_no, line in enumerate(text.splitlines(), 1):
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                match = CRON_PATTERN.match(line)
                if not match:
                    continue
                minute, hour, day, month, weekday, command = match.groups()
                # Skip env variables (no @ or letters in minute field for cron)
                if any(c.isalpha() for c in minute) and minute != "@reboot":
                    continue
                schedule = _describe_schedule(minute, hour, day, month, weekday)
                results.append({
                    "name": command.strip()[:120],
                    "schedule": schedule,
                    "command": command.strip(),
                    "file": file_path,
                    "line": line_no,
                    "type": "cron",
                })

        # Yii console command config
        if "urlManager" not in text and ("command" in text.lower() or "console" in text.lower()):
            for match in YII_CONSOLE_MAP.finditer(text):
                controller, action, cls = match.group(1), match.group(2), match.group(3)
                line_no = text[:match.start()].count("\n") + 1
                results.append({
                    "name": f"{controller}/{action}",
                    "schedule": "on-demand",
                    "command": f"{controller} {action}",
                    "file": file_path,
                    "line": line_no,
                    "type": "yii_console",
                })

        # Laravel scheduler
        for match in LARAVEL_SCHEDULE.finditer(text):
            command = match.group(1)
            schedule_method = match.group(2) or "daily"
            schedule_arg = match.group(3) or ""
            line_no = text[:match.start()].count("\n") + 1
            results.append({
                "name": command,
                "schedule": f"{schedule_method}({schedule_arg})" if schedule_arg else schedule_method,
                "command": command,
                "file": file_path,
                "line": line_no,
                "type": "laravel",
            })

        return {
            "classes": [],
            "functions": [],
            "imports": [],
            "calls": [],
            "tables": [],
            "endpoints": [],
            "external_services": [],
            "framework_usage": [],
            "config_entries": [],
            "scheduled_tasks": results,
        }

    def _extract_classes(self, root, file_path, source):
        return []

    def _extract_functions(self, root, file_path, source):
        return []

    def _extract_imports(self, root, file_path, source):
        return []

    def _extract_calls(self, root, file_path, source):
        return []
