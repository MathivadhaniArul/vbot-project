import { NextResponse } from "next/server";
import {connectDB} from "@/lib/mongodb";
import Chat from "@/lib/models/Chat";

export async function GET(
  _req: Request,
  { params }: { params: Promise<{ id: string }> }
) {
  await connectDB();
  const { id } = await params;
  const chat = await Chat.findById(id);
  return NextResponse.json(chat);
}