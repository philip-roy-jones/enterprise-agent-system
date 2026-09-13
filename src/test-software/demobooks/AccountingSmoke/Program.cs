using DemoBooks;
using System.Text.Json;

string directory = Path.Combine(Path.GetTempPath(), "eas-native-tests-" + Guid.NewGuid().ToString("N"));
int checks = 0;
void Check(bool test, string reason) { if (!test) throw new Exception(reason); checks++; }
JsonElement Args(object value) => JsonSerializer.SerializeToElement(value);
try
{
    var store = new AccountingStore(directory);
    Check(store.State.invoices.Count == 3, "Seed three synthetic invoices");
    store.Apply("open", Args(new { invoice_id = "INV-1043" }), scopedInvoice: "INV-1043");
    try { store.Apply("field", Args(new { field = "amount", value = "1" }), scopedInvoice: "INV-1042"); throw new Exception("Expected scope denial"); } catch (UnauthorizedAccessException) { checks++; }
    store.Apply("field", Args(new { field = "amount", value = "2400.00" }), scopedInvoice: "INV-1043");
    store.Apply("field", Args(new { field = "note", value = "Match PO-1043." }), scopedInvoice: "INV-1043");
    store.Scenario(Args(new { interrupt_save = true }));
    store.Apply("save", Args(new { }), "operation-1", "INV-1043");
    Check(store.State.dialog == "unfamiliar", "Interrupted confirmation leaves an unfamiliar dialog");
    Check(store.State.drafts.Single().amount == 240000, "Saved draft amount matches purchase order");
    Check(store.State.invoices.Single(i => i.id == "INV-1043").amount == 264000, "Original invoice remains unchanged");
    store = new AccountingStore(directory);
    Check(store.State.drafts.Count == 1 && store.State.dialog == "unfamiliar", "Restart recovers persisted external state");
    store.Apply("dialog", Args(new { response = "review" }));
    store.Apply("save", Args(new { }), "operation-1", "INV-1043");
    Check(store.State.save_requests == 1 && store.State.drafts.Count == 1, "Idempotency prevents duplicate native draft");
    store.Scenario(Args(new { dialog = "info" }));
    try { store.Apply("dialog", Args(new { response = "discard" })); throw new Exception("Expected response denial"); } catch (UnauthorizedAccessException) { checks++; }
    store.Apply("dialog", Args(new { response = "acknowledge" }));
    store.Scenario(Args(new { variant = "renamed", reordered = true }));
    Check(store.State.variant == "renamed" && store.State.reordered, "UI variants persist");
    store.Apply("field", Args(new { field = "note", value = "Unsaved edit" }), scopedInvoice: "INV-1043");
    store.Apply("navigate", Args(new { view = "dashboard" }));
    Check(store.State.dialog == "unsaved", "Navigation preserves unsaved work for a staff decision");
    Console.WriteLine($"{checks} native accounting invariants passed.");
}
finally { Directory.Delete(directory, true); }
