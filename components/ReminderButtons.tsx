'use client';

import React, { useState, useEffect } from 'react';
import { Button } from '@/components/ui/button';
import { cn } from '@/lib/models/utils';
import { Bell, Calendar, Mail, Check, AlertCircle, Clock, Settings, Loader2 } from 'lucide-react';

const API_BASE = process.env.NEXT_PUBLIC_API_BASE || "http://127.0.0.1:8000";

interface Entity {
  type: string;
  name: string;
  date: string;
  confidence: number;
  timezone?: string;
  event_name?: string;
  event_date?: string;
  event_type?: string;
  show_reminder?: boolean;
}

interface ReminderButtonsProps {
  userId: string;
  entity: Entity;
  chatId: string;
  onSuccess?: (msg: string) => void;
}

// FastAPI's `detail` is a string for HTTPException but an array of issues for a
// validation error; rendering the raw value yields "[object Object]".
function describeError(detail: unknown, fallback: string): string {
  if (typeof detail === 'string') return detail;
  if (Array.isArray(detail)) {
    const msg = (detail as { msg?: string }[])
      .map(d => d?.msg).filter(Boolean).join('; ');
    if (msg) return msg;
  }
  return fallback;
}

export default function ReminderButtons({ userId, entity, chatId, onSuccess }: ReminderButtonsProps) {
  const [step, setStep] = useState<number>(0);
  const [loading, setLoading] = useState<boolean>(false);
  const [pref, setPref] = useState<any>(null);
  
  // Form values
  const [notifType, setNotifType] = useState<string>('in_app');
  const [email, setEmail] = useState<string>('');
  const [offset, setOffset] = useState<string>('1d');
  const [customOffsetDate, setCustomOffsetDate] = useState<string>('');
  const [googleConnected, setGoogleConnected] = useState<boolean>(false);
  
  const [error, setError] = useState<string>('');
  const [successMsg, setSuccessMsg] = useState<string>('');
  const [isDuplicate, setIsDuplicate] = useState<boolean>(false);
  const [rejected, setRejected] = useState<boolean>(false);

  // Load preferences
  const fetchPreferences = async () => {
    try {
      const res = await fetch(`${API_BASE}/api/user/preferences?userId=${userId}`);
      if (!res.ok) throw new Error("Failed to load preferences");
      const data = await res.json();
      if (data.success && data.preferences) {
        setPref(data.preferences);
        setNotifType(data.preferences.notification_type || 'in_app');
        setEmail(data.preferences.email || '');
        setGoogleConnected(data.preferences.google_oauth?.connected || false);
      }
    } catch (err) {
      console.error(err);
    }
  };

  // Check if reminder is already set for this event, date, and user
  const checkReminderStatus = async () => {
    try {
      const res = await fetch(`${API_BASE}/api/reminders/upcoming?userId=${userId}`);
      if (!res.ok) return;
      const data = await res.json();
      if (data.success && data.reminders) {
        const normalizeName = (name: string) => name.trim().toLowerCase().replace(/\s+/g, ' ');
        const targetName = normalizeName(entity.name);
        const targetTime = new Date(entity.date).getTime();

        const existing = data.reminders.find((r: any) => {
          const matchName = normalizeName(r.event_name) === targetName;
          const matchDate = Math.abs(new Date(r.event_date).getTime() - targetTime) < 5000;
          return matchName && matchDate;
        });

        if (existing) {
          setNotifType(existing.notification_type || 'in_app');
          setOffset(existing.reminder_offset || '1d');
          setIsDuplicate(true);
          setSuccessMsg(`Reminder set for: ${entity.name}`);
          setStep(5);
        }
      }
    } catch (err) {
      console.error("Error checking reminder status:", err);
    }
  };

  useEffect(() => {
    if (userId) {
      fetchPreferences();
      checkReminderStatus();
    }
  }, [userId]);

  // Listen for Google Calendar OAuth success from popup
  useEffect(() => {
    const handleOAuthMessage = (event: MessageEvent) => {
      if (event.data?.type === 'GOOGLE_CALENDAR_CONNECTED') {
        setGoogleConnected(true);
        fetchPreferences(); // reload preferences
        setStep(4); // proceed to timing select step
      }
    };
    window.addEventListener('message', handleOAuthMessage);
    return () => window.removeEventListener('message', handleOAuthMessage);
  }, []);

  // Format date for user presentation
  const formatDate = (dateStr: string) => {
    try {
      const d = new Date(dateStr);
      if (isNaN(d.getTime())) return dateStr;
      return d.toLocaleDateString('en-US', {
        month: 'short',
        day: 'numeric',
        year: 'numeric',
        hour: '2-digit',
        minute: '2-digit'
      });
    } catch {
      return dateStr;
    }
  };

  const startReminderFlow = () => {
    setStep(1); // Always allow channel choice first
  };




  const handleSavePrefAndContinue = async () => {
    setError('');
    
    // Validate email if needed
    if ((notifType === 'email' || notifType === 'all') && !email.trim()) {
      setError('Please provide your email address.');
      return;
    }

    setLoading(true);
    try {
      const res = await fetch(`${API_BASE}/api/user/preferences`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          userId,
          notificationType: notifType,
          email: email.trim() || null
        })
      });
      const data = await res.json();
      if (!res.ok || !data.success) {
        throw new Error(describeError(data.detail, 'Failed to save preferences'));
      }
      
      setPref(data.preferences);
      
      // Decide next step
      if ((notifType === 'google_calendar' || notifType === 'all') && !googleConnected) {
        setStep(3); // Must connect Google Calendar first
      } else {
        setStep(4); // Direct to timing select step
      }
    } catch (err: any) {
      setError(err.message || 'Error updating preferences.');
    } finally {
      setLoading(false);
    }
  };

  const handleConnectGoogle = async () => {
    setLoading(true);
    try {
      const res = await fetch(`${API_BASE}/api/google/auth-url?userId=${userId}`);
      const data = await res.json();
      if (data.success && data.url) {
        // Open authorization popup window
        const width = 500;
        const height = 600;
        const left = (window.innerWidth - width) / 2;
        const top = (window.innerHeight - height) / 2;
        window.open(
          data.url, 
          'Google OAuth', 
          `width=${width},height=${height},left=${left},top=${top}`
        );
      } else {
        setError('Google OAuth configuration is missing on the server.');
      }
    } catch {
      setError('Failed to initiate Google Calendar connection.');
    } finally {
      setLoading(false);
    }
  };

  const handleCreateReminder = async () => {
    setLoading(true);
    setError('');
    
    let reminderOffsetVal = offset;
    if (offset === 'custom') {
      if (!customOffsetDate) {
        setError('Please select a custom reminder time.');
        setLoading(false);
        return;
      }
      reminderOffsetVal = customOffsetDate;
    }

    try {
      const res = await fetch(`${API_BASE}/api/reminders`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          userId,
          eventName: entity.name,
          eventDate: entity.date,
          sourceType: entity.type,
          notificationType: notifType,
          reminderOffset: reminderOffsetVal,
          chatId
        })
      });
      const data = await res.json();
      if (res.status === 422 && typeof data.detail === 'string') {
        // Policy refusal: the subject is not official college information.
        setRejected(true);
        setError(data.detail);
        return;
      }
      if (!res.ok || !data.success) {
        throw new Error(describeError(data.detail, 'Failed to create reminder'));
      }

      setIsDuplicate(data.is_duplicate || false);
      setSuccessMsg(`Reminder set for: ${entity.name}`);
      setStep(5);
      if (onSuccess) {
        onSuccess(`Reminder successfully created for ${entity.name}.`);
      }
    } catch (err: any) {
      setError(err.message || 'Failed to create reminder.');
    } finally {
      setLoading(false);
    }
  };

  // Skip showing reminder button if show_reminder is false
  if (!entity.show_reminder) {
    return null;
  }

  // Server-side policy refused this subject — explain rather than retry.
  if (rejected) {
    return (
      <div className="animate-fadeIn my-3 p-4 rounded-xl border border-amber-500/30 bg-amber-500/5 max-w-lg text-sm flex gap-2 items-start">
        <AlertCircle className="w-4 h-4 text-amber-500 flex-shrink-0 mt-0.5" />
        <p className="text-xs text-muted-foreground leading-relaxed">{error}</p>
      </div>
    );
  }

  return (
    <div className={cn(
      "animate-fadeIn text-sm",
      step === 0 
        ? "my-2 flex gap-2 flex-wrap" 
        : "my-3 p-4 rounded-xl border border-border/40 bg-muted/20 backdrop-blur-md max-w-lg shadow-lg"
    )}>
      {step === 0 && (
        <>
          <Button 
            size="sm" 
            onClick={() => {
              setNotifType('in_app');
              setStep(1);
            }} 
            className="gap-1.5 font-medium bg-secondary text-secondary-foreground hover:bg-secondary/80 cursor-pointer"
          >
            <Bell className="w-4 h-4" />
            Set Reminder
          </Button>
          <Button 
            size="sm" 
            onClick={() => {
              setNotifType('google_calendar');
              if (!googleConnected) {
                setStep(3);
              } else {
                setStep(4);
              }
            }} 
            className="gap-1.5 font-medium bg-[#4285F4] text-white hover:bg-[#357ae8] cursor-pointer"
          >
            <Calendar className="w-4 h-4" />
            Add to Google Calendar
          </Button>
        </>
      )}

      {step === 1 && (
        <div className="flex flex-col gap-3">
          <p className="font-semibold text-foreground flex items-center gap-1.5">
            <Settings className="w-4 h-4 text-muted-foreground" />
            Reminder Channel
          </p>
          <p className="text-xs text-muted-foreground">How would you like to receive reminders for this event?</p>
          
          <div className="grid grid-cols-2 gap-2 mt-1">
            {[
              { id: 'in_app', label: 'In-App Alert', icon: Bell },
              { id: 'email', label: 'Email', icon: Mail },
              { id: 'google_calendar', label: 'Google Calendar', icon: Calendar },
              { id: 'all', label: 'All Channels', icon: Check },
            ].map(ch => {
              const Icon = ch.icon;
              return (
                <button
                  key={ch.id}
                  onClick={() => setNotifType(ch.id)}
                  className={cn(
                    "flex items-center gap-2 p-2.5 rounded-lg border text-left transition-all hover:bg-muted/50 cursor-pointer",
                    notifType === ch.id 
                      ? "border-primary/80 bg-primary/5 text-foreground font-medium" 
                      : "border-border/30 text-muted-foreground"
                  )}
                >
                  <Icon className="w-4 h-4 flex-shrink-0" />
                  <span className="text-xs">{ch.label}</span>
                </button>
              );
            })}
          </div>

          {error && (
            <p className="text-xs text-red-500 flex items-center gap-1">
              <AlertCircle className="w-3.5 h-3.5" />
              {error}
            </p>
          )}

          <div className="flex justify-end gap-2 mt-2">
            <Button size="sm" variant="ghost" onClick={() => setStep(0)} disabled={loading}>Back</Button>
            <Button size="sm" disabled={loading} onClick={async () => {
              if ((notifType === 'email' || notifType === 'all') && !email.trim()) {
                setStep(2);
              } else if (notifType === 'google_calendar' && !googleConnected) {
                setStep(3);
              } else {
                await handleSavePrefAndContinue();
              }
            }}>{loading ? <Loader2 className="w-4 h-4 animate-spin" /> : 'Next'}</Button>
          </div>
        </div>
      )}

      {step === 2 && (
        <div className="flex flex-col gap-3">
          <p className="font-semibold text-foreground flex items-center gap-1.5">
            <Mail className="w-4 h-4 text-muted-foreground" />
            Email Configuration
          </p>
          <p className="text-xs text-muted-foreground">Please enter your email to receive email reminders:</p>
          
          <input
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="name@university.edu"
            className="w-full h-10 px-3 rounded-lg border border-border/40 bg-input/10 backdrop-blur-sm focus:outline-none focus:ring-1 focus:ring-primary text-foreground"
          />

          {error && (
            <p className="text-xs text-red-500 flex items-center gap-1">
              <AlertCircle className="w-3.5 h-3.5" />
              {error}
            </p>
          )}

          <div className="flex justify-end gap-2 mt-1">
            <Button size="sm" variant="ghost" onClick={() => setStep(1)} disabled={loading}>Back</Button>
            <Button size="sm" onClick={handleSavePrefAndContinue} disabled={loading}>
              {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : 'Continue'}
            </Button>
          </div>
        </div>
      )}

      {step === 3 && (
        <div className="flex flex-col gap-3">
          <p className="font-semibold text-foreground flex items-center gap-1.5">
            <Calendar className="w-4 h-4 text-muted-foreground" />
            Connect Google Calendar
          </p>
          <p className="text-xs text-muted-foreground">
            Allow VBOT to create events in your Google Calendar calendar. Secure authorization is required.
          </p>
          
          <Button 
            onClick={handleConnectGoogle} 
            disabled={loading}
            className="w-full mt-1 bg-[#4285F4] hover:bg-[#357ae8] text-white font-medium gap-2"
          >
            {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : (
              <>
                <svg className="w-4 h-4 fill-current" viewBox="0 0 24 24">
                  <path d="M12.24 10.285V14.4h6.887c-.648 2.41-2.519 4.114-5.136 4.114-3.535 0-6.403-2.87-6.403-6.402a6.406 6.406 0 016.403-6.403c1.558 0 2.977.564 4.08 1.493l3.056-3.057C19.262 2.2 16.035 1 12.24 1 5.928 1 1 5.928 1 12.24S5.928 23.48 12.24 23.48c5.845 0 10.51-4.103 10.51-10.51 0-.68-.06-1.343-.17-1.99L12.24 10.285z"/>
                </svg>
                Sign in with Google
              </>
            )}
          </Button>

          {error && (
            <p className="text-xs text-red-500 flex items-center gap-1">
              <AlertCircle className="w-3.5 h-3.5" />
              {error}
            </p>
          )}

          <div className="flex justify-between items-center mt-2">
            <Button size="sm" variant="ghost" onClick={() => setStep(1)} disabled={loading}>Back</Button>
            <button 
              onClick={() => {
                setNotifType('in_app');
                setStep(4);
              }} 
              className="text-xs text-muted-foreground hover:text-foreground underline"
            >
              Skip (Use In-App instead)
            </button>
          </div>
        </div>
      )}

      {step === 4 && (
        <div className="flex flex-col gap-3">
          <p className="font-semibold text-foreground flex items-center gap-1.5">
            <Clock className="w-4 h-4 text-muted-foreground" />
            Reminder Timing
          </p>
          <p className="text-xs text-muted-foreground">When would you like to receive the reminder?</p>

          <div className="grid grid-cols-3 gap-2 mt-1">
            {[
              { id: '1h', label: '1 Hour' },
              { id: '1d', label: '1 Day' },
              { id: '3d', label: '3 Days' },
            ].map(t => (
              <button
                key={t.id}
                onClick={() => setOffset(t.id)}
                className={cn(
                  "py-2 px-3 text-center rounded-lg border transition-all cursor-pointer",
                  offset === t.id 
                    ? "border-primary/80 bg-primary/5 text-foreground font-medium" 
                    : "border-border/30 text-muted-foreground"
                )}
              >
                {t.label}
              </button>
            ))}
          </div>

          <button
            onClick={() => setOffset('custom')}
            className={cn(
              "w-full py-2 px-3 text-center rounded-lg border transition-all cursor-pointer text-xs mt-1",
              offset === 'custom' 
                ? "border-primary/80 bg-primary/5 text-foreground font-medium" 
                : "border-border/30 text-muted-foreground"
            )}
          >
            Custom date & time
          </button>

          {offset === 'custom' && (
            <input
              type="datetime-local"
              value={customOffsetDate}
              onChange={(e) => setCustomOffsetDate(e.target.value)}
              className="w-full h-10 px-3 rounded-lg border border-border/40 bg-input/10 backdrop-blur-sm focus:outline-none focus:ring-1 focus:ring-primary text-foreground text-xs mt-1"
            />
          )}

          {error && (
            <p className="text-xs text-red-500 flex items-center gap-1">
              <AlertCircle className="w-3.5 h-3.5" />
              {error}
            </p>
          )}

          <div className="flex justify-end gap-2 mt-2">
            <Button size="sm" variant="ghost" onClick={() => setStep(1)} disabled={loading}>Back</Button>
            <Button size="sm" onClick={handleCreateReminder} disabled={loading} className="bg-foreground text-background dark:bg-foreground dark:text-background hover:opacity-90">
              {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : 'Set Reminder'}
            </Button>
          </div>
        </div>
      )}

      {step === 5 && (
        <div className="flex flex-col gap-3 animate-fadeIn">
          <div className="flex items-center gap-2">
            {isDuplicate ? (
              <>
                <span className="p-2 bg-amber-500/10 text-amber-500 rounded-full">
                  <AlertCircle className="w-5 h-5" />
                </span>
                <p className="font-semibold text-amber-500">Reminder Already Exists!</p>
              </>
            ) : (
              <>
                <span className="p-2 bg-green-500/10 text-green-500 rounded-full">
                  <Check className="w-5 h-5" />
                </span>
                <p className="font-semibold text-green-500">Reminder Created!</p>
              </>
            )}
          </div>
          <div className="p-3 rounded-lg bg-muted/30 border border-border/20 flex flex-col gap-1.5 text-xs">
            <div className="flex justify-between">
              <span className="text-muted-foreground">Event</span>
              <span className="font-medium text-foreground truncate max-w-[180px]">{entity.name}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-muted-foreground">Date</span>
              <span className="font-medium text-foreground">{formatDate(entity.date)}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-muted-foreground">Channel</span>
              <span className="font-medium text-foreground capitalize">{notifType.replace('_', ' ')}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-muted-foreground">Remind</span>
              <span className="font-medium text-foreground">
                {offset === '1h' ? '1 hour before' : offset === '1d' ? '1 day before' : offset === '3d' ? '3 days before' : 'Custom time'}
              </span>
            </div>
          </div>
          <p className="text-[10px] text-muted-foreground text-center">You can manage this reminder from the notification bell.</p>
        </div>
      )}
    </div>
  );
}
