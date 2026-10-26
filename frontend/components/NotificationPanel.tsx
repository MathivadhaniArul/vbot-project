'use client';

import React, {
  useState,
  useEffect,
  useCallback,
  useRef,
} from 'react';

import { Button } from '@/components/ui/button';
import { ScrollArea } from '@/components/ui/scroll-area';
import { cn } from '@/lib/models/utils';

import {
  Bell,
  X,
  Check,
  Clock,
  Trash2,
  Loader2,
  Calendar,
  Info,
  CalendarCheck,
  Plus,
} from 'lucide-react';

const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE || 'http://127.0.0.1:8000';

/* -------------------------------------------------------------------------- */
/* Types                                                                      */
/* -------------------------------------------------------------------------- */

interface Notification {
  id?: string;
  reminder_id?: string;
  title?: string;
  message?: string;
  read?: boolean;
  event_date?: string;
  created_at?: string;
}

interface UpcomingReminder {
  id?: string;
  event_name?: string;
  event_date?: string;
  source_type?: string;
  reminder_offset?: string;
  days_remaining?: number;
  status?: string;
}

interface NotificationPanelProps {
  userId: string;
  isOpen: boolean;
  onClose: () => void;
  onUnreadCountChange?: (count: number) => void;
  onAddReminder?: () => void;
}

/* -------------------------------------------------------------------------- */
/* Helpers                                                                    */
/* -------------------------------------------------------------------------- */

/**
 * Convert an arbitrary API value into a safe array.
 *
 * This prevents:
 *   Cannot read properties of undefined (reading 'map')
 *
 * when the backend temporarily returns a missing field.
 */
function safeArray<T>(value: unknown): T[] {
  return Array.isArray(value) ? (value as T[]) : [];
}

/**
 * React requires every sibling produced by .map() to have a unique key.
 *
 * Backend IDs should normally be unique, but this function also protects
 * against:
 *
 *   - missing id
 *   - duplicate id
 *   - missing reminder_id
 *
 * The array index is only used as the final uniqueness fallback.
 */
function notificationKey(
  notification: Notification,
  index: number
): string {
  const id =
    notification.id ||
    notification.reminder_id ||
    'notification';

  const created =
    notification.created_at ||
    notification.event_date ||
    'unknown';

  return `notification-${id}-${created}-${index}`;
}

function reminderKey(
  reminder: UpcomingReminder,
  index: number
): string {
  const id =
    reminder.id ||
    reminder.event_name ||
    'reminder';

  const eventDate =
    reminder.event_date ||
    'unknown';

  return `reminder-${id}-${eventDate}-${index}`;
}

/**
 * Safely display dates.
 */
function formatDate(dateStr?: string): string {
  if (!dateStr) {
    return 'Date not specified';
  }

  const date = new Date(dateStr);

  if (Number.isNaN(date.getTime())) {
    return dateStr;
  }

  return date.toLocaleDateString('en-US', {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    timeZone: 'Asia/Kolkata',
  });
}

/**
 * Relative time for notifications.
 */
function getRelativeTime(dateStr?: string): string {
  if (!dateStr) {
    return '';
  }

  const date = new Date(dateStr);

  if (Number.isNaN(date.getTime())) {
    return '';
  }

  const diffMs = Date.now() - date.getTime();

  const diffMin = Math.floor(diffMs / 60000);

  if (diffMin < 1) {
    return 'Just now';
  }

  if (diffMin < 60) {
    return `${diffMin}m ago`;
  }

  const diffHrs = Math.floor(diffMin / 60);

  if (diffHrs < 24) {
    return `${diffHrs}h ago`;
  }

  const diffDays = Math.floor(diffHrs / 24);

  if (diffDays === 1) {
    return 'Yesterday';
  }

  return date.toLocaleDateString('en-US', {
    month: 'short',
    day: 'numeric',
    timeZone: 'Asia/Kolkata',
  });
}

/* -------------------------------------------------------------------------- */
/* Component                                                                  */
/* -------------------------------------------------------------------------- */

