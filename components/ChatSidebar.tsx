'use client';

import { useEffect, useState } from "react";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { MoreVertical, Trash2, Pencil, MessageSquarePlus } from "lucide-react";
import { cn } from "@/lib/models/utils";


const API_BASE = process.env.NEXT_PUBLIC_API_BASE || "http://localhost:8000";

interface Chat {
  _id: string;
  title: string;
  updatedAt: string;
}

export default function ChatSidebar({
  userId,
  activeChatId,
  onChatSelect,
  refreshTrigger = 0,
  onChatDeleted,
  onNewChat,
  collapsed = false,
}: {
  userId?: string;
  activeChatId?: string;
  onChatSelect: (chatId: string) => void;
  refreshTrigger?: number;
  onChatDeleted?: () => void;
  onNewChat?: () => void;
  collapsed?: boolean;
}) {
  const [chats, setChats] = useState<Chat[]>([]);
  const [loading, setLoading] = useState(true);
  

  //  Load chats
 useEffect(() => {
    async function loadChats() {
      try {
        setLoading(true);
        const res = await fetch(`${API_BASE}/api/chats?userId=${userId}`);
        const data = await res.json();
        setChats(data);
      } catch (err) {
        console.error("Failed to load chats:", err);
      } finally {
        setLoading(false);
      }
    }

    if (userId) loadChats(); //  guard
  }, [refreshTrigger, userId]);

  // 🗑 Delete chat (user-safe)
  const handleDeleteChat = async (chatId: string) => {
    if (!confirm("Delete this chat?")) return;
    

    try {
      const res = await fetch(
  `${API_BASE}/api/chats/${chatId}?userId=${userId}`,
  {
    method: "DELETE",
  }
);

      if (!res.ok) {
        const errText = await res.text();
        console.error("Delete failed:", errText);
        return;
      }

      setChats(prev => prev.filter(chat => chat._id !== chatId));

      if (activeChatId === chatId) onChatSelect("");

      onChatDeleted?.();

    } catch (err) {
      console.error("Delete failed:", err);
    }
  };
  //  Rename chat
const handleRenameChat = async (chatId: string) => {
  const newTitle = prompt("Enter new chat name:");
  if (!newTitle?.trim()) return;

  try {
    const res = await fetch(
  `${API_BASE}/api/chats/${chatId}?userId=${userId}`,
  {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ title: newTitle.trim() }),
  }

    );

    const text = await res.text();
    console.log("Rename response:", res.status, text);

    if (!res.ok) throw new Error("Rename failed");

    setChats(prev =>
      prev.map(chat =>
        chat._id === chatId ? { ...chat, title: newTitle.trim() } : chat
      )
    );

  } catch (err) {
    console.error("Rename failed:", err);
  }
};

  return (
    <div
      className={cn(
        "h-screen border-r bg-muted/5 flex flex-col transition-all duration-300",
        collapsed ? "w-16" : "w-64"
      )}
    >
      {/* Header */}
      <div className="p-3 pt-10 border-b space-y-2">
        <Button
          variant="ghost"
          className={cn(
            "flex items-center gap-2 w-full justify-start",
            collapsed && "justify-center"
          )}
          onClick={onNewChat}
        >
          <MessageSquarePlus className="w-4 h-4" />
          {!collapsed && <span>New Chat</span>}
        </Button>

        {!collapsed && (
          <h2 className="font-semibold text-sm text-muted-foreground">
            Your conversations
          </h2>
        )}
      </div>

      {/* Chat list */}
     <ScrollArea className="flex-1 [&>div]:overflow-x-hidden">
  <div className="p-2">
    {loading ? (
      <div className="text-center py-8 text-muted-foreground">
        Loading...
      </div>
    ) : chats.length === 0 ? (
      <div className="text-center py-8 text-muted-foreground">
        No conversations yet
      </div>
    ) : (
      chats.map(chat => (
        <div
          key={chat._id}
          onClick={() => onChatSelect(chat._id)}
          className={`flex items-center gap-2 p-2 mb-1 rounded-md hover:bg-muted cursor-pointer overflow-hidden ${
            activeChatId === chat._id ? "bg-muted" : ""
          } ${collapsed ? "justify-center" : ""}`}
        >
          {/* Chat icon */}
          <div className="flex-shrink-0">
            <MessageSquarePlus className="w-4 h-4" />
          </div>

          {/* Title */}
          {!collapsed && (
            <div className="flex-1 min-w-0 max-w-[160px] pr-2">
              <p className="truncate text-sm">
                {chat.title || "New conversation"}
              </p>
            </div>
          )}

          {/* Menu */}
          {!collapsed && (
            <div className="flex-shrink-0">
              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <Button
                    variant="ghost"
                    size="icon"
                    className="w-8 h-8"
                    onClick={(e) => e.stopPropagation()}
                  >
                    <MoreVertical className="h-4 w-4" />
                  </Button>
                </DropdownMenuTrigger>

                <DropdownMenuContent align="end">
                  <DropdownMenuItem
                    onClick={(e) => {
                      e.stopPropagation();
                      handleRenameChat(chat._id);
                    }}
                  >
                    <Pencil className="mr-2 h-4 w-4" />
                    Rename
                  </DropdownMenuItem>

                  <DropdownMenuItem
                    onClick={(e) => {
                      e.stopPropagation();
                      handleDeleteChat(chat._id);
                    }}
                    className="text-red-600"
                  >
                    <Trash2 className="mr-2 h-4 w-4" />
                    Delete
                  </DropdownMenuItem>
                </DropdownMenuContent>
              </DropdownMenu>
            </div>
          )}
        </div>
      ))
    )}
  </div>
</ScrollArea>
    </div>
  );

}