"""Read-only host details for /状态情报."""
import platform
from pathlib import Path


def format_system_info(os_name, kernel, uptime_seconds, total_kib, available_kib):
    days, remaining = divmod(int(uptime_seconds), 86400)
    hours = remaining // 3600
    used_kib = total_kib - available_kib
    return (f"【机器状态情报】\n系统：{os_name}\n内核：{kernel}"
            f"\n已运行：{days}天{hours}小时"
            f"\n内存：{used_kib / 1048576:.1f}/{total_kib / 1048576:.1f} GiB"
            f"（{used_kib / total_kib * 100:.0f}%）")


def read_system_info():
    try:
        os_name = platform.freedesktop_os_release().get("PRETTY_NAME", platform.system())
    except (OSError, AttributeError):
        os_name = platform.platform()
    uptime = float(Path("/proc/uptime").read_text().split()[0])
    memory = {}
    for line in Path("/proc/meminfo").read_text().splitlines():
        key, value = line.split(":", 1)
        if key in ("MemTotal", "MemAvailable"):
            memory[key] = int(value.strip().split()[0])
    total, available = memory["MemTotal"], memory["MemAvailable"]
    if total <= 0 or not 0 <= available <= total:
        raise ValueError("invalid host memory")
    return format_system_info(os_name, platform.release(), uptime, total, available)
