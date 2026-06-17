import json
import subprocess
import sys
import os
from pathlib import Path
from datetime import datetime
from typing import Callable

PROFILES_DIR = Path(__file__).parent.parent / "config" / "profiles"
SCRIPTS_DIR = Path(__file__).parent.parent / "scripts"
ROLLBACK_DIR = Path(__file__).parent.parent / "data" / "rollbacks"

IS_WINDOWS = sys.platform == "win32"


class SettingsManager:
    def __init__(self, db, current_user):
        self.db = db
        self.current_user = current_user
        ROLLBACK_DIR.mkdir(parents=True, exist_ok=True)

    def load_profiles_from_disk(self):
        """Import all JSON profiles from config/profiles/ into database."""
        if not PROFILES_DIR.exists():
            return
        for p in PROFILES_DIR.glob("*.json"):
            try:
                data = json.loads(p.read_text())
                self.db.upsert_profile(
                    name=data.get("name", p.stem),
                    description=data.get("description", ""),
                    settings=data.get("settings", {}),
                )
            except Exception:
                pass

    def get_preview(self, profile_name: str) -> list[str]:
        """Return human-readable list of changes a profile will make."""
        row = self.db.get_profile(profile_name)
        if not row:
            return [f"Profile '{profile_name}' not found."]
        s = json.loads(row["settings_json"])
        lines = [f"=== Preview: {profile_name} ===", ""]
        lines += self._settings_to_lines(s)
        return lines

    def _settings_to_lines(self, s: dict) -> list[str]:
        lines = []
        pm = s.get("power_mode")
        if pm:
            lines.append(f"[Power]       Mode → {pm}")
        ve = s.get("visual_effects")
        if ve:
            lines.append(f"[Visual]      Effects → {ve}")
        sa = s.get("startup_apps", {})
        for app in sa.get("disable", []):
            lines.append(f"[Startup]     Disable → {app}")
        for app in sa.get("enable", []):
            lines.append(f"[Startup]     Enable  → {app}")
        tb = s.get("taskbar", {})
        if tb:
            for k, v in tb.items():
                lines.append(f"[Taskbar]     {k} → {v}")
        fe = s.get("file_explorer", {})
        if fe:
            for k, v in fe.items():
                lines.append(f"[Explorer]    {k} → {v}")
        notif = s.get("notifications", {})
        if notif:
            for k, v in notif.items():
                lines.append(f"[Notif]       {k} → {v}")
        wu = s.get("windows_update", {})
        if wu:
            for k, v in wu.items():
                lines.append(f"[WinUpdate]   {k} → {v}")
        net = s.get("network", {})
        if net:
            if net.get("disable_ipv6"):
                lines.append("[Network]     Disable IPv6")
            dns = net.get("dns_servers", [])
            if dns:
                lines.append(f"[Network]     DNS → {', '.join(dns)}")
        defender = s.get("defender", {})
        for path in defender.get("exclusion_paths", []):
            lines.append(f"[Defender]    Exclusion → {path}")
        return lines

    def apply_profile(self, profile_name: str,
                      progress_cb: Callable[[str], None] | None = None) -> tuple[bool, str]:
        row = self.db.get_profile(profile_name)
        if not row:
            return False, f"Profile '{profile_name}' not found."

        settings = json.loads(row["settings_json"])
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        rollback_file = ROLLBACK_DIR / f"rollback_{profile_name}_{timestamp}.json"

        def log(msg: str):
            if progress_cb:
                progress_cb(msg)

        log(f"Applying profile: {profile_name}")
        log(f"Rollback snapshot: {rollback_file.name}")

        if not IS_WINDOWS:
            log("[SIMULATION MODE — not Windows, no changes applied]")
            for line in self._settings_to_lines(settings):
                log(f"  WOULD: {line}")
            self.db.log_action(
                self.current_user.username, "apply_profile",
                {"profile": profile_name, "simulated": True},
                status="simulated",
            )
            return True, "Simulation complete (non-Windows host)."

        script_path = SCRIPTS_DIR / "apply_settings.ps1"
        profile_json_path = ROLLBACK_DIR / f"profile_{profile_name}_{timestamp}.json"
        profile_json_path.write_text(json.dumps({"name": profile_name, "settings": settings}, indent=2))

        args = [
            "powershell", "-ExecutionPolicy", "Bypass", "-File", str(script_path),
            "-ProfilePath", str(profile_json_path),
            "-BackupPath", str(rollback_file),
        ]

        try:
            result = subprocess.run(
                args, capture_output=True, text=True, timeout=120
            )
            for line in result.stdout.splitlines():
                log(line)
            if result.returncode != 0:
                for line in result.stderr.splitlines():
                    log(f"[ERR] {line}")
                self.db.log_action(
                    self.current_user.username, "apply_profile",
                    {"profile": profile_name, "error": result.stderr[:500]},
                    status="error",
                )
                return False, "PowerShell script returned errors."
            self.db.log_action(
                self.current_user.username, "apply_profile",
                {"profile": profile_name, "rollback_file": rollback_file.name},
            )
            return True, "Profile applied successfully."
        except subprocess.TimeoutExpired:
            return False, "Timed out waiting for PowerShell."
        except FileNotFoundError:
            return False, "PowerShell not found."

    def rollback(self, rollback_file: str,
                 progress_cb: Callable[[str], None] | None = None) -> tuple[bool, str]:
        path = ROLLBACK_DIR / rollback_file
        if not path.exists():
            return False, f"Rollback file not found: {rollback_file}"

        def log(msg):
            if progress_cb:
                progress_cb(msg)

        if not IS_WINDOWS:
            log("[SIMULATION MODE] Would rollback from: " + rollback_file)
            return True, "Simulation complete."

        script_path = SCRIPTS_DIR / "rollback_settings.ps1"
        args = [
            "powershell", "-ExecutionPolicy", "Bypass", "-File", str(script_path),
            "-BackupPath", str(path),
        ]
        try:
            result = subprocess.run(args, capture_output=True, text=True, timeout=120)
            for line in result.stdout.splitlines():
                log(line)
            if result.returncode != 0:
                return False, "Rollback script returned errors."
            self.db.log_action(
                self.current_user.username, "rollback",
                {"rollback_file": rollback_file},
            )
            return True, "Rollback applied successfully."
        except Exception as e:
            return False, str(e)

    def list_rollbacks(self) -> list[str]:
        if not ROLLBACK_DIR.exists():
            return []
        return sorted(
            [f.name for f in ROLLBACK_DIR.glob("rollback_*.json")],
            reverse=True,
        )