export default function NotificationPanel({
  userId,
  isOpen,
  onClose,
  onUnreadCountChange,
  onAddReminder,
}: NotificationPanelProps) {
  const [activeTab, setActiveTab] = useState<
    'notifications' | 'upcoming'
  >('notifications');

  const [notifications, setNotifications] = useState<Notification[]>([]);
  const [reminders, setReminders] = useState<UpcomingReminder[]>([]);

  const [loading, setLoading] = useState(false);

  const [actioningId, setActioningId] = useState<string | null>(
    null
  );

  /**
   * Prevent an older request from overwriting newer state.
   */
  const requestIdRef = useRef(0);

  /**
   * Report the unread count to the parent only after render/commit,
   * never from inside a setState updater (which runs during render
   * and would otherwise trigger React's "Cannot update a component
   * while rendering a different component" warning/error).
   */
  useEffect(() => {
    const unread = notifications.filter(
      (notification) => notification.read !== true
    ).length;

    onUnreadCountChange?.(unread);
  }, [notifications, onUnreadCountChange]);

  /* ------------------------------------------------------------------------ */
  /* Fetch                                                                    */
  /* ------------------------------------------------------------------------ */

  const fetchData = useCallback(async () => {
    if (!userId) {
      setNotifications([]);
      setReminders([]);
      return;
    }

    const currentRequestId = ++requestIdRef.current;

    setLoading(true);

    try {
      const [notifRes, remRes] = await Promise.all([
        fetch(
          `${API_BASE}/api/notifications?userId=${encodeURIComponent(
            userId
          )}`,
          {
            cache: 'no-store',
          }
        ),

        fetch(
          `${API_BASE}/api/reminders/upcoming?userId=${encodeURIComponent(
            userId
          )}`,
          {
            cache: 'no-store',
          }
        ),
      ]);

      let notifData: any = {};
      let remData: any = {};

      try {
        notifData = await notifRes.json();
      } catch {
        notifData = {};
      }

      try {
        remData = await remRes.json();
      } catch {
        remData = {};
      }

      /**
       * Ignore stale requests.
       */
      if (currentRequestId !== requestIdRef.current) {
        return;
      }

      /* ---------------------------- Notifications ------------------------ */

      if (notifRes.ok && notifData?.success) {
        const nextNotifications = safeArray<Notification>(
          notifData.notifications
        );

        setNotifications(nextNotifications);
      } else {
        /**
         * Don't destroy existing data on a temporary backend error.
         */
        console.warn(
          'Notifications API returned an error:',
          notifData
        );
      }

      /* ------------------------------- Reminders ------------------------- */

      if (remRes.ok && remData?.success) {
        const nextReminders = safeArray<UpcomingReminder>(
          remData.reminders
        );

        setReminders(nextReminders);
      } else {
        console.warn(
          'Reminders API returned an error:',
          remData
        );
      }
    } catch (error) {
      console.error(
        'Failed to load notifications/reminders:',
        error
      );
    } finally {
      if (currentRequestId === requestIdRef.current) {
        setLoading(false);
      }
    }
  }, [userId, onUnreadCountChange]);

  /* ------------------------------------------------------------------------ */
  /* Open / refresh                                                           */
  /* ------------------------------------------------------------------------ */

  useEffect(() => {
    if (!isOpen) {
      return;
    }

    fetchData();
  }, [isOpen, fetchData]);

  /**
   * Refresh every 30 seconds while panel is open.
   */
  useEffect(() => {
    if (!isOpen) {
      return;
    }

    const interval = window.setInterval(() => {
      fetchData();
    }, 30_000);

    return () => {
      window.clearInterval(interval);
    };
  }, [isOpen, fetchData]);

  /* ------------------------------------------------------------------------ */
  /* Mark notification read                                                   */
  /* ------------------------------------------------------------------------ */

  const handleMarkRead = async (id?: string) => {
    if (!id) {
      return;
    }

    setActioningId(id);

    try {
      const res = await fetch(
        `${API_BASE}/api/notifications/${encodeURIComponent(
          id
        )}/read?userId=${encodeURIComponent(userId)}`,
        {
          method: 'PATCH',
        }
      );

      if (!res.ok) {
        throw new Error(
          `Mark-read failed with status ${res.status}`
        );
      }

      let readData: any = {};
      try {
        readData = await res.json();
      } catch {
        readData = {};
      }

      if (readData?.success === false) {
        throw new Error(
          'Mark-read failed: notification not found or already updated'
        );
      }

      let dismissedReminderId: string | undefined;

      setNotifications((previous) => {
        const target = previous.find(
          (notification) => notification.id === id
        );
        dismissedReminderId = target?.reminder_id;

        const next = previous.map((notification) =>
          notification.id === id
            ? {
                ...notification,
                read: true,
              }
            : notification
        );

        return next;
      });

      // Dismissing the alert also clears its entry from the
      // Scheduled tab, since the user has already acknowledged it.
      // This only updates local UI state — the reminder stays
      // "pending" server-side so email/calendar/completion jobs
      // still fire on schedule.
      if (dismissedReminderId) {
        setReminders((previous) =>
          previous.filter(
            (reminder) => reminder.id !== dismissedReminderId
          )
        );
      }
    } catch (error) {
      console.error(
        'Failed to mark notification as read:',
        error
      );
    } finally {
      setActioningId(null);
    }
  };

  /* ------------------------------------------------------------------------ */
  /* Snooze                                                                    */
  /* ------------------------------------------------------------------------ */

  const handleSnooze = async (
    reminderId: string | undefined,
    minutes: number
  ) => {
    if (!reminderId) {
      return;
    }

    setActioningId(reminderId);

    try {
      const res = await fetch(
        `${API_BASE}/api/notifications/${encodeURIComponent(
          reminderId
        )}/snooze`,
        {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
          },
          body: JSON.stringify({
            userId,
            snoozeMinutes: minutes,
          }),
        }
      );

      if (!res.ok) {
        throw new Error(
          `Snooze failed with status ${res.status}`
        );
      }

      let snoozeData: any = {};
      try {
        snoozeData = await res.json();
      } catch {
        snoozeData = {};
      }

      if (snoozeData?.success === false) {
        throw new Error(
          'Snooze failed: reminder not found or already updated'
        );
      }

      setNotifications((previous) =>
        previous.filter(
          (notification) => notification.reminder_id !== reminderId
        )
      );

      /**
       * Refresh scheduled reminders after snooze.
       */
      await fetchData();
    } catch (error) {
      console.error(
        'Failed to snooze notification:',
        error
      );
    } finally {
      setActioningId(null);
    }
  };

  /* ------------------------------------------------------------------------ */
  /* Cancel reminder                                                          */
  /* ------------------------------------------------------------------------ */

  const handleCancelReminder = async (
    id?: string
  ) => {
    if (!id) {
      return;
    }

    const confirmed = window.confirm(
      'Are you sure you want to cancel this reminder?'
    );

    if (!confirmed) {
      return;
    }

    setActioningId(id);

    try {
      const res = await fetch(
        `${API_BASE}/api/reminders/${encodeURIComponent(
          id
        )}?userId=${encodeURIComponent(userId)}`,
        {
          method: 'DELETE',
        }
      );

      if (!res.ok) {
        throw new Error(
          `Cancel reminder failed with status ${res.status}`
        );
      }

      setReminders((previous) =>
        previous.filter(
          (reminder) => reminder.id !== id
        )
      );
    } catch (error) {
      console.error(
        'Failed to cancel reminder:',
        error
      );
    } finally {
      setActioningId(null);
    }
  };

  /* ------------------------------------------------------------------------ */
  /* Derived state                                                            */
  /* ------------------------------------------------------------------------ */

  const unreadNotifications = notifications.filter(
    (notification) => notification.read !== true
  );

  /* ------------------------------------------------------------------------ */
  /* Render                                                                   */
  /* ------------------------------------------------------------------------ */

  return (
    <>
      {/* ------------------------------------------------------------------ */}
      {/* Backdrop                                                           */}
      {/* ------------------------------------------------------------------ */}

      {isOpen && (
        <div
          onClick={onClose}
          className="fixed inset-0 z-40 bg-black/30 backdrop-blur-[2px] transition-opacity duration-300 animate-fadeIn"
          aria-hidden="true"
        />
      )}

      {/* ------------------------------------------------------------------ */}
      {/* Panel                                                              */}
      {/* ------------------------------------------------------------------ */}

      <div
        className={cn(
          'fixed top-0 right-0 h-screen w-80 sm:w-96 z-50',
          'bg-card/95 backdrop-blur-md',
          'border-l border-border/40 shadow-2xl',
          'flex flex-col',
          'transition-transform duration-300 ease-out transform',
          isOpen
            ? 'translate-x-0'
            : 'translate-x-full'
        )}
        role="dialog"
        aria-modal="true"
        aria-label="Alerts and reminders"
      >
        {/* ---------------------------------------------------------------- */}
        {/* Header                                                           */}
        {/* ---------------------------------------------------------------- */}

        <div className="p-4 border-b border-border/30 flex items-center justify-between">
          <h3 className="font-semibold text-lg text-foreground flex items-center gap-2">
            <Bell className="w-5 h-5 text-primary" />
            Alerts & Reminders
          </h3>

          <Button
            variant="ghost"
            size="icon"
            onClick={onClose}
            className="rounded-full w-8 h-8"
            aria-label="Close notifications"
          >
            <X className="w-4 h-4" />
          </Button>
        </div>

        {/* ---------------------------------------------------------------- */}
        {/* Add Reminder                                                     */}
        {/* ---------------------------------------------------------------- */}

        {onAddReminder && (
          <div className="px-4 pt-3 pb-1">
            <Button
              type="button"
              variant="outline"
              onClick={onAddReminder}
              className="w-full h-9 justify-center gap-2 text-sm"
            >
              <Plus className="w-4 h-4" />
              Add Reminder
            </Button>
          </div>
        )}

        {/* ---------------------------------------------------------------- */}
        {/* Tabs                                                             */}
        {/* ---------------------------------------------------------------- */}

        <div className="flex border-b border-border/30 px-2 py-1 gap-1">
          <button
            type="button"
            onClick={() =>
              setActiveTab('notifications')
            }
            className={cn(
              'flex-1 py-2 text-xs font-medium rounded-lg',
              'transition-colors cursor-pointer',
              activeTab === 'notifications'
                ? 'bg-muted text-foreground'
                : 'text-muted-foreground hover:text-foreground'
            )}
          >
            Notifications ({unreadNotifications.length})
          </button>

          <button
            type="button"
            onClick={() =>
              setActiveTab('upcoming')
            }
            className={cn(
              'flex-1 py-2 text-xs font-medium rounded-lg',
              'transition-colors cursor-pointer',
              activeTab === 'upcoming'
                ? 'bg-muted text-foreground'
                : 'text-muted-foreground hover:text-foreground'
            )}
          >
            Scheduled ({reminders.length})
          </button>
        </div>

        {/* ---------------------------------------------------------------- */}
        {/* Content                                                          */}
        {/* ---------------------------------------------------------------- */}

        <ScrollArea className="flex-1 p-4">
          {loading &&
          notifications.length === 0 &&
          reminders.length === 0 ? (
            <LoadingState />
          ) : activeTab === 'notifications' ? (
            <NotificationsTab
              notifications={unreadNotifications}
              actioningId={actioningId}
              onMarkRead={handleMarkRead}
              onSnooze={handleSnooze}
            />
          ) : (
            <UpcomingTab
              reminders={reminders}
              actioningId={actioningId}
              onCancel={handleCancelReminder}
            />
          )}
        </ScrollArea>
      </div>
    </>
  );
}

