import { NextResponse } from "next/server";
import {connectDB} from "@/lib/mongodb";
import Chat from "@/lib/models/Chat";

export async function GET(
  _req: Request,
  { params }: { params: { id: string } }
) {
  await connectDB();
  const chat = await Chat.findById(params.id);
  return NextResponse.json(chat);
}