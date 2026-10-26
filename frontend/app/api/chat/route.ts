import { getChat, createChat, saveMessages } from '@/app/actions/chat-actions';

export async function POST(req: Request) {
  try {
    const { messages, chatId } = await req.json();

    if (!messages || !Array.isArray(messages) || messages.length === 0) {
      return new Response(JSON.stringify({ error: "Messages required" }), { status: 400 });
    }

    // Create chat if needed
    let currentChatId = chatId || await createChat();

    // Load existing history
    const existingChat = await getChat(currentChatId);
    const existingMessages = existingChat?.messages || [];

    const updatedMessages = [...existingMessages, ...messages];

    const lastUserMessage = messages[messages.length - 1];
    if (!lastUserMessage?.content) {
      return new Response(JSON.stringify({ error: "Invalid message" }), { status: 400 });
    }

    // Call Python backend
    const response = await fetch("http://127.0.0.1:8000/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query: lastUserMessage.content }),
    });

    if (!response.ok) {
      throw new Error("Python backend error");
    }

    const data = await response.json();

    const assistantMessage = {
      id: Date.now().toString(),
      role: "assistant",
      content: data.answer,
    };

    const finalMessages = [...updatedMessages, assistantMessage];

    // Save to MongoDB
    await saveMessages(currentChatId, finalMessages);

    return new Response(
      JSON.stringify({ messages: [assistantMessage] }),
      {
        headers: {
          "Content-Type": "application/json",
          "X-Chat-Id": currentChatId,
        },
      }
    );

  } catch (error) {
    console.error("Chat API error:", error);
    return new Response(JSON.stringify({ error: "Internal error" }), { status: 500 });
  }
}