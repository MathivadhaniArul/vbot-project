'use client';

import React, { useState, useEffect, useCallback } from 'react';
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
  History
} from 'lucide-react';

const API_BASE = process.env.NEXT_PUBLIC_API_BASE || "http://127.0.0.1:8000";

interface Notification {
  id: string;
  reminder_id: string;
  title: string;
  message: string;
  read: boolean;
  event_date: string;
  created_at: string;
}

interface ReminderRecord {
  id: string;
  event_name: string;
  event_date: string;
  source_type: string;
  official_category?: string | null;
  notification_type?: string;
  reminder_offset: string;
  days_remaining?: number;
  status: string;
}

type PanelTab = 'notifications' | 'upcoming' | 'history';

// Keep in sync with reminder_service.HISTORY_STATUSES.
const HISTORY_STATUS_LABELS: Record<string, string> = {
  expired: 'Expired',
  completed: 'Completed',
  cancelled: 'Cancelled',
  failed: 'Failed',
};

const POLL_INTERVAL_MS = 30000;

interface NotificationPanelProps {
  userId: string;
  isOpen: boolean;
  onClose: () => void;
  onUnreadCountChange?: (count: number) => void;
  /** Bumped by the page's realtime stream to force an immediate refresh. */
  refreshSignal?: number;
}

