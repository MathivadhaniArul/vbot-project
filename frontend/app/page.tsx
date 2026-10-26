'use client';

import { Fragment, useState, useCallback, useRef, useEffect, type FormEvent } from 'react';
import { useChat } from '@ai-sdk/react';

import { useRouter } from 'next/navigation';
import { useAuth } from '@/lib/context/AuthContext';

import ChatSidebar from '@/components/ChatSidebar';
import { AnimatedThemeToggler } from "@/components/ui/theme_toggler";
import { AuroraText } from "@/components/ui/aurora";
import { ShineBorder } from "@/components/ui/shine_border";
import {
  Conversation,
  ConversationContent,
  ConversationScrollButton,
} from '@/components/ai-elements/conversation';

import { Message, MessageContent } from '@/components/ai-elements/message';
import { Response } from '@/components/ai-elements/response';
import { PanelLeftClose, PanelLeftOpen, Bell, SquareIcon } from "lucide-react";
import NotificationPanel from '@/components/NotificationPanel';
import { Volume2Icon, X, CalendarClock } from "lucide-react";

import {
  PromptInput,
  PromptInputBody,
  PromptInputSubmit,
  PromptInputTextarea,
  PromptInputFooter,
} from '@/components/ai-elements/prompt-input';

import { Actions, Action } from '@/components/ai-elements/actions';
import { Suggestions, Suggestion } from '@/components/ai-elements/suggestion';
import { Loader } from '@/components/ai-elements/loader';

import { CopyIcon, Mic, MicOff } from 'lucide-react';
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";

import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuTrigger,DropdownMenuLabel,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuSeparator,
} from "@/components/ui/dropdown-menu";
import { Languages } from "lucide-react"



const API_BASE = process.env.NEXT_PUBLIC_API_BASE || "http://127.0.0.1:8000";
const suggestions = [
  "when absolute grading is adopted ?",
  "what is the FAT re-evaluation procedure?",
  "what is the minimum credits we can register during FFCS",
];

