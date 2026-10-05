"""Windows isolation for desktop Python steps: AppContainer + Job Object (Win32 API through ctypes).

What Windows enforces for every run:
  * AppContainer "Isocline.PythonSandbox" with NO capabilities. The process gets a separate low-privilege identity:
    it can open only objects whose permissions name that identity (or "ALL APPLICATION PACKAGES", which Windows grants
    to system folders such as C:\\Windows). Isocline grants it read/execute on the Python runtime and full access to
    the run's private work folder, nothing else. The user's files, Isocline's database and secrets are not readable.
  * No network: without the internetClient / privateNetworkClientServer capabilities the Windows firewall blocks all
    connections, and AppContainers cannot reach loopback (127.0.0.1) either, so not even Isocline's own API.
  * No child processes: PROCESS_CREATION_CHILD_PROCESS_RESTRICTED, plus a Job limit of one active process.
  * Job Object limits: memory per process, CPU time, wall-clock time (the job is terminated), UI restrictions
    (no clipboard, no desktop switching, no handles to other windows), and KILL_ON_JOB_CLOSE, so the process dies
    with Isocline even if Isocline crashes.
  * No inherited handles and a minimal environment block (see runner._env).
"""
from __future__ import annotations

import ctypes
import subprocess
import threading
import time
from ctypes import wintypes as wt
from pathlib import Path

from dataclasses import dataclass

from isocline.desktop.sandbox.runner import Outcome


@dataclass
class Protections:
    """All on in the app. The diagnostic (packaging/desktop/tests/diagnose_sandbox.py) switches them on one by one to
    find which one stops Python from starting on a given Windows version."""
    appcontainer: bool = True
    job_limits: bool = True
    ui_limits: bool = True
    child_policy: bool = True


PROTECTIONS = Protections()

PROFILE_NAME = "Isocline.PythonSandbox"

# ------------------------------------------------------------------------------------------------- Win32 constants
EXTENDED_STARTUPINFO_PRESENT = 0x00080000
CREATE_SUSPENDED = 0x00000004
CREATE_UNICODE_ENVIRONMENT = 0x00000400
DETACHED_PROCESS = 0x00000008  # no console at all: Windows would otherwise start a conhost.exe helper process
PROC_THREAD_ATTRIBUTE_SECURITY_CAPABILITIES = 0x00020009
PROC_THREAD_ATTRIBUTE_CHILD_PROCESS_POLICY = 0x0002000E
PROCESS_CREATION_CHILD_PROCESS_RESTRICTED = 0x01

JobObjectBasicUIRestrictions = 4
JobObjectExtendedLimitInformation = 9
JOB_OBJECT_LIMIT_PROCESS_TIME = 0x00000002
JOB_OBJECT_LIMIT_ACTIVE_PROCESS = 0x00000008
JOB_OBJECT_LIMIT_PROCESS_MEMORY = 0x00000100
JOB_OBJECT_LIMIT_DIE_ON_UNHANDLED_EXCEPTION = 0x00000400
JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
JOB_OBJECT_UILIMIT_ALL = 0x000000FF  # handles, clipboard read/write, system parameters, display, atoms, desktop, exit

WAIT_OBJECT_0 = 0x00000000
WAIT_TIMEOUT = 0x00000102

SE_FILE_OBJECT = 1
DACL_SECURITY_INFORMATION = 0x00000004
GRANT_ACCESS = 1
SUB_CONTAINERS_AND_OBJECTS_INHERIT = 0x3
TRUSTEE_IS_SID = 0
TRUSTEE_IS_UNKNOWN = 0
FILE_GENERIC_READ_EXECUTE = 0x001200A9  # FILE_GENERIC_READ | FILE_GENERIC_EXECUTE
FILE_ALL_ACCESS = 0x001F01FF

E_ALREADY_EXISTS = 0x800700B7  # HRESULT_FROM_WIN32(ERROR_ALREADY_EXISTS)
SE_DACL_PROTECTED = 0x1000  # security descriptor control bit: the folder does not inherit permissions


# ------------------------------------------------------------------------------------------------------ structures
class SECURITY_CAPABILITIES(ctypes.Structure):
    _fields_ = [("AppContainerSid", ctypes.c_void_p), ("Capabilities", ctypes.c_void_p),
                ("CapabilityCount", wt.DWORD), ("Reserved", wt.DWORD)]


