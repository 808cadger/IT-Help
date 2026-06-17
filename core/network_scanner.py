import socket
import subprocess
import sys
import ipaddress
import json
import concurrent.futures
from datetime import datetime
from typing import Callable

IS_WINDOWS = sys.platform == "win32"

try:
    import psutil
    PSUTIL_OK = True
except ImportError:
    PSUTIL_OK = False

try:
    import wmi as wmilib
    WMI_OK = True
except ImportError:
    WMI_OK = False


def _ping(ip: str) -> bool:
    if IS_WINDOWS:
        result = subprocess.run(
            ["ping", "-n", "1", "-w", "500", ip],
            capture_output=True,
        )
    else:
        result = subprocess.run(
            ["ping", "-c", "1", "-W", "1", ip],
            capture_output=True,
        )
    return result.returncode == 0


def _hostname(ip: str) -> str:
    try:
        return socket.gethostbyaddr(ip)[0]
    except Exception:
        return ip


def _local_device_info() -> dict:
    info = {
        "hostname": socket.gethostname(),
        "ip_address": socket.gethostbyname(socket.gethostname()),
        "cpu_model": "Unknown",
        "cores": 0,
        "ram_gb": 0.0,
        "disk_gb_free": 0.0,
        "disk_pct_used": 0.0,
        "os_version": sys.platform,
        "status": "online",
        "last_seen": datetime.now().isoformat(timespec="seconds"),
        "uptime_hours": 0.0,
        "cpu_pct": 0.0,
        "mem_pct": 0.0,
    }
    if PSUTIL_OK:
        import psutil
        mem = psutil.virtual_memory()
        info["ram_gb"] = round(mem.total / 1e9, 1)
        info["mem_pct"] = mem.percent
        info["cpu_pct"] = psutil.cpu_percent(interval=0.5)
        info["cores"] = psutil.cpu_count(logical=True) or 0
        try:
            disk = psutil.disk_usage("C:\\" if IS_WINDOWS else "/")
            info["disk_gb_free"] = round(disk.free / 1e9, 1)
            info["disk_pct_used"] = disk.percent
        except Exception:
            pass
        try:
            info["uptime_hours"] = round(
                (datetime.now().timestamp() - psutil.boot_time()) / 3600, 1
            )
        except Exception:
            pass
    if IS_WINDOWS:
        try:
            result = subprocess.run(
                ["powershell", "-Command",
                 "(Get-WmiObject Win32_Processor).Name"],
                capture_output=True, text=True, timeout=10,
            )
            cpu = result.stdout.strip()
            if cpu:
                info["cpu_model"] = cpu
        except Exception:
            pass
        try:
            result = subprocess.run(
                ["powershell", "-Command",
                 "(Get-WmiObject Win32_OperatingSystem).Caption"],
                capture_output=True, text=True, timeout=10,
            )
            os_ver = result.stdout.strip()
            if os_ver:
                info["os_version"] = os_ver
        except Exception:
            pass
    return info


def _remote_device_info(ip: str, username: str = "", password: str = "") -> dict:
    hostname = _hostname(ip)
    info = {
        "hostname": hostname,
        "ip_address": ip,
        "cpu_model": "Unknown",
        "cores": 0,
        "ram_gb": 0.0,
        "disk_gb_free": 0.0,
        "disk_pct_used": 0.0,
        "os_version": "Unknown",
        "status": "online",
        "last_seen": datetime.now().isoformat(timespec="seconds"),
        "uptime_hours": 0.0,
        "cpu_pct": 0.0,
        "mem_pct": 0.0,
    }
    if not IS_WINDOWS or not WMI_OK:
        return info
    try:
        conn_args = {"computer": ip}
        if username:
            conn_args["user"] = username
            conn_args["password"] = password
        w = wmilib.WMI(**conn_args)
        for cpu in w.Win32_Processor():
            info["cpu_model"] = cpu.Name.strip()
            info["cores"] = cpu.NumberOfLogicalProcessors or 0
        for mem in w.Win32_ComputerSystem():
            info["ram_gb"] = round(int(mem.TotalPhysicalMemory) / 1e9, 1)
        for os_ in w.Win32_OperatingSystem():
            info["os_version"] = os_.Caption
            free_mb = int(os_.FreePhysicalMemory) / 1024
            total_mb = info["ram_gb"] * 1024
            if total_mb:
                info["mem_pct"] = round((1 - free_mb / total_mb) * 100, 1)
            try:
                last_boot = os_.LastBootUpTime[:14]
                boot_dt = datetime.strptime(last_boot, "%Y%m%d%H%M%S")
                info["uptime_hours"] = round(
                    (datetime.now() - boot_dt).total_seconds() / 3600, 1
                )
            except Exception:
                pass
        for disk in w.Win32_LogicalDisk(DriveType=3):
            if disk.DeviceID == "C:":
                free = int(disk.FreeSpace or 0)
                total = int(disk.Size or 1)
                info["disk_gb_free"] = round(free / 1e9, 1)
                info["disk_pct_used"] = round((1 - free / total) * 100, 1)
    except Exception:
        pass
    return info


