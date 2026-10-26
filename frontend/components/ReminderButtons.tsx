'use client';

import React, { useCallback, useEffect, useState } from 'react';
import {
  Bell,
  BellOff,
  CalendarPlus,
  Check,
  Loader2,
} from 'lucide-react';

import { Button } from '@/components/ui/button';
import { cn } from '@/lib/models/utils';

const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE || 'http://127.0.0.1:8000';

interface ReminderButtonsProps {
  userId: string;
  eventName?: string | null;
  eventDate?: string | null;
  eventType?: string | null;
  className?: string;
  onReminderChange?: (active: boolean) => void;
}

interface Reminder {
  id?: string;
  _id?: string;

  event_name?: string | null;
  eventName?: string | null;
  name?: string | null;
  title?: string | null;

  event_date?: string | null;
  eventDate?: string | null;
  date?: string | null;

  event_type?: string | null;
  eventType?: string | null;
  type?: string | null;

  status?: string | null;
  reminder_offset?: string | null;
  reminderOffset?: string | null;
}

interface ReminderResponse {
  success?: boolean;
  reminders?: Reminder[];
  reminder?: Reminder | null;
  message?: string;
}

/**
 * Always convert API/user values into a safe string.
 *
 * This prevents:
 *   Cannot read properties of undefined/null
 *   inside normalizeName().
 */
function safeString(value: unknown): string {
  if (typeof value === 'string') {
    return value;
  }

  if (typeof value === 'number' || typeof value === 'boolean') {
    return String(value);
  }

  return '';
}

/**
 * Normalize reminder names safely.
 *
 * IMPORTANT:
 * Never call .trim(), .toLowerCase(), .replace(), etc.
 * directly on an unknown API value.
 */
function normalizeName(value: unknown): string {
  return safeString(value)
    .normalize('NFKC')
    .trim()
    .toLowerCase()
    .replace(/\s+/g, ' ')
    .replace(/[^\p{L}\p{N}\s]/gu, '');
}

/**
 * Get the actual reminder name regardless of which
 * field the backend returned.
 */
function getReminderName(reminder: Reminder): string {
  return safeString(
    reminder.event_name ??
      reminder.eventName ??
      reminder.name ??
      reminder.title
  );
}

/**
 * Get reminder ID safely.
 */
function getReminderId(reminder: Reminder): string {
  return safeString(reminder.id ?? reminder._id);
}

/**
 * Get event date safely.
 */
function getReminderDate(reminder: Reminder): string {
  return safeString(
    reminder.event_date ??
      reminder.eventDate ??
      reminder.date
  );
}

/**
 * Get event type safely.
 */
function getReminderType(reminder: Reminder): string {
  return safeString(
    reminder.event_type ??
      reminder.eventType ??
      reminder.type
  );
}

/**
 * Parse API JSON safely.
 */
async function readJson<T>(response: Response): Promise<T | null> {
  try {
    const text = await response.text();

    if (!text) {
      return null;
    }

    return JSON.parse(text) as T;
  } catch (error) {
    console.error('[ReminderButtons] Invalid JSON response:', error);
    return null;
  }
}