export default function ChatBotDemo() {
  const [activeChatId, setActiveChatId] = useState<string | undefined>();
  const [refreshCounter, setRefreshCounter] = useState(0);
  const router = useRouter();
  const { user, loading, logout } = useAuth();
  const userId = user?.username || "";
  //const [feedback, setFeedback] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [language, setLanguage] = useState("en");
  const [notifCount, setNotifCount] = useState(0);
  const [notifPanelOpen, setNotifPanelOpen] = useState(false);
  const [addReminderOpen, setAddReminderOpen] = useState(false);
  const [reminderSaving, setReminderSaving] = useState(false);
  const [reminderForm, setReminderForm] = useState({
    eventName: "",
    eventDate: "",
    eventTime: "18:30",
    reminderOffset: "1h",
    notificationType: "in_app",
  });
  const [speakingId, setSpeakingId] =
    useState<string | null>(null);
  

  // Fetch unread count helper
  const fetchUnreadCount = useCallback(async () => {
    if (!userId) return;
    try {
      const res = await fetch(`${API_BASE}/api/notifications?userId=${userId}`);
      if (!res.ok) throw new Error();
      const data = await res.json();
      if (data.success) {
        const unread = data.notifications.filter((n: any) => !n.read).length;
        setNotifCount(unread);
      }
    } catch (err) {
      console.error(err);
    }
  }, [userId]);

  // Initial fetch on mount / user change
  useEffect(() => {
    if (userId) {
      fetchUnreadCount();
      const interval = setInterval(fetchUnreadCount, 30000);
      return () => clearInterval(interval);
    }
  }, [userId, fetchUnreadCount]);

  const { messages, setMessages, status } = useChat();
  const [input, setInput] = useState('');
  const [isLoading, setIsLoading] = useState(false);

const getMessageText = (message: any) => {
  const text = message.parts
    .filter((p: any) => p.type === "text")
    .map((p: any) => p.text)
    .join("\n");

  return text.replace(/```[\s\S]*?```/g, "");
};

  const [isRecording, setIsRecording] = useState(false);
  const recorderRef = useRef<any>(null);
  const audioContextRef = useRef<AudioContext | null>(null);
  const analyserRef = useRef<AnalyserNode | null>(null);
  const silenceTimerRef = useRef<NodeJS.Timeout | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const [isProcessingAudio, setIsProcessingAudio] = useState(false);
  const startRecording = async () => {
  if (isLoading || isRecording) return;

  try {
    setIsListening(true);

    const stream = await navigator.mediaDevices.getUserMedia({
      audio: {
        echoCancellation: true,
        noiseSuppression: true,
        autoGainControl: true,
      },
    });

    streamRef.current = stream;

    const RecordRTCModule = await import("recordrtc");
    const RecordRTC = RecordRTCModule.default;

    const recorder = new RecordRTC(stream, {
      type: "audio",
      mimeType: "audio/webm",
    });

    recorder.startRecording();

    recorderRef.current = { recorder, stream };
    setIsRecording(true);

    startVAD(stream);

  } catch (err) {
    console.error(err);
    setIsListening(false);
    setIsRecording(false);
  }
};


const startVAD = (stream: MediaStream) => {
  const audioContext = new AudioContext();
  audioContextRef.current = audioContext;

  const source = audioContext.createMediaStreamSource(stream);
  const analyser = audioContext.createAnalyser();

  analyser.fftSize = 2048;
  analyserRef.current = analyser;

  source.connect(analyser);

  const dataArray = new Uint8Array(analyser.frequencyBinCount);

  const checkVolume = () => {
    if (!analyserRef.current) return;

    analyserRef.current.getByteTimeDomainData(dataArray);

    let sum = 0;

    for (let i = 0; i < dataArray.length; i++) {
      const v = (dataArray[i] - 128) / 128;
      sum += v * v;
    }

    const rms = Math.sqrt(sum / dataArray.length);

    const isSilent = rms < 0.01;

    console.log("rms:", rms, "silent:", isSilent);

    if (isSilent) {
      if (!silenceTimerRef.current) {
        silenceTimerRef.current = setTimeout(() => {
          console.log("🛑 Auto stop triggered");
          stopRecording();
        }, 1200);
      }
    } else {
      if (silenceTimerRef.current) {
        clearTimeout(silenceTimerRef.current);
        silenceTimerRef.current = null;
      }
    }

    requestAnimationFrame(checkVolume);
  };

  checkVolume();
};

  const stopRecording = () => {
  if (!recorderRef.current || !isRecording) return;

  recorderRef.current.recorder.stopRecording(async () => {
    const blob = recorderRef.current.recorder.getBlob();

    recorderRef.current.stream
      .getTracks()
      .forEach((t: MediaStreamTrack) => t.stop());

    recorderRef.current = null;

    setIsRecording(false);
    setIsListening(false);

    audioContextRef.current?.close();
    audioContextRef.current = null;

    if (silenceTimerRef.current) {
      clearTimeout(silenceTimerRef.current);
      silenceTimerRef.current = null;
    }

    if (blob.size < 1000) return;

    await handleVoiceSubmit(blob);
  });
};



 const [isListening, setIsListening] = useState(false);
 const handleVoiceSubmit = async (audioBlob: Blob) => {
  try {
    setIsProcessingAudio(true);

    const formData = new FormData();
    formData.append("file", audioBlob, "recording.webm");
    formData.append("language", language);

    const res = await fetch(`${API_BASE}/api/transcribe`, {
      method: "POST",
      body: formData,
    });

    if (!res.ok) throw new Error("Transcription failed");

    const data = await res.json();

    setInput(data.text || "");

  } catch (err) {
    console.error(err);
    setInput("");
  } finally {
    setIsProcessingAudio(false);
  }
};

  
  // Send message
  const handleSubmit = async ({ text }: { text?: string }) => {
    if (!text || !text.trim() || isLoading) return;

    let chatId = activeChatId;

    if (!chatId) {
      chatId = crypto.randomUUID();
      setActiveChatId(chatId);
      refreshSidebar();
    }

    const userText = text;
    setInput('');

    setMessages(prev => [
      ...prev,
      {
        id: crypto.randomUUID(),
        role: 'user',
        parts: [{ type: 'text', text: userText }],
      },
    ]);

    setIsLoading(true);

    try {
      const res = await fetch(`${API_BASE}/api/chat`, {
        method: "POST",
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          chatId,
          userId,
          text: userText,
          language,
        }),
      });

      const data = await res.json();
      // Guard: if answer is still a JSON string, unwrap it
      let answer = data.answer || "";
      if (answer.trim().startsWith("{")) {
        try {
    const inner = JSON.parse(answer);
    if (inner.answer) answer = inner.answer;
  } catch {}
}

      setMessages(prev => [
        ...prev,
        {
          id: crypto.randomUUID(),
          role: 'assistant',
          parts: [{ type: 'text', text: answer }],
          entities: data.entities,
          actions: data.actions,
        } as any,
      ]);

    } catch {
      setMessages(prev => [
        ...prev,
        {
          id: crypto.randomUUID(),
          role: 'assistant',
          parts: [{ type: 'text', text: 'Error connecting to backend.' }],
        },
      ]);
    } finally {
      setIsLoading(false);
    }
  };

  const handleSuggestionClick = (suggestion: string) => {
    handleSubmit({ text: suggestion });
  };

  const handleChatSelect = async (chatId: string) => {
    setActiveChatId(chatId);

    const res = await fetch(
      `${API_BASE}/api/messages?chatId=${chatId}&userId=${userId}`
    );
    const msgs = await res.json();

    setMessages(
      msgs.map((m: any, index: number) => ({
        id: m.id || m._id || `msg-${index}`,
        role: m.role,
        parts: [{ type: "text", text: m.content }],
        entities: m.entities || [],
        actions: m.actions || [],
      }))
    );
  };

  //  Feedback
  // const submitFeedback = async () => {
  //   if (!feedback.trim()) return;
  //   setSubmitting(true);

  //   await fetch(`${API_BASE}/api/feedback`, {
  //     method: "POST",
  //     headers: { "Content-Type": "application/json" },
  //     body: JSON.stringify({ feedback }),
  //   });

  //   setFeedback("");
  //   setSubmitting(false);
  // };

  // New chat
  const handleNewChat = () => {
    const newId = crypto.randomUUID();
    setActiveChatId(newId);
    setMessages([]);
    refreshSidebar();
  };
   const handleCreateReminder = async (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();

    if (!userId || !reminderForm.eventName.trim() || !reminderForm.eventDate || !reminderForm.eventTime) {
      return;
    }

    setReminderSaving(true);

    try {
      const eventDate = new Date(
        `${reminderForm.eventDate}T${reminderForm.eventTime}`
      );

      if (Number.isNaN(eventDate.getTime())) {
        throw new Error("Invalid reminder date/time");
      }

      const res = await fetch(`${API_BASE}/api/reminders`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          userId,
          eventName: reminderForm.eventName.trim(),
          eventDate: eventDate.toISOString(),
          sourceType: "manual",
          sourceId: null,
          notificationType: reminderForm.notificationType,
          reminderOffset: reminderForm.reminderOffset,
          chatId: activeChatId || "",
          confirmed: true,
        }),
      });

      const data = await res.json();

      if (!res.ok || !data.success) {
        throw new Error(data?.detail || "Failed to create reminder");
      }

      setReminderForm({
        eventName: "",
        eventDate: "",
        eventTime: "18:30",
        reminderOffset: "1h",
        notificationType: "in_app",
      });
      setAddReminderOpen(false);
      setNotifPanelOpen(true);
      await fetchUnreadCount();
    } catch (err) {
      console.error("Failed to create reminder:", err);
      window.alert(
        err instanceof Error ? err.message : "Failed to create reminder"
      );
    } finally {
      setReminderSaving(false);
    }
  };

  // Auth Guard
  useEffect(() => {
    if (!loading && !user) {
      router.push("/login");
    }
  }, [user, loading, router]);

  const refreshSidebar = useCallback(() => {
    setRefreshCounter(prev => prev + 1);
  }, []);

  if (loading || !user) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-background">
        <div className="flex flex-col items-center gap-4">
          <div className="w-10 h-10 border-4 border-primary border-t-transparent rounded-full animate-spin"></div>
          <p className="text-sm text-muted-foreground animate-pulse">Initializing VBOT Assistant...</p>
        </div>
      </div>
    );
  }


