using System.Drawing.Imaging;
using System.Net;
using System.Runtime.InteropServices;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;

namespace DemoBooks;

static class Program
{
    [STAThread]
    static void Main(string[] args)
    {
        using var mutex = new Mutex(true, "Local\\EAS-DemoBooks", out bool first);
        if (!first) return;
        ApplicationConfiguration.Initialize();
        Application.Run(new AccountingWindow(!args.Contains("--no-api")));
    }
}

public sealed class AccountingWindow : Form
{
    readonly AccountingStore store;
    readonly Panel content = new() { Dock = DockStyle.Fill, BackColor = Color.FromArgb(243, 245, 247), Padding = new(24) };
    readonly Dictionary<string, Control> targets = new();
    readonly StatusStrip status = new();
    readonly ToolStripStatusLabel statusText = new();
    readonly System.Windows.Forms.Timer timer = new() { Interval = 250 };
    readonly string token;
    readonly string dataDir;
    HttpListener? listener;
    Panel? overlay;
    Exception? actionError;
    string? operationId;
    string? scopedInvoice;
    bool rendering;
    bool automated;
    bool loadingShown;
    [DllImport("user32.dll")] static extern IntPtr GetForegroundWindow();
    [DllImport("user32.dll")] static extern bool SetForegroundWindow(IntPtr hWnd);