class STARTUPINFOW(ctypes.Structure):
    _fields_ = [("cb", wt.DWORD), ("lpReserved", wt.LPWSTR), ("lpDesktop", wt.LPWSTR), ("lpTitle", wt.LPWSTR),
                ("dwX", wt.DWORD), ("dwY", wt.DWORD), ("dwXSize", wt.DWORD), ("dwYSize", wt.DWORD),
                ("dwXCountChars", wt.DWORD), ("dwYCountChars", wt.DWORD), ("dwFillAttribute", wt.DWORD),
                ("dwFlags", wt.DWORD), ("wShowWindow", wt.WORD), ("cbReserved2", wt.WORD),
                ("lpReserved2", ctypes.c_void_p), ("hStdInput", wt.HANDLE), ("hStdOutput", wt.HANDLE),
                ("hStdError", wt.HANDLE)]


class STARTUPINFOEXW(ctypes.Structure):
    _fields_ = [("StartupInfo", STARTUPINFOW), ("lpAttributeList", ctypes.c_void_p)]


class PROCESS_INFORMATION(ctypes.Structure):
    _fields_ = [("hProcess", wt.HANDLE), ("hThread", wt.HANDLE), ("dwProcessId", wt.DWORD), ("dwThreadId", wt.DWORD)]


class JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64),
                ("LimitFlags", wt.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wt.DWORD),
                ("Affinity", ctypes.c_size_t), ("PriorityClass", wt.DWORD), ("SchedulingClass", wt.DWORD)]


