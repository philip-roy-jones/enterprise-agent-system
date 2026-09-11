using System.Diagnostics;
using System.Drawing;
using System.Drawing.Imaging;
using System.IO;
using System.Net;
using System.Runtime.InteropServices;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Windows.Automation;

namespace EnterpriseDesktop;

// Out-of-process Windows automation. This project has no DemoBooks reference,
// accounting model, application API client, or access to its database.
static class Program
{
    static void Main(string[] args)
    {
        string processName = args.Length > 0 ? args[0] : "DemoBooks";
        string root = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "EnterpriseAgentSystem", "DesktopAgent", "data");
        Directory.CreateDirectory(root);
        string tokenPath = Path.Combine(root, "bridge.token");
        if (!File.Exists(tokenPath)) File.WriteAllText(tokenPath, Convert.ToHexString(RandomNumberGenerator.GetBytes(32)));
        string token = File.ReadAllText(tokenPath).Trim();
        try
        {
            using var listener = new HttpListener();
            listener.Prefixes.Add("http://127.0.0.1:8766/"); listener.Start();
            File.WriteAllText(Path.Combine(root, "ready.json"), JsonSerializer.Serialize(new { pid = Environment.ProcessId, target_process = processName, session = Process.GetCurrentProcess().SessionId }));
            var desktop = new Desktop(processName);
            // One request at a time; observation, revision validation, and action
            // cannot interleave with another controller request.
            while (true)
            {
                var context = listener.GetContext();
                try
                {
                    if (!CryptographicOperations.FixedTimeEquals(Encoding.UTF8.GetBytes(context.Request.Headers["Authorization"] ?? ""), Encoding.UTF8.GetBytes("Bearer " + token)))
                        throw new UnauthorizedAccessException("Desktop controller credential required");
                    string body = new StreamReader(context.Request.InputStream).ReadToEnd();
                    var data = JsonSerializer.Deserialize<JsonElement>(string.IsNullOrEmpty(body) ? "{}" : body);
                    object result = context.Request.Url!.AbsolutePath switch
                    {
                        "/health" => new { status = "ok", target_process = processName, transport = "windows_accessibility_and_input", session_id = Process.GetCurrentProcess().SessionId },
                        "/window" => desktop.Window(),
                        "/activate" when context.Request.HttpMethod == "POST" => desktop.Activate(),
                        "/observe" => desktop.Observe(!data.TryGetProperty("screenshot", out var shot) || shot.GetBoolean()),
                        "/action" when context.Request.HttpMethod == "POST" => desktop.Action(data),
                        _ => throw new ArgumentException("Unknown desktop controller endpoint")
                    };
                    Reply(context, result);
                }
                catch (Exception error)
                {
                    context.Response.StatusCode = error is UnauthorizedAccessException ? 403 : 409;
                    Reply(context, new { error = error.Message });
                }
            }
        }
        catch (Exception error) { File.WriteAllText(Path.Combine(root, "error.txt"), error.ToString()); }
    }
    static void Reply(HttpListenerContext context, object data)
    {
        byte[] bytes = JsonSerializer.SerializeToUtf8Bytes(data);
        context.Response.ContentType = "application/json";
        context.Response.ContentLength64 = bytes.Length;
        context.Response.OutputStream.Write(bytes); context.Response.Close();
    }
}

record Element(string element, string automation_id, string name, string type, string? value, double x, double y, double width, double height, bool enabled, bool invoke, bool edit);
record Snapshot(string revision, int pid, long window, string title, bool foreground, bool minimized, int width, int height, Element[] elements, string? screenshot, int desktop_session);

