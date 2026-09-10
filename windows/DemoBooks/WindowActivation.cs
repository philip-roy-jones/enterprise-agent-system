using System.Runtime.InteropServices;

namespace DemoBooks;

// Narrow desktop setup: only our own window and its inert header can be targeted.
// No arbitrary window titles, keyboard shortcuts, or business controls are accepted.
static class WindowActivation
{
    [StructLayout(LayoutKind.Sequential)] struct MouseInput { public int dx, dy; public uint mouseData, flags, time; public UIntPtr extraInfo; }
    [StructLayout(LayoutKind.Sequential)] struct Input { public uint type; public MouseInput mouse; }
    [DllImport("user32.dll")] static extern uint SendInput(uint count, Input[] inputs, int size);
    [DllImport("user32.dll")] static extern IntPtr WindowFromPoint(Point point);
    [DllImport("user32.dll")] static extern IntPtr GetAncestor(IntPtr window, uint flags);
    [DllImport("user32.dll")] static extern bool SetForegroundWindow(IntPtr window);
    [DllImport("user32.dll")] static extern IntPtr GetForegroundWindow();
    [DllImport("user32.dll")] static extern bool SetWindowPos(IntPtr window, IntPtr after, int x, int y, int width, int height, uint flags);

    public static object Restore(AccountingWindow window)
    {
        if (window.WindowState == FormWindowState.Minimized) window.WindowState = FormWindowState.Maximized;
        window.Show();
        SetForegroundWindow(window.Handle);
        if (GetForegroundWindow() == window.Handle) return new { activated = true, method = "window_api" };
        // Windows may refuse background activation. Raise our window, confirm the
        // exact target belongs to it, then supply a normal click on its inert header.
        // Unlike attaching input queues, this cannot hang on another app's UI thread.
        SetWindowPos(window.Handle, new IntPtr(-1), 0, 0, 0, 0, 0x13);
        try
        {
            window.Update();
            Point point = window.PointToScreen(new Point(350, 55));
            if (GetAncestor(WindowFromPoint(point), 2) != window.Handle)
                throw new InvalidOperationException("Assigned window header is not available for activation");
            Rectangle desktop = SystemInformation.VirtualScreen;
            int x = (int)((point.X - desktop.Left) * 65535L / (desktop.Width - 1));
            int y = (int)((point.Y - desktop.Top) * 65535L / (desktop.Height - 1));
            var inputs = new[] {
                new Input { mouse = new MouseInput { dx = x, dy = y, flags = 0xC001 } },
                new Input { mouse = new MouseInput { flags = 0x0002 } },
                new Input { mouse = new MouseInput { flags = 0x0004 } }
            };
            if (SendInput((uint)inputs.Length, inputs, Marshal.SizeOf<Input>()) != inputs.Length)
                throw new InvalidOperationException("Desktop input is unavailable for assigned-window activation");
            return new { activated = GetForegroundWindow() == window.Handle, method = "verified_header_click" };
        }
        finally { SetWindowPos(window.Handle, new IntPtr(-2), 0, 0, 0, 0, 0x13); }
    }
}
