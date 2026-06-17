import subprocess
import sys
from pathlib import Path

IS_WINDOWS = sys.platform == "win32"
SCRIPTS_DIR = Path(__file__).parent.parent / "scripts"

ACCESS_LEVELS = ["FullControl", "Modify", "ReadAndExecute", "Read", "Write", "NoAccess"]


class PermissionsManager:
    def __init__(self, db, current_user):
        self.db = db
        self.current_user = current_user

    def apply_permission(self, target_name: str, resource_path: str,
                         access_level: str, progress_cb=None) -> tuple[bool, str]:
        def log(msg):
            if progress_cb:
                progress_cb(msg)

        log(f"Applying {access_level} on '{resource_path}' for '{target_name}'")

        if not IS_WINDOWS:
            log("[SIMULATION MODE — not Windows]")
            self.db.add_permission(target_name, resource_path, access_level, self.current_user.id)
            self.db.log_action(
                self.current_user.username, "set_permission",
                {"target": target_name, "path": resource_path,
                 "level": access_level, "simulated": True},
                status="simulated",
            )
            return True, "Simulation complete."

        script = SCRIPTS_DIR / "set_permissions.ps1"
        args = [
            "powershell", "-ExecutionPolicy", "Bypass", "-File", str(script),
            "-TargetName", target_name,
            "-ResourcePath", resource_path,
            "-AccessLevel", access_level,
        ]
        try:
            result = subprocess.run(args, capture_output=True, text=True, timeout=60)
            for line in result.stdout.splitlines():
                log(line)
            if result.returncode != 0:
                for line in result.stderr.splitlines():
                    log(f"[ERR] {line}")
                self.db.log_action(
                    self.current_user.username, "set_permission",
                    {"target": target_name, "path": resource_path,
                     "level": access_level, "error": result.stderr[:300]},
                    status="error",
                )
                return False, "Permission script returned errors."
            self.db.add_permission(target_name, resource_path, access_level, self.current_user.id)
            self.db.log_action(
                self.current_user.username, "set_permission",
                {"target": target_name, "path": resource_path, "level": access_level},
            )
            return True, "Permission applied."
        except Exception as e:
            return False, str(e)

    def revoke_permission(self, perm_id: int) -> tuple[bool, str]:
        perms = self.db.list_permissions()
        target = next((p for p in perms if p["id"] == perm_id), None)
        if not target:
            return False, "Permission record not found."
        self.db.delete_permission(perm_id)
        self.db.log_action(
            self.current_user.username, "revoke_permission",
            {"target": target["target_name"], "path": target["resource_path"],
             "level": target["access_level"]},
        )
        return True, "Permission record removed."

    def query_acl(self, resource_path: str) -> list[str]:
        if not IS_WINDOWS:
            return ["[SIMULATION] ACL query not available on non-Windows."]
        try:
            result = subprocess.run(
                ["powershell", "-Command",
                 f"(Get-Acl '{resource_path}').Access | "
                 f"Select-Object IdentityReference, FileSystemRights, AccessControlType | "
                 f"Format-Table -AutoSize | Out-String"],
                capture_output=True, text=True, timeout=30,
            )
            return result.stdout.splitlines()
        except Exception as e:
            return [str(e)]
