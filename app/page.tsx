'use client';

import { Fragment, useState, useCallback, useRef, useEffect } from 'react';
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
import { PanelLeftClose, PanelLeftOpen } from "lucide-react";

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
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE || "http://localhost:8000";

const suggestions = [
  "when absolute grading is adopted ?",
  "what is the FAT re-evaluation procedure?",
  "what is the minimum credits we can register during FFCS",
];

export default function ChatBotDemo() {
  const router = useRouter();
  const { user, loading, logout } = useAuth();

  const [activeChatId, setActiveChatId] = useState<string | undefined>();
  const [refreshCounter, setRefreshCounter] = useState(0);
  const [feedback, setFeedback] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [sidebarOpen, setSidebarOpen] = useState(true);

  const { messages, setMessages, status } = useChat();
  const [input, setInput] = useState('');
  const [isLoading, setIsLoading] = useState(false);

  const userId = user?.username || "";

  // Auth Guard
  useEffect(() => {
    if (!loading && !user) {
      router.push("/login");
    }
  }, [user, loading, router]);

  const refreshSidebar = useCallback(() => {
    setRefreshCounter(prev => prev + 1);
  }, []);

  const [isRecording, setIsRecording] = useState(false);
  const recorderRef = useRef<any>(null);

  const startRecording = async () => {
    if (isLoading) return;
    try {
      const RecordRTC = (await import("recordrtc")).default;
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          echoCancellation: true,
          noiseSuppression: true,
          sampleRate: 44100,
        },
      });

      const recorder = new RecordRTC(stream, {
        type: "audio",
        mimeType: "audio/wav",
        recorderType: (RecordRTC as any).StereoAudioRecorder,
        desiredSampRate: 16000,
        numberOfAudioChannels: 1,
      });

      recorder.startRecording();

      recorderRef.current = { recorder, stream };
      setIsRecording(true);
      console.log("✅ RecordRTC recording started");
    } catch (err) {
      console.error("Error accessing microphone:", err);
    }
  };

  const stopRecording = () => {
    if (!recorderRef.current || !isRecording) return;

    recorderRef.current.recorder.stopRecording(async () => {
      const blob = recorderRef.current.recorder.getBlob();
      console.log("🔊 Recording blob size:", blob.size, "bytes");
      console.log("🔊 Recording blob type:", blob.type);

      // Stop all mic tracks
      recorderRef.current.stream
        .getTracks()
        .forEach((track: MediaStreamTrack) => track.stop());

      recorderRef.current = null;
      setIsRecording(false);

      if (blob.size < 1000) {
        console.warn("⚠️ Recording too small, likely empty audio");
        return;
      }

      await handleVoiceSubmit(blob);
    });
  };

  const handleVoiceSubmit = async (audioBlob: Blob) => {
    let chatId = activeChatId;

    if (!chatId) {
      chatId = crypto.randomUUID();
      setActiveChatId(chatId);
      refreshSidebar();
    }

    // RecordRTC produces WAV audio
    const formData = new FormData();
    formData.append("file", audioBlob, "recording.wav");
    formData.append("chatId", chatId);
    formData.append("userId", userId);

    setMessages(prev => [
      ...prev,
      {
        id: crypto.randomUUID(),
        role: 'user',
        parts: [{ type: 'text', text: '🎙️ Processing voice...' }],
      },
    ]);

    setIsLoading(true);
    try {
      const res = await fetch(`${API_BASE}/api/voice`, {
        method: "POST",
        body: formData,
      });

      if (!res.ok) {
        const errorData = await res.text();
        console.error("Voice API error:", errorData);
        throw new Error("Voice processing failed");
      }

      // Read the audio blob FIRST before trying to read headers
      const blob = await res.blob();

      const userTextRaw = res.headers.get("X-User-Text");
      const assistantTextRaw = res.headers.get("X-Assistant-Text");

      const userText = userTextRaw ? decodeURIComponent(userTextRaw) : "Voice Message";
      const assistantText = assistantTextRaw ? decodeURIComponent(assistantTextRaw) : "Audio response";

      setMessages(prev => {
        const newMessages = [...prev];
        newMessages[newMessages.length - 1] = {
          id: crypto.randomUUID(),
          role: 'user',
          parts: [{ type: 'text', text: `🎙️ ${userText}` }],
        };
        newMessages.push({
          id: crypto.randomUUID(),
          role: 'assistant',
          parts: [{ type: 'text', text: assistantText }],
        });
        return newMessages;
      });

      const audioUrl = URL.createObjectURL(blob);
      const audio = new Audio(audioUrl);
      audio.play();

      refreshSidebar();
    } catch (err) {
      console.error("Voice submit error:", err);
      setMessages(prev => {
        const newMessages = [...prev];
        newMessages[newMessages.length - 1] = {
          id: crypto.randomUUID(),
          role: 'assistant',
          parts: [{ type: 'text', text: '❌ Voice processing failed. Please try again or type your question.' }],
        };
        return newMessages;
      });
    } finally {
      setIsLoading(false);
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
          text: userText
        }),
      });

      const data = await res.json();

      setMessages(prev => [
        ...prev,
        {
          id: crypto.randomUUID(),
          role: 'assistant',
          parts: [{ type: 'text', text: data.answer }],
        },
      ]);

    } catch {
      setMessages(prev => [
        ...prev,
        {
          id: crypto.randomUUID(),
          role: 'assistant',
          parts: [{ type: 'text', text: ' Error connecting to backend.' }],
        },
      ]);
    } finally {
      setIsLoading(false);
    }
  };

  const handleSuggestionClick = (suggestion: string) => {
    handleSubmit({ text: suggestion });
  };

  // Load chat
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
      }))
    );
  };

  //  Feedback
  const submitFeedback = async () => {
    if (!feedback.trim()) return;
    setSubmitting(true);

    await fetch(`${API_BASE}/api/feedback`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ feedback }),
    });

    setFeedback("");
    setSubmitting(false);
  };

  // New chat
  const handleNewChat = () => {
    const newId = crypto.randomUUID();
    setActiveChatId(newId);
    setMessages([]);
    refreshSidebar();
  };

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

  {/* Chat Area */}
  <div className="flex-1 relative size-full h-screen">
        <div className="flex flex-col h-full">

          <h1 className="text-6xl font-bold">
            V<AuroraText>BOT</AuroraText>
          </h1>
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
          {/* Theme toggle */}
          <div className="fixed top-4 right-4 z-50">
            <AnimatedThemeToggler />
          </div>

          {/* Feedback Dialog */}
          <Dialog>
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
          </Dialog>

          {/* Conversation */}
          <Conversation className="h-full mt-8">
            <ConversationContent>

              {/* Suggestions */}
              <Suggestions className="mt-4">
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
              message.parts.map((p) => p.type === 'text' ? p.text : '').join('\n')
            )
          }
        >
          <CopyIcon className="size-3" />
        </Action>
      </Actions>
    )}
  </div>
))}

              {(status === 'submitted' || isLoading) && <Loader />}

            </ConversationContent>

            <ConversationScrollButton />
          </Conversation>

          {/* Input */}
          <PromptInput onSubmit={handleSubmit} className="mt-4">
            <PromptInputBody>
              <ShineBorder />
              <PromptInputTextarea
                value={input}
                onChange={(e) => setInput(e.target.value)}
                placeholder={
                  activeChatId
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
                <PromptInputSubmit disabled={!input.trim() || isLoading} />
              </div>
            </PromptInputFooter>
          </PromptInput>

        </div>
      </div>
    </main>
  );
}