export default function ReminderButtons({
  userId,
  eventName,
  eventDate,
  eventType,
  className,
  onReminderChange,
}: ReminderButtonsProps) {
  const [isReminderActive, setIsReminderActive] = useState(false);
  const [checking, setChecking] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  /**
   * Safe values derived from props.
   */
  const normalizedEventName = normalizeName(eventName);
  const safeEventName =
    safeString(eventName).trim() || 'Event reminder';

  const safeEventDate = safeString(eventDate).trim();
  const safeEventType =
    safeString(eventType).trim() || 'event';

  /**
   * Check whether this event already has a reminder.
   */
  const checkReminderStatus = useCallback(async () => {
    if (!userId || !normalizedEventName) {
      setIsReminderActive(false);
      setChecking(false);
      return;
    }

    setChecking(true);
    setError(null);

    try {
      const url =
        `${API_BASE}/api/reminders/upcoming` +
        `?userId=${encodeURIComponent(userId)}`;

      const response = await fetch(url, {
        method: 'GET',
        headers: {
          Accept: 'application/json',
        },
        cache: 'no-store',
      });

      if (!response.ok) {
        throw new Error(
          `Reminder status request failed: ${response.status}`
        );
      }

      const data = await readJson<ReminderResponse>(response);

      if (!data?.success) {
        setIsReminderActive(false);
        return;
      }

      /**
       * IMPORTANT:
       * API may return:
       *   reminders: undefined
       *   reminders: null
       *   reminders: [...]
       *
       * Never call .some() on an unknown value.
       */
      const reminders: Reminder[] = Array.isArray(data.reminders)
        ? data.reminders
        : [];

      const existing = reminders.some((reminder) => {
        if (!reminder || typeof reminder !== 'object') {
          return false;
        }

        const reminderName = normalizeName(
          getReminderName(reminder)
        );

        if (!reminderName) {
          return false;
        }

        return reminderName === normalizedEventName;
      });

      setIsReminderActive(existing);
      onReminderChange?.(existing);
    } catch (err) {
      console.error(
        '[ReminderButtons] Failed to check reminder status:',
        err
      );

      /**
       * Do not crash the React tree if the backend is unavailable.
       */
      setIsReminderActive(false);
    } finally {
      setChecking(false);
    }
  }, [
    userId,
    normalizedEventName,
    onReminderChange,
  ]);

  useEffect(() => {
    void checkReminderStatus();
  }, [checkReminderStatus]);

  /**
   * Create reminder.
   */
  const handleSetReminder = useCallback(async () => {
    if (!userId) {
      setError('User is not available.');
      return;
    }

    if (!safeEventName.trim()) {
      setError('Event name is required.');
      return;
    }

    if (!safeEventDate) {
      setError('Event date and time are required.');
      return;
    }

    setSaving(true);
    setError(null);

    try {
      const response = await fetch(
        `${API_BASE}/api/reminders`,
        {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            Accept: 'application/json',
          },
          body: JSON.stringify({
            userId,
            event_name: safeEventName,
            event_date: safeEventDate,
            event_type: safeEventType,
            source_type: safeEventType,
            reminder_offset: '1 day',
          }),
        }
      );

      const data = await readJson<ReminderResponse>(response);

      if (!response.ok || data?.success === false) {
        throw new Error(
          data?.message ||
            `Failed to create reminder (${response.status})`
        );
      }

      setIsReminderActive(true);
      onReminderChange?.(true);
    } catch (err) {
      console.error(
        '[ReminderButtons] Failed to create reminder:',
        err
      );

      setError(
        err instanceof Error
          ? err.message
          : 'Failed to create reminder.'
      );
    } finally {
      setSaving(false);
    }
  }, [
    userId,
    safeEventName,
    safeEventDate,
    safeEventType,
    onReminderChange,
  ]);

  /**
   * Delete/cancel reminder.
   */
  const handleCancelReminder = useCallback(async () => {
    if (!userId || !normalizedEventName) {
      return;
    }

    setSaving(true);
    setError(null);

    try {
      const url =
        `${API_BASE}/api/reminders` +
        `?userId=${encodeURIComponent(userId)}`;

      const response = await fetch(url, {
        method: 'GET',
        headers: {
          Accept: 'application/json',
        },
        cache: 'no-store',
      });

      if (!response.ok) {
        throw new Error(
          `Failed to load reminders (${response.status})`
        );
      }

      const data = await readJson<ReminderResponse>(response);

      const reminders: Reminder[] = Array.isArray(data?.reminders)
        ? data!.reminders!
        : [];

      const existing = reminders.find((reminder) => {
        if (!reminder || typeof reminder !== 'object') {
          return false;
        }

        return (
          normalizeName(getReminderName(reminder)) ===
          normalizedEventName
        );
      });

      if (!existing) {
        setIsReminderActive(false);
        onReminderChange?.(false);
        return;
      }

      const reminderId = getReminderId(existing);

      if (!reminderId) {
        throw new Error(
          'Reminder exists but has no valid ID.'
        );
      }

      const deleteResponse = await fetch(
        `${API_BASE}/api/reminders/${encodeURIComponent(
          reminderId
        )}?userId=${encodeURIComponent(userId)}`,
        {
          method: 'DELETE',
          headers: {
            Accept: 'application/json',
          },
        }
      );

      if (!deleteResponse.ok) {
        const deleteData =
          await readJson<ReminderResponse>(deleteResponse);

        throw new Error(
          deleteData?.message ||
            `Failed to cancel reminder (${deleteResponse.status})`
        );
      }

      setIsReminderActive(false);
      onReminderChange?.(false);
    } catch (err) {
      console.error(
        '[ReminderButtons] Failed to cancel reminder:',
        err
      );

      setError(
        err instanceof Error
          ? err.message
          : 'Failed to cancel reminder.'
      );
    } finally {
      setSaving(false);
    }
  }, [
    userId,
    normalizedEventName,
    onReminderChange,
  ]);

  if (!userId) {
    return null;
  }

  return (
    <div className={cn('flex flex-col gap-1', className)}>
      <div className="flex items-center gap-2">
        {checking ? (
          <Button
            type="button"
            size="sm"
            variant="outline"
            disabled
            className="gap-2"
          >
            <Loader2 className="h-4 w-4 animate-spin" />
            Checking...
          </Button>
        ) : isReminderActive ? (
          <Button
            type="button"
            size="sm"
            variant="outline"
            onClick={() => void handleCancelReminder()}
            disabled={saving}
            className="gap-2"
          >
            {saving ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <BellOff className="h-4 w-4" />
            )}

            {saving
              ? 'Updating...'
              : 'Reminder set'}
          </Button>
        ) : (
          <Button
            type="button"
            size="sm"
            variant="outline"
            onClick={() => void handleSetReminder()}
            disabled={
              saving ||
              !normalizedEventName ||
              !safeEventDate
            }
            className="gap-2"
          >
            {saving ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <CalendarPlus className="h-4 w-4" />
            )}

            {saving
              ? 'Setting...'
              : 'Set reminder'}
          </Button>
        )}

        {isReminderActive && !saving && (
          <Check className="h-4 w-4 text-green-500" />
        )}
      </div>

      {error && (
        <p className="text-[11px] text-destructive">
          {error}
        </p>
      )}
    </div>
  );
}