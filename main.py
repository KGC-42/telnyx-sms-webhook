"""
Complete Fixed Telnyx SMS Webhook Server
Save this as: main.py
"""

from fastapi import FastAPI, Request
import json
import sqlite3
from datetime import datetime, timedelta
import re
import uvicorn
import os

app = FastAPI(title="Telnyx SMS Webhook", version="1.0.2")

def init_db():
    """Initialize SQLite database"""
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
    """Health check endpoint"""
    return {"status": "Telnyx SMS Webhook Server Running", "version": "1.0.2"}

@app.post("/webhook/telnyx")
async def receive_sms(request: Request):
    """Receive SMS from Telnyx webhook - FIXED VERSION"""
    try:
        data = await request.json()
        print(f"Webhook received: {data}")
        
        # Extract from correct Telnyx structure
        phone = None
        message_text = None
        received_at = datetime.now().isoformat()
        
        if 'data' in data and 'payload' in data['data']:
            payload = data['data']['payload']
            
            # Get sender's phone number (person who sent the SMS)
            if 'from' in payload and 'phone_number' in payload['from']:
                phone = payload['from']['phone_number']
            
            # Get message text
            message_text = payload.get('text', '')
            
            # Get timestamp
            if 'received_at' in payload:
                received_at = payload['received_at']
        
        print(f"Extracted: phone={phone}, message={message_text}")
        
        if not phone or not message_text:
            return {"status": "error", "message": "Could not extract phone or message"}
        
        # Extract verification code (common patterns)
        code_patterns = [
            r'\b(\d{6})\b',           # 6 digits
            r'\b(\d{5})\b',           # 5 digits  
            r'\b(\d{4})\b',           # 4 digits
            r'code[:\s]*(\d{4,8})',   # "code: 123456"
            r'verification[:\s]*(\d{4,8})',  # "verification: 123456"
        ]
        
        extracted_code = None
        for pattern in code_patterns:
            match = re.search(pattern, message_text, re.IGNORECASE)
            if match:
                extracted_code = match.group(1)
                break
        
        # Detect platform from message content
        platform = "unknown"
        message_lower = message_text.lower()
        
        if any(keyword in message_lower for keyword in ['instagram', 'ig']):
            platform = "instagram"
        elif any(keyword in message_lower for keyword in ['tiktok', 'tik tok']):
            platform = "tiktok"
        elif any(keyword in message_lower for keyword in ['youtube', 'google']):
            platform = "youtube"
        elif any(keyword in message_lower for keyword in ['twitter', 'x.com']):
            platform = "twitter"
        
        # Store in database
        conn = sqlite3.connect('sms_messages.db')
        conn.execute('''INSERT INTO sms_messages 
                       (phone, message, timestamp, extracted_code, platform) 
                       VALUES (?, ?, ?, ?, ?)''',
                    (phone, message_text, received_at, extracted_code, platform))
        conn.commit()
        conn.close()
        
        print(f"Stored SMS: {phone} | Platform: {platform} | Code: {extracted_code}")
        return {"status": "received", "code_extracted": bool(extracted_code), "sender": phone}
        
    except Exception as e:
        print(f"Error: {e}")
        return {"status": "error", "message": str(e)}

@app.get("/get_code/{phone}")
async def get_latest_code(phone: str):
    """Get latest verification code for phone number"""
    try:
        conn = sqlite3.connect('sms_messages.db')
        cursor = conn.execute('''SELECT extracted_code, platform, timestamp 
                                FROM sms_messages 
                                WHERE phone = ? AND extracted_code IS NOT NULL 
                                ORDER BY timestamp DESC LIMIT 1''', (phone,))
        result = cursor.fetchone()
        conn.close()
        
        if result:
            return {
                "code": result[0],
                "platform": result[1],
                "timestamp": result[2]
            }
        else:
            return {"code": None, "message": "No codes found"}
            
    except Exception as e:
        return {"error": str(e)}

@app.get("/get_code/{phone}/{platform}")
async def get_platform_code(phone: str, platform: str):
    """Get verification code for specific platform"""
    try:
        conn = sqlite3.connect('sms_messages.db')
        cursor = conn.execute('''SELECT extracted_code, timestamp 
                                FROM sms_messages 
                                WHERE phone = ? AND platform = ? 
                                AND extracted_code IS NOT NULL 
                                AND used = 0
                                ORDER BY timestamp DESC LIMIT 1''', (phone, platform))
        result = cursor.fetchone()
        
        if result:
            # Mark as used
            conn.execute('''UPDATE sms_messages 
                           SET used = 1 
                           WHERE phone = ? AND platform = ? AND extracted_code = ?''',
                        (phone, platform, result[0]))
            conn.commit()
        
        conn.close()
        
        if result:
            return {
                "code": result[0],
                "timestamp": result[1],
                "platform": platform
            }
        else:
            return {"code": None, "message": f"No unused codes for {platform}"}
            
    except Exception as e:
        return {"error": str(e)}

@app.get("/messages/{phone}")
async def get_messages(phone: str, limit: int = 10):
    """Get recent messages for phone number"""
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

@app.get("/all_messages")
async def get_all_messages(limit: int = 50):
    """Get all recent messages from any phone number"""
    try:
        conn = sqlite3.connect('sms_messages.db')
        cursor = conn.execute('''SELECT phone, message, timestamp, extracted_code, platform 
                                FROM sms_messages 
                                ORDER BY timestamp DESC LIMIT ?''', (limit,))
        results = cursor.fetchall()
        conn.close()
        
        messages = []
        for row in results:
            messages.append({
                "phone": row[0],
                "message": row[1],
                "timestamp": row[2],
                "extracted_code": row[3],
                "platform": row[4]
            })
        
        return {"total_messages": len(messages), "messages": messages}
        
    except Exception as e:
        return {"error": str(e)}

@app.get("/health")
async def health_check():
    """Health check with database status"""
    try:
        conn = sqlite3.connect('sms_messages.db')
        cursor = conn.execute("SELECT COUNT(*) FROM sms_messages WHERE timestamp > ?", 
                             ((datetime.now() - timedelta(hours=24)).isoformat(),))
        count_24h = cursor.fetchone()[0]
        
        cursor = conn.execute("SELECT COUNT(*) FROM sms_messages")
        total_count = cursor.fetchone()[0]
        
        conn.close()
        
        return {
            "status": "healthy",
            "database": "connected",
            "messages_24h": count_24h,
            "total_messages": total_count
        }
    except Exception as e:
        return {"status": "error", "error": str(e)}

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