    public AccountingWindow(bool enableApi = true)
    {
        dataDir = Environment.GetEnvironmentVariable("EAS_WINDOWS_DATA_DIR") ?? Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "EnterpriseAgentSystem", "DemoBooks", "data");
        store = new AccountingStore(dataDir);
        string tokenPath = Path.Combine(dataDir, "bridge.token");
        if (!File.Exists(tokenPath)) File.WriteAllText(tokenPath, Convert.ToHexString(RandomNumberGenerator.GetBytes(32)));
        token = File.ReadAllText(tokenPath).Trim();
        Text = "DemoBooks Desktop — Acme Manufacturing [SYNTHETIC]";
        Name = "EAS-DemoBooks";
        Font = new("Segoe UI", 10);
        ClientSize = new(1180, 790);
        MinimumSize = new(1000, 700);
        StartPosition = FormStartPosition.CenterScreen;
        WindowState = FormWindowState.Maximized;
        BackColor = Color.White;
        var menu = new MenuStrip();
        foreach (string name in new[] { "File", "Edit", "View", "Company", "Vendors", "Reports", "Help" }) menu.Items.Add(name);
        ((ToolStripMenuItem)menu.Items[0]).DropDownItems.Add("Exit", null, (_, _) => Close());
        ((ToolStripMenuItem)menu.Items[6]).DropDownItems.Add("About this synthetic application", null, (_, _) => MessageBox.Show("DemoBooks is an Enterprise Agent System test application. It is not QuickBooks or an Intuit product. All records are synthetic.", "About DemoBooks"));
        var trainingMenu = new ToolStripMenuItem("Training scenarios");
        foreach (var item in new[] {
            ("Standard layout", "{\"variant\":\"standard\",\"dialog\":null}"),
            ("Changed amount label", "{\"variant\":\"renamed\"}"),
            ("Changed layout", "{\"variant\":\"layout\"}"),
            ("Informational notice", "{\"dialog\":\"info\"}"),
            ("Unfamiliar notice", "{\"dialog\":\"unfamiliar\"}"),
            ("Unsaved changes", "{\"dialog\":\"unsaved\",\"unsaved\":true}"),
            ("Reordered records", "{\"reordered\":true}"),
            ("Interrupted save confirmation", "{\"interrupt_save\":true}") })
            trainingMenu.DropDownItems.Add(item.Item1, null, (_, _) => { store.Scenario(JsonSerializer.Deserialize<JsonElement>(item.Item2)); Render(); });
        menu.Items.Add(trainingMenu);
        if (!enableApi) Text += " — Application API disabled";
        var header = new Panel { Dock = DockStyle.Top, Width = ClientSize.Width, Height = 72, BackColor = Color.FromArgb(26, 67, 48) };
        header.Controls.Add(new Label { Text = "DemoBooks Desktop", ForeColor = Color.White, Font = new("Segoe UI", 20, FontStyle.Bold), AutoSize = true, Location = new(23, 15) });
        var company = MakeButton("company", "Acme Manufacturing  ▾", () => Apply("company", new { company_id = "ACME" }));
        company.SetBounds(875, 17, 265, 38); company.Anchor = AnchorStyles.Top | AnchorStyles.Right;
        header.Controls.Add(company);
        var nav = new Panel { Dock = DockStyle.Left, Width = 193, Height = ClientSize.Height - 122, BackColor = Color.FromArgb(235, 238, 234) };
        nav.Controls.Add(new Label { Text = "MY SHORTCUTS", AutoSize = true, Font = new("Segoe UI", 9, FontStyle.Bold), ForeColor = Color.DimGray, Location = new(20, 25) });
        int y = 65;
        foreach (var item in new[] { ("dashboard", "Company home"), ("invoices", "Vendor invoices"), ("purchase_orders", "Purchase orders") })
        {
            var button = MakeButton(item.Item1, item.Item2, () => Apply("navigate", new { view = item.Item1 }));
            button.SetBounds(12, y, 169, 44); button.FlatStyle = FlatStyle.Flat; button.FlatAppearance.BorderSize = 0; button.TextAlign = ContentAlignment.MiddleLeft;
            nav.Controls.Add(button); y += 51;
        }
        var training = new Label { Text = "TRAINING COMPANY\nSynthetic records only\nNo payments or postings", ForeColor = Color.DimGray, AutoSize = false, Size = new(170, 75), Location = new(18, 565), Anchor = AnchorStyles.Left | AnchorStyles.Bottom };
        nav.Controls.Add(training);
        status.Items.Add(statusText);
        Controls.Add(content); Controls.Add(nav); Controls.Add(status); Controls.Add(header); Controls.Add(menu);
        MainMenuStrip = menu;
        timer.Tick += (_, _) => { if (loadingShown && store.State.loading_until <= AccountingStore.Now) Render(); };
        timer.Start();
        Shown += (_, _) => { Render(); if (enableApi) StartBridge(); Activate(); };
        FormClosed += (_, _) => { listener?.Stop(); timer.Stop(); };
    }

    Button MakeButton(string id, string text, Action action)
    {
        var button = new Button { Name = id, AccessibleName = text, Text = text, AutoSize = false, UseVisualStyleBackColor = true };
        button.Click += (_, _) => { try { actionError = null; action(); } catch (Exception error) { actionError = error; statusText.Text = error.Message; if (!automated) MessageBox.Show(error.Message, "DemoBooks", MessageBoxButtons.OK, MessageBoxIcon.Warning); } };
        targets[id] = button;
        return button;
    }
    void Apply(string action, object args)
    {
        store.Apply(action, JsonSerializer.SerializeToElement(args), operationId ?? "manual-" + Guid.NewGuid().ToString("N"), scopedInvoice);
        Render();
    }
    Label Label(string text, int x, int y, int size = 10, bool bold = false)
    {
        var label = new Label { Text = text, Location = new(x, y), AutoSize = true, Font = new("Segoe UI", size, bold ? FontStyle.Bold : FontStyle.Regular), ForeColor = Color.FromArgb(43, 53, 61) };
        content.Controls.Add(label); return label;
    }
    static string Money(long cents) => (cents / 100m).ToString("C2", System.Globalization.CultureInfo.GetCultureInfo("en-US"));

    void Render()
    {
        rendering = true;
        SuspendLayout();
        foreach (var key in targets.Where(p => p.Value.IsDisposed || content.Contains(p.Value)).Select(p => p.Key).ToList()) targets.Remove(key);
        content.Controls.Clear();
        if (overlay is not null) { Controls.Remove(overlay); overlay.Dispose(); overlay = null; }
        var s = store.State;
        statusText.Text = $"Company: {s.company_id}    |    {(s.unsaved ? "Unsaved draft changes" : "Ready")}    |    Synthetic environment    |    {s.app_version}";
        Label("ACME MANUFACTURING  /  FINANCE", 24, 22, 9, true);
        loadingShown = s.loading_until > AccountingStore.Now;
        if (loadingShown) Label("Loading accounting records…", 24, 75, 22, true);
        else if (s.view == "dashboard")
        {
            Label("Company home", 24, 65, 25, true);
            Label("Vendors & accounts payable", 24, 125, 14, true);
            Label("Open invoices", 24, 195); Label(s.invoices.Count.ToString(), 24, 225, 30, true);
            Label("Amount awaiting review", 300, 195); Label(Money(s.invoices.Sum(i => i.amount)), 300, 225, 30, true);
            Label("Correction drafts", 670, 195); Label(s.drafts.Count.ToString(), 670, 225, 30, true);
            var open = MakeButton("view-invoices", "Open vendor invoices", () => Apply("navigate", new { view = "invoices" }));
            open.SetBounds(24, 330, 240, 47); content.Controls.Add(open);
            Label("Recent activity", 24, 425, 14, true);
            Label(s.drafts.Count == 0 ? "No correction drafts saved yet." : $"{s.drafts.Last().id} — {s.drafts.Last().invoice_id} — {Money(s.drafts.Last().amount)}", 24, 467);
        }
        else if (s.view is "invoices" or "purchase_orders")
        {
            bool po = s.view == "purchase_orders";
            Label(po ? "Purchase order center" : "Vendor invoice center", 24, 65, 25, true);
            Label("Open a record to review its invoice and purchase order.", 24, 119);
            var table = new DataGridView { Location = new(24, 165), Size = new(content.Width - 48, 205), Anchor = AnchorStyles.Top | AnchorStyles.Left | AnchorStyles.Right, ReadOnly = true, AllowUserToAddRows = false, AllowUserToDeleteRows = false, RowHeadersVisible = false, AutoSizeColumnsMode = DataGridViewAutoSizeColumnsMode.Fill, BackgroundColor = Color.White, BorderStyle = BorderStyle.FixedSingle, SelectionMode = DataGridViewSelectionMode.FullRowSelect, MultiSelect = false };
            table.Columns.Add(new DataGridViewButtonColumn { HeaderText = "Record", Name = "record" });
            table.Columns.Add("vendor", "Vendor"); table.Columns.Add("amount", "Amount"); table.Columns.Add("status", "Status");
            var records = (s.reordered ? s.invoices.AsEnumerable().Reverse() : s.invoices).ToList();
            foreach (var inv in records) table.Rows.Add(po ? inv.po_id : inv.id, inv.vendor, Money(po ? inv.po_amount : inv.amount), po ? "Approved" : "Needs review");
            table.RowTemplate.Height = 40;
            foreach (DataGridViewRow row in table.Rows) row.Height = 43;
            table.CellContentClick += (_, e) => { if (e.RowIndex >= 0) { try { Apply("open", new { invoice_id = records[e.RowIndex].id }); } catch (Exception ex) { statusText.Text = ex.Message; } } };
            content.Controls.Add(table);
            int y = 407;
            foreach (var inv in records)
            {
                var button = MakeButton("open-" + inv.id, "Open " + inv.id + "  ·  " + inv.vendor, () => Apply("open", new { invoice_id = inv.id }));
                button.SetBounds(24, y, Math.Min(700, content.Width - 48), 42); content.Controls.Add(button); y += 50;
            }
        }
        else if (s.view == "invoice" && s.invoices.Any(i => i.id == s.invoice_id))
        {
            var inv = s.invoices.Single(i => i.id == s.invoice_id);
            Label("Vendor invoice " + inv.id, 24, 65, 24, true); Label(inv.vendor, 24, 115, 12);
            Label("Invoice amount", 24, 172); Label(Money(inv.amount), 24, 203, 23, true);
            Label("Purchase order " + inv.po_id, 310, 172); Label(Money(inv.po_amount), 310, 203, 23, true);
            Label("Discrepancy", 665, 172); Label(Money(inv.amount - inv.po_amount), 665, 203, 23, true);
            Label("Correction draft", 24, 288, 16, true);
            var bank = Label("Vendor bank account: 000123456789 (synthetic)", 24, 250);
            bank.Name = "vendor-bank-account";
            string amountLabel = s.variant == "renamed" ? "Adjusted total" : "Correction amount";
            int amountX = s.variant == "layout" ? 660 : 24, noteX = s.variant == "layout" ? 24 : 310;
            Label(amountLabel, amountX, 340);
            AddField("amount", amountLabel, amountX, 370, 230);
            Label("Correction explanation", noteX, 340);
            AddField("note", "Correction explanation", noteX, 370, s.variant == "layout" ? 580 : 580);
            var save = MakeButton("save", "Save correction draft", () => Apply("save", new { }));
            save.SetBounds(660, 431, 230, 44); save.BackColor = Color.FromArgb(38, 103, 68); save.ForeColor = Color.White; save.FlatStyle = FlatStyle.Flat;
            content.Controls.Add(save);
            Label("Original invoice is unchanged. This saves a draft for review.", 24, 442);
            Label("Saved correction drafts", 24, 519, 14, true);
            var drafts = s.drafts.Where(d => d.invoice_id == inv.id).ToList();
            Label(drafts.Count == 0 ? "No draft saved for this invoice." : string.Join("\n", drafts.TakeLast(3).Select(d => $"{d.id}    {Money(d.amount)}    Draft    {d.note}")), 24, 561, 10);
        }
        if (s.dialog is not null) ShowDialogOverlay(s.dialog);
        ResumeLayout(true); rendering = false;
    }
    void AddField(string id, string label, int x, int y, int width)
    {
        var field = new TextBox { Name = id, AccessibleName = label, Text = store.State.fields[id], Location = new(x, y), Size = new(width, 32), Font = new("Segoe UI", 12) };
        field.TextChanged += (_, _) => { if (rendering) return; store.State.fields[id] = field.Text; store.State.unsaved = true; store.Changed(); statusText.Text = $"Company: {store.State.company_id}    |    Unsaved correction draft changes"; };
        content.Controls.Add(field); targets[id] = field;
    }
    void ShowDialogOverlay(string kind)
    {
        overlay = new Panel { Name = "dialog", Size = new(535, 235), BackColor = Color.White, BorderStyle = BorderStyle.FixedSingle, Location = new((ClientSize.Width - 535) / 2, 230) };
        string title = kind switch { "info" => "Accounting notice", "unsaved" => "Unsaved changes", _ => "Review workspace update" };
        overlay.Controls.Add(new Label { Text = title, Location = new(24, 24), AutoSize = true, Font = new("Segoe UI", 16, FontStyle.Bold) });
        overlay.Controls.Add(new Label { Text = kind == "unsaved" ? "This draft contains unsaved changes. Choose how to continue." : kind == "info" ? "You are working in a synthetic training company." : "A new review notice is available. Review it before continuing.", Location = new(24, 77), Size = new(480, 58) });
        var actions = kind switch { "info" => new[] { ("acknowledge", "Understood") }, "unsaved" => new[] { ("keep", "Keep editing"), ("discard", "Discard draft changes") }, _ => new[] { ("review", "Reviewed — continue") } };
        int x = 24;
        foreach (var (response, label) in actions)
        {
            var button = MakeButton("dialog-" + response, label, () => Apply("dialog", new { response }));
            button.SetBounds(x, 155, 230, 43); overlay.Controls.Add(button); x += 245;
        }
        Controls.Add(overlay); overlay.BringToFront();
    }

    object[] TargetGeometry()
    {
        var origin = PointToScreen(Point.Empty);
        return targets.Where(t => !t.Value.IsDisposed && t.Value.Visible).Select(t => {
            Rectangle r = t.Value.RectangleToScreen(t.Value.ClientRectangle);
            return (object)new { target = t.Key, label = t.Value.AccessibleName ?? t.Value.Text, x = r.X - origin.X + r.Width / 2.0, y = r.Y - origin.Y + r.Height / 2.0, width = r.Width, height = r.Height };
        }).ToArray();
    }
    string Screenshot()
    {
        Update(); content.Update(); overlay?.Update();
        using var image = new Bitmap(ClientSize.Width, ClientSize.Height);
        using (var graphics = Graphics.FromImage(image)) graphics.CopyFromScreen(PointToScreen(Point.Empty), Point.Empty, ClientSize);
        using var stream = new MemoryStream(); image.Save(stream, ImageFormat.Png);
        return Convert.ToBase64String(stream.ToArray());
    }
    object Observe() => new { state = store.State, targets = TargetGeometry(), width = ClientSize.Width, height = ClientSize.Height,
        foreground = GetForegroundWindow() == Handle, screenshot = Screenshot(), application = "DemoBooks Desktop", desktop_session = System.Diagnostics.Process.GetCurrentProcess().SessionId };

    void StartBridge()
    {
        try
        {
            listener = new HttpListener(); listener.Prefixes.Add("http://127.0.0.1:8765/"); listener.Start();
            _ = Task.Run(async () => {
                while (listener.IsListening)
                {
                    HttpListenerContext context;
                    try { context = await listener.GetContextAsync(); } catch { break; }
                    _ = HandleRequest(context);
                }
            });
            File.WriteAllText(Path.Combine(dataDir, "ready.json"), JsonSerializer.Serialize(new { pid = Environment.ProcessId, session = System.Diagnostics.Process.GetCurrentProcess().SessionId, bridge = "http://127.0.0.1:8765", started = DateTimeOffset.UtcNow }));
        }
        catch (Exception error) { statusText.Text = "Automation bridge unavailable: " + error.Message; File.WriteAllText(Path.Combine(dataDir, "bridge-error.txt"), error.ToString()); }
    }
    async Task HandleRequest(HttpListenerContext context)
    {
        try
        {
            string provided = context.Request.Headers["Authorization"] ?? "";
            if (!CryptographicOperations.FixedTimeEquals(Encoding.UTF8.GetBytes(provided), Encoding.UTF8.GetBytes("Bearer " + token))) { context.Response.StatusCode = 401; await Reply(context, new { error = "Authorization required" }); return; }
            string path = context.Request.Url!.AbsolutePath;
            string body = await new StreamReader(context.Request.InputStream).ReadToEndAsync();
            JsonElement data = JsonSerializer.SerializeToElement(new { });
            if (!string.IsNullOrWhiteSpace(body)) data = JsonDocument.Parse(body).RootElement.Clone();
            var completion = new TaskCompletionSource<object>(TaskCreationOptions.RunContinuationsAsynchronously);
            BeginInvoke(() => {
                try
                {
                    object result;
                    switch (path)
                    {
                        case "/health": result = new { status = "ok", application = "DemoBooks Desktop", version = store.State.app_version, session_id = System.Diagnostics.Process.GetCurrentProcess().SessionId }; break;
                        case "/state": result = store.State; break;
                        case "/observe": result = Observe(); break;
                        case "/scenario": store.Scenario(data); Render(); result = store.State; break;
                        case "/window": result = new { foreground = GetForegroundWindow() == Handle, minimized = WindowState == FormWindowState.Minimized }; break;
                        case "/activate": result = WindowActivation.Restore(this); break;
                        case "/action": result = ExecuteBridgeAction(data); break;
                        default: throw new ArgumentException("Unknown bridge endpoint");
                    }
                    // Serialize on the UI thread: state cannot change while it is encoded.
                    completion.SetResult(JsonSerializer.SerializeToElement(result));
                }
                catch (Exception error) { completion.SetException(error); }
            });
            var response = await completion.Task.WaitAsync(TimeSpan.FromSeconds(10));
            await Reply(context, response);
        }
        catch (Exception error) { context.Response.StatusCode = error is UnauthorizedAccessException ? 403 : 409; await Reply(context, new { error = error.Message }); }
    }
    object ExecuteBridgeAction(JsonElement data)
    {
        if (GetForegroundWindow() != Handle) throw new InvalidOperationException("DemoBooks must be the foreground application before an automated action");
        string name = data.GetProperty("name").GetString()!;
        JsonElement args = data.TryGetProperty("args", out var a) ? a : JsonSerializer.SerializeToElement(new { });
        scopedInvoice = data.TryGetProperty("invoice_id", out var invoice) ? invoice.GetString() : null;
        operationId = data.TryGetProperty("operation_id", out var op) ? op.GetString() : null;
        automated = true;
        try
        {
            if (data.TryGetProperty("revision", out var rev) && rev.GetInt32() != store.State.revision) throw new InvalidOperationException("Application revision changed before execution");
            if (name == "field")
            {
                if (store.State.dialog is not null || store.State.view != "invoice" || store.State.company_id != "ACME" || scopedInvoice != store.State.invoice_id) throw new UnauthorizedAccessException("Wrong company, invoice, or dialog state");
                string field = args.GetProperty("field").GetString()!;
                if (!new[] { "amount", "note" }.Contains(field) || !targets.TryGetValue(field, out var control) || control is not TextBox text) throw new UnauthorizedAccessException("Unknown draft field");
                text.Text = args.GetProperty("value").ToString();
            }
            else if (name == "click")
            {
                string target = args.GetProperty("target").GetString()!;
                if (store.State.dialog is not null && !target.StartsWith("dialog-")) throw new InvalidOperationException("Resolve the visible dialog first");
                if (!targets.TryGetValue(target, out var control) || control.IsDisposed || !control.Visible || control is not Button button) throw new ArgumentException("Target is unavailable");
                if (target.StartsWith("open-") && target != "open-" + scopedInvoice) throw new UnauthorizedAccessException("Target invoice is outside scope");
                actionError = null; button.PerformClick();
                if (actionError is not null) throw actionError;
            }
            else
            {
                // Staff mirror requests use the application's scoped API, not arbitrary desktop commands.
                store.Apply(name, args, operationId, scopedInvoice); Render();
            }
            return store.State;
        }
        finally { automated = false; operationId = null; scopedInvoice = null; }
    }
    static async Task Reply(HttpListenerContext context, object data)
    {
        byte[] bytes = JsonSerializer.SerializeToUtf8Bytes(data);
        context.Response.ContentType = "application/json"; context.Response.ContentLength64 = bytes.Length;
        await context.Response.OutputStream.WriteAsync(bytes); context.Response.Close();
    }
}