/* ========================================================================== */
/* Loading                                                                    */
/* ========================================================================== */

function LoadingState() {
  return (
    <div className="flex flex-col items-center justify-center py-20 text-muted-foreground gap-2">
      <Loader2 className="w-6 h-6 animate-spin text-primary" />

      <p className="text-xs">
        Loading records...
      </p>
    </div>
  );
}

/* ========================================================================== */
/* Notifications Tab                                                         */
/* ========================================================================== */

interface NotificationsTabProps {
  notifications: Notification[];
  actioningId: string | null;
  onMarkRead: (id?: string) => void;
  onSnooze: (
    id: string | undefined,
    minutes: number
  ) => void;
}

function NotificationsTab({
  notifications,
  actioningId,
  onMarkRead,
  onSnooze,
}: NotificationsTabProps) {
  if (notifications.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-20 text-muted-foreground gap-2">
        <Info className="w-8 h-8 opacity-40" />

        <p className="text-xs">
          No active notifications
        </p>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-3">
      {notifications.map(
        (notification, index) => {
          const id = notification.id;
          const reminderId = notification.reminder_id;

          return (
            <div
              key={notificationKey(
                notification,
                index
              )}
              className={cn(
                'p-3 rounded-xl border transition-all text-xs',
                notification.read
                  ? 'bg-muted/10 border-border/20 opacity-60'
                  : 'bg-primary/5 border-primary/20 shadow-sm'
              )}
            >
              {/* Title / time */}
              <div className="flex justify-between items-start gap-2">
                <p className="font-semibold text-foreground">
                  {notification.title ||
                    'Reminder'}
                </p>

                <span className="text-[10px] text-muted-foreground flex-shrink-0">
                  {getRelativeTime(
                    notification.created_at
                  )}
                </span>
              </div>

              {/* Message */}
              <p className="text-muted-foreground mt-1 leading-normal">
                {notification.message ||
                  'You have a scheduled reminder.'}
              </p>

              {/* Event date */}
              {notification.event_date && (
                <p className="text-[10px] text-muted-foreground mt-2 flex items-center gap-1">
                  <Calendar className="w-3 h-3" />

                  {formatDate(
                    notification.event_date
                  )}
                </p>
              )}

              {/* Actions */}
              {!notification.read && (
                <div className="flex items-center gap-2 mt-3 pt-2 border-t border-border/10 justify-end">
                  <DropdownSnoozeButton
                    onSnooze={(minutes) =>
                      onSnooze(reminderId, minutes)
                    }
                    disabled={
                      actioningId === reminderId ||
                      !reminderId
                    }
                  />

                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() =>
                      onMarkRead(id)
                    }
                    disabled={
                      !id ||
                      actioningId === id
                    }
                    className="h-7 px-2 text-[10px] gap-1"
                  >
                    {actioningId === id ? (
                      <Loader2 className="w-3 h-3 animate-spin" />
                    ) : (
                      <>
                        <Check className="w-3.5 h-3.5" />
                        Dismiss
                      </>
                    )}
                  </Button>
                </div>
              )}
            </div>
          );
        }
      )}
    </div>
  );
}