export default function NotificationPanel({ userId, isOpen, onClose, onUnreadCountChange, refreshSignal }: NotificationPanelProps) {
  const [activeTab, setActiveTab] = useState<PanelTab>('notifications');
  const [notifications, setNotifications] = useState<Notification[]>([]);
  const [reminders, setReminders] = useState<ReminderRecord[]>([]);
  const [history, setHistory] = useState<ReminderRecord[]>([]);
  const [loading, setLoading] = useState<boolean>(false);
  const [actioningId, setActioningId] = useState<string | null>(null);

  // Defence in depth: the backend already excludes past events from the active
  // list, but a reminder can lapse while the panel sits open between polls.
  const isStillUpcoming = (r: ReminderRecord) => {
    const eventTime = new Date(r.event_date).getTime();
    return Number.isNaN(eventTime) || eventTime > Date.now();
  };

  const fetchData = useCallback(async () => {
    if (!userId) return;
    setLoading(true);
    try {
      const [notifRes, remRes, histRes] = await Promise.all([
        fetch(`${API_BASE}/api/notifications?userId=${userId}`),
        fetch(`${API_BASE}/api/reminders/upcoming?userId=${userId}`),
        fetch(`${API_BASE}/api/reminders/history?userId=${userId}`),
      ]);

      const notifData = await notifRes.json();
      if (notifData.success) {
        setNotifications(notifData.notifications);
        const unread = notifData.notifications.filter((n: Notification) => !n.read).length;
        if (onUnreadCountChange) onUnreadCountChange(unread);
      }

      const remData = await remRes.json();
      if (remData.success) {
        setReminders(remData.reminders.filter(isStillUpcoming));
      }

      const histData = await histRes.json();
      if (histData.success) {
        setHistory(histData.reminders);
      }
    } catch (err) {
      console.error("Failed to load notifications/reminders:", err);
    } finally {
      setLoading(false);
    }
  }, [userId, onUnreadCountChange]);

  useEffect(() => {
    if (isOpen) {
      fetchData();
    }
  }, [isOpen, userId, fetchData]);

  // Realtime push: the page's SSE stream bumps refreshSignal on every new
  // notification, so the panel updates without waiting for the next poll.
  useEffect(() => {
    if (isOpen && refreshSignal) {
      fetchData();
    }
  }, [refreshSignal, isOpen, fetchData]);

  // Polling fallback — also re-evaluates which reminders have lapsed.
  useEffect(() => {
    if (!isOpen) return;
    const interval = setInterval(fetchData, POLL_INTERVAL_MS);
    return () => clearInterval(interval);
  }, [isOpen, fetchData]);

  const handleMarkRead = async (id: string) => {
    setActioningId(id);
    try {
      const res = await fetch(`${API_BASE}/api/notifications/${id}/read?userId=${userId}`, {
        method: 'PATCH'
      });
      if (res.ok) {
        setNotifications(prev => 
          prev.map(n => n.id === id ? { ...n, read: true } : n)
        );
        const unread = notifications.filter(n => n.id !== id && !n.read).length;
        if (onUnreadCountChange) onUnreadCountChange(unread);
      }
    } catch (err) {
      console.error(err);
    } finally {
      setActioningId(null);
    }
  };

  const handleSnooze = async (id: string, minutes: number) => {
    setActioningId(id);
    try {
      const res = await fetch(`${API_BASE}/api/notifications/${id}/snooze`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ userId, snoozeMinutes: minutes })
      });
      if (res.ok) {
        // Notification is marked read automatically by backend when snoozed
        setNotifications(prev => prev.filter(n => n.id !== id));
        const unread = notifications.filter(n => n.id !== id && !n.read).length;
        if (onUnreadCountChange) onUnreadCountChange(unread);
        // The reminder's trigger time moved — reload every list.
        await fetchData();
      }
    } catch (err) {
      console.error(err);
    } finally {
      setActioningId(null);
    }
  };

  const handleCancelReminder = async (id: string) => {
    setActioningId(id);
    if (!confirm("Are you sure you want to cancel this reminder?")) {
      setActioningId(null);
      return;
    }
    try {
      const res = await fetch(`${API_BASE}/api/reminders/${id}?userId=${userId}`, {
        method: 'DELETE'
      });
      if (res.ok) {
        setReminders(prev => prev.filter(r => r.id !== id));
        // A cancelled reminder belongs in History now.
        await fetchData();
      }
    } catch (err) {
      console.error(err);
    } finally {
      setActioningId(null);
    }
  };

  const formatDate = (dateStr: string) => {
    try {
      const d = new Date(dateStr);
      return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
    } catch {
      return dateStr;
    }
  };

  const getRelativeTime = (dateStr: string) => {
    try {
      const d = new Date(dateStr);
      const diffMs = new Date().getTime() - d.getTime();
      const diffMin = Math.round(diffMs / 60000);
      if (diffMin < 1) return 'Just now';
      if (diffMin < 60) return `${diffMin}m ago`;
      const diffHrs = Math.round(diffMin / 60);
      if (diffHrs < 24) return `${diffHrs}h ago`;
      return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
    } catch {
      return '';
    }
  };

  const unreadNotifications = notifications.filter(n => !n.read);

  return (
    <>
      {/* Backdrop */}
      {isOpen && (
        <div 
          onClick={onClose}
          className="fixed inset-0 z-40 bg-black/30 backdrop-blur-[2px] transition-opacity duration-300 animate-fadeIn"
        />
      )}

      {/* Slide-out Panel */}
      <div className={cn(
        "fixed top-0 right-0 h-screen w-80 sm:w-96 z-50 bg-card/95 backdrop-blur-md border-l border-border/40 shadow-2xl flex flex-col transition-transform duration-300 ease-out transform",
        isOpen ? "translate-x-0" : "translate-x-full"
      )}>
        {/* Header */}
        <div className="p-4 border-b border-border/30 flex items-center justify-between">
          <h3 className="font-semibold text-lg text-foreground flex items-center gap-2">
            <Bell className="w-5 h-5 text-primary" />
            Alerts & Reminders
          </h3>
          <Button variant="ghost" size="icon" onClick={onClose} className="rounded-full w-8 h-8">
            <X className="w-4 h-4" />
          </Button>
        </div>

        {/* Navigation Tabs */}
        <div className="flex border-b border-border/30 px-2 py-1 gap-1">
          {([
            { id: 'notifications', label: 'Alerts', count: unreadNotifications.length },
            { id: 'upcoming', label: 'Scheduled', count: reminders.length },
            { id: 'history', label: 'History', count: history.length },
          ] as { id: PanelTab; label: string; count: number }[]).map(tab => (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              className={cn(
                "flex-1 py-2 text-xs font-medium rounded-lg transition-colors cursor-pointer",
                activeTab === tab.id
                  ? "bg-muted text-foreground"
                  : "text-muted-foreground hover:text-foreground"
              )}
            >
              {tab.label} ({tab.count})
            </button>
          ))}
        </div>

        {/* Content Area */}
        <ScrollArea className="flex-1 p-4">
          {loading && notifications.length === 0 && reminders.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-20 text-muted-foreground gap-2">
              <Loader2 className="w-6 h-6 animate-spin text-primary" />
              <p className="text-xs">Loading records...</p>
            </div>
          ) : activeTab === 'notifications' ? (
            /* Notifications Tab */
            notifications.length === 0 ? (
              <div className="flex flex-col items-center justify-center py-20 text-muted-foreground gap-2">
                <Info className="w-8 h-8 opacity-40" />
                <p className="text-xs">No active notifications</p>
              </div>
            ) : (
              <div className="flex flex-col gap-3">
                {notifications.map((notif) => (
                  <div 
                    key={notif.id} 
                    className={cn(
                      "p-3 rounded-xl border transition-all text-xs",
                      notif.read 
                        ? "bg-muted/10 border-border/20 opacity-60" 
                        : "bg-primary/5 border-primary/20 shadow-sm"
                    )}
                  >
                    <div className="flex justify-between items-start gap-2">
                      <p className="font-semibold text-foreground">{notif.title}</p>
                      <span className="text-[10px] text-muted-foreground flex-shrink-0">
                        {getRelativeTime(notif.created_at)}
                      </span>
                    </div>
                    <p className="text-muted-foreground mt-1 leading-normal">{notif.message}</p>
                    
                    {!notif.read && (
                      <div className="flex items-center gap-2 mt-3 pt-2 border-t border-border/10 justify-end">
                        <DropdownSnoozeButton 
                          onSnooze={(mins) => handleSnooze(notif.id, mins)} 
                          disabled={actioningId === notif.id}
                        />
                        <Button 
                          size="sm" 
                          variant="outline" 
                          onClick={() => handleMarkRead(notif.id)}
                          disabled={actioningId === notif.id}
                          className="h-7 px-2 text-[10px] gap-1"
                        >
                          {actioningId === notif.id ? <Loader2 className="w-3 h-3 animate-spin" /> : (
                            <>
                              <Check className="w-3.5 h-3.5" />
                              Dismiss
                            </>
                          )}
                        </Button>
                      </div>
                    )}
                  </div>
                ))}
              </div>
            )
          ) : activeTab === 'upcoming' ? (
            /* Upcoming Reminders Tab */
            reminders.length === 0 ? (
              <div className="flex flex-col items-center justify-center py-20 text-muted-foreground gap-2">
                <CalendarCheck className="w-8 h-8 opacity-40" />
                <p className="text-xs">No reminders scheduled</p>
              </div>
            ) : (
              <div className="flex flex-col gap-3">
                {reminders.map((rem) => (
                  <div 
                    key={rem.id} 
                    className="p-3 rounded-xl border border-border/30 bg-muted/20 text-xs flex flex-col justify-between"
                  >
                    <div>
                      <div className="flex justify-between items-start gap-2">
                        <p className="font-semibold text-foreground truncate max-w-[200px]">{rem.event_name}</p>
                        <span className={cn(
                          "px-1.5 py-0.5 rounded-sm text-[9px] font-semibold uppercase tracking-wider",
                          (rem.days_remaining ?? 0) <= 1
                            ? "bg-red-500/10 text-red-500 animate-pulse"
                            : "bg-blue-500/10 text-blue-500"
                        )}>
                          {rem.days_remaining === 0 ? 'Today' : rem.days_remaining === 1 ? '1 day left' : `${rem.days_remaining} days left`}
                        </span>
                      </div>
                      <p className="text-[10px] text-muted-foreground capitalize mt-1">
                        Category: {(rem.official_category || rem.source_type).replace(/_/g, ' ')} • Offset: {rem.reminder_offset}
                      </p>
                      <p className="text-muted-foreground mt-2 flex items-center gap-1">
                        <Calendar className="w-3.5 h-3.5" />
                        {formatDate(rem.event_date)}
                      </p>
                    </div>

                    <div className="flex justify-end mt-3 pt-2 border-t border-border/10">
                      <Button 
                        size="sm" 
                        variant="ghost" 
                        onClick={() => handleCancelReminder(rem.id)}
                        disabled={actioningId === rem.id}
                        className="h-7 px-2 text-red-500 hover:text-red-600 hover:bg-red-500/5 gap-1"
                      >
                        {actioningId === rem.id ? <Loader2 className="w-3 h-3 animate-spin" /> : (
                          <>
                            <Trash2 className="w-3.5 h-3.5" />
                            Cancel
                          </>
                        )}
                      </Button>
                    </div>
                  </div>
                ))}
              </div>
            )
          ) : (
            /* History Tab — reminders that expired, completed, failed or were cancelled */
            history.length === 0 ? (
              <div className="flex flex-col items-center justify-center py-20 text-muted-foreground gap-2">
                <History className="w-8 h-8 opacity-40" />
                <p className="text-xs">No past reminders yet</p>
              </div>
            ) : (
              <div className="flex flex-col gap-3">
                {history.map((rem) => (
                  <div
                    key={rem.id}
                    className="p-3 rounded-xl border border-border/20 bg-muted/10 text-xs opacity-75"
                  >
                    <div className="flex justify-between items-start gap-2">
                      <p className="font-semibold text-foreground truncate max-w-[200px]">{rem.event_name}</p>
                      <span className={cn(
                        "px-1.5 py-0.5 rounded-sm text-[9px] font-semibold uppercase tracking-wider flex-shrink-0",
                        rem.status === 'completed'
                          ? "bg-green-500/10 text-green-600"
                          : rem.status === 'failed'
                            ? "bg-red-500/10 text-red-500"
                            : "bg-muted text-muted-foreground"
                      )}>
                        {HISTORY_STATUS_LABELS[rem.status] || rem.status}
                      </span>
                    </div>
                    <p className="text-[10px] text-muted-foreground capitalize mt-1">
                      Category: {(rem.official_category || rem.source_type).replace(/_/g, ' ')}
                    </p>
                    <p className="text-muted-foreground mt-2 flex items-center gap-1">
                      <Calendar className="w-3.5 h-3.5" />
                      {formatDate(rem.event_date)}
                    </p>
                  </div>
                ))}
              </div>
            )
          )}
        </ScrollArea>
      </div>
    </>
  );
}

