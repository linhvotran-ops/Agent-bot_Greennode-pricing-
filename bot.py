import os
import json
import base64
import logging
import glob
import traceback
import anthropic
import pandas as pd
from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, CommandHandler, filters, ContextTypes
from flask import Flask
import threading

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")

logger.info(f"TELEGRAM_TOKEN set: {bool(TELEGRAM_TOKEN)}")
logger.info(f"ANTHROPIC_API_KEY set: {bool(ANTHROPIC_API_KEY)}")

client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

def load_all_pricing():
    all_items = []
    xlsx_files = glob.glob("/app/data/*.xlsx")
    logger.info(f"Found {len(xlsx_files)} xlsx files: {xlsx_files}")

    for filepath in xlsx_files:
        if "pricing.xlsx" in filepath:
            continue
        service_name = os.path.basename(filepath).replace("Export-Pricing-Table-", "").replace(".xlsx", "").strip()
        try:
            # Đọc thử để tìm đúng header row
            df_raw = pd.read_excel(filepath, sheet_name="Items", header=None, nrows=5)
            logger.info(f"{filepath} first rows: {df_raw.values.tolist()}")
            
            # Tìm row chứa "Name"
            header_row = 0
            for i, row in df_raw.iterrows():
                if "Name" in row.values:
                    header_row = i
                    break
            
            df = pd.read_excel(filepath, sheet_name="Items", header=header_row)
            df = df.dropna(subset=["Name"])
            df = df[df["Name"].astype(str).str.strip() != ""]
            df = df[df["Name"].astype(str).str.strip() != "nan"]
            
            count = 0
            for _, row in df.iterrows():
                name = str(row.get("Name", "")).strip()
                if not name or name == "nan":
                    continue
                all_items.append({
                    "service": service_name,
                    "name": name,
                    "description": str(row.get("Description", "")).strip(),
                    "unit": str(row.get("Unit", "")).strip(),
                    "price": row.get("Public Price", 0),
                    "vat": row.get("% VAT", 0),
                    "currency": str(row.get("Currency", "VND")).strip(),
                    "item_group": str(row.get("Item Group", "")).strip(),
                })
                count += 1
            logger.info(f"Loaded {count} items from {service_name}")
        except Exception as e:
            logger.error(f"Error loading {filepath}: {e}")
            logger.error(traceback.format_exc())

    logger.info(f"Total loaded: {len(all_items)} items from {len(xlsx_files)} files")
    return all_items

PRICING_DATA = load_all_pricing()
PRICING_JSON = json.dumps(PRICING_DATA, ensure_ascii=False)

SYSTEM_PROMPT = f"""Bạn là trợ lý tư vấn báo giá của Greennode/VNG Cloud. Nhiệm vụ:
1. Phân tích nhu cầu khách hàng (từ text hoặc hình ảnh)
2. Tìm cấu hình phù hợp nhất từ bảng giá
3. Trả lời ĐÚNG theo template sau:

* Nhu cầu: [mô tả nhu cầu của khách]
* Cấu hình/solution: [tên cấu hình + thông số kỹ thuật + service]
* Total giá: [giá + đơn vị + VAT]

BẢNG GIÁ (JSON):
{PRICING_JSON}

Quy tắc:
- Ưu tiên item có status "Active"
- Giá VND: hiển thị có dấu phẩy, ví dụ 76,416,211 VND/tháng
- Giá USD: hiển thị theo đơn vị gốc
- Nếu không tìm thấy chính xác, đề xuất cấu hình gần nhất
- Luôn ghi rõ tên service (AI Cloud, vServer, vStorage, vCDN, vMonitor, AI Base, AI MaaS)"""


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_text = update.message.text
    await update.message.reply_text("⏳ Đang tra cứu báo giá...")
    try:
        response = client.messages.create(
            model="claude-sonnet-4-5",
            max_tokens=1000,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_text}]
        )
        reply = response.content[0].text
        await update.message.reply_text(reply)
    except Exception as e:
        logger.error(f"Error in handle_text: {e}")
        logger.error(traceback.format_exc())
        await update.message.reply_text(f"❌ Lỗi: {str(e)[:200]}")


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⏳ Đang đọc hình ảnh và tra cứu báo giá...")
    try:
        photo = update.message.photo[-1]
        file = await context.bot.get_file(photo.file_id)
        file_bytes = await file.download_as_bytearray()
        image_b64 = base64.b64encode(file_bytes).decode("utf-8")
        caption = update.message.caption or "Phân tích hình ảnh này và báo giá phù hợp."

        response = client.messages.create(
            model="claude-sonnet-4-5",
            max_tokens=1000,
            system=SYSTEM_PROMPT,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": image_b64}},
                    {"type": "text", "text": caption}
                ]
            }]
        )
        reply = response.content[0].text
        await update.message.reply_text(reply)
    except Exception as e:
        logger.error(f"Error in handle_photo: {e}")
        logger.error(traceback.format_exc())
        await update.message.reply_text(f"❌ Lỗi: {str(e)[:200]}")


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Xin chào! Tôi là bot báo giá Greennode/VNG Cloud.\n\n"
        f"📦 Đã load {len(PRICING_DATA)} sản phẩm từ bảng giá.\n\n"
        "💬 Gõ nhu cầu hoặc gửi ảnh yêu cầu để tôi báo giá! 🚀"
    )

app = Flask(__name__)

@app.route("/health")
def health():
    return {"status": "ok"}, 200

def run_flask():
    app.run(host="0.0.0.0", port=8080)

def main():
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()

    application = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    logger.info("Bot started!")
    application.run_polling()

if __name__ == "__main__":
    main()
