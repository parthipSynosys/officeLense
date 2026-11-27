import { useEffect, useId, useState, type FormEvent } from "react";
import { Button } from "@/components/Button";
import { Modal } from "@/components/Modal";
import { Alert, errorMessage } from "@/components/States";
import { EVENT_TYPES, type AdminEvent, type EventInput, type EventType } from "@/lib/api";
import { todayIso } from "@/lib/format";

interface Props {
  open: boolean;
  event?: AdminEvent | null; // edit mode when set
  onClose: () => void;
  onSubmit: (input: EventInput) => Promise<void>;
}

const EMPTY: EventInput = { name: "", type: "Conference", event_date: todayIso(), description: "", is_published: false };

export function EventFormModal({ open, event, onClose, onSubmit }: Props) {
  const ids = { name: useId(), type: useId(), date: useId(), desc: useId(), pub: useId() };
  const [form, setForm] = useState<EventInput>(EMPTY);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<unknown>(null);

  useEffect(() => {
    if (!open) return;
    setError(null);
    setForm(
      event
        ? { name: event.name, type: event.type, event_date: event.event_date, description: event.description, is_published: event.is_published }
        : { ...EMPTY, event_date: todayIso() },
    );
  }, [open, event]);

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!form.name.trim()) return;
    setSaving(true);
    setError(null);
    try {
      await onSubmit({ ...form, name: form.name.trim() });
      onClose();
    } catch (err) {
      setError(err);
    } finally {
      setSaving(false);
    }
  }

  const set = <K extends keyof EventInput>(k: K, v: EventInput[K]) => setForm((f) => ({ ...f, [k]: v }));

  return (
    <Modal
      open={open}
      onClose={onClose}
      dismissible={!saving}
      title={event ? "Edit event" : "New event"}
      description={event ? undefined : "Create the event first, then upload its photos."}
      footer={
        <>
          <Button variant="secondary" onClick={onClose} disabled={saving}>
            Cancel
          </Button>
          <Button type="submit" form="event-form" loading={saving} disabled={!form.name.trim()}>
            {event ? "Save changes" : "Create event"}
          </Button>
        </>
      }
    >
      <form id="event-form" onSubmit={submit} className="space-y-4 pb-2">
        {error ? <Alert tone="danger">{errorMessage(error)}</Alert> : null}
        <div>
          <label htmlFor={ids.name} className="label">
            Event name
          </label>
          <input
            id={ids.name}
            className="input"
            value={form.name}
            maxLength={200}
            required
            placeholder="Annual Day 2025"
            onChange={(e) => set("name", e.target.value)}
            data-autofocus
          />
        </div>
        <div className="grid gap-4 sm:grid-cols-2">
          <div>
            <label htmlFor={ids.type} className="label">
              Type
            </label>
            <select id={ids.type} className="input" value={form.type} onChange={(e) => set("type", e.target.value as EventType)}>
              {EVENT_TYPES.map((t) => (
                <option key={t} value={t}>
                  {t}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label htmlFor={ids.date} className="label">
              Date
            </label>
            <input id={ids.date} type="date" className="input" value={form.event_date} required onChange={(e) => set("event_date", e.target.value)} />
          </div>
        </div>
        <div>
          <label htmlFor={ids.desc} className="label">
            Description <span className="font-normal text-ink-subtle">(optional)</span>
          </label>
          <textarea
            id={ids.desc}
            className="input min-h-[96px]"
            maxLength={5000}
            value={form.description}
            onChange={(e) => set("description", e.target.value)}
          />
        </div>
        <label htmlFor={ids.pub} className="flex cursor-pointer items-start gap-3 rounded-2xl border border-line p-3">
          <input
            id={ids.pub}
            type="checkbox"
            className="mt-0.5 h-5 w-5 accent-primary"
            checked={form.is_published}
            onChange={(e) => set("is_published", e.target.checked)}
          />
          <span className="text-sm">
            <span className="font-semibold text-ink">Published</span>
            <span className="block text-ink-muted">Guests can see and search this event.</span>
          </span>
        </label>
      </form>
    </Modal>
  );
}