// Inline dropdown component for Snoozing options
function DropdownSnoozeButton({ onSnooze, disabled }: { onSnooze: (mins: number) => void, disabled?: boolean }) {
  const [showOptions, setShowOptions] = useState(false);
  const dropdownRef = React.useRef<HTMLDivElement>(null);

  useEffect(() => {
    function handleClickOutside(event: MouseEvent) {
      if (dropdownRef.current && !dropdownRef.current.contains(event.target as Node)) {
        setShowOptions(false);
      }
    }
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  return (
    <div className="relative inline-block text-left" ref={dropdownRef}>
      <Button 
        size="sm" 
        variant="ghost" 
        onClick={() => setShowOptions(!showOptions)}
        disabled={disabled}
        className="h-7 px-2 text-[10px] gap-1 hover:bg-muted"
      >
        <Clock className="w-3.5 h-3.5" />
        Snooze
      </Button>

      {showOptions && (
        <div className="absolute right-0 bottom-full mb-1 z-50 w-28 bg-popover border border-border/40 rounded-lg shadow-lg overflow-hidden animate-slideUp">
          <button 
            onClick={() => { onSnooze(5); setShowOptions(false); }}
            className="w-full text-left px-3 py-2 text-[10px] text-foreground hover:bg-muted cursor-pointer transition-colors"
          >
            5 minutes
          </button>
          <button 
            onClick={() => { onSnooze(60); setShowOptions(false); }}
            className="w-full text-left px-3 py-2 text-[10px] text-foreground hover:bg-muted cursor-pointer transition-colors"
          >
            1 hour
          </button>
          <button 
            onClick={() => { onSnooze(1440); setShowOptions(false); }}
            className="w-full text-left px-3 py-2 text-[10px] text-foreground hover:bg-muted cursor-pointer transition-colors"
          >
            1 day
          </button>
        </div>
      )}
    </div>
  );
}
