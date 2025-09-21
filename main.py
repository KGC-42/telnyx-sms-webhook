from fastapi import FastAPI, Request
import json
import sqlite3
from datetime import datetime, timedelta
import re
import uvicorn
import os

app = FastAPI(title="Telnyx SMS Webhook", version="1.0.0")

def init_db():
    conn = sqlite3.connect('sms_messages.db')
    conn.execute('''CREATE TABLE IF NOT EXISTS sms_messages 
                   (id INTEGER PRIMARY KEY AUTOINCREMENT,
                    phone TEXT NOT NULL,
                    message TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    extracted_code TEXT,
                    platform TEXT,
                    used INTEGER DEFAULT 0)''')
    conn.commit()
    conn.close()

init_db()

@app.get("/")
async def root():
    return {"status": "Telnyx SMS Webhook Server Running", "version": "1.0.0"}

@app.post("/webhook/telnyx")
async def receive_sms(request: Request):
    try:
        data = await request.json()
        print(f"Webhook received: {data}")
        
        # Try to extract phone and message from webhook data
        phone = None
        message_text = None
        
        # Method 1: Standard Telnyx format
        if 'data' in data:
            message_data = data['data']
            if 'from' in message_data:
                if isinstance(message_data['from'], dict):
                    phone = message_data['from'].get('phone_number', '')
                else:
                    phone = message_data['from']
            message_text = message_data.get('text', '')
        
        print(f"Extracted: phone={phone}, message={message_text}")
        
        if not phone or not message_text:
            return {"status": "error", "message": "Could not extract phone or message"}
        
        # Extract code
        code_match = re.search(r'\b(\d{4,8})\b', message_text)
        extracted_code = code_match.group(1) if code_match else None
        
        # Store in database
        conn = sqlite3.connect('sms_messages.db')
        conn.execute('''INSERT INTO sms_messages 
                       (phone, message, timestamp, extracted_code, platform) 
                       VALUES (?, ?, ?, ?, ?)''',
                    (phone, message_text, datetime.now().isoformat(), extracted_code, "unknown"))
        conn.commit()
        conn.close()
        
        print(f"Stored SMS: {phone} | Code: {extracted_code}")
        return {"status": "received", "code_extracted": bool(extracted_code)}
        
    except Exception as e:
        print(f"Error: {e}")
        return {"status": "error", "message": str(e)}

@app.get("/messages/{phone}")
async def get_messages(phone: str, limit: int = 10):
    try:
        conn = sqlite3.connect('sms_messages.db')
        cursor = conn.execute('''SELECT message, timestamp, extracted_code, platform 
                                FROM sms_messages 
                                WHERE phone = ? 
                                ORDER BY timestamp DESC LIMIT ?''', (phone, limit))
        results = cursor.fetchall()
        conn.close()
        
        messages = []
        for row in results:
            messages.append({
                "message": row[0],
                "timestamp": row[1],
                "extracted_code": row[2],
                "platform": row[3]
            })
        
        return {"phone": phone, "messages": messages}
        
    except Exception as e:
        return {"error": str(e)}

@app.get("/get_code/{phone}")
async def get_latest_code(phone: str):
    try:
        conn = sqlite3.connect('sms_messages.db')
        cursor = conn.execute('''SELECT extracted_code FROM sms_messages 
                                WHERE phone = ? AND extracted_code IS NOT NULL 
                                ORDER BY timestamp DESC LIMIT 1''', (phone,))
        result = cursor.fetchone()
        conn.close()
        
        return {"code": result[0] if result else None}
        
    except Exception as e:
        return {"error": str(e)}

@app.get("/health")
async def health_check():
    try:
        conn = sqlite3.connect('sms_messages.db')
        cursor = conn.execute("SELECT COUNT(*) FROM sms_messages")
        count = cursor.fetchone()[0]
        conn.close()
        
        return {"status": "healthy", "database": "connected", "total_messages": count}
    except Exception as e:
        return {"status": "error", "error": str(e)}

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