/* ========================================================================== */
/* Upcoming Reminders Tab                                                     */
/* ========================================================================== */

interface UpcomingTabProps {
  reminders: UpcomingReminder[];
  actioningId: string | null;
  onCancel: (id?: string) => void;
}

function UpcomingTab({
  reminders,
  actioningId,
  onCancel,
}: UpcomingTabProps) {
  if (reminders.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-20 text-muted-foreground gap-2">
        <CalendarCheck className="w-8 h-8 opacity-40" />

        <p className="text-xs">
          No reminders scheduled
        </p>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-3">
      {reminders.map(
        (reminder, index) => {
          const id = reminder.id;

          const daysRemaining =
            typeof reminder.days_remaining ===
            'number'
              ? reminder.days_remaining
              : null;

          return (
            <div
              key={reminderKey(
                reminder,
                index
              )}
              className="p-3 rounded-xl border border-border/30 bg-muted/20 text-xs flex flex-col justify-between"
            >
              {/* Main information */}
              <div>
                <div className="flex justify-between items-start gap-2">
                  <p className="font-semibold text-foreground truncate max-w-[200px]">
                    {reminder.event_name ||
                      'Untitled reminder'}
                  </p>

                  {daysRemaining !== null && (
                    <span
                      className={cn(
                        'px-1.5 py-0.5 rounded-sm',
                        'text-[9px] font-semibold',
                        'uppercase tracking-wider',
                        daysRemaining <= 1
                          ? 'bg-red-500/10 text-red-500 animate-pulse'
                          : 'bg-blue-500/10 text-blue-500'
                      )}
                    >
                      {daysRemaining === 0
                        ? 'Today'
                        : daysRemaining === 1
                        ? '1 day left'
                        : `${daysRemaining} days left`}
                    </span>
                  )}
                </div>

                {/* Category */}
                <p className="text-[10px] text-muted-foreground capitalize mt-1">
                  Category:{' '}
                  {reminder.source_type ||
                    'event'}
                  {' • '}
                  Offset:{' '}
                  {reminder.reminder_offset ||
                    'at event time'}
                </p>

                {/* Event date */}
                <p className="text-muted-foreground mt-2 flex items-center gap-1">
                  <Calendar className="w-3.5 h-3.5" />

                  {formatDate(
                    reminder.event_date
                  )}
                </p>
              </div>

              {/* Cancel */}
              <div className="flex justify-end mt-3 pt-2 border-t border-border/10">
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() =>
                    onCancel(id)
                  }
                  disabled={
                    !id ||
                    actioningId === id
                  }
                  className="h-7 px-2 text-red-500 hover:text-red-600 hover:bg-red-500/5 gap-1"
                >
                  {actioningId === id ? (
                    <Loader2 className="w-3 h-3 animate-spin" />
                  ) : (
                    <>
                      <Trash2 className="w-3.5 h-3.5" />
                      Cancel
                    </>
                  )}
                </Button>
              </div>
            </div>
          );
        }
      )}
    </div>
  );
}

