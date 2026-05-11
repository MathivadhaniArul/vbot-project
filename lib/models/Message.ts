import mongoose, { Schema, model, models } from "mongoose";

const MessageSchema = new Schema({
  chatId: { type: Schema.Types.ObjectId, ref: "Chat", required: true },
  role: { type: String, enum: ["user", "assistant"], required: true },
  content: String,
  createdAt: { type: Date, default: Date.now }
});

export default models.Message || model("Message", MessageSchema);