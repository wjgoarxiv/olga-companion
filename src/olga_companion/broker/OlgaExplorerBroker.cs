using System;
using System.Diagnostics;
using System.IO;
using System.Runtime.InteropServices;
using System.Text;

internal static partial class OlgaExplorerBroker
{
    private sealed class Request
    {
        public string protocol { get; set; }
        public string token { get; set; }
        public string request_id { get; set; }
        public string expires_utc { get; set; }
        public string run_dir { get; set; }
        public string engine { get; set; }
        public string engine_sha256 { get; set; }
        public string broker_sha256 { get; set; }
        public string staged_case { get; set; }
        public string staged_case_sha256 { get; set; }
        public string[] argv { get; set; }
        public int timeout_s { get; set; }
    }

    private sealed class CancelRequest
    {
        public string protocol { get; set; }
        public string request_id { get; set; }
        public string reason { get; set; }
    }

    public static int Main()
    {
        string baseDir = Path.GetFullPath(AppDomain.CurrentDomain.BaseDirectory.TrimEnd(Path.DirectorySeparatorChar));
        string requestPath = Path.Combine(baseDir, RequestName);
        string claimedPath = Path.Combine(baseDir, ClaimedName);
        string statusPath = Path.Combine(baseDir, StatusName);
        Request request = null;
        IntPtr job = IntPtr.Zero;
        ProcessInformation child = new ProcessInformation();
        bool childCreated = false;
        bool jobAssigned = false;
        bool claimWon = false;
        string startedUtc = null;
        try
        {
            if (!File.Exists(requestPath))
            {
                return 2;
            }
            request = DeserializeBounded<Request>(requestPath);
            ValidateRequest(request, baseDir);
            File.Move(requestPath, claimedPath);
            claimWon = true;
            if (ValidCancel(Path.Combine(baseDir, CancelName), request.request_id))
            {
                WriteStatus(statusPath, request, "terminal", null, 1223, "pre_cancelled", null, UtcNow());
                return 3;
            }
            string stagedPath = Path.GetFullPath(Path.Combine(baseDir, request.staged_case));
            using (FileStream engineLock = new FileStream(request.engine, FileMode.Open, FileAccess.Read, FileShare.Read))
            using (FileStream caseLock = new FileStream(stagedPath, FileMode.Open, FileAccess.Read, FileShare.Read))
            {
                if (!HashEquals(engineLock, request.engine_sha256)) throw new InvalidDataException("final engine hash");
                if (!HashEquals(caseLock, request.staged_case_sha256)) throw new InvalidDataException("final case hash");
                startedUtc = UtcNow();
                WriteStatus(statusPath, request, "launching", null, null, "validated_claimed", startedUtc, null);

                job = CreateKillOnCloseJob();
                string logPath = Path.Combine(baseDir, "run.log");
                string inputPath = Path.Combine(baseDir, "broker-stdin.empty");
                File.WriteAllBytes(inputPath, new byte[0]);
                using (FileStream log = new FileStream(logPath, FileMode.Create, FileAccess.Write, FileShare.Read))
                using (FileStream input = new FileStream(inputPath, FileMode.Open, FileAccess.Read, FileShare.Read))
                {
                    StartupInfo startup = new StartupInfo();
                    startup.cb = Marshal.SizeOf(typeof(StartupInfo));
                    startup.dwFlags = StartfUseStdHandles;
                    startup.hStdInput = input.SafeFileHandle.DangerousGetHandle();
                    startup.hStdOutput = log.SafeFileHandle.DangerousGetHandle();
                    startup.hStdError = startup.hStdOutput;
                    if (!SetHandleInformation(startup.hStdOutput, HandleFlagInherit, HandleFlagInherit))
                        throw Win32("SetHandleInformation(inherit)");
                    if (!SetHandleInformation(startup.hStdInput, HandleFlagInherit, HandleFlagInherit))
                        throw Win32("SetHandleInformation(stdin inherit)");
                    string commandLine = Quote(request.engine) + " " + Quote(request.staged_case);
                    if (!CreateProcessW(request.engine, new StringBuilder(commandLine), IntPtr.Zero, IntPtr.Zero, true,
                        CreateSuspended, IntPtr.Zero, baseDir, ref startup, out child))
                    {
                        throw Win32("CreateProcessW");
                    }
                    SetHandleInformation(startup.hStdOutput, HandleFlagInherit, 0);
                    SetHandleInformation(startup.hStdInput, HandleFlagInherit, 0);
                    childCreated = true;
                    if (!AssignProcessToJobObject(job, child.hProcess))
                    {
                        throw Win32("AssignProcessToJobObject");
                    }
                    jobAssigned = true;
                    if (ResumeThread(child.hThread) == UInt32.MaxValue)
                    {
                        throw Win32("ResumeThread");
                    }
                    CloseHandle(child.hThread);
                    child.hThread = IntPtr.Zero;
                    WriteStatus(statusPath, request, "running", (int)child.dwProcessId, null, "child_running", startedUtc, null);

                    Stopwatch elapsed = Stopwatch.StartNew();
                    long lastHeartbeat = 0;
                    string reason = "child_exit";
                    while (true)
                    {
                        uint wait = WaitForSingleObject(child.hProcess, 250);
                        if (wait == WaitObject0)
                        {
                            break;
                        }
                        if (wait != WaitTimeout)
                        {
                            throw Win32("WaitForSingleObject");
                        }
                        if (ValidCancel(Path.Combine(baseDir, CancelName), request.request_id))
                        {
                            reason = "cancelled";
                            if (!TerminateJobObject(job, 1223)) throw Win32("TerminateJobObject(cancel)");
                            EnsureProcessStopped(child.hProcess, 1223);
                            break;
                        }
                        if (elapsed.Elapsed.TotalSeconds >= request.timeout_s)
                        {
                            reason = "timed_out";
                            if (!TerminateJobObject(job, 1460)) throw Win32("TerminateJobObject(timeout)");
                            EnsureProcessStopped(child.hProcess, 1460);
                            break;
                        }
                        if (elapsed.ElapsedMilliseconds - lastHeartbeat >= 1000)
                        {
                            lastHeartbeat = elapsed.ElapsedMilliseconds;
                            TryWriteStatus(statusPath, request, "running", (int)child.dwProcessId, null, "child_running", startedUtc, null);
                        }
                    }
                    uint rawExit;
                    if (!GetExitCodeProcess(child.hProcess, out rawExit)) throw Win32("GetExitCodeProcess");
                    int exitCode = unchecked((int)rawExit);
                    WriteStatus(statusPath, request, "terminal", (int)child.dwProcessId, exitCode, reason, startedUtc, UtcNow());
                    return exitCode;
                }
            }
        }
        catch (Exception ex)
        {
            if (!claimWon)
            {
                return 2;
            }
            if (request != null && claimWon)
            {
                try
                {
                    int terminalExit = 125;
                    if (childCreated)
                    {
                        if (jobAssigned)
                        {
                            TerminateJobObject(job, 125);
                        }
                        else
                        {
                            TerminateProcess(child.hProcess, 125);
                        }
                        uint stopped = WaitForSingleObject(child.hProcess, TerminationWaitMs);
                        if (stopped == WaitTimeout)
                        {
                            TerminateProcess(child.hProcess, 125);
                            WaitForSingleObject(child.hProcess, TerminationWaitMs);
                        }
                        uint rawExit;
                        if (GetExitCodeProcess(child.hProcess, out rawExit)) terminalExit = unchecked((int)rawExit);
                    }
                    WriteStatus(statusPath, request, "terminal", childCreated ? (int?)child.dwProcessId : null,
                        terminalExit, "broker_error:" + Bound(ex.Message, 512), startedUtc, UtcNow());
                }
                catch { }
            }
            return 125;
        }
        finally
        {
            if (claimWon && child.hThread != IntPtr.Zero) CloseHandle(child.hThread);
            if (claimWon && child.hProcess != IntPtr.Zero) CloseHandle(child.hProcess);
            if (claimWon && job != IntPtr.Zero) CloseHandle(job);
        }
    }
}
