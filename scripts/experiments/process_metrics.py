"""Read-only Windows process counters for isolated experiments."""

import ctypes
from ctypes import wintypes


class Counters(ctypes.Structure):
    _fields_ = [('cb', wintypes.DWORD), ('PageFaultCount', wintypes.DWORD)] + [
        (name, ctypes.c_size_t) for name in (
            'PeakWorkingSetSize', 'WorkingSetSize', 'QuotaPeakPagedPoolUsage',
            'QuotaPagedPoolUsage', 'QuotaPeakNonPagedPoolUsage', 'QuotaNonPagedPoolUsage',
            'PagefileUsage', 'PeakPagefileUsage',
        )
    ]


def process_metrics(pid):
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.OpenProcess.restype = wintypes.HANDLE
    handle = kernel.OpenProcess(0x0410, False, pid)
    if not handle:
        raise OSError(ctypes.get_last_error(), 'cannot inspect experiment process')
    try:
        values = Counters()
        values.cb = ctypes.sizeof(values)
        if not ctypes.windll.psapi.GetProcessMemoryInfo(
            ctypes.c_void_p(handle), ctypes.byref(values), values.cb,
        ):
            raise OSError('process memory unavailable')
        times = [ctypes.c_ulonglong() for _ in range(4)]
        if not kernel.GetProcessTimes(ctypes.c_void_p(handle), *(ctypes.byref(t) for t in times)):
            raise OSError('process CPU unavailable')
        return dict(workingSetBytes=values.WorkingSetSize, privateBytes=values.PagefileUsage,
                    cpuSeconds=(times[2].value+times[3].value)/10**7)
    finally:
        kernel.CloseHandle(ctypes.c_void_p(handle))
