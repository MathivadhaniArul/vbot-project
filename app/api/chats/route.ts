import { NextResponse } from "next/server";
import {connectDB} from "@/lib/mongodb";
import Chat from "@/lib/models/Chat";

export async function GET() {
  await connectDB();

  const chats = await Chat.find().sort({ updatedAt: -1 });

  const formatted = chats.map((chat) => ({
    _id: chat._id,
    title: chat.messages?.[0]?.content?.slice(0, 40) || "New Chat",
    updatedAt: chat.updatedAt,
  }));

  return NextResponse.json(formatted);
}

export async function POST(req: Request) {
  await connectDB();
  const { title } = await req.json();

  const chat = await Chat.create({
    title: title || "New Chat"
  });

  return NextResponse.json(chat);
}