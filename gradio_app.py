import gradio as gr
import requests

RASA_URL = "http://localhost:5005/webhooks/rest/webhook"

def chat_with_bot(message, history):
    # ✅ history эхний удаа None байж болно
    if history is None:
        history = []

    payload = {"sender": "web_user", "message": message}

    try:
        r = requests.post(RASA_URL, json=payload, timeout=8)
        # Хэрвээ 500/404 гэх мэт бол алдаа үүсгэнэ
        r.raise_for_status()

        replies = r.json()

        bot_text = "\n".join(
            rep.get("text", "") for rep in replies if rep.get("text")
        ).strip()

        if not bot_text:
            bot_text = "⚠️ Бот хариу өгөөгүй байна (empty response)"

    except Exception as e:
        bot_text = f"⚠️ Холболтын алдаа: {e}"

    history.append((message, bot_text))
    return history, ""


with gr.Blocks(title="Lab Error AI Bot") as demo:
    gr.Markdown("## 🧪 Лабораторийн туршилтын алдаа тооцоолох AI бот")

    chatbot = gr.Chatbot(height=420)
    msg = gr.Textbox(
        placeholder="Хэмжилтийн утгуудаа бичнэ үү...",
        label="Таны мессеж"
    )

    msg.submit(chat_with_bot, [msg, chatbot], [chatbot, msg])

demo.launch(server_name="127.0.0.1", share=False, show_api=False, show_error=True)