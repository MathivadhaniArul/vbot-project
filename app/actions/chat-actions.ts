
"use server";

import Chat from "@/lib/models/Chat";
import { connectDB } from "@/lib/mongodb";

export async function createChat() {
  await connectDB();
  const chat = await Chat.create({ messages: [] });
  return chat._id.toString();
}

export async function getChat(chatId: string) {
  await connectDB();
  return Chat.findById(chatId);
}

export async function saveMessages(chatId: string, messages: any[]) {
  await connectDB();
  await Chat.findByIdAndUpdate(chatId, { messages });
}