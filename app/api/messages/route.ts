import { NextResponse } from "next/server";
import { connectDB } from "@/lib/mongodb";
import Message from "@/lib/models/Message";

export async function GET(req: Request) {
  await connectDB();

  const { searchParams } = new URL(req.url);
  const chatId = searchParams.get("chatId");

  const messages = await Message.find({ chatId }).sort({ createdAt: 1 });
  return NextResponse.json(messages);
}

export async function POST(req: Request) {
  await connectDB();

  const { chatId, content } = await req.json();

  // Save user message
  await Message.create({ chatId, role: "user", content });

  // Call FastAPI RAG backend
  const res = await fetch("http://localhost:8000/api/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      chatId,
      text: content,
    }),
  });

  const data = await res.json();

  // Save assistant reply
  await Message.create({
    chatId,
    role: "assistant",
    content: data.answer,
  });

  return NextResponse.json({ role: "assistant", content: data.answer });
}