sealed class Desktop(string processName)
{
    [StructLayout(LayoutKind.Sequential)] struct Rect { public int left, top, right, bottom; }
    [StructLayout(LayoutKind.Sequential)] struct MouseInput { public int dx, dy; public uint data, flags, time; public UIntPtr extra; }
    [StructLayout(LayoutKind.Sequential)] struct KeyInput { public ushort key, scan; public uint flags, time; public UIntPtr extra; }
    [StructLayout(LayoutKind.Explicit)] struct InputUnion { [FieldOffset(0)] public MouseInput mouse; [FieldOffset(0)] public KeyInput key; }
    [StructLayout(LayoutKind.Sequential)] struct Input { public uint type; public InputUnion data; }
    [DllImport("user32.dll")] static extern bool GetWindowRect(IntPtr window, out Rect rect);
    [DllImport("user32.dll")] static extern bool GetClientRect(IntPtr window, out Rect rect);
    [DllImport("user32.dll")] static extern bool ClientToScreen(IntPtr window, ref Point point);
    [DllImport("user32.dll")] static extern IntPtr GetForegroundWindow();
    [DllImport("user32.dll")] static extern bool SetForegroundWindow(IntPtr window);
    [DllImport("user32.dll")] static extern bool ShowWindow(IntPtr window, int command);
    [DllImport("user32.dll")] static extern bool IsIconic(IntPtr window);
    [DllImport("user32.dll")] static extern bool IsZoomed(IntPtr window);
    [DllImport("user32.dll")] static extern bool SetWindowPos(IntPtr window, IntPtr after, int x, int y, int width, int height, uint flags);
    [DllImport("user32.dll")] static extern IntPtr WindowFromPoint(Point point);
    [DllImport("user32.dll")] static extern IntPtr GetAncestor(IntPtr window, uint flags);
    [DllImport("user32.dll")] static extern uint GetWindowThreadProcessId(IntPtr window, out uint process);
    [DllImport("user32.dll")] static extern uint SendInput(uint count, Input[] inputs, int size);
    delegate bool EnumWindow(IntPtr window, IntPtr parameter);
    [DllImport("user32.dll")] static extern bool EnumWindows(EnumWindow callback, IntPtr parameter);
    [DllImport("user32.dll")] static extern bool IsWindowVisible(IntPtr window);
    [DllImport("user32.dll")] static extern int GetWindowText(IntPtr window, StringBuilder text, int count);
    IntPtr AssignedWindow(Process process)
    {
        var windows = new List<IntPtr>();
        EnumWindows((window, _) => {
            GetWindowThreadProcessId(window, out var pid);
            var title = new StringBuilder(512); GetWindowText(window, title, title.Capacity);
            if (pid == process.Id && IsWindowVisible(window) && title.Length > 0 && GetAncestor(window, 3) == window)
                windows.Add(window);
            return true;
        }, IntPtr.Zero);
        if (windows.Count != 1) throw new InvalidOperationException("Assigned application has no unambiguous primary window");
        return windows[0];
    }
    Process Target()
    {
        var found = Process.GetProcessesByName(processName).Where(p => p.SessionId == Process.GetCurrentProcess().SessionId).ToArray();
        if (found.Length != 1) throw new InvalidOperationException("Exactly one assigned application window must be open in this desktop session");
        return found[0];
    }
    static Point Origin(IntPtr window) { Point p = new(); ClientToScreen(window, ref p); return p; }
    static string Id(AutomationElement element) => string.Join(".", element.GetRuntimeId());
    public object Window()
    {
        using var p = Target();
        var window = AssignedWindow(p);
        GetWindowRect(window, out var bounds);
        bool onscreen = IsZoomed(window) || System.Windows.Forms.Screen.FromHandle(window).WorkingArea.Contains(Rectangle.FromLTRB(bounds.left, bounds.top, bounds.right, bounds.bottom));
        return new { foreground = GetForegroundWindow() == window, minimized = IsIconic(window), onscreen, pid = p.Id };
    }
    public object Activate()
    {
        using var p = Target(); IntPtr window = AssignedWindow(p);
        if (IsIconic(window)) ShowWindow(window, 9);
        GetWindowRect(window, out var bounds);
        var workArea = System.Windows.Forms.Screen.FromHandle(window).WorkingArea;
        if (!workArea.Contains(Rectangle.FromLTRB(bounds.left, bounds.top, bounds.right, bounds.bottom)))
            ShowWindow(window, 3); // Recover a window left off-screen by a resolution change.
        SetForegroundWindow(window);
        if (GetForegroundWindow() != window)
        {
            SetWindowPos(window, new IntPtr(-1), 0, 0, 0, 0, 0x13);
            try
            {
                GetWindowRect(window, out var r);
                Click(window, new Point((r.left + r.right) / 2, r.top + 18), requireForeground: false);
            }
            finally { SetWindowPos(window, new IntPtr(-2), 0, 0, 0, 0, 0x13); }
        }
        return new { activated = GetForegroundWindow() == window };
    }
    public Snapshot Observe(bool screenshot = true)
    {
        using var p = Target(); var window = AssignedWindow(p);
        Point origin = Origin(window); GetClientRect(window, out var rect);
        var root = AutomationElement.FromHandle(window);
        var nodes = root.FindAll(TreeScope.Descendants, Condition.TrueCondition);
        var elements = new List<Element>();
        foreach (AutomationElement node in nodes)
        {
            try
            {
                var c = node.Current; var r = c.BoundingRectangle;
                if (c.IsOffscreen || r.IsEmpty || r.Width <= 0 || r.Height <= 0 || c.IsPassword) continue;
                string? value = node.TryGetCurrentPattern(ValuePattern.Pattern, out var pattern) ? ((ValuePattern)pattern).Current.Value : null;
                elements.Add(new(Id(node), c.AutomationId, c.Name, c.ControlType.ProgrammaticName.Replace("ControlType.", ""), value,
                    r.X - origin.X + r.Width / 2, r.Y - origin.Y + r.Height / 2, r.Width, r.Height, c.IsEnabled,
                    node.TryGetCurrentPattern(InvokePattern.Pattern, out _), pattern is not null));
                if (elements.Count >= 1000) throw new InvalidOperationException("Accessibility tree exceeds observation limit");
            }
            catch (ElementNotAvailableException) { throw new InvalidOperationException("Application changed during accessibility observation; observe again"); }
        }
        bool foreground = GetForegroundWindow() == window;
        string revision = Convert.ToHexString(SHA256.HashData(JsonSerializer.SerializeToUtf8Bytes(new { pid = p.Id, window = window.ToInt64(), foreground, origin, width = rect.right, height = rect.bottom, elements })));
        string? png = null;
        if (screenshot && !IsIconic(window))
        {
            using var bitmap = new Bitmap(rect.right, rect.bottom);
            using (var g = Graphics.FromImage(bitmap)) g.CopyFromScreen(origin, Point.Empty, bitmap.Size);
            using var output = new MemoryStream(); bitmap.Save(output, ImageFormat.Png); png = Convert.ToBase64String(output.ToArray());
        }
        var title = new StringBuilder(512); GetWindowText(window, title, title.Capacity);
        return new(revision, p.Id, window.ToInt64(), title.ToString(), foreground, IsIconic(window), rect.right, rect.bottom, elements.ToArray(), png, p.SessionId);
    }
    public object Action(JsonElement args)
    {
        var observation = Observe(false);
        if (!observation.foreground) throw new InvalidOperationException("Assigned application is not in the foreground");
        if (args.GetProperty("revision").GetString() != observation.revision) throw new InvalidOperationException("Observation revision changed before action");
        var window = new IntPtr(observation.window);
        string operation = args.GetProperty("operation").GetString()!;
        if (operation == "click")
        {
            double x = args.GetProperty("x").GetDouble(), y = args.GetProperty("y").GetDouble();
            if (x < 0 || y < 0 || x >= observation.width || y >= observation.height) throw new UnauthorizedAccessException("Click is outside assigned window");
            Point origin = Origin(window);
            Click(window, new Point(origin.X + (int)x, origin.Y + (int)y));
            return new { executed = true, method = "mouse_input" };
        }
        string id = args.GetProperty("element").GetString()!;
        var known = observation.elements.SingleOrDefault(e => e.element == id && e.enabled) ?? throw new UnauthorizedAccessException("Element is not visible and enabled in the current observation");
        var nodes = AutomationElement.FromHandle(window).FindAll(TreeScope.Descendants, Condition.TrueCondition);
        var element = nodes.Cast<AutomationElement>().Single(e => Id(e) == id);
        if (operation == "invoke")
        {
            if (element.TryGetCurrentPattern(InvokePattern.Pattern, out var invoke))
            {
                ((InvokePattern)invoke).Invoke(); return new { executed = true, method = "accessibility_invoke" };
            }
            if (element.TryGetCurrentPattern(ExpandCollapsePattern.Pattern, out var expand))
            {
                ((ExpandCollapsePattern)expand).Expand(); return new { executed = true, method = "accessibility_expand" };
            }
            Point origin = Origin(window); Click(window, new Point(origin.X + (int)known.x, origin.Y + (int)known.y));
            return new { executed = true, method = "mouse_input" };
        }
        if (operation == "set_value")
        {
            string text = args.GetProperty("value").GetString()!;
            if (text.Length > 4096 || text.Contains('\n') || text.Contains('\r')) throw new UnauthorizedAccessException("Only bounded single-line text is supported");
            bool keyboard = args.TryGetProperty("keyboard", out var force) && force.GetBoolean();
            if (!keyboard && element.TryGetCurrentPattern(ValuePattern.Pattern, out var value))
            {
                if (((ValuePattern)value).Current.IsReadOnly) throw new UnauthorizedAccessException("Field is read-only");
                ((ValuePattern)value).SetValue(text); return new { executed = true, method = "accessibility_value" };
            }
            if (known.type != "Edit") throw new UnauthorizedAccessException("Keyboard entry requires a visible edit control");
            element.SetFocus();
            // UI Automation can report the previous focused element briefly after
            // SetFocus returns. Wait for the exact target, while retaining the
            // foreground guard; never type merely because SetFocus succeeded.
            var focusWait = Stopwatch.StartNew();
            while (!HasInputFocus(window, element, id))
            {
                if (focusWait.ElapsedMilliseconds >= 500) throw new InvalidOperationException("Input focus did not reach the approved field before the deadline");
                Thread.Sleep(10);
            }
            var input = new List<Input> { Key(0x11), Key(0x41), Key(0x41, 2), Key(0x11, 2) };
            foreach (char c in text) { input.Add(Key(0, 4, c)); input.Add(Key(0, 6, c)); }
            if (!HasInputFocus(window, element, id)) throw new InvalidOperationException("Input focus changed before typing");
            Send(input.ToArray()); return new { executed = true, method = "keyboard_input" };
        }
        throw new UnauthorizedAccessException("Unsupported desktop operation");
    }
    static bool HasInputFocus(IntPtr window, AutomationElement element, string id)
    {
        if (GetForegroundWindow() != window) throw new InvalidOperationException("Assigned application lost foreground before typing");
        return element.Current.HasKeyboardFocus && Id(AutomationElement.FocusedElement) == id;
    }
    static Input Key(ushort key, uint flags = 0, ushort scan = 0) => new() { type = 1, data = new() { key = new() { key = key, scan = scan, flags = flags } } };
    static void Send(Input[] inputs)
    {
        if (SendInput((uint)inputs.Length, inputs, Marshal.SizeOf<Input>()) != inputs.Length) throw new InvalidOperationException("Windows input was blocked or incomplete");
    }
    static void Click(IntPtr window, Point point, bool requireForeground = true)
    {
        if (requireForeground && GetForegroundWindow() != window) throw new InvalidOperationException("Window focus changed before click");
        Rectangle desktop = System.Windows.Forms.SystemInformation.VirtualScreen;
        if (!desktop.Contains(point)) throw new InvalidOperationException("Click point is outside the visible desktop");
        var hit = WindowFromPoint(point);
        GetWindowThreadProcessId(window, out var targetPid); GetWindowThreadProcessId(hit, out var hitPid);
        if (hitPid != targetPid || GetAncestor(hit, 2) != window) throw new InvalidOperationException("Click point is covered by another window");
        int x = (int)((point.X - desktop.Left) * 65535L / (desktop.Width - 1));
        int y = (int)((point.Y - desktop.Top) * 65535L / (desktop.Height - 1));
        Send([new() { data = new() { mouse = new() { dx = x, dy = y, flags = 0xC001 } } }, new() { data = new() { mouse = new() { flags = 2 } } }, new() { data = new() { mouse = new() { flags = 4 } } }]);
    }
}
