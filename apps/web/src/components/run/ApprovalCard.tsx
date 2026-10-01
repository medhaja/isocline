"use client";
import { useState } from "react";
import { Button, Textarea, toast } from "@/components/ui";
import { api, errorMessage } from "@/lib/api";
import { ago, toText } from "@/lib/format";
import type { Approval } from "@/lib/types";

export default function ApprovalCard({ approval, onDecided }: { approval: Approval; onDecided?: () => void }) {
  const original = toText(approval.content);
  const [text, setText] = useState(original);
  const [comment, setComment] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const pending = approval.status === "pending";

  async function decide(decision: "approved" | "rejected") {
    setBusy(decision);
    try {
      const edited = approval.allow_edit && text !== original ? (typeof approval.content === "string" ? text : safeParse(text)) : null;
      await api(`/approvals/${approval.id}/decide`, { body: { decision, comment: comment || null, edited_content: edited } });
      toast(decision === "approved" ? "Approved — the run is resuming" : "Rejected — the run continues on the rejected branch");
      onDecided?.();
    } catch (e) { toast(errorMessage(e), "error"); } finally { setBusy(null); }
  }

  return (
    <div className="rounded-lg border-2 border-state-waiting/40 bg-paper p-4">
      <div className="flex items-start justify-between gap-3">
        <div><h3 className="font-semibold text-ink-900">{approval.title}</h3>
          <p className="text-xs text-ink-400">{approval.workflow_name ? `${approval.workflow_name} · ` : ""}requested {ago(approval.created_at)}</p></div>
        {!pending && <span className="text-sm font-medium capitalize text-ink-600">{approval.status}</span>}
      </div>
      {approval.instructions && <p className="mt-2 text-sm text-ink-700">{approval.instructions}</p>}
      <div className="mt-3">
        {pending && approval.allow_edit ? (
          <Textarea rows={10} mono={typeof approval.content !== "string"} value={text} onChange={(e) => setText(e.target.value)} aria-label="Content to review" />
        ) : <pre className="max-h-72 overflow-auto whitespace-pre-wrap rounded-md bg-canvas p-3 text-sm">{toText(approval.edited_content ?? approval.content)}</pre>}
        {pending && approval.allow_edit && text !== original && <p className="mt-1 text-xs text-warn">Your edits will be passed downstream instead of the original.</p>}
      </div>
      {pending ? (
        <>
          <Textarea className="mt-3" rows={2} placeholder="Comment (optional)" value={comment} onChange={(e) => setComment(e.target.value)} />
          <div className="mt-3 flex justify-end gap-2">
            <Button onClick={() => decide("rejected")} loading={busy === "rejected"} disabled={!!busy}>Reject</Button>
            <Button variant="primary" onClick={() => decide("approved")} loading={busy === "approved"} disabled={!!busy}>Approve</Button>
          </div>
        </>
      ) : approval.comment && <p className="mt-2 text-sm text-ink-600">“{approval.comment}”</p>}
    </div>
  );
}

function safeParse(t: string) { try { return JSON.parse(t); } catch { return t; } }
