using System.Text.Json;
using System.Text.Json.Serialization;

namespace DemoBooks;

public record Invoice(string id, string company_id, string vendor, string po_id, long amount, long po_amount);
public record Draft(string id, string operation_id, string company_id, string invoice_id, long amount, string note, string status = "draft");

public sealed class AccountingState
{
    public int revision { get; set; } = 1;
    public string app_version { get; set; } = "demobooks-windows-1";
    public string company_id { get; set; } = "ACME";
    public string view { get; set; } = "dashboard";
    public string? invoice_id { get; set; }
    public string? dialog { get; set; }
    public double loading_until { get; set; }
    public bool unsaved { get; set; }
    public Dictionary<string, string> fields { get; set; } = new() { ["amount"] = "", ["note"] = "" };
    public string variant { get; set; } = "standard";
    public bool reordered { get; set; }
    public bool interrupt_save { get; set; }
    public List<Invoice> invoices { get; set; } = [
        new("INV-1042","ACME","Northstar Office Supply","PO-1042",148000,128000),
        new("INV-1043","ACME","Cedar IT Services","PO-1043",264000,240000),
        new("INV-1044","ACME","Atlas Packaging","PO-1044",97500,90000)];
    public List<Draft> drafts { get; set; } = [];
    public int save_requests { get; set; }
}

public sealed class AccountingStore
{
    public AccountingState State { get; private set; }
    readonly string path;
    public AccountingStore(string directory)
    {
        Directory.CreateDirectory(directory);
        path = Path.Combine(directory, "accounting-records.json");
        State = File.Exists(path) ? JsonSerializer.Deserialize<AccountingState>(File.ReadAllText(path))! : new();
        Persist();
    }
    public void Persist()
    {
        string temporary = path + ".tmp";
        File.WriteAllText(temporary, JsonSerializer.Serialize(State, new JsonSerializerOptions { WriteIndented = true }));
        File.Move(temporary, path, true);
    }
    public void Changed() { State.revision++; Persist(); }
    public static double Now => DateTimeOffset.UtcNow.ToUnixTimeMilliseconds() / 1000.0;
    public Invoice CurrentInvoice => State.invoices.Single(i => i.id == State.invoice_id && i.company_id == State.company_id);

    public void Apply(string action, JsonElement args, string? operationId = null, string? scopedInvoice = null)
    {
        var s = State;
        string Text(string key) => args.TryGetProperty(key, out var p) ? p.ToString() : "";
        if (s.loading_until > Now) throw new InvalidOperationException("Application is loading");
        if (s.dialog is not null && action != "dialog") throw new InvalidOperationException("Resolve the visible dialog first");
        switch (action)
        {
            case "navigate":
                if (s.unsaved) { s.dialog = "unsaved"; break; }
                if (!new[] { "dashboard", "invoices", "purchase_orders" }.Contains(Text("view"))) throw new ArgumentException("Unknown view");
                s.view = Text("view"); s.invoice_id = null; break;
            case "company":
                if (Text("company_id") != "ACME") throw new UnauthorizedAccessException("Company out of scope");
                s.company_id = "ACME"; break;
            case "open":
                if (scopedInvoice is not null && Text("invoice_id") != scopedInvoice) throw new UnauthorizedAccessException("Invoice out of scope");
                if (!s.invoices.Any(i => i.id == Text("invoice_id"))) throw new ArgumentException("Invoice does not exist");
                if (s.unsaved) { s.dialog = "unsaved"; break; }
                s.view = "invoice"; s.invoice_id = Text("invoice_id"); s.fields = new() { ["amount"] = "", ["note"] = "" }; break;
            case "dialog":
                string response = Text("response");
                bool permitted = s.dialog switch { "info" => response == "acknowledge", "unfamiliar" => response == "review", "unsaved" => response is "keep" or "discard", _ => false };
                if (!permitted) throw new UnauthorizedAccessException("Response is not applicable to this dialog");
                if (response == "discard") { s.unsaved = false; s.fields = new() { ["amount"] = "", ["note"] = "" }; }
                s.dialog = null; break;
            case "field":
            case "save":
                if (s.view != "invoice" || s.company_id != "ACME" || (scopedInvoice is not null && s.invoice_id != scopedInvoice)) throw new UnauthorizedAccessException("Wrong record or company");
                if (action == "field")
                {
                    if (!s.fields.ContainsKey(Text("field"))) throw new UnauthorizedAccessException("Field outside draft scope");
                    s.fields[Text("field")] = Text("value"); s.unsaved = true;
                }
                else
                {
                    if (string.IsNullOrWhiteSpace(operationId)) throw new ArgumentException("Operation ID required");
                    var existing = s.drafts.SingleOrDefault(d => d.operation_id == operationId);
                    if (existing is null)
                    {
                        if (!decimal.TryParse(s.fields["amount"], System.Globalization.NumberStyles.Number, System.Globalization.CultureInfo.InvariantCulture, out decimal amount)) throw new ArgumentException("Enter a valid correction amount");
                        long cents = checked((long)(amount * 100));
                        if (cents != CurrentInvoice.po_amount || string.IsNullOrWhiteSpace(s.fields["note"])) throw new UnauthorizedAccessException("Correction must match the purchase order and include an explanation");
                        s.drafts.Add(new($"DRAFT-{s.drafts.Count + 1:0000}", operationId, s.company_id, s.invoice_id!, cents, s.fields["note"]));
                        s.save_requests++;
                    }
                    else if (existing.invoice_id != s.invoice_id || existing.company_id != s.company_id) throw new UnauthorizedAccessException("Operation ID belongs to a different record");
                    s.unsaved = false;
                    if (s.interrupt_save) { s.interrupt_save = false; s.dialog = "unfamiliar"; }
                }
                break;
            default: throw new ArgumentException("Unknown accounting action");
        }
        Changed();
    }

    public void Scenario(JsonElement config)
    {
        foreach (var property in config.EnumerateObject())
        {
            switch (property.Name)
            {
                case "view": if (!new[] { "dashboard", "invoice", "invoices", "purchase_orders" }.Contains(property.Value.GetString())) throw new ArgumentException("Invalid view"); State.view = property.Value.GetString()!; break;
                case "invoice_id": State.invoice_id = property.Value.ValueKind == JsonValueKind.Null ? null : property.Value.GetString(); break;
                case "company_id": State.company_id = property.Value.GetString()!; break;
                case "dialog": var d = property.Value.ValueKind == JsonValueKind.Null ? null : property.Value.GetString(); if (d is not null && !new[] { "info", "unfamiliar", "unsaved" }.Contains(d)) throw new ArgumentException("Invalid dialog"); State.dialog = d; break;
                case "variant": if (!new[] { "standard", "renamed", "layout" }.Contains(property.Value.GetString())) throw new ArgumentException("Invalid UI variant"); State.variant = property.Value.GetString()!; break;
                case "reordered": State.reordered = property.Value.GetBoolean(); break;
                case "interrupt_save": State.interrupt_save = property.Value.GetBoolean(); break;
                case "unsaved": State.unsaved = property.Value.GetBoolean(); break;
                case "delay_seconds": State.loading_until = Now + Math.Clamp(property.Value.GetDouble(), 0, 15); break;
                default: throw new ArgumentException("Unknown scenario option");
            }
        }
        Changed();
    }
}
