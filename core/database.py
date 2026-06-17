import sqlite3
import json
from pathlib import Path
from datetime import datetime
from contextlib import contextmanager


DB_PATH = Path(__file__).parent.parent / "data" / "it_manager.db"


class Database:
    def __init__(self, path: Path = DB_PATH):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def conn(self):
        c = sqlite3.connect(self.path)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA foreign_keys = ON")
        try:
            yield c
            c.commit()
        except Exception:
            c.rollback()
            raise
        finally:
            c.close()

    def initialize(self):
        with self.conn() as c:
            c.executescript("""
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT UNIQUE NOT NULL,
                    email TEXT,
                    role TEXT NOT NULL DEFAULT 'Standard_User',
                    password_hash TEXT NOT NULL,
                    created_at TEXT DEFAULT (datetime('now'))
                );

                CREATE TABLE IF NOT EXISTS devices (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    hostname TEXT,
                    cpu_model TEXT,
                    cores INTEGER,
                    ram_gb REAL,
                    disk_gb_free REAL,
                    disk_pct_used REAL,
                    os_version TEXT,
                    ip_address TEXT UNIQUE,
                    status TEXT DEFAULT 'unknown',
                    last_seen TEXT,
                    uptime_hours REAL,
                    cpu_pct REAL,
                    mem_pct REAL
                );

                CREATE TABLE IF NOT EXISTS settings_profiles (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT UNIQUE NOT NULL,
                    description TEXT,
                    settings_json TEXT NOT NULL,
                    created_at TEXT DEFAULT (datetime('now')),
                    modified_at TEXT DEFAULT (datetime('now'))
                );

                CREATE TABLE IF NOT EXISTS permissions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    target_name TEXT NOT NULL,
                    resource_path TEXT NOT NULL,
                    access_level TEXT NOT NULL,
                    applied_by INTEGER REFERENCES users(id),
                    created_at TEXT DEFAULT (datetime('now'))
                );

                CREATE TABLE IF NOT EXISTS change_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    device_hostname TEXT,
                    username TEXT,
                    action_type TEXT NOT NULL,
                    details_json TEXT,
                    status TEXT DEFAULT 'success',
                    timestamp TEXT DEFAULT (datetime('now'))
                );
            """)

    # --- Users ---
    def get_user(self, username: str) -> sqlite3.Row | None:
        with self.conn() as c:
            return c.execute(
                "SELECT * FROM users WHERE username = ?", (username,)
            ).fetchone()

    def create_user(self, username: str, email: str, role: str, password_hash: str):
        with self.conn() as c:
            c.execute(
                "INSERT INTO users (username, email, role, password_hash) VALUES (?,?,?,?)",
                (username, email, role, password_hash),
            )

    def list_users(self) -> list[sqlite3.Row]:
        with self.conn() as c:
            return c.execute("SELECT * FROM users ORDER BY username").fetchall()

    def update_user_role(self, user_id: int, role: str):
        with self.conn() as c:
            c.execute("UPDATE users SET role = ? WHERE id = ?", (role, user_id))

    def delete_user(self, user_id: int):
        with self.conn() as c:
            c.execute("DELETE FROM users WHERE id = ?", (user_id,))

    # --- Devices ---
    def upsert_device(self, device: dict):
        with self.conn() as c:
            c.execute("""
                INSERT INTO devices
                    (hostname, cpu_model, cores, ram_gb, disk_gb_free, disk_pct_used,
                     os_version, ip_address, status, last_seen, uptime_hours, cpu_pct, mem_pct)
                VALUES
                    (:hostname, :cpu_model, :cores, :ram_gb, :disk_gb_free, :disk_pct_used,
                     :os_version, :ip_address, :status, :last_seen, :uptime_hours, :cpu_pct, :mem_pct)
                ON CONFLICT(ip_address) DO UPDATE SET
                    hostname=excluded.hostname,
                    cpu_model=excluded.cpu_model,
                    cores=excluded.cores,
                    ram_gb=excluded.ram_gb,
                    disk_gb_free=excluded.disk_gb_free,
                    disk_pct_used=excluded.disk_pct_used,
                    os_version=excluded.os_version,
                    status=excluded.status,
                    last_seen=excluded.last_seen,
                    uptime_hours=excluded.uptime_hours,
                    cpu_pct=excluded.cpu_pct,
                    mem_pct=excluded.mem_pct
            """, device)

    def list_devices(self) -> list[sqlite3.Row]:
        with self.conn() as c:
            return c.execute("SELECT * FROM devices ORDER BY hostname").fetchall()

    def delete_device(self, device_id: int):
        with self.conn() as c:
            c.execute("DELETE FROM devices WHERE id = ?", (device_id,))

    # --- Profiles ---
    def upsert_profile(self, name: str, description: str, settings: dict):
        with self.conn() as c:
            c.execute("""
                INSERT INTO settings_profiles (name, description, settings_json, modified_at)
                VALUES (?, ?, ?, datetime('now'))
                ON CONFLICT(name) DO UPDATE SET
                    description=excluded.description,
                    settings_json=excluded.settings_json,
                    modified_at=excluded.modified_at
            """, (name, description, json.dumps(settings)))

    def list_profiles(self) -> list[sqlite3.Row]:
        with self.conn() as c:
            return c.execute("SELECT * FROM settings_profiles ORDER BY name").fetchall()

    def get_profile(self, name: str) -> sqlite3.Row | None:
        with self.conn() as c:
            return c.execute(
                "SELECT * FROM settings_profiles WHERE name = ?", (name,)
            ).fetchone()

    # --- Permissions ---
    def add_permission(self, target_name: str, resource_path: str,
                       access_level: str, applied_by: int):
        with self.conn() as c:
            c.execute("""
                INSERT INTO permissions (target_name, resource_path, access_level, applied_by)
                VALUES (?, ?, ?, ?)
            """, (target_name, resource_path, access_level, applied_by))

    def list_permissions(self) -> list[sqlite3.Row]:
        with self.conn() as c:
            return c.execute("""
                SELECT p.*, u.username as applied_by_name
                FROM permissions p
                LEFT JOIN users u ON p.applied_by = u.id
                ORDER BY p.created_at DESC
            """).fetchall()

    def delete_permission(self, perm_id: int):
        with self.conn() as c:
            c.execute("DELETE FROM permissions WHERE id = ?", (perm_id,))

    # --- Audit Logs ---
    def log_action(self, username: str, action_type: str,
                   details: dict, device_hostname: str = "", status: str = "success"):
        with self.conn() as c:
            c.execute("""
                INSERT INTO change_logs (device_hostname, username, action_type, details_json, status)
                VALUES (?, ?, ?, ?, ?)
            """, (device_hostname, username, action_type, json.dumps(details), status))

    def get_logs(self, limit: int = 500) -> list[sqlite3.Row]:
        with self.conn() as c:
            return c.execute("""
                SELECT * FROM change_logs ORDER BY timestamp DESC LIMIT ?
            """, (limit,)).fetchall()
