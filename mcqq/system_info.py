"""Read-only host details for /状态情报."""
import platform
import shutil
import time
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


def cpu_times():
    with Path("/proc/stat").open() as stats:
        fields = stats.readline().split()
    if fields[0] != "cpu" or len(fields) < 9:
        raise ValueError("invalid CPU counters")
    counters = tuple(map(int, fields[1:9]))
    return sum(counters), counters[3] + counters[4]


def read_extra_metrics():
    try:
        first_total, first_idle = cpu_times()
        time.sleep(0.2)
        total, idle = cpu_times()
        elapsed = total - first_total
        idle_elapsed = idle - first_idle
        if elapsed <= 0 or not 0 <= idle_elapsed <= elapsed:
            raise ValueError("invalid CPU sample")
        cpu = f"{100 * (elapsed - idle_elapsed) / elapsed:.1f}%"
    except (OSError, ValueError, IndexError):
        cpu = "暂时无法读取"
    try:
        disk = shutil.disk_usage(Path.home())
        disk_space = f"{disk.free / 1024**3:.1f}/{disk.total / 1024**3:.1f} GiB"
    except OSError:
        disk_space = "暂时无法读取"
    return f"CPU 占用率：{cpu}\n硬碟剩余空间：{disk_space}"
