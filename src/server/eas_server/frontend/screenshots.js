// Trusted renderer for data-only annotations. The model supplies neither SVG nor HTML.
function renderScreenshot(attachment) {
  if (!/^[a-zA-Z0-9_-]+\.png$/.test(attachment.screenshot || "")) return "";
  const width = Number(attachment.width), height = Number(attachment.height);
  if (!(width > 0 && height > 0 && width <= 20000 && height <= 20000)) return "";
  const stroke = Math.max(width, height) / 350;
  const shapes = (attachment.annotations || []).slice(0,12).map(a => {
    if (![a.x,a.y].every(v => Number.isFinite(v) && v >= 0 && v <= 1)) return "";
    const x = a.x*width, y = a.y*height, x2 = a.x2*width, y2 = a.y2*height;
    const color = {red:"#f43f5e",blue:"#38bdf8",yellow:"#facc15"}[a.color] || "#f43f5e";
    let shape = "";
    if (a.kind !== "text" && ![a.x2,a.y2].every(v => Number.isFinite(v) && v >= 0 && v <= 1)) return "";
    if (a.kind === "rectangle") shape = `<rect x="${Math.min(x,x2)}" y="${Math.min(y,y2)}" width="${Math.abs(x2-x)}" height="${Math.abs(y2-y)}"/>`;
    if (a.kind === "circle") shape = `<ellipse cx="${(x+x2)/2}" cy="${(y+y2)/2}" rx="${Math.abs(x2-x)/2}" ry="${Math.abs(y2-y)/2}"/>`;
    if (a.kind === "arrow") {
      const angle = Math.atan2(y2-y,x2-x), head = stroke*5;
      shape = `<path d="M ${x} ${y} L ${x2} ${y2} M ${x2-head*Math.cos(angle-.5)} ${y2-head*Math.sin(angle-.5)} L ${x2} ${y2} L ${x2-head*Math.cos(angle+.5)} ${y2-head*Math.sin(angle+.5)}"/>`;
    }
    const label = a.label ? `<text x="${x}" y="${Math.max(stroke*5,y-stroke*2)}" fill="${color}" stroke="#142434" stroke-width="${stroke/2}" paint-order="stroke" font-size="${stroke*5}" font-family="sans-serif">${esc(a.label)}</text>` : "";
    return `<g fill="none" stroke="${color}" stroke-width="${stroke}">${shape}</g>${label}`;
  }).join("");
  const captured = new Date(attachment.captured_at*1000);
  // Historical captures retain their original surface label after mediator removal.
  return `<figure class="chat-screenshot"><div class="chat-screenshot-image" style="--preview-width:${280*width/height}px"><img loading="lazy" width="${width}" height="${height}" src="/api/artifacts/${esc(attachment.screenshot)}" alt="${esc(attachment.caption)}"/><svg viewBox="0 0 ${width} ${height}" aria-hidden="true">${shapes}</svg></div><figcaption>${esc(attachment.caption)}<small>Captured ${esc(captured.toLocaleString())} · ${attachment.surface === "desktop" ? "Entire desktop" : attachment.surface === "mediated_application" ? "Mediated application view" : "Browser test viewport"}${shapes ? " · Agent annotations" : ""}</small><button type="button" class="screenshot-size" aria-expanded="false">Enlarge image</button></figcaption></figure>`;
}

document.addEventListener("click", event => {
  const button = event.target.closest(".screenshot-size");
  if (!button) return;
  const expanded = button.closest(".chat-screenshot").classList.toggle("expanded");
  button.setAttribute("aria-expanded", String(expanded));
  button.textContent = expanded ? "Fit in chat" : "Enlarge image";
});