const toggleSpeech = (id: string, text: string) => {
  if (speakingId === id) {
    speechSynthesis.cancel();
    setSpeakingId(null);
    return;
  }

  speechSynthesis.cancel();

  const utterance = new SpeechSynthesisUtterance(text);

  utterance.onstart = () => setSpeakingId(id);
  utterance.onend = () => setSpeakingId(null);
  utterance.onerror = () => setSpeakingId(null);

  speechSynthesis.speak(utterance);
};



  return (
   <main className="min-h-screen flex max-w-6xl w-full shadow-sm">
  
  {/* Sidebar */}
  
  <div className="flex flex-col h-full">

    {/*  ADD HERE */}
    <div
  className={`absolute top-2 z-50 transition-all duration-300 ${
    sidebarOpen ? "left-54" : "left-3"
  }`}
>
  <Button
    variant="ghost"
    size="icon"
    onClick={() => setSidebarOpen(prev => !prev)}
  >
    {sidebarOpen ? (
      <PanelLeftClose className="w-5 h-5" />
    ) : (
      <PanelLeftOpen className="w-5 h-5" />
    )}
  </Button>
</div>

          
          {/* Theme toggle */}
    
   <ChatSidebar
  userId={userId}   //  pass down
  activeChatId={activeChatId}
  onChatSelect={handleChatSelect}
  refreshTrigger={refreshCounter}
  onChatDeleted={refreshSidebar}
  onNewChat={handleNewChat}
  collapsed={!sidebarOpen}
/>
  </div>

  <Button
    variant="outline"
    size="icon"
    onClick={() => { setNotifPanelOpen(true); setAddReminderOpen(false); }}
    className="fixed top-4 right-80 z-50 rounded-full bg-background border-border/60 hover:bg-muted/30 h-10 w-10 flex items-center justify-center cursor-pointer"
  >
    <Bell className="w-5 h-5 text-foreground" />
    {notifCount > 0 && (
      <span className="absolute -top-1 -right-1 min-w-5 h-5 bg-red-500 text-white rounded-full flex items-center justify-center text-[10px] font-bold px-1 animate-pulse">
        {notifCount}
      </span>
    )}
  </Button>

  <DropdownMenu>
  <DropdownMenuTrigger asChild>
    <Button variant="outline" className="fixed top-4 right-15 z-50 capitalize gap-2 font-medium bg-background border-border/60 hover:bg-muted/30">
      <span className="text-[11px] px-1.5 py-0.5 rounded-sm bg-muted/80 text-muted-foreground font-semibold uppercase">{user.role}</span>
      <span>{userId}</span>
    </Button>
  </DropdownMenuTrigger>

  <DropdownMenuContent className="w-48 bg-popover border border-border/40 backdrop-blur-md">
    <div className="px-2 py-1.5 text-xs text-muted-foreground border-b border-border/30 mb-1">
      Role: <span className="font-semibold text-foreground">{user.role}</span>
    </div>
    <DropdownMenuItem
      onClick={logout}
      className="text-red-500 hover:text-red-600 focus:text-red-600 cursor-pointer"
    >
      Logout Session
    </DropdownMenuItem>






  </DropdownMenuContent>
</DropdownMenu>
  

  {/* Chat Area */}
  <div className="flex-1 relative size-full h-screen">
        <div className="flex flex-col h-full">

          <h1 className="text-6xl font-bold ml-5 ">
            V<AuroraText>BOT</AuroraText>
          </h1>
       
          {/* Theme toggle */}
          <div className="fixed top-4 right-4 z-50">
            <AnimatedThemeToggler />
          </div>

          {/* Feedback Dialog */}
          {/* <Dialog>
            <DialogTrigger asChild>
              <Button variant="outline" className="absolute right-1 top-8">
                Feedback
              </Button>
            </DialogTrigger>

            <DialogContent>
              <DialogHeader>
                <DialogTitle>Feedback</DialogTitle>
              </DialogHeader>

              <Textarea
                placeholder="Type your feedback..."
                value={feedback}
                onChange={(e) => setFeedback(e.target.value)}
              />

              <DialogFooter>
                <Button disabled={!feedback.trim()} onClick={submitFeedback}>
                  {submitting ? "Sending..." : "Submit"}
                </Button>
              </DialogFooter>
            </DialogContent>
          </Dialog> */}

          {/* Conversation */}
          <Conversation className="h-full mt-8">
            <ConversationContent>

              {/* Suggestions */}
              <Suggestions className="mt-4 ml-5">
                {suggestions.map(s => (
                  <Suggestion
                    key={s}
                    suggestion={s}
                    onClick={() => handleSuggestionClick(s)}
                  />
                ))}
              </Suggestions>

              {/* Messages */}
              {messages.map((message, index) => (
  <div key={message.id ?? index}>
    {message.parts.map((part, i) => (
      <Fragment key={`${message.id}-${i}`}>
        {part.type === "text" && (
          <Message from={message.role}>
            <MessageContent>
              <Response>{part.text}</Response>

            </MessageContent>
          </Message>
        )}
      </Fragment>
    ))}

   {message.role === "assistant" && (
  <Actions className="mt-2">
    <Action
      label="Copy"
      onClick={() =>
        navigator.clipboard.writeText(
          message.parts
            .map((p) => (p.type === "text" ? p.text : ""))
            .join("\n")
        )
      }
    >
      <CopyIcon className="size-3" />
    </Action>

    <Action
  label={speakingId === message.id ? "Stop" : "Listen"}
  onClick={() =>
    toggleSpeech(message.id, getMessageText(message))
    
  }
>
  {speakingId === message.id ? (
    <SquareIcon className="size-3" />
  ) : (
    <Volume2Icon className="size-3" />
  )}
</Action>
  </Actions>
)}
  </div>
))}


              {(status === 'submitted' || isLoading ) && <Loader />}

            </ConversationContent>

            <ConversationScrollButton />
          </Conversation>

          {/* Input */}
          <PromptInput onSubmit={handleSubmit} className="mt-4 ml-5">
            <PromptInputBody>
              <ShineBorder />
              <PromptInputTextarea
                value={input}
                onChange={(e) => setInput(e.target.value)}
                placeholder={
  isRecording
    ? "🎙️ Recording..."
    : isProcessingAudio
      ? "⏳ Processing audio..."
      : isListening
        ? "🎧 Listening..."
        : activeChatId
          ? "Type your message..."
          : "Start a new chat..."
}
              />
            </PromptInputBody>

            <PromptInputFooter>
              <div className="flex gap-2">
                {!isRecording ? (
                  <Button
                    variant="secondary"
                    size="icon"
                    className="rounded-full"
                    onClick={startRecording}
                    title="Start recording"
                  >
                    <Mic className="w-5 h-5" />
                  </Button>
                ) : (
                  <Button
                    variant="destructive"
                    size="icon"
                    className="rounded-full animate-pulse"
                    onClick={stopRecording}
                    title="Stop recording"
                  >
                    <MicOff className="w-5 h-5" />
                  </Button>
                )}
                
                {/* <PromptInputSubmit disabled={!input.trim() || isLoading} /> */}
              </div>
              <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="outline">
          <Languages className="h-4 w-4" />
          Language
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent className="w-48">
        <DropdownMenuLabel>Select Language</DropdownMenuLabel>
        <DropdownMenuSeparator />
        <DropdownMenuRadioGroup onValueChange={setLanguage} value={language}>
          <DropdownMenuRadioItem value="en">
            <span className="flex items-center gap-2">
              <span>English</span>
            </span>
          </DropdownMenuRadioItem>
          <DropdownMenuRadioItem value="Hindi">
            <span className="flex items-center gap-2">
              <span>हिंदी</span>
            </span>
          </DropdownMenuRadioItem>
          <DropdownMenuRadioItem value="Tamil">
            <span className="flex items-center gap-2">
              <span>தமிழ்</span>
            </span>
          </DropdownMenuRadioItem>
          <DropdownMenuRadioItem value="Telugu">
            <span className="flex items-center gap-2">
              <span>దేశం</span>
            </span>
          </DropdownMenuRadioItem>
          <DropdownMenuRadioItem value="Kannada">
            <span className="flex items-center gap-2">
              <span>ಕನ್ನಡ</span>
            </span>
          </DropdownMenuRadioItem>
          <DropdownMenuRadioItem value="Malayalam">
            <span className="flex items-center gap-2">
              <span>മലയാളം</span>
            </span>
          </DropdownMenuRadioItem>
        </DropdownMenuRadioGroup>
      </DropdownMenuContent>
    </DropdownMenu>
              
            </PromptInputFooter>
          </PromptInput>

        </div>
      </div>
      <NotificationPanel
        userId={userId}
        isOpen={notifPanelOpen}
        onClose={() => setNotifPanelOpen(false)}
        onUnreadCountChange={setNotifCount}
        onAddReminder={() => setAddReminderOpen(true)}
      />

      {/* Add Reminder now lives inside the bell panel itself (above the
          Notifications/Scheduled tabs). Reminders are no longer inferred
          from/classified from chat entities. */}
      {addReminderOpen && (
        <div className="fixed inset-0 z-[80] flex items-center justify-center bg-black/50 backdrop-blur-sm">
          <div className="w-[min(92vw,430px)] rounded-xl border border-border/60 bg-background p-5 shadow-2xl">
            <div className="mb-5 flex items-center justify-between">
              <div>
                <h2 className="text-lg font-semibold">Add Reminder</h2>
                <p className="text-xs text-muted-foreground">
                  Create a reminder manually from the bell panel.
                </p>
              </div>
              <Button
                type="button"
                variant="ghost"
                size="icon"
                onClick={() => setAddReminderOpen(false)}
                disabled={reminderSaving}
                aria-label="Close add reminder"
              >
                <X className="h-4 w-4" />
              </Button>
            </div>

            <form onSubmit={handleCreateReminder} className="space-y-4">
              <div className="space-y-1.5">
                <label htmlFor="reminder-event-name" className="text-sm font-medium">
                  Reminder title
                </label>
                <input
                  id="reminder-event-name"
                  value={reminderForm.eventName}
                  onChange={(e) =>
                    setReminderForm((prev) => ({
                      ...prev,
                      eventName: e.target.value,
                    }))
                  }
                  placeholder="e.g. DBMS quiz"
                  required
                  className="w-full rounded-md border border-border bg-background px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-ring"
                />
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div className="space-y-1.5">
                  <label htmlFor="reminder-event-date" className="text-sm font-medium">
                    Date
                  </label>
                  <input
                    id="reminder-event-date"
                    type="date"
                    value={reminderForm.eventDate}
                    onChange={(e) =>
                      setReminderForm((prev) => ({
                        ...prev,
                        eventDate: e.target.value,
                      }))
                    }
                    required
                    className="w-full rounded-md border border-border bg-background px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-ring"
                  />
                </div>

                <div className="space-y-1.5">
                  <label htmlFor="reminder-event-time" className="text-sm font-medium">
                    Time
                  </label>
                  <input
                    id="reminder-event-time"
                    type="time"
                    value={reminderForm.eventTime}
                    onChange={(e) =>
                      setReminderForm((prev) => ({
                        ...prev,
                        eventTime: e.target.value,
                      }))
                    }
                    required
                    className="w-full rounded-md border border-border bg-background px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-ring"
                  />
                </div>
              </div>

              <div className="space-y-1.5">
                <label htmlFor="reminder-offset" className="text-sm font-medium">
                  Remind me
                </label>
                <select
                  id="reminder-offset"
                  value={reminderForm.reminderOffset}
                  onChange={(e) =>
                    setReminderForm((prev) => ({
                      ...prev,
                      reminderOffset: e.target.value,
                    }))
                  }
                  className="w-full rounded-md border border-border bg-background px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-ring"
                >
                  <option value="15m">15 minutes before</option>
                  <option value="30m">30 minutes before</option>
                  <option value="1h">1 hour before</option>
                  <option value="2h">2 hours before</option>
                  <option value="1d">1 day before</option>
                </select>
              </div>

              <div className="space-y-1.5">
                <label htmlFor="reminder-notification-type" className="text-sm font-medium">
                  Notify via
                </label>
                <select
                  id="reminder-notification-type"
                  value={reminderForm.notificationType}
                  onChange={(e) =>
                    setReminderForm((prev) => ({
                      ...prev,
                      notificationType: e.target.value,
                    }))
                  }
                  className="w-full rounded-md border border-border bg-background px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-ring"
                >
                  <option value="in_app">App notification</option>
                  <option value="email">Email</option>
                  <option value="google_calendar">Google Calendar</option>
                </select>
                <p className="text-[11px] text-muted-foreground">
                  Google Calendar requires your Google Calendar account to be connected.
                </p>
              </div>

              <div className="flex justify-end gap-2 pt-2">
                <Button
                  type="button"
                  variant="ghost"
                  onClick={() => setAddReminderOpen(false)}
                  disabled={reminderSaving}
                >
                  Cancel
                </Button>
                <Button type="submit" disabled={reminderSaving}>
                  <CalendarClock className="mr-2 h-4 w-4" />
                  {reminderSaving ? "Saving..." : "Save Reminder"}
                </Button>
              </div>
            </form>
          </div>
        </div>
      )}
    </main>
  );
}