class IO_COUNTERS(ctypes.Structure):
    _fields_ = [(n, ctypes.c_uint64) for n in ("ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
                                               "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]


class JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [("BasicLimitInformation", JOBOBJECT_BASIC_LIMIT_INFORMATION), ("IoInfo", IO_COUNTERS),
                ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t)]


class JOBOBJECT_BASIC_UI_RESTRICTIONS(ctypes.Structure):
    _fields_ = [("UIRestrictionsClass", wt.DWORD)]


class TRUSTEE_W(ctypes.Structure):
    _fields_ = [("pMultipleTrustee", ctypes.c_void_p), ("MultipleTrusteeOperation", ctypes.c_int),
                ("TrusteeForm", ctypes.c_int), ("TrusteeType", ctypes.c_int), ("ptstrName", ctypes.c_void_p)]


class EXPLICIT_ACCESS_W(ctypes.Structure):
    _fields_ = [("grfAccessPermissions", wt.DWORD), ("grfAccessMode", ctypes.c_int),
                ("grfInheritance", wt.DWORD), ("Trustee", TRUSTEE_W)]


# ------------------------------------------------------------------------------------------------------- functions
_api = None


class _Api:
    def __init__(self):
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        adv = ctypes.WinDLL("advapi32", use_last_error=True)
        uenv = ctypes.WinDLL("userenv", use_last_error=True)

        def fn(dll, name, res, *args):
            f = getattr(dll, name)
            f.restype, f.argtypes = res, list(args)
            return f

        P, H, D, B = ctypes.c_void_p, wt.HANDLE, wt.DWORD, wt.BOOL
        self.CreateAppContainerProfile = fn(uenv, "CreateAppContainerProfile", ctypes.c_long,
                                            wt.LPCWSTR, wt.LPCWSTR, wt.LPCWSTR, P, D, ctypes.POINTER(P))
        self.DeriveAppContainerSidFromAppContainerName = fn(uenv, "DeriveAppContainerSidFromAppContainerName",
                                                            ctypes.c_long, wt.LPCWSTR, ctypes.POINTER(P))
        self.DeleteAppContainerProfile = fn(uenv, "DeleteAppContainerProfile", ctypes.c_long, wt.LPCWSTR)
        self.FreeSid = fn(adv, "FreeSid", P, P)
        self.ConvertSidToStringSidW = fn(adv, "ConvertSidToStringSidW", B, P, ctypes.POINTER(wt.LPWSTR))
        self.GetNamedSecurityInfoW = fn(adv, "GetNamedSecurityInfoW", D, wt.LPCWSTR, ctypes.c_int, D,
                                        P, P, ctypes.POINTER(P), P, ctypes.POINTER(P))
        self.SetEntriesInAclW = fn(adv, "SetEntriesInAclW", D, wt.ULONG, ctypes.POINTER(EXPLICIT_ACCESS_W), P,
                                   ctypes.POINTER(P))
        self.SetNamedSecurityInfoW = fn(adv, "SetNamedSecurityInfoW", D, wt.LPWSTR, ctypes.c_int, D, P, P, P, P)
        self.GetSecurityDescriptorControl = fn(adv, "GetSecurityDescriptorControl", B, P, ctypes.POINTER(wt.WORD),
                                               ctypes.POINTER(D))
        self.LocalFree = fn(k32, "LocalFree", P, P)
        self.InitializeProcThreadAttributeList = fn(k32, "InitializeProcThreadAttributeList", B, P, D, D,
                                                    ctypes.POINTER(ctypes.c_size_t))
        self.UpdateProcThreadAttribute = fn(k32, "UpdateProcThreadAttribute", B, P, D, ctypes.c_size_t, P,
                                            ctypes.c_size_t, P, P)
        self.DeleteProcThreadAttributeList = fn(k32, "DeleteProcThreadAttributeList", None, P)
        self.CreateProcessW = fn(k32, "CreateProcessW", B, wt.LPCWSTR, wt.LPWSTR, P, P, B, D, P, wt.LPCWSTR,
                                 ctypes.POINTER(STARTUPINFOEXW), ctypes.POINTER(PROCESS_INFORMATION))
        self.CreateJobObjectW = fn(k32, "CreateJobObjectW", H, P, wt.LPCWSTR)
        self.SetInformationJobObject = fn(k32, "SetInformationJobObject", B, H, ctypes.c_int, P, D)
        self.AssignProcessToJobObject = fn(k32, "AssignProcessToJobObject", B, H, H)
        self.TerminateJobObject = fn(k32, "TerminateJobObject", B, H, wt.UINT)
        self.ResumeThread = fn(k32, "ResumeThread", D, H)
        self.WaitForSingleObject = fn(k32, "WaitForSingleObject", D, H, D)
        self.GetExitCodeProcess = fn(k32, "GetExitCodeProcess", B, H, ctypes.POINTER(D))
        self.TerminateProcess = fn(k32, "TerminateProcess", B, H, wt.UINT)
        self.CloseHandle = fn(k32, "CloseHandle", B, H)


def api() -> _Api:
    global _api
    if _api is None:
        _api = _Api()
    return _api


def _check(ok, what: str):
    if not ok:
        raise OSError(ctypes.get_last_error(), f"{what} failed", None, ctypes.get_last_error())


# --------------------------------------------------------------------------------------------- AppContainer profile
_sid_lock = threading.Lock()
_sid: ctypes.c_void_p | None = None


def container_sid() -> ctypes.c_void_p:
    """SID of the Isocline AppContainer profile, created on first use (no administrator rights needed)."""
    global _sid
    with _sid_lock:
        if _sid is None:
            a, sid = api(), ctypes.c_void_p()
            hr = a.CreateAppContainerProfile(PROFILE_NAME, "Isocline Python sandbox",
                                             "Runs Python steps of Isocline workflows in isolation", None, 0,
                                             ctypes.byref(sid))
            if hr & 0xFFFFFFFF == E_ALREADY_EXISTS:
                hr = a.DeriveAppContainerSidFromAppContainerName(PROFILE_NAME, ctypes.byref(sid))
            if hr != 0:
                raise OSError(f"could not create the AppContainer profile (HRESULT 0x{hr & 0xFFFFFFFF:08X})")
            _sid = sid  # kept for the life of the process
        return _sid


def sid_string(sid) -> str:
    a, s = api(), wt.LPWSTR()
    _check(a.ConvertSidToStringSidW(sid, ctypes.byref(s)), "ConvertSidToStringSidW")
    try:
        return s.value
    finally:
        a.LocalFree(s)


def remove_profile() -> None:
    """Deletes the AppContainer profile (used by the uninstaller)."""
    api().DeleteAppContainerProfile(PROFILE_NAME)


def grant(path: Path, sid, access: int) -> None:
    """Adds an inheritable allow-ACE for the AppContainer to path (and, through inheritance, everything below it)."""
    a = api()
    old_dacl, sd = ctypes.c_void_p(), ctypes.c_void_p()
    rc = a.GetNamedSecurityInfoW(str(path), SE_FILE_OBJECT, DACL_SECURITY_INFORMATION, None, None,
                                 ctypes.byref(old_dacl), None, ctypes.byref(sd))
    if rc:
        raise OSError(rc, f"GetNamedSecurityInfo failed for {path}")
    try:
        ea = EXPLICIT_ACCESS_W()
        ea.grfAccessPermissions = access
        ea.grfAccessMode = GRANT_ACCESS
        ea.grfInheritance = SUB_CONTAINERS_AND_OBJECTS_INHERIT
        ea.Trustee.TrusteeForm = TRUSTEE_IS_SID
        ea.Trustee.TrusteeType = TRUSTEE_IS_UNKNOWN
        ea.Trustee.ptstrName = sid.value if isinstance(sid, ctypes.c_void_p) else sid
        new_dacl = ctypes.c_void_p()
        rc = a.SetEntriesInAclW(1, ctypes.byref(ea), old_dacl, ctypes.byref(new_dacl))
        if rc:
            raise OSError(rc, f"SetEntriesInAcl failed for {path}")
        try:
            rc = a.SetNamedSecurityInfoW(str(path), SE_FILE_OBJECT, DACL_SECURITY_INFORMATION, None, None,
                                         new_dacl, None)
            if rc:
                raise OSError(rc, f"SetNamedSecurityInfo failed for {path}")
        finally:
            a.LocalFree(new_dacl)
    finally:
        a.LocalFree(sd)


def inherits(path: Path) -> bool:
    """False if the folder's permissions are protected (inheritance switched off), so a grant on a parent folder does
    not reach it. Folders moved from a Python 3.13+ temporary directory (e.g. by pip) are like this."""
    a = api()
    dacl, sd = ctypes.c_void_p(), ctypes.c_void_p()
    rc = a.GetNamedSecurityInfoW(str(path), SE_FILE_OBJECT, DACL_SECURITY_INFORMATION, None, None,
                                 ctypes.byref(dacl), None, ctypes.byref(sd))
    if rc:
        raise OSError(rc, f"GetNamedSecurityInfo failed for {path}")
    try:
        control, revision = wt.WORD(), wt.DWORD()
        _check(a.GetSecurityDescriptorControl(sd, ctypes.byref(control), ctypes.byref(revision)),
               "GetSecurityDescriptorControl")
        return not (control.value & SE_DACL_PROTECTED)
    finally:
        a.LocalFree(sd)


def grant_tree(root: Path, sid, access: int) -> int:
    """grant() on root, plus on every folder below it that does not inherit. Returns the number of grants."""
    import os
    grant(root, sid, access)
    n = 1
    for dirpath, dirnames, _ in os.walk(root):
        for d in dirnames:
            p = Path(dirpath) / d
            if not inherits(p):
                grant(p, sid, access)
                n += 1
    return n


_runtime_lock = threading.Lock()
_granted: set[str] = set()  # stamps already applied by this process


def ensure_runtime_access(runtime_root: Path, sid, marker_dir: Path) -> None:
    """Read/execute on the Python runtime for the AppContainer, once per installation of the runtime.

    Installing for all users (Program Files) already grants this to ALL APPLICATION PACKAGES; the default per-user
    install does not, so Isocline adds it (the user owns that folder, no administrator rights needed). Granting
    propagates to every file below, which takes a few seconds the first time."""
    with _runtime_lock:
        exe = runtime_root / "python.exe"
        stamp = f"v2|{runtime_root}|{exe.stat().st_mtime_ns}|{sid_string(sid)}"
        if stamp in _granted:
            return
        marker = marker_dir / ".runtime-access"
        try:
            if marker.read_text(encoding="utf-8") == stamp:
                _granted.add(stamp)
                return
        except OSError:
            pass
        grant_tree(runtime_root, sid, FILE_GENERIC_READ_EXECUTE)
        marker_dir.mkdir(parents=True, exist_ok=True)
        marker.write_text(stamp, encoding="utf-8")
        _granted.add(stamp)


# ---------------------------------------------------------------------------------------------------------- launch
def _job(cpu_seconds: float, memory_mb: int, prot: Protections):
    a = api()
    job = a.CreateJobObjectW(None, None)
    _check(job, "CreateJobObject")
    info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
    b = info.BasicLimitInformation
    b.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE  # always: nothing outlives the run
    if prot.job_limits:
        b.LimitFlags |= (JOB_OBJECT_LIMIT_PROCESS_TIME | JOB_OBJECT_LIMIT_ACTIVE_PROCESS
                         | JOB_OBJECT_LIMIT_PROCESS_MEMORY | JOB_OBJECT_LIMIT_DIE_ON_UNHANDLED_EXCEPTION)
        b.PerProcessUserTimeLimit = int(cpu_seconds * 10_000_000)  # 100-ns units
        b.ActiveProcessLimit = 1
        info.ProcessMemoryLimit = memory_mb * 1024 * 1024
    _check(a.SetInformationJobObject(job, JobObjectExtendedLimitInformation, ctypes.byref(info), ctypes.sizeof(info)),
           "SetInformationJobObject(limits)")
    if prot.ui_limits:
        ui = JOBOBJECT_BASIC_UI_RESTRICTIONS(JOB_OBJECT_UILIMIT_ALL)
        _check(a.SetInformationJobObject(job, JobObjectBasicUIRestrictions, ctypes.byref(ui), ctypes.sizeof(ui)),
               "SetInformationJobObject(ui)")
    return job


def launch(argv: list[str], work: Path, env: dict[str, str], *, runtime_root: Path, wall_seconds: float,
           cpu_seconds: float, memory_mb: int) -> Outcome:
    a = api()
    prot = PROTECTIONS
    sid = container_sid()
    ensure_runtime_access(runtime_root, sid, work.parent)
    grant(work, sid, FILE_ALL_ACCESS)  # this run's folder only; other runs' folders stay unreadable

    caps = SECURITY_CAPABILITIES(AppContainerSid=sid.value, Capabilities=None, CapabilityCount=0)
    child_policy = wt.DWORD(PROCESS_CREATION_CHILD_PROCESS_RESTRICTED)
    n_attrs = int(prot.appcontainer) + int(prot.child_policy)
    size = ctypes.c_size_t(0)
    a.InitializeProcThreadAttributeList(None, max(n_attrs, 1), 0, ctypes.byref(size))  # sizing call: fails by design
    attrs = ctypes.create_string_buffer(size.value)
    _check(a.InitializeProcThreadAttributeList(attrs, max(n_attrs, 1), 0, ctypes.byref(size)),
           "InitializeProcThreadAttributeList")
    job = None
    pi = PROCESS_INFORMATION()
    try:
        if prot.appcontainer:
            _check(a.UpdateProcThreadAttribute(attrs, 0, PROC_THREAD_ATTRIBUTE_SECURITY_CAPABILITIES, ctypes.byref(caps),
                                               ctypes.sizeof(caps), None, None), "UpdateProcThreadAttribute(capabilities)")
        if prot.child_policy:
            _check(a.UpdateProcThreadAttribute(attrs, 0, PROC_THREAD_ATTRIBUTE_CHILD_PROCESS_POLICY,
                                               ctypes.byref(child_policy), ctypes.sizeof(child_policy), None, None),
                   "UpdateProcThreadAttribute(child process policy)")
        si = STARTUPINFOEXW()
        si.StartupInfo.cb = ctypes.sizeof(STARTUPINFOEXW)
        si.lpAttributeList = ctypes.cast(attrs, ctypes.c_void_p)
        env_block = ctypes.create_unicode_buffer("".join(f"{k}={v}\0" for k, v in sorted(env.items())) + "\0")
        cmdline = ctypes.create_unicode_buffer(subprocess.list2cmdline(argv))
        job = _job(cpu_seconds, memory_mb, prot)
        flags = EXTENDED_STARTUPINFO_PRESENT | CREATE_SUSPENDED | CREATE_UNICODE_ENVIRONMENT | DETACHED_PROCESS
        _check(a.CreateProcessW(argv[0], cmdline, None, None, False, flags, ctypes.cast(env_block, ctypes.c_void_p),
                                str(work), ctypes.byref(si), ctypes.byref(pi)), "CreateProcess (AppContainer)")
        # Into the job before the first instruction runs, so no limit can be raced.
        if not a.AssignProcessToJobObject(job, pi.hProcess):
            err = ctypes.get_last_error()
            a.TerminateProcess(pi.hProcess, 1)
            raise OSError(err, "AssignProcessToJobObject failed")
        a.ResumeThread(pi.hThread)
        start = time.monotonic()
        r = a.WaitForSingleObject(pi.hProcess, int(wall_seconds * 1000))
        elapsed = time.monotonic() - start
        if r == WAIT_TIMEOUT:
            a.TerminateJobObject(job, 1)
            a.WaitForSingleObject(pi.hProcess, 5000)
            return Outcome(None, True, elapsed)
        code = wt.DWORD()
        a.GetExitCodeProcess(pi.hProcess, ctypes.byref(code))
        # 1816 = ERROR_NOT_ENOUGH_QUOTA: the job's CPU time limit ended the process.
        return Outcome(code.value, code.value == 1816, elapsed)
    finally:
        for h in (pi.hThread, pi.hProcess):
            if h:
                a.CloseHandle(h)
        if job:
            a.CloseHandle(job)  # KILL_ON_JOB_CLOSE: nothing survives this point
        a.DeleteProcThreadAttributeList(attrs)
