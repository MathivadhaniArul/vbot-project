import mongoose, { Schema } from "mongoose";

const MessageSchema = new Schema({
  id: String,
  role: String,
  content: String,
});

const ChatSchema = new Schema({
  messages: [MessageSchema],
}, { timestamps: true });

export default mongoose.models.Chat || mongoose.model("Chat", ChatSchema);