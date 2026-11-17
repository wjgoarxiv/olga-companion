using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Globalization;
using System.IO;
using System.Security.Cryptography;
using System.Text;
using System.Text.RegularExpressions;
using System.Web.Script.Serialization;

internal static partial class OlgaExplorerBroker
{
    private const string Protocol = "olga-explorer-broker.v1";
    private const string RequestName = "broker-request.json";
    private const string ClaimedName = "broker-request.claimed.json";
    private const string StatusName = "broker-status.json";
    private const string CancelName = "broker-cancel.json";
    private const int MaxJsonBytes = 65536;

    private static void ValidateRequest(Request request, string baseDir)
    {
        if (request == null || request.protocol != Protocol) throw new InvalidDataException("protocol");
        if (!Hex(request.token, 64) || !Hex(request.request_id, 64)) throw new InvalidDataException("token");
        DateTime expires;
        if (!DateTime.TryParse(request.expires_utc, CultureInfo.InvariantCulture,
            DateTimeStyles.AdjustToUniversal | DateTimeStyles.AssumeUniversal, out expires) || expires <= DateTime.UtcNow)
            throw new InvalidDataException("expired");
        if (!String.Equals(Path.GetFullPath(request.run_dir).TrimEnd(Path.DirectorySeparatorChar), baseDir,
            StringComparison.OrdinalIgnoreCase)) throw new InvalidDataException("run containment");
        if (request.staged_case != "case.genkey" || request.argv == null || request.argv.Length != 1 ||
            request.argv[0] != request.staged_case) throw new InvalidDataException("argv");
        if (request.timeout_s <= 0 || request.timeout_s > 604800) throw new InvalidDataException("timeout");
        string staged = Path.GetFullPath(Path.Combine(baseDir, request.staged_case));
        if (!String.Equals(Path.GetDirectoryName(staged), baseDir, StringComparison.OrdinalIgnoreCase))
            throw new InvalidDataException("case containment");
        if (!Path.IsPathRooted(request.engine) || !File.Exists(request.engine)) throw new InvalidDataException("engine");
        if (!HashEquals(request.engine, request.engine_sha256)) throw new InvalidDataException("engine hash");
        if (!HashEquals(staged, request.staged_case_sha256)) throw new InvalidDataException("case hash");
        if (!HashEquals(Process.GetCurrentProcess().MainModule.FileName, request.broker_sha256))
            throw new InvalidDataException("broker hash");
    }

    private static bool ValidCancel(string path, string requestId)
    {
        if (!File.Exists(path)) return false;
        try
        {
            CancelRequest cancel = DeserializeBounded<CancelRequest>(path);
            return cancel.protocol == Protocol && cancel.request_id == requestId;
        }
        catch { return false; }
    }

    private static T DeserializeBounded<T>(string path)
    {
        FileInfo info = new FileInfo(path);
        if (!info.Exists || info.Length <= 0 || info.Length > MaxJsonBytes) throw new InvalidDataException("bounded JSON");
        string json = File.ReadAllText(path, Encoding.UTF8);
        return new JavaScriptSerializer().Deserialize<T>(json);
    }

    private static void WriteStatus(string path, Request request, string state, int? childPid,
        int? childExit, string reason, string startedUtc, string finishedUtc)
    {
        Dictionary<string, object> value = new Dictionary<string, object>();
        value["protocol"] = Protocol;
        value["request_id"] = request.request_id;
        value["state"] = state;
        value["reason"] = Bound(reason, 768);
        value["broker_pid"] = Process.GetCurrentProcess().Id;
        value["child_pid"] = childPid;
        value["child_exit_code"] = childExit;
        value["started_utc"] = startedUtc;
        value["updated_utc"] = UtcNow();
        value["finished_utc"] = finishedUtc;
        string json = new JavaScriptSerializer().Serialize(value);
        if (Encoding.UTF8.GetByteCount(json) > MaxJsonBytes) throw new InvalidDataException("status too large");
        string temp = path + "." + Guid.NewGuid().ToString("N") + ".tmp";
        File.WriteAllText(temp, json, new UTF8Encoding(false));
        // A reader may hold the status file open for a moment; retry for about a second.
        for (int attempt = 0; ; attempt++)
        {
            try
            {
                if (File.Exists(path)) File.Replace(temp, path, null); else File.Move(temp, path);
                return;
            }
            catch (IOException)
            {
                if (attempt >= 39) { TryDelete(temp); throw; }
            }
            catch (UnauthorizedAccessException)
            {
                if (attempt >= 39) { TryDelete(temp); throw; }
            }
            System.Threading.Thread.Sleep(25);
        }
    }

    private static bool TryWriteStatus(string path, Request request, string state, int? childPid,
        int? childExit, string reason, string startedUtc, string finishedUtc)
    {
        try
        {
            WriteStatus(path, request, state, childPid, childExit, reason, startedUtc, finishedUtc);
            return true;
        }
        catch (IOException) { return false; }
        catch (UnauthorizedAccessException) { return false; }
    }

    private static void TryDelete(string path)
    {
        try { File.Delete(path); } catch (IOException) { } catch (UnauthorizedAccessException) { }
    }

    private static bool HashEquals(string path, string expected)
    {
        if (!Hex(expected, 64) || !File.Exists(path)) return false;
        using (FileStream stream = File.OpenRead(path))
        {
            return HashEquals(stream, expected);
        }
    }

    private static bool HashEquals(Stream stream, string expected)
    {
        if (!Hex(expected, 64) || stream == null || !stream.CanRead || !stream.CanSeek) return false;
        stream.Position = 0;
        byte[] hash;
        using (SHA256 sha = SHA256.Create())
        {
            hash = sha.ComputeHash(stream);
        }
        stream.Position = 0;
        StringBuilder text = new StringBuilder(hash.Length * 2);
        foreach (byte value in hash) text.Append(value.ToString("x2", CultureInfo.InvariantCulture));
        return String.Equals(text.ToString(), expected, StringComparison.OrdinalIgnoreCase);
    }

    private static bool Hex(string value, int length)
    {
        return value != null && value.Length == length && Regex.IsMatch(value, "\\A[0-9a-fA-F]+\\z");
    }

    private static string Quote(string value)
    {
        return "\"" + value.Replace("\"", "\\\"") + "\"";
    }

    private static string UtcNow()
    {
        return DateTime.UtcNow.ToString("o", CultureInfo.InvariantCulture);
    }

    private static string Bound(string value, int limit)
    {
        if (value == null) return null;
        return value.Length <= limit ? value : value.Substring(0, limit);
    }
}