/* ========================================================================== */
/* Snooze Dropdown                                                            */
/* ========================================================================== */

function DropdownSnoozeButton({
  onSnooze,
  disabled,
}: {
  onSnooze: (minutes: number) => void;
  disabled?: boolean;
}) {
  const [showOptions, setShowOptions] =
    useState(false);

  const dropdownRef =
    useRef<HTMLDivElement>(null);

  /* ------------------------------------------------------------------------ */
  /* Close when clicking outside                                               */
  /* ------------------------------------------------------------------------ */

  useEffect(() => {
    function handleClickOutside(
      event: MouseEvent
    ) {
      if (
        dropdownRef.current &&
        !dropdownRef.current.contains(
          event.target as Node
        )
      ) {
        setShowOptions(false);
      }
    }

    document.addEventListener(
      'mousedown',
      handleClickOutside
    );

    return () => {
      document.removeEventListener(
        'mousedown',
        handleClickOutside
      );
    };
  }, []);

  /* ------------------------------------------------------------------------ */
  /* Escape key                                                               */
  /* ------------------------------------------------------------------------ */

  useEffect(() => {
    if (!showOptions) {
      return;
    }

    function handleEscape(
      event: KeyboardEvent
    ) {
      if (event.key === 'Escape') {
        setShowOptions(false);
      }
    }

    document.addEventListener(
      'keydown',
      handleEscape
    );

    return () => {
      document.removeEventListener(
        'keydown',
        handleEscape
      );
    };
  }, [showOptions]);

  return (
    <div
      className="relative inline-block text-left"
      ref={dropdownRef}
    >
      <Button
        type="button"
        size="sm"
        variant="ghost"
        onClick={() =>
          setShowOptions(
            (previous) => !previous
          )
        }
        disabled={disabled}
        className="h-7 px-2 text-[10px] gap-1 hover:bg-muted"
        aria-expanded={showOptions}
        aria-haspopup="menu"
      >
        <Clock className="w-3.5 h-3.5" />

        Snooze
      </Button>

      {showOptions && (
        <div
          className={cn(
            'absolute right-0 bottom-full mb-1 z-[60]',
            'w-28 bg-popover',
            'border border-border/40',
            'rounded-lg shadow-lg overflow-hidden',
            'animate-slideUp'
          )}
          role="menu"
        >
          <SnoozeOption
            label="5 minutes"
            minutes={5}
            onSnooze={onSnooze}
          />

          <SnoozeOption
            label="1 hour"
            minutes={60}
            onSnooze={onSnooze}
          />

          <SnoozeOption
            label="1 day"
            minutes={1440}
            onSnooze={onSnooze}
          />
        </div>
      )}
    </div>
  );
}

/* ========================================================================== */
/* Snooze Option                                                              */
/* ========================================================================== */

function SnoozeOption({
  label,
  minutes,
  onSnooze,
}: {
  label: string;
  minutes: number;
  onSnooze: (minutes: number) => void;
}) {
  return (
    <button
      type="button"
      role="menuitem"
      onClick={() =>
        onSnooze(minutes)
      }
      className="w-full text-left px-3 py-2 text-[10px] text-foreground hover:bg-muted cursor-pointer transition-colors"
    >
      {label}
    </button>
  );
}