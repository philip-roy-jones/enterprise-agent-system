// Fold replayable public text chunks into one provisional or completed message.
const chatStream = (() => {
  function events(rows, status) {
    const partials = new Map(), completed = new Set(), ended = new Set();
    for (const row of rows) {
      const id = row.data.message_id;
      if (row.kind === "assistant_message_delta" && id && typeof row.data.text === "string") {
        if (!partials.has(id)) partials.set(id, {at:row.at, seq:row.seq, text:""});
        partials.get(id).text += row.data.text;
      }
      if (row.kind === "assistant_message") completed.add(id);
      if (row.kind === "assistant_stream_end") ended.add(id);
    }
    const result = rows.filter(row => !["assistant_message_delta", "assistant_stream_end"].includes(row.kind)).map(row => {
      const first = row.kind === "assistant_message" && partials.get(row.data.message_id);
      return first ? {...row, at:first.at, seq:first.seq} : row;
    });
    for (const [id, part] of partials) {
      if (completed.has(id)) continue;
      const interrupted = ended.has(id) || ["completed", "failed", "denied", "rejected", "cancelled"].includes(status);
      result.push({kind:"assistant_message", seq:part.seq, at:part.at, data:{text:part.text, message_id:id}, partial:true, interrupted});
    }
    return result.sort((a,b) => a.seq-b.seq);
  }
  return {events};
})();