def _get_local_subnet() -> str | None:
    if not PSUTIL_OK:
        return None
    import psutil
    try:
        for iface, addrs in psutil.net_if_addrs().items():
            for addr in addrs:
                if addr.family == socket.AF_INET and not addr.address.startswith("127."):
                    net = ipaddress.IPv4Network(
                        f"{addr.address}/{addr.netmask}", strict=False
                    )
                    if net.prefixlen >= 24:
                        return str(net)
    except Exception:
        pass
    return None


class NetworkScanner:
    def __init__(self, db, current_user):
        self.db = db
        self.current_user = current_user

    def scan_local(self, progress_cb: Callable[[str], None] | None = None) -> list[dict]:
        def log(msg):
            if progress_cb:
                progress_cb(msg)

        devices = []
        log("Collecting local machine info...")
        local = _local_device_info()
        local["status"] = self._classify(local)
        devices.append(local)
        self.db.upsert_device(local)

        subnet = _get_local_subnet()
        if not subnet:
            log("Could not detect local subnet — skipping network sweep.")
            return devices

        log(f"Scanning subnet {subnet}...")
        network = ipaddress.IPv4Network(subnet)
        hosts = [str(h) for h in network.hosts()]
        local_ip = local["ip_address"]
        hosts = [h for h in hosts if h != local_ip]

        log(f"Pinging {len(hosts)} hosts (may take a moment)...")
        online_ips = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=50) as pool:
            futures = {pool.submit(_ping, ip): ip for ip in hosts}
            for fut in concurrent.futures.as_completed(futures):
                ip = futures[fut]
                if fut.result():
                    online_ips.append(ip)

        log(f"Found {len(online_ips)} additional online host(s).")

        for ip in online_ips:
            log(f"  Querying {ip}...")
            info = _remote_device_info(ip)
            info["status"] = self._classify(info)
            devices.append(info)
            self.db.upsert_device(info)

        self.db.log_action(
            self.current_user.username, "network_scan",
            {"subnet": subnet, "devices_found": len(devices)},
        )
        log(f"Scan complete. {len(devices)} device(s) recorded.")
        return devices

    def scan_single(self, ip: str, username: str = "", password: str = "",
                    progress_cb: Callable[[str], None] | None = None) -> dict | None:
        def log(msg):
            if progress_cb:
                progress_cb(msg)

        log(f"Pinging {ip}...")
        if not _ping(ip):
            log(f"{ip} did not respond to ping.")
            return None
        log(f"Querying {ip}...")
        info = _remote_device_info(ip, username, password)
        info["status"] = self._classify(info)
        self.db.upsert_device(info)
        log(f"Done. Hostname: {info['hostname']}")
        return info

    @staticmethod
    def _classify(d: dict) -> str:
        warnings = 0
        if d.get("disk_pct_used", 0) >= 90:
            warnings += 2
        elif d.get("disk_pct_used", 0) >= 75:
            warnings += 1
        if d.get("mem_pct", 0) >= 90:
            warnings += 2
        elif d.get("mem_pct", 0) >= 75:
            warnings += 1
        if d.get("cpu_pct", 0) >= 95:
            warnings += 1
        if warnings >= 3:
            return "critical"
        if warnings >= 1:
            return "warning"
        return "healthy"
