'use client';

import { Fragment, useState, useCallback } from 'react';
import { useChat } from '@ai-sdk/react';

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

import { CopyIcon } from 'lucide-react';
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

const API_BASE = "http://127.0.0.1:8000";

const suggestions = [
  "when absolute grading is adopted ?",
  "what is the FAT re-evaluation procedure?",
  "what is the minimum credits we can register during FFCS",
];

export default function ChatBotDemo() {
  const [activeChatId, setActiveChatId] = useState<string | undefined>();
  const [refreshCounter, setRefreshCounter] = useState(0);
  const [feedback, setFeedback] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [userId, setUserId] = useState("user1");

  const { messages, setMessages, status } = useChat();
  const [input, setInput] = useState('');

  const refreshSidebar = useCallback(() => {
    setRefreshCounter(prev => prev + 1);
  }, []);

  // Send message
  const handleSubmit = async ({ text }: { text: string }) => {
    if (!text.trim()) return;

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

    await fetch("/api/feedback", {
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
    <Button variant="outline" className="fixed top-4 right-15 z-50">
      {userId}
    </Button>
  </DropdownMenuTrigger>

  <DropdownMenuContent>
    <DropdownMenuGroup>
      {["user1", "user2", "user3", "user4"].map((u) => (
        <DropdownMenuItem
          key={u}
          onClick={() => {
            setUserId(u);
            setActiveChatId(undefined);
            setMessages([]); // clear chat
            refreshSidebar();
          }}
        >
          {u}
        </DropdownMenuItem>
      ))}
    </DropdownMenuGroup>
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
              message.parts.map((p) => p.text).join("\n")
            )
          }
        >
          <CopyIcon className="size-3" />
        </Action>
      </Actions>
    )}
  </div>
))}

              {status === 'submitted' && <Loader />}

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
              <PromptInputSubmit disabled={!input.trim()} />
            </PromptInputFooter>
          </PromptInput>

        </div>
      </div>
    </main>
  );
